"""
tests/test_geospatial_core.py
Tests for the generic AOI abstraction and georeferenced raster primitives.

Covers:
  - AOI construction from every supported input form (point / bbox / polygon /
    GeoJSON / geometry object / place name)
  - Geodesic area correctness
  - Affine transform inversion and round-tripping
  - GeoTIFF CRS + transform persistence
  - Pixel-to-coordinate geolocation
  - Mask-to-polygon conversion with true geographic output
  - Co-registration / alignment validation
  - Monitoring-mode sensor selection
  - Arbitrary worldwide AOIs (no hard-coded location support)
"""

import math

import numpy as np
import pytest
from shapely.geometry import Polygon

from satguard.geospatial.area_of_interest import (
    AOI,
    AOITooLargeError,
    InvalidGeometryError,
    MonitoringMode,
    SensorStrategy,
    UnsupportedAOIInputError,
    aoi_from_bbox,
    aoi_from_critical_location,
    aoi_from_point,
    aoi_from_polygon,
    build_aoi,
    get_mode_profile,
)
from satguard.geospatial.raster import (
    GEOGRAPHIC_CRS,
    GeoTransform,
    RasterError,
    RasterProfile,
    check_alignment,
    geographic_area_m2,
    polygons_from_mask,
    rasterize_geometry,
    read_geotiff,
    utm_crs_for,
    write_geotiff,
)


# ---------------------------------------------------------------------------
# AOI construction from all supported input forms
# ---------------------------------------------------------------------------

DELHI_SQUARE = [
    [77.1990, 28.6039],
    [77.2190, 28.6039],
    [77.2190, 28.6239],
    [77.1990, 28.6239],
    [77.1990, 28.6039],
]


def test_aoi_schema_contains_all_required_fields():
    aoi = aoi_from_point(28.6139, 77.2090, radius_m=1500,
                         monitoring_mode="infrastructure", user_label="Delhi")
    payload = aoi.to_dict()
    for key in ("id", "geometry", "bbox", "center_lat", "center_lon",
                "area_km2", "crs", "user_label", "monitoring_mode"):
        assert key in payload, f"missing required AOI field: {key}"
    assert payload["crs"] == GEOGRAPHIC_CRS
    assert payload["monitoring_mode"] == "infrastructure"


def test_aoi_from_point_area_is_geodesically_correct():
    radius_m = 1500.0
    aoi = aoi_from_point(28.6139, 77.2090, radius_m=radius_m)
    expected_km2 = math.pi * (radius_m / 1000.0) ** 2
    # 64-gon inscribed in a circle underestimates by ~(1 - pi/(3n)) ~ 1.6%
    assert aoi.area_km2 == pytest.approx(expected_km2, rel=0.02)
    assert aoi.area_km2 == pytest.approx(7.0686, rel=0.02)


def test_aoi_area_at_multiple_latitudes_matches_planar_expectation():
    """Area must not be computed with a flat-earth degree approximation."""
    for lat, lon in [(0.0, 0.0), (28.61, 77.21), (35.55, 77.0), (-33.87, 151.21), (64.15, -21.94)]:
        aoi = aoi_from_point(lat, lon, radius_m=2000.0, validate=False)
        expected = math.pi * 4.0  # km2 for r=2km
        assert aoi.area_km2 == pytest.approx(expected, rel=0.02), f"latitude {lat}"


def test_all_input_forms_agree():
    forms = [
        build_aoi(bbox=[77.1990, 28.6039, 77.2190, 28.6239], validate=False),
        build_aoi(polygon=DELHI_SQUARE, validate=False),
        build_aoi(geojson={"type": "Polygon", "coordinates": [DELHI_SQUARE]}, validate=False),
        build_aoi(geometry={"type": "Polygon", "coordinates": [DELHI_SQUARE]}, validate=False),
    ]
    reference = forms[0]
    for aoi in forms[1:]:
        assert aoi.area_km2 == pytest.approx(reference.area_km2, rel=1e-6)
        assert aoi.center_lat == pytest.approx(reference.center_lat, rel=1e-6)
        assert aoi.center_lon == pytest.approx(reference.center_lon, rel=1e-6)


def test_build_aoi_rejects_missing_and_ambiguous_input():
    with pytest.raises(UnsupportedAOIInputError):
        build_aoi()
    with pytest.raises(UnsupportedAOIInputError):
        build_aoi(bbox=[0, 0, 1, 1], polygon=DELHI_SQUARE)


