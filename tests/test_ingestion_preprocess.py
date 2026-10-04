"""
Regression tests for preprocessing and georeferenced acquisition.

These lock in the two defects that made the original pipeline scientifically invalid:

  * Optical change was computed from raw B03/B08 with no cloud or shadow mask, so a
    cloud in one date registered as surface change.
  * Imagery was forced onto a 256x256 grid and read with `tifffile.imread`, which
    discarded the affine transform and CRS, so nothing could be geolocated.

No test in this file contacts a network service. Sentinel Hub responses are synthesised
as genuine GeoTIFF bytes and served through a stubbed transport, so the tests assert real
GDAL-level georeferencing without requiring credentials.
"""

from __future__ import annotations

import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import requests

from satguard.geospatial.raster import GeoTransform, RasterProfile, write_geotiff
from satguard.ingestion import acquisition as acq_module
from satguard.ingestion.acquisition import (
    AcquisitionError,
    AuthenticationError,
    CloudCoverTooHighError,
    NoValidImageError,
    SentinelHubAcquirer,
)
from satguard.processing.preprocess import (
    SCL_REJECT_CLASSES,
    PreprocessingError,
    build_quality_mask,
    fill_masked,
    observation_pair_mask,
    preprocess_optical,
    preprocess_sar,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

LAT, LON = 28.60, 77.25
M_PER_DEG_LAT = 111320.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(LAT))


def _bounds_for(width: int, height: int, res_m: float):
    dx = res_m / M_PER_DEG_LON
    dy = res_m / M_PER_DEG_LAT
    return (LON - width * dx / 2, LAT - height * dy / 2,
            LON + width * dx / 2, LAT + height * dy / 2)


def _geotiff_bytes(array: np.ndarray, transform: GeoTransform) -> bytes:
    path = Path(tempfile.mkdtemp()) / "band.tif"
    write_geotiff(path, array, transform=transform, crs="EPSG:4326")
    return path.read_bytes()