def test_aoi_handles_polygon_with_hole():
    outer = [[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, 0.1], [0.0, 0.0]]
    hole = [[0.03, 0.03], [0.07, 0.03], [0.07, 0.07], [0.03, 0.07], [0.03, 0.03]]
    aoi = aoi_from_polygon([outer, hole], validate=False)
    full = geographic_area_m2(Polygon(outer))
    assert aoi.area_m2 < full


def test_aoi_rejects_invalid_coordinates():
    with pytest.raises(InvalidGeometryError):
        aoi_from_point(95.0, 10.0, radius_m=100)
    with pytest.raises(InvalidGeometryError):
        aoi_from_point(10.0, 200.0, radius_m=100)
    with pytest.raises(InvalidGeometryError):
        aoi_from_point(10.0, 10.0, radius_m=-5)


def test_aoi_rejects_oversized_extent():
    with pytest.raises(AOITooLargeError):
        aoi_from_point(28.61, 77.21, radius_m=200_000)


# ---------------------------------------------------------------------------
# Arbitrary AOIs: the platform must not be tied to any one location
# ---------------------------------------------------------------------------

ARBITRARY_LOCATIONS = [
    ("Antarctica", -77.85, 166.67),
    ("Reykjavik", 64.1466, -21.9426),
    ("Cusco Peru", -13.5319, -71.9675),
    ("Svalbard", 78.2232, 15.6267),
    ("Jakarta", -6.2088, 106.8456),
    ("Lagos", 6.5244, 3.3792),
    ("Ushuaia", -54.8019, -68.3030),
    ("Ulaanbaatar", 47.8864, 106.9057),
]


@pytest.mark.parametrize("name,lat,lon", ARBITRARY_LOCATIONS)
def test_arbitrary_aoi_worldwide(name, lat, lon):
    aoi = aoi_from_point(lat, lon, radius_m=5000.0, monitoring_mode="general")
    assert aoi.area_km2 == pytest.approx(78.54, rel=0.02)
    assert aoi.utm_crs().startswith(("EPSG:326", "EPSG:327"))
    assert -180 <= aoi.center_lon <= 180
    assert -90 <= aoi.center_lat <= 90


@pytest.mark.parametrize("name,lat,lon", ARBITRARY_LOCATIONS)
def test_arbitrary_aoi_grid_and_mask(name, lat, lon):
    aoi = aoi_from_point(lat, lon, radius_m=4000.0, validate=False)
    transform, width, height = aoi.transform_for(30.0)
    mask = aoi.mask_for(transform, (height, width))
    assert mask.any()
    masked_area_km2 = mask.sum() * transform.pixel_area_m2(aoi.center_lat) / 1e6
    assert masked_area_km2 == pytest.approx(aoi.area_km2, rel=0.02)


def test_utm_zone_selection():
    assert utm_crs_for(77.21, 28.61) == "EPSG:32643"   # northern India
    assert utm_crs_for(-68.30, -54.80) == "EPSG:32719"  # southern Argentina (zone 19)
    assert utm_crs_for(180.0, 0.0) in ("EPSG:32660", "EPSG:32760")


# ---------------------------------------------------------------------------
# Monitoring mode / sensor selection
# ---------------------------------------------------------------------------

def test_every_monitoring_mode_resolves_to_a_sensor_strategy():
    for mode in MonitoringMode:
        profile = get_mode_profile(mode)
        assert profile.strategy in SensorStrategy
        assert profile.indices, f"{mode} defines no spectral indices"
        assert profile.required_bands, f"{mode} defines no required bands"


def test_sensor_selection_differs_by_domain():
    veg = get_mode_profile("vegetation").strategy
    flood = get_mode_profile("flood").strategy
    glacier = get_mode_profile("glacier").strategy
    # Vegetation condition is an optical task; flood mapping relies on SAR.
    assert veg == SensorStrategy.OPTICAL
    assert flood == SensorStrategy.OPTICAL_AND_SAR
    assert glacier == SensorStrategy.OPTICAL_AND_SAR


def test_monitoring_mode_is_recorded_on_aoi():
    aoi = aoi_from_point(28.61, 77.21, radius_m=1000, monitoring_mode="glacier")
    assert aoi.monitoring_mode is MonitoringMode.GLACIER
    assert aoi.to_dict()["monitoring_mode"] == "glacier"
    assert "ndsi" in aoi.profile.indices