class _FakeResponse:
    def __init__(self, status_code: int, body: bytes, content_type: str):
        self.status_code = status_code
        self.content = body
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def optical_scene():
    """A physically consistent 10 m Sentinel-2 reflectance scene plus a 20 m SCL band."""
    width, height = 100, 110
    bounds = _bounds_for(width, height, 10.0)
    transform = GeoTransform.from_bounds(bounds, width, height)

    reflectance = np.zeros((height, width, 4), dtype=np.float32)
    for i, value in enumerate((900, 1100, 1200, 3200)):
        reflectance[..., i] = value

    scl_20m = np.random.default_rng(2).choice(
        [4, 5, 6, 9], size=(height // 2, width // 2)
    ).astype(np.uint8)

    return {
        "width": width,
        "height": height,
        "bounds": bounds,
        "transform": transform,
        "reflectance": reflectance,
        "scl_20m": scl_20m,
        "reflectance_bytes": _geotiff_bytes(reflectance, transform),
        "scl_bytes": _geotiff_bytes(
            scl_20m, GeoTransform.from_bounds(bounds, width // 2, height // 2)
        ),
    }


def _multipart(parts, boundary="testboundary123"):
    body = b""
    for identifier, payload in parts:
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{identifier}"; '
            f'filename="{identifier}.tif"\r\n'
            f"Content-Type: image/tiff\r\n\r\n"
        ).encode() + payload + b"\r\n"
    return body + f"--{boundary}--\r\n".encode()


def _stub_post(monkeypatch, response):
    """Replace requests.post inside the acquisition module with a stub."""
    def _post(*args, **kwargs):
        return response
    monkeypatch.setattr(acq_module.requests, "post", _post)


# ---------------------------------------------------------------------------
# preprocessing: SCL quality masking
# ---------------------------------------------------------------------------

def test_cloud_and_shadow_pixels_are_excluded_from_valid():
    scl = np.full((50, 50), 4, dtype=np.uint8)
    scl[10:20, 10:20] = 9    # high probability cloud
    scl[30:35, 30:35] = 3    # cloud shadow
    scl[40, 40] = 2          # cast shadow

    mask = build_quality_mask(scl, (50, 50))

    assert mask.scl_available is True
    assert not mask.valid[10:20, 10:20].any(), "cloud must never be valid"
    assert not mask.valid[30:35, 30:35].any(), "shadow must never be valid"
    assert not mask.valid[40, 40].any()
    # 2500 - 100 cloud - 25 shadow - 1 shadow
    assert mask.valid.sum() == 2500 - 126


def test_aoi_mask_restricts_valid_pixels_to_the_aoi():
    scl = np.full((40, 40), 4, dtype=np.uint8)
    aoi = np.zeros((40, 40), dtype=bool)
    aoi[5:15, 5:15] = True

    mask = build_quality_mask(scl, (40, 40), aoi_mask=aoi)

    assert mask.valid.sum() == 100
    assert not (mask.valid & ~aoi).any()


def test_missing_scl_is_reported_not_silently_assumed_clear():
    """Without SCL the caller must be able to tell cloud screening did not happen."""
    cloud = np.full((30, 30), 4, dtype=np.uint8)
    cloud[0:5, 0:5] = 9
    aoi = np.ones((30, 30), dtype=bool)

    with_scl = build_quality_mask(cloud, (30, 30), aoi_mask=aoi)
    without_scl = build_quality_mask(None, (30, 30), aoi_mask=aoi)

    assert with_scl.scl_available is True
    assert without_scl.scl_available is False
    assert without_scl.valid_fraction > with_scl.valid_fraction


def test_nodata_and_saturation_are_flagged_separately():
    bands = np.full((10, 10), 1200.0)
    bands[0, 0] = 0.0            # no signal
    bands[1, 1] = np.nan
    bands[2, 2] = 10000.0        # saturated

    mask = build_quality_mask(None, (10, 10), bands={"b": bands})

    assert mask.nodata[0, 0]
    assert mask.nodata[1, 1]
    assert mask.saturated[2, 2]
    assert not mask.valid[0, 0]
    assert not mask.valid[2, 2]


def test_snow_handling_depends_on_monitoring_mode():
    scl = np.full((20, 20), 4, dtype=np.uint8)
    scl[5:15, 5:15] = 11       # snow / ice

    mask = build_quality_mask(scl, (20, 20))

    glacier_valid = mask.reject_for_mode("glacier").valid
    vegetation_valid = mask.reject_for_mode("vegetation").valid

    assert glacier_valid[5:15, 5:15].all(), "snow is real cover for glacier monitoring"
    assert not vegetation_valid[5:15, 5:15].any(), (
        "snow is a seasonal artefact for vegetation monitoring"
    )


def test_pair_mask_intersection_blocks_single_date_clouds():
    """
    The decisive regression: a cloud present in only one of two dates must not be
    compared, because that difference is not surface change.
    """
    baseline_scl = np.full((60, 60), 4, dtype=np.uint8)
    current_scl = baseline_scl.copy()
    current_scl[20:40, 20:40] = 9

    baseline = build_quality_mask(baseline_scl, (60, 60))
    current = build_quality_mask(current_scl, (60, 60))

    pair = observation_pair_mask(baseline, current)

    assert not pair[20:40, 20:40].any()
    assert pair.sum() == 60 * 60 - 400


def test_pair_mask_rejects_mismatched_grids():
    a = build_quality_mask(np.full((10, 10), 4), (10, 10))
    b = build_quality_mask(np.full((12, 12), 4), (12, 12))

    with pytest.raises(PreprocessingError):
        observation_pair_mask(a, b)


def test_quality_mask_summary_reports_fractions():
    scl = np.full((100, 100), 4, dtype=np.uint8)
    scl[:10, :10] = 9

    summary = build_quality_mask(scl, (100, 100)).summary()

    assert summary["total_pixels"] == 10000
    assert summary["cloud_fraction"] == pytest.approx(0.01)
    assert summary["valid_fraction"] == pytest.approx(0.99)


def test_scl_shape_mismatch_is_rejected():
    with pytest.raises(PreprocessingError):
        build_quality_mask(np.zeros((10, 10)), (20, 20))


# ---------------------------------------------------------------------------
# preprocessing: gap filling and integration
# ---------------------------------------------------------------------------

def test_nearest_fill_replaces_nodata_without_leaving_nans():
    array = np.arange(400.0).reshape(20, 20)
    array[:, :5] = np.nan

    filled = fill_masked(array, np.isfinite(array), method="nearest")

    assert not np.isnan(filled).any()
    assert filled[0, 0] == array[0, 5]


def test_fill_leaves_fully_masked_grid_untouched():
    array = np.full((10, 10), np.nan)
    filled = fill_masked(array, np.zeros((10, 10), dtype=bool))

    assert np.isnan(filled).all()


def test_preprocess_optical_returns_masked_profile_and_mask():
    height, width = 60, 60
    transform = GeoTransform.from_bounds(_bounds_for(width, height, 10.0), width, height)
    data = np.random.default_rng(1).uniform(800, 3000, (height, width))
    scl = np.full((height, width), 4, dtype=np.uint8)
    scl[10:20, 10:20] = 9

    profile = RasterProfile(array=data, transform=transform, crs="EPSG:4326")
    processed, mask = preprocess_optical(profile, scl_band=scl, fill_nodata=False)

    assert processed.transform == transform
    assert processed.crs == profile.crs
    assert not mask.valid[10:20, 10:20].any()
    assert np.isnan(processed.array[10:20, 10:20]).all()
    assert np.isfinite(processed.array[40:50, 40:50]).all()


def test_preprocess_sar_converts_linear_to_db_and_masks():
    height, width = 40, 40
    transform = GeoTransform.from_bounds(_bounds_for(width, height, 10.0), width, height)
    linear = np.full((height, width, 1), 0.05)   # linear backscatter
    aoi = np.ones((height, width), dtype=bool)
    aoi[0:5, 0:5] = False

    profile = RasterProfile(array=linear, transform=transform, crs="EPSG:4326")
    processed, mask = preprocess_sar(profile, aoi_mask=aoi, speckle_filter=None)

    assert processed.transform == transform
    # 10*log10(0.05) == -13.01 dB
    assert processed.array[20, 20] == pytest.approx(-13.01, abs=0.05)
    assert not mask.valid[0:5, 0:5].any()


def test_preprocess_sar_rejects_acquisition_missing_the_aoi():
    transform = GeoTransform.from_bounds(_bounds_for(20, 20, 10.0), 20, 20)
    profile = RasterProfile(
        array=np.full((20, 20, 1), np.nan), transform=transform, crs="EPSG:4326"
    )

    with pytest.raises(PreprocessingError):
        preprocess_sar(profile, speckle_filter=None)


# ---------------------------------------------------------------------------
# acquisition: georeferencing is preserved
# ---------------------------------------------------------------------------

def test_acquisition_preserves_georeferencing(monkeypatch, optical_scene):
    """The legacy provider read responses with tifffile and threw the transform away."""
    meta = json.dumps({
        "startDate": "2024-08-14T05:22:31Z",
        "platform": "SENTINEL-2A",
        "instrument": "MSI",
        "cloud_cover": 4.2,
    }).encode()
    body = _multipart([
        ("reflectance", optical_scene["reflectance_bytes"]),
        ("scl", optical_scene["scl_bytes"]),
        ("metadata", meta),
    ])
    _stub_post(monkeypatch, _FakeResponse(
        200, body, "multipart/form-data; boundary=testboundary123"))

    result = SentinelHubAcquirer(lambda: "token").acquire_sentinel2(
        optical_scene["bounds"],
        (datetime(2024, 8, 10, tzinfo=timezone.utc),
         datetime(2024, 8, 20, tzinfo=timezone.utc)),
        bands=("B02", "B03", "B04", "B08"),
        resolution_m=10.0,
    )

    assert "4326" in str(result.profile.crs)
    assert result.profile.pixel_area_m2() == pytest.approx(100.0, rel=0.05)

    # A pixel index must resolve to a real coordinate inside the requested AOI.
    lon, lat = result.profile.pixel_to_lonlat(50, 55)
    assert optical_scene["bounds"][0] <= lon <= optical_scene["bounds"][2]
    assert optical_scene["bounds"][1] <= lat <= optical_scene["bounds"][3]


def test_acquisition_requests_native_resolution_not_a_fixed_grid(monkeypatch, optical_scene):
    captured = {}

    def _post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _FakeResponse(200, b"", "application/json")

    monkeypatch.setattr(acq_module.requests, "post", _post)
    acquirer = SentinelHubAcquirer(lambda: "token")
    with pytest.raises(AcquisitionError):
        acquirer.acquire_sentinel2(
            optical_scene["bounds"],
            (datetime(2024, 8, 10, tzinfo=timezone.utc),
             datetime(2024, 8, 20, tzinfo=timezone.utc)),
            resolution_m=10.0,
        )

    assert captured["payload"]["output"]["resx"] == 10.0
    assert captured["payload"]["output"]["resy"] == 10.0
    assert "256" not in json.dumps(captured["payload"]), (
        "the request must not encode the legacy fixed 256x256 grid"
    )


def test_scl_is_nearest_resampled_without_inventing_class_codes(monkeypatch, optical_scene):
    meta = json.dumps({"startDate": "2024-08-14T05:22:31Z"}).encode()
    body = _multipart([
        ("reflectance", optical_scene["reflectance_bytes"]),
        ("scl", optical_scene["scl_bytes"]),
        ("metadata", meta),
    ])
    _stub_post(monkeypatch, _FakeResponse(
        200, body, "multipart/form-data; boundary=testboundary123"))

    result = SentinelHubAcquirer(lambda: "token").acquire_sentinel2(
        optical_scene["bounds"],
        (datetime(2024, 8, 10, tzinfo=timezone.utc),
         datetime(2024, 8, 20, tzinfo=timezone.utc)),
        resolution_m=10.0,
    )

    assert result.scl is not None
    assert result.scl.shape == (optical_scene["height"], optical_scene["width"])
    # Nearest neighbour must not blend class codes into values that mean nothing.
    assert set(np.unique(result.scl)).issubset({4.0, 5.0, 6.0, 9.0})


def test_cloud_cover_gate_rejects_unusable_scenes(monkeypatch, optical_scene):
    meta = json.dumps({
        "startDate": "2024-08-14T05:22:31Z",
        "cloud_cover": 87.5,
    }).encode()
    body = _multipart([
        ("reflectance", optical_scene["reflectance_bytes"]),
        ("scl", optical_scene["scl_bytes"]),
        ("metadata", meta),
    ])
    _stub_post(monkeypatch, _FakeResponse(
        200, body, "multipart/form-data; boundary=testboundary123"))

    with pytest.raises(CloudCoverTooHighError):
        SentinelHubAcquirer(lambda: "token").acquire_sentinel2(
            optical_scene["bounds"],
            (datetime(2024, 8, 1, tzinfo=timezone.utc),
             datetime(2024, 8, 31, tzinfo=timezone.utc)),
            max_cloud_cover=20.0,
        )


# ---------------------------------------------------------------------------
# acquisition: failure handling must never fabricate data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status_code,expected",
    [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (404, NoValidImageError),
    ],
)
def test_http_failures_map_to_typed_errors(monkeypatch, optical_scene, status_code, expected):
    _stub_post(monkeypatch, _FakeResponse(status_code, b"", "application/json"))

    with pytest.raises(expected):
        SentinelHubAcquirer(lambda: "token", backoff_seconds=0).acquire_sentinel2(
            optical_scene["bounds"],
            (datetime(2024, 8, 1, tzinfo=timezone.utc),
             datetime(2024, 8, 31, tzinfo=timezone.utc)),
        )