def test_unknown_monitoring_mode_is_rejected():
    with pytest.raises(UnsupportedAOIInputError):
        get_mode_profile("volcanic_eruption")


# ---------------------------------------------------------------------------
# Affine transform correctness
# ---------------------------------------------------------------------------

def test_transform_roundtrip_is_lossless():
    transform = GeoTransform.from_bounds((77.10, 28.55, 77.15, 28.60), 500, 500)
    rng = np.random.default_rng(0)
    for _ in range(500):
        col = rng.uniform(0, 500)
        row = rng.uniform(0, 500)
        lon, lat = transform.pixel_to_lonlat(col, row)
        col2, row2 = transform.lonlat_to_pixel(lon, lat)
        assert col2 == pytest.approx(col, abs=1e-6)
        assert row2 == pytest.approx(row, abs=1e-6)


def test_pixel_area_is_accurate_for_geographic_grid():
    """A grid built from true 10 m spacing must report ~100 m2 pixels."""
    for lat in [0.0, 28.57, 45.0, 60.0, 77.0]:
        lat_rad = math.radians(lat)
        m_lat = (111132.92 - 559.82 * math.cos(2 * lat_rad)
                 + 1.175 * math.cos(4 * lat_rad))
        m_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)
        transform = GeoTransform.from_bounds(
            (77.0, lat, 77.0 + 10.0 / m_lon, lat + 10.0 / m_lat), 1, 1
        )
        assert transform.pixel_area_m2(lat) == pytest.approx(100.0, rel=0.001)


def test_transform_rejects_degenerate_bounds():
    with pytest.raises(RasterError):
        GeoTransform.from_bounds((10.0, 10.0, 10.0, 20.0), 10, 10)
    with pytest.raises(RasterError):
        GeoTransform.from_bounds((0.0, 0.0, 1.0, 1.0), 0, 10)


# ---------------------------------------------------------------------------
# GeoTIFF persistence: CRS and transform must survive a write/read cycle
# ---------------------------------------------------------------------------

def test_geotiff_preserves_crs_and_transform(tmp_path):
    bounds = (77.10, 28.55, 77.15, 28.60)
    transform = GeoTransform.from_bounds(bounds, 250, 250)
    array = np.random.default_rng(1).random((250, 250)).astype(np.float32)

    path = write_geotiff(tmp_path / "band.tif", array, transform, GEOGRAPHIC_CRS)
    profile = read_geotiff(path)

    assert profile.crs == GEOGRAPHIC_CRS
    assert profile.transform.a == pytest.approx(transform.a, rel=1e-9)
    assert profile.transform.c == pytest.approx(transform.c, rel=1e-9)
    assert profile.transform.f == pytest.approx(transform.f, rel=1e-9)
    assert profile.bounds == pytest.approx(bounds, abs=1e-9)
    assert profile.array.shape == (250, 250)


def test_geotiff_preserves_multiband(tmp_path):
    transform = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 60, 60)
    array = np.random.default_rng(2).random((60, 60, 3)).astype(np.float32)
    path = write_geotiff(tmp_path / "rgb.tif", array, transform, GEOGRAPHIC_CRS,
                         band_names=["R", "G", "B"])
    profile = read_geotiff(path)
    assert profile.array.shape == (60, 60, 3)
    assert profile.band_count == 3
    assert profile.band(1).shape == (60, 60)


def test_geotiff_is_readable_by_gdal(tmp_path):
    """The artifact must be a genuine GeoTIFF, not a plain TIFF."""
    import rasterio
    transform = GeoTransform.from_bounds((77.0, 28.5, 77.05, 28.55), 32, 32)
    array = np.zeros((32, 32), dtype=np.float32)
    path = write_geotiff(tmp_path / "real.tif", array, transform)
    with rasterio.open(path) as src:
        assert src.crs is not None
        assert src.crs.to_epsg() == 4326
        assert src.transform is not None
        assert src.transform.a == pytest.approx(transform.a, rel=1e-9)


# ---------------------------------------------------------------------------
# Geolocation: pixel -> real geographic coordinates
# ---------------------------------------------------------------------------