def test_server_errors_are_retried_then_reported(monkeypatch, optical_scene):
    attempts = {"count": 0}

    def _post(*args, **kwargs):
        attempts["count"] += 1
        return _FakeResponse(500, b"boom", "application/json")

    monkeypatch.setattr(acq_module.requests, "post", _post)

    with pytest.raises(AcquisitionError):
        SentinelHubAcquirer(
            lambda: "token", max_attempts=3, backoff_seconds=0
        ).acquire_sentinel2(
            optical_scene["bounds"],
            (datetime(2024, 8, 1, tzinfo=timezone.utc),
             datetime(2024, 8, 31, tzinfo=timezone.utc)),
        )

    assert attempts["count"] == 3


def test_missing_credentials_raise_instead_of_returning_synthetic_data(optical_scene):
    with pytest.raises(AuthenticationError):
        SentinelHubAcquirer(lambda: None).acquire_sentinel2(
            optical_scene["bounds"],
            (datetime(2024, 8, 1, tzinfo=timezone.utc),
             datetime(2024, 8, 31, tzinfo=timezone.utc)),
        )


def test_response_without_reflectance_raises(monkeypatch, optical_scene):
    """A scene that misses the AOI must surface as an error, not zero-filled imagery."""
    body = _multipart([("scl", optical_scene["scl_bytes"])])
    _stub_post(monkeypatch, _FakeResponse(
        200, body, "multipart/form-data; boundary=testboundary123"))

    with pytest.raises(NoValidImageError):
        SentinelHubAcquirer(lambda: "token").acquire_sentinel2(
            optical_scene["bounds"],
            (datetime(2024, 8, 1, tzinfo=timezone.utc),
             datetime(2024, 8, 31, tzinfo=timezone.utc)),
        )


def test_sentinel1_request_pins_orbit_direction_and_polarisation_order(
    monkeypatch, optical_scene
):
    captured = {}

    def _post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _FakeResponse(200, optical_scene["reflectance_bytes"], "image/tiff")

    monkeypatch.setattr(acq_module.requests, "post", _post)
    try:
        SentinelHubAcquirer(lambda: "token").acquire_sentinel1(
            optical_scene["bounds"],
            (datetime(2024, 8, 1, tzinfo=timezone.utc),
             datetime(2024, 8, 31, tzinfo=timezone.utc)),
            orbit_direction="ASCENDING",
        )
    except AcquisitionError:
        pass  # response body is not a real S1 scene; the request shape is what matters

    payload = captured["payload"]
    data_filter = payload["input"]["data"][0]["dataFilter"]

    # Differencing ascending against descending passes is invalid: viewing geometry
    # differs, so backscatter changes without any surface change.
    assert data_filter["orbitDirection"] == "ASCENDING"
    assert "sample.VV" in payload["evalscript"]
    assert "sample.VH" in payload["evalscript"]
    assert payload["output"]["resx"] == 10.0


def test_reject_class_list_excludes_every_atmospheric_scl_code():
    """Guard the class table: adding a class here changes change-detection validity."""
    # Class 7 is "unclassified / low probability cloud" and must be rejected: it is
    # cloud, and treating it as usable would let cloud through as valid data.
    for atmospheric in (0, 1, 2, 3, 7, 8, 9, 10):
        assert atmospheric in SCL_REJECT_CLASSES
    for surface in (4, 5, 6, 11):
        assert surface not in SCL_REJECT_CLASSES