def test_mask_polygonization_yields_true_coordinates(tmp_path):
    bounds = (77.10, 28.55, 77.15, 28.60)
    transform = GeoTransform.from_bounds(bounds, 500, 500)
    mask = np.zeros((500, 500), dtype=bool)
    mask[100:140, 200:260] = True

    regions = polygons_from_mask(mask, transform, min_pixels=10)
    assert len(regions) == 1
    region = regions[0]

    assert region["pixel_count"] == 40 * 60
    # The block is 40 rows x 60 cols of ~10 m pixels -> tens of thousands of m2.
    assert region["area_m2"] > 0

    # Centroid must map back into the block.
    col, row = transform.lonlat_to_pixel(region["centroid_lon"], region["centroid_lat"])
    assert 200 <= col <= 260
    assert 100 <= row <= 140

    # GeoJSON geometry must be a valid polygon in lon/lat.
    assert region["geometry"]["type"] in ("Polygon", "MultiPolygon")
    minx, miny, maxx, maxy = region["bbox"]
    assert 77.10 <= minx <= 77.15
    assert 28.55 <= miny <= 28.60
    assert minx < maxx and miny < maxy


def test_mask_polygonization_drops_isolated_noise():
    transform = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 200, 200)
    mask = np.zeros((200, 200), dtype=bool)
    mask[50:70, 50:70] = True       # 400 px real region
    mask[0, 0] = True               # isolated noise
    mask[199, 5] = True
    mask[120, 120] = True

    assert len(polygons_from_mask(mask, transform, min_pixels=10)) == 1
    assert len(polygons_from_mask(mask, transform, min_pixels=1)) == 4


def test_empty_mask_returns_no_regions():
    transform = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 50, 50)
    assert polygons_from_mask(np.zeros((50, 50), dtype=bool), transform) == []


def test_mask_polygonization_sorts_by_area_descending():
    transform = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 300, 300)
    mask = np.zeros((300, 300), dtype=bool)
    mask[10:40, 10:40] = True     # 900 px
    mask[150:220, 150:250] = True  # 4900 px
    regions = polygons_from_mask(mask, transform, min_pixels=5)
    assert len(regions) == 2
    assert regions[0]["area_m2"] > regions[1]["area_m2"]
    assert regions[0]["region_id"] == 1


def test_rasterize_geometry_is_georeferenced():
    aoi = aoi_from_point(28.6139, 77.2090, radius_m=2000.0, validate=False)
    transform, width, height = aoi.transform_for(10.0)
    mask = rasterize_geometry(aoi.geometry, transform, (height, width))
    assert mask.sum() > 0

    masked_km2 = mask.sum() * transform.pixel_area_m2(aoi.center_lat) / 1e6
    assert masked_km2 == pytest.approx(aoi.area_km2, rel=0.01)


# ---------------------------------------------------------------------------
# Co-registration validation
# ---------------------------------------------------------------------------

def test_check_alignment_accepts_identical_grids():
    transform = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 100, 100)
    a = RasterProfile(array=np.zeros((100, 100)), transform=transform)
    b = RasterProfile(array=np.zeros((100, 100)), transform=transform)
    result = check_alignment(a, b)
    assert result["aligned"] is True


def test_check_alignment_rejects_offset_grid():
    base = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 100, 100)
    shifted = GeoTransform(
        a=base.a, b=base.b, c=base.c + 0.003,
        d=base.d, e=base.e, f=base.f,
    )
    a = RasterProfile(array=np.zeros((100, 100)), transform=base)
    b = RasterProfile(array=np.zeros((100, 100)), transform=shifted)
    result = check_alignment(a, b, tolerance_pixels=0.5)
    assert result["aligned"] is False
    assert "co-registration" in result["reason"].lower()


def test_check_alignment_rejects_crs_mismatch():
    t = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 100, 100)
    a = RasterProfile(array=np.zeros((100, 100)), transform=t, crs="EPSG:4326")
    b = RasterProfile(array=np.zeros((100, 100)), transform=t, crs="EPSG:32643")
    result = check_alignment(a, b)
    assert result["aligned"] is False
    assert "CRS mismatch" in result["reason"]


def test_check_alignment_rejects_resolution_mismatch():
    a = RasterProfile(
        array=np.zeros((100, 100)),
        transform=GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 100, 100),
    )
    b = RasterProfile(
        array=np.zeros((200, 200)),
        transform=GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 200, 200),
    )
    result = check_alignment(a, b)
    assert result["aligned"] is False
    assert "Pixel size mismatch" in result["reason"]


# ---------------------------------------------------------------------------
# RasterProfile behaviour
# ---------------------------------------------------------------------------