def test_low_probability_cloud_class_is_actually_masked():
    """SCL_REJECT_CLASSES must agree with the validity mask that is really applied."""
    grid = np.array([[4, 5, 6], [7, 8, 9]], dtype=np.uint8)
    valid = build_quality_mask(grid, grid.shape).valid
    assert not valid[1, 0], "class 7 must not count as valid"
    assert valid[0].all(), "clear, vegetation and water classes must stay usable"


def test_request_only_advertises_responses_the_evalscript_defines(monkeypatch, optical_scene):
    """Asking for an undeclared output makes the Process API reject the request."""
    captured = {}

    def _post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _FakeResponse(200, optical_scene["reflectance_bytes"], "image/tiff")

    monkeypatch.setattr(acq_module.requests, "post", _post)
    bounds = optical_scene["bounds"]
    window = (datetime(2024, 6, 1, tzinfo=timezone.utc),
              datetime(2024, 6, 30, tzinfo=timezone.utc))

    for include_scl, expected in ((True, ["reflectance", "scl"]),
                                  (False, ["reflectance"])):
        try:
            SentinelHubAcquirer(lambda: "token").acquire_sentinel2(
                bounds, window, include_scl=include_scl
            )
        except AcquisitionError:
            pass  # the stub body is not a real S2 scene; the request shape is what matters
        payload = captured["payload"]
        assert [r["identifier"] for r in payload["output"]["responses"]] == expected
        declared = payload["evalscript"].split("output:")[1].split("function")[0]
        for identifier in expected:
            assert identifier in declared, "advertised response missing from evalscript"
        if not include_scl:
            assert "SCL" not in payload["evalscript"], "SCL must not be sampled at all"


def test_sentinel1_declared_inputs_match_the_requested_polarisations(monkeypatch, optical_scene):
    """A hard-coded input list silently returns the wrong band for other polarisations."""
    captured = {}

    def _post(*args, **kwargs):
        captured["payload"] = kwargs.get("json")
        return _FakeResponse(200, optical_scene["reflectance_bytes"], "image/tiff")

    monkeypatch.setattr(acq_module.requests, "post", _post)
    try:
        SentinelHubAcquirer(lambda: "token").acquire_sentinel1(
            optical_scene["bounds"],
            (datetime(2024, 8, 1, tzinfo=timezone.utc),
             datetime(2024, 8, 31, tzinfo=timezone.utc)),
            polarizations=("VV",),
        )
    except AcquisitionError:
        pass

    evalscript = captured["payload"]["evalscript"]
    declared = evalscript.split("input:")[1].split("]", 1)[0].strip() + "]"
    assert declared == '["VV"]', "declared inputs must match the requested polarisations"
    assert "sample.VV" in evalscript
    assert "sample.VH" not in evalscript