def test_raster_profile_subwindow_preserves_georeferencing():
    transform = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 200, 200)
    array = np.arange(200 * 200, dtype=np.float64).reshape(200, 200)
    profile = RasterProfile(array=array, transform=transform)

    window = profile.subwindow((77.02, 28.55, 77.06, 28.58))
    assert window.height < profile.height
    assert window.width < profile.width
    # The transform must still place a known pixel at its true coordinate.
    col, row = window.transform.lonlat_to_pixel(77.03, 28.565)
    value = window.array[int(row), int(col)]
    # Locate the same value in the source array and confirm the coordinate matches.
    src_row, src_col = np.unravel_index(int(value), array.shape)
    assert transform.pixel_to_lonlat(src_col + 0.5, src_row + 0.5)[0] == pytest.approx(
        window.transform.pixel_to_lonlat(col + 0.5, row + 0.5)[0], abs=1e-9
    )


def test_raster_profile_valid_mask_excludes_nan():
    transform = GeoTransform.from_bounds((77.0, 28.5, 77.1, 28.6), 10, 10)
    array = np.ones((10, 10))
    array[0, 0] = np.nan
    array[1, 1] = np.nan
    profile = RasterProfile(array=array, transform=transform)
    valid = profile.valid_mask()
    assert valid.sum() == 98
    assert not valid[0, 0]


def test_raster_profile_rejects_zero_size_transform():
    array = np.ones((5, 5))
    with pytest.raises(RasterError):
        RasterProfile(array=array, transform=GeoTransform(0, 0, 0, 0, 0, 0))


def test_raster_profile_reproject_to_utm():
    transform = GeoTransform.from_bounds((77.19, 28.60, 77.24, 28.65), 100, 100)
    profile = RasterProfile(array=np.ones((100, 100)), transform=transform)
    projected = profile.reproject_to("EPSG:32643")
    assert "32643" in projected.crs
    assert projected.array.shape[0] > 0
    # A projected-CRS pixel area is now expressed in square metres on the ground.
    px_area = projected.pixel_area_m2()
    assert 1.0 < px_area < 10_000.0, px_area
    # Reprojection must land on the correct UTM easting/northing for Delhi.
    easting, northing = projected.center_lonlat
    assert 700_000 < easting < 730_000, easting
    assert 3_150_000 < northing < 3_185_000, northing
    # A projected CRS needs no latitude correction.
    assert projected.is_geographic is False


# ---------------------------------------------------------------------------
# Legacy bridge: configured sample locations must keep working
# ---------------------------------------------------------------------------

class _FakeLocation:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_aoi_from_critical_location_with_polygon():
    aoi = aoi_from_critical_location(_FakeLocation(
        id="loc-test", name="Test Dam", location_type="dam",
        risk_category="structural", priority="critical",
        latitude=30.3781, longitude=78.4803, radius_m=8000, geometry=None,
    ))
    assert aoi.id == "loc-test"
    assert aoi.user_label == "Test Dam"
    assert aoi.source == "critical_location"
    assert aoi.area_km2 == pytest.approx(201.06, rel=0.02)  # pi * 8^2


def test_aoi_from_critical_location_prefers_stored_geometry():
    poly = Polygon([(77.19, 28.60), (77.21, 28.60), (77.21, 28.62), (77.19, 28.62)])
    aoi = aoi_from_critical_location(_FakeLocation(
        id="loc-geo", name="Geo Dam", location_type="dam",
        risk_category="structural", priority="routine",
        latitude=28.61, longitude=77.20, radius_m=8000, geometry=poly.wkt,
    ))
    assert aoi.source == "critical_location"
    assert aoi.center_lat == pytest.approx(28.61, abs=0.01)
    assert aoi.area_km2 < 10.0


def test_all_repository_sample_locations_build_valid_aois():
    """The 10 seeded locations must all produce usable AOIs."""
    from satguard.config import settings
    for entry in settings.get_critical_locations():
        aoi = aoi_from_critical_location(_FakeLocation(
            id=entry["id"],
            name=entry["name"],
            location_type=entry.get("location_type"),
            risk_category=entry.get("risk_category"),
            priority=entry.get("priority"),
            latitude=float(entry["latitude"]),
            longitude=float(entry["longitude"]),
            radius_m=int(entry["radius_meters"]),
            geometry=None,
        ))
        assert aoi.area_km2 > 0
        assert aoi.utm_crs().startswith(("EPSG:326", "EPSG:327"))
        transform, w, h = aoi.transform_for(60.0)
        assert w > 0 and h > 0