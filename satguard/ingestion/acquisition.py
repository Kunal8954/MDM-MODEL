"""
satguard/ingestion/acquisition.py
Georeferenced Sentinel-2 / Sentinel-1 acquisition for arbitrary AOIs.

This replaces the legacy fixed 256x256 retrieval in
`CopernicusSatelliteProvider.retrieve_aoi_bands`, which had two disqualifying defects:

  1. It forced every AOI to a 256x256 grid regardless of size, so an 8 km radius AOI
     was resampled to 62 m pixels -- a single building occupies a fraction of one pixel
     and cannot be detected.
  2. It read the response with `tifffile.imread`, discarding the affine transform and
     CRS that the Sentinel Hub returns, so nothing downstream could be geolocated.

Requests here specify a ground resolution in metres, request the Scene Classification
Layer alongside the spectral bands, and preserve the returned georeferencing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import requests

from satguard.geospatial.raster import GeoTransform, RasterProfile, read_geotiff

logger = logging.getLogger("satguard.acquisition")

SENTINEL_HUB_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Native Sentinel-2 L2A resolutions in metres, by band.
S2_BAND_RESOLUTION: Dict[str, float] = {
    "B01": 60.0, "B02": 10.0, "B03": 10.0, "B04": 10.0,
    "B05": 20.0, "B06": 20.0, "B07": 20.0, "B08": 10.0,
    "B8A": 20.0, "B09": 60.0, "B11": 20.0, "B12": 20.0,
}

# Scene Classification Layer is delivered at 20 m.
SCL_RESOLUTION = 20.0


class AcquisitionError(Exception):
    """Base class for acquisition failures. Carries an operational error code."""

    error_code = "DOWNLOAD_FAILED"


class AuthenticationError(AcquisitionError):
    error_code = "API_AUTH_ERROR"


class NoValidImageError(AcquisitionError):
    error_code = "NO_VALID_IMAGE"


class CloudCoverTooHighError(AcquisitionError):
    error_code = "CLOUD_COVER_TOO_HIGH"


class AOICoverageError(AcquisitionError):
    error_code = "AOI_OUTSIDE_COVERAGE"


class InsufficientTemporalDataError(AcquisitionError):
    error_code = "INSUFFICIENT_TEMPORAL_DATA"


@dataclass
class AcquisitionResult:
    """
    One acquired, georeferenced observation.

    `profile` always carries the affine transform and CRS, so every pixel index in the
    array is convertible to a real longitude and latitude.
    """
    profile: RasterProfile
    scl: Optional[np.ndarray]
    acquisition_time: datetime
    platform: str
    instrument: str
    collection: str
    product_id: Optional[str] = None
    cloud_cover: Optional[float] = None
    epsg: int = 4326
    source: str = "LIVE"
    evalscript_version: str = "3"

    band_names: Optional[List[str]] = None

    @property
    def width(self) -> int:
        return self.profile.width

    @property
    def height(self) -> int:
        return self.profile.height

    @property
    def pixel_area_m2(self) -> float:
        return self.profile.pixel_area_m2()

    def metadata(self) -> Dict[str, Any]:
        meta = {
            "acquisition_time": self.acquisition_time.isoformat(),
            "platform": self.platform,
            "instrument": self.instrument,
            "collection": self.collection,
            "product_id": self.product_id,
            "cloud_cover": self.cloud_cover,
            "crs": f"EPSG:{self.epsg}",
            "resolution_m": round(
                float(np.sqrt(self.pixel_area_m2)), 3
            ),
            "width": self.width,
            "height": self.height,
            "coverage_area_km2": round(
                self.width * self.height * self.pixel_area_m2 / 1e6, 4
            ),
            "bounds": [round(v, 8) for v in self.profile.bounds],
            "band_names": self.band_names,
            "has_scl": self.scl is not None,
            "source": self.source,
        }
        return meta


class SentinelHubAcquirer:
    """
    Retrieves georeferenced Sentinel-2 (optical) and Sentinel-1 (SAR) observations
    for an arbitrary AOI from the Copernicus Data Space Ecosystem.
    """

    def __init__(
        self,
        access_token_provider: Any,
        timeout: float = 60.0,
        max_attempts: int = 3,
        backoff_seconds: float = 2.0,
    ):
        """
        Args:
            access_token_provider: Callable returning a valid CDSE bearer token.
            timeout: Per-request timeout in seconds.
            max_attempts: Retry budget for transient failures.
        """
        self._token_provider = access_token_provider
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds

    # ------------------------------------------------------------------
    # Sentinel-2 optical
    # ------------------------------------------------------------------

    def acquire_sentinel2(
        self,
        bbox: Tuple[float, float, float, float],
        time_range: Tuple[datetime, datetime],
        bands: Sequence[str] = ("B02", "B03", "B04", "B08"),
        resolution_m: float = 10.0,
        include_scl: bool = True,
        max_cloud_cover: Optional[float] = None,
        mosaicking: str = "ORBIT",
    ) -> AcquisitionResult:
        """
        Acquire a Sentinel-2 L2A observation clipped to `bbox`.

        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat) in EPSG:4326.
            time_range: (start, end) acquisition window.
            bands: Spectral bands to retrieve.
            resolution_m: Ground resolution. Bands coarser than this are upsampled by
                the service to the requested grid, which is required for index maths.
            include_scl: Request the Scene Classification Layer for cloud masking.
            max_cloud_cover: When set, reject the acquisition if the returned scene's
                cloud cover exceeds it.
            mosaicking: Sentinel Hub mosaicking strategy; ORBIT keeps a single
                acquisition, which is required for valid change detection.
        """
        requested = list(dict.fromkeys(list(bands) + (["SCL"] if include_scl else [])))
        payload = self._build_s2_payload(
            bbox, time_range, requested, resolution_m, mosaicking
        )
        profile, scl, meta = self._execute_process_request(payload)

        acquisition_time = self._parse_acquisition_time(meta, fallback=time_range[1])

        if max_cloud_cover is not None:
            cloud = meta.get("cloud_cover")
            if cloud is not None and float(cloud) > max_cloud_cover:
                raise CloudCoverTooHighError(
                    f"Scene cloud cover {float(cloud):.1f}% exceeds the "
                    f"{max_cloud_cover:.1f}% limit for the requested window."
                )

        band_names = [b for b in bands]
        return AcquisitionResult(
            profile=profile,
            scl=scl,
            acquisition_time=acquisition_time,
            platform=meta.get("platform", "SENTINEL-2"),
            instrument=meta.get("instrument", "MSI"),
            collection=meta.get("collection", "sentinel-2-l2a"),
            product_id=meta.get("product_id"),
            cloud_cover=meta.get("cloud_cover"),
            epsg=int(meta.get("epsg", 4326)),
            source="LIVE",
            band_names=band_names,
        )

    def _build_s2_payload(
        self,
        bbox: Tuple[float, float, float, float],
        time_range: Tuple[datetime, datetime],
        bands: List[str],
        resolution_m: float,
        mosaicking: str,
    ) -> Dict[str, Any]:
        min_lon, min_lat, max_lon, max_lat = bbox

        band_list = ", ".join(f"'{b}'" for b in bands)
        # SCL is categorical; every other band is continuous reflectance. Mixing them in
        # one array would corrupt the reflectance values, so SCL is a separate response.
        refl_bands = [b for b in bands if b != "SCL"]
        scl_included = "SCL" in bands

        outputs: List[str] = []
        if refl_bands:
            outputs.append(
                f'{{ identifier: "reflectance", bands: {len(refl_bands)}, '
                f'sampleType: "FLOAT32" }}'
            )
        if scl_included:
            outputs.append('{ identifier: "scl", bands: 1, sampleType: "UINT8" }')

        evalscript = f"""//VERSION=3
function setup() {{
  return {{
    input: ["{band_list}"],
    output: [{{{", ".join(outputs)}}}]
  }};
}}
function evaluatePixel(sample) {{
  var results = {{}};
  {'results.reflectance = [' + ", ".join(f"sample.{b}" for b in refl_bands) + '];' if refl_bands else ''}
  {'results.scl = [sample.SCL];' if scl_included else ''}
  return results;
}}
"""

        return {
            "input": {
                "bounds": {"bbox": [min_lon, min_lat, max_lon, max_lat]},
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "mosaicking": mosaicking,
                        "dataFilter": {
                            "timeRange": {
                                "from": self._iso(time_range[0]),
                                "to": self._iso(time_range[1]),
                            }
                        },
                    }
                ],
            },
            "output": {
                "resx": resolution_m,
                "resy": resolution_m,
                # Every advertised response must be produced by the evalscript. Asking
                # for an SCL response that setup() never declares makes the Process API
                # reject the entire request.
                "responses": [
                    {"identifier": identifier, "format": {"type": "image/tiff"}}
                    for identifier in (
                        (["reflectance"] if refl_bands else []) +
                        (["scl"] if scl_included else [])
                    )
                ],
            },
            "evalscript": evalscript,
        }

    # ------------------------------------------------------------------
    # Sentinel-1 SAR
    # ------------------------------------------------------------------

    def acquire_sentinel1(
        self,
        bbox: Tuple[float, float, float, float],
        time_range: Tuple[datetime, datetime],
        polarizations: Sequence[str] = ("VV", "VH"),
        resolution_m: float = 10.0,
        orbit_direction: Optional[str] = None,
        product_type: str = "GRD",
    ) -> AcquisitionResult:
        """
        Acquire a Sentinel-1 GRD observation clipped to `bbox`.

        `orbit_direction` should be fixed across a temporal pair so that ascending and
        descending passes, which have different viewing geometry, are never differenced
        against each other.
        """
        min_lon, min_lat, max_lon, max_lat = bbox

        band_count = len(polarizations)
        # The declared inputs must match the samples evaluatePixel reads, otherwise the
        # request fails or silently returns the wrong band.
        polarization_list = ", ".join(f'"{p}"' for p in polarizations)
        evalscript = f"""//VERSION=3
function setup() {{
  return {{
    input: [{polarization_list}],
    output: {{ bands: {band_count}, sampleType: "FLOAT32" }}
  }};
}}
function evaluatePixel(sample) {{
  return [{", ".join(f"sample.{p}" for p in polarizations)}];
}}
"""

        data_filter: Dict[str, Any] = {
            "timeRange": {
                "from": self._iso(time_range[0]),
                "to": self._iso(time_range[1]),
            }
        }
        if orbit_direction:
            data_filter["orbitDirection"] = orbit_direction.upper()

        payload = {
            "input": {
                "bounds": {"bbox": [min_lon, min_lat, max_lon, max_lat]},
                "data": [
                    {
                        "type": f"sentinel-1-{product_type.lower()}",
                        "mosaicking": "ORBIT",
                        "dataFilter": data_filter,
                    }
                ],
            },
            "output": {
                "resx": resolution_m,
                "resy": resolution_m,
                "responses": [
                    {"identifier": "default", "format": {"type": "image/tiff"}}
                ],
            },
            "evalscript": evalscript,
        }

        profile, _, meta = self._execute_process_request(payload, single_response=True)
        acquisition_time = self._parse_acquisition_time(meta, fallback=time_range[1])

        return AcquisitionResult(
            profile=profile,
            scl=None,
            acquisition_time=acquisition_time,
            platform=meta.get("platform", "SENTINEL-1"),
            instrument=meta.get("instrument", "SAR C-band"),
            collection=meta.get("collection", f"sentinel-1-{product_type.lower()}"),
            product_id=meta.get("product_id"),
            cloud_cover=None,
            epsg=int(meta.get("epsg", 4326)),
            source="LIVE",
            band_names=list(polarizations),
        )

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------

    def _execute_process_request(
        self,
        payload: Dict[str, Any],
        single_response: bool = False,
    ) -> Tuple[RasterProfile, Optional[np.ndarray], Dict[str, Any]]:
        """
        POST a Process API request and parse the georeferenced GeoTIFF responses.

        The transform and CRS are taken from the GeoTIFF itself via GDAL, which is the
        only reliable source; deriving them from the requested bounds would be wrong
        whenever the service returns an actual scene footprint.
        """
        token = self._token_provider()
        if not token:
            raise AuthenticationError(
                "No Copernicus Data Space access token available. "
                "Check CDSE_CLIENT_ID / CDSE_CLIENT_SECRET."
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = requests.post(
                    SENTINEL_HUB_PROCESS_URL,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                if resp.status_code in (401, 403):
                    raise AuthenticationError(
                        f"Copernicus Data Space rejected the credentials "
                        f"(HTTP {resp.status_code})."
                    )
                if resp.status_code == 404:
                    raise NoValidImageError(
                        "No Sentinel observation covers the requested AOI and date range."
                    )
                resp.raise_for_status()

                return self._parse_multipart_response(resp, single_response)
            except (AuthenticationError, NoValidImageError):
                raise
            except (requests.RequestException, ValueError) as e:
                last_error = e
                if attempt < self.max_attempts:
                    wait = self.backoff_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        "Process API attempt %d/%d failed (%s); retrying in %.1fs",
                        attempt, self.max_attempts, e, wait,
                    )
                    import time as _time
                    _time.sleep(wait)

        raise AcquisitionError(
            f"Failed to retrieve imagery after {self.max_attempts} attempts: {last_error}"
        )

    def _parse_multipart_response(
        self,
        resp: "requests.Response",
        single_response: bool,
    ) -> Tuple[RasterProfile, Optional[np.ndarray], Dict[str, Any]]:
        """
        Split a Sentinel Hub response into named GeoTIFFs and read their georeferencing.

        The service returns a multipart body whose parts are tagged with the response
        identifier; when a single response is requested it returns a bare GeoTIFF.
        """
        import re
        import tarfile
        import tempfile

        content_type = resp.headers.get("Content-Type", "")
        tmpdir = Path(tempfile.mkdtemp(prefix="satguard_sh_"))

        named_parts: Dict[str, bytes] = {}

        if "multipart" in content_type:
            boundary_match = re.search(r"boundary=([^;]+)", content_type)
            if not boundary_match:
                raise AcquisitionError(
                    f"Malformed multipart response from Process API: {content_type}"
                )
            boundary = boundary_match.group(1).strip('"').encode()
            parts = resp.content.split(b"--" + boundary)
            for part in parts:
                if not part or part in (b"--", b"--\r\n"):
                    continue
                head, _, body = part.partition(b"\r\n\r\n")
                if not body:
                    continue
                name_match = re.search(rb'name="([^"]+)"', head)
                tiff_match = re.search(
                    rb"filename=\"?([^\";\r\n]+)\"?", head
                )
                if tiff_match:
                    key = tiff_match.group(1).decode(errors="ignore")
                    # Strip any multipart sub-extension the service appends.
                    key = key.replace(".tif", "").split(".")[-1] or "default"
                    named_parts[key] = body.rstrip(b"\r\n-")
                elif name_match:
                    named_parts[name_match.group(1).decode()] = body
        elif "tar" in content_type.lower():
            tar_path = tmpdir / "response.tar"
            tar_path.write_bytes(resp.content)
            with tarfile.open(tar_path) as tf:
                for member in tf.getmembers():
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    key = Path(member.name).name.replace(".tif", "")
                    named_parts[key] = f.read()
        else:
            # Single bare GeoTIFF response.
            named_parts["default"] = resp.content

        meta = self._extract_metadata(named_parts)

        reflectance_key = next(
            (k for k in named_parts if k.lower() in ("reflectance", "default")), None
        )
        if reflectance_key is None:
            raise NoValidImageError(
                "Process API returned no reflectance image for the requested AOI. "
                "The scene may not intersect the AOI."
            )

        refl_path = tmpdir / "reflectance.tif"
        refl_path.write_bytes(named_parts[reflectance_key])
        profile = self._read_response_geotiff(refl_path, "reflectance")

        scl = None
        scl_key = next((k for k in named_parts if k.lower() == "scl"), None)
        if scl_key:
            scl_path = tmpdir / "scl.tif"
            scl_path.write_bytes(named_parts[scl_key])
            scl_profile = self._read_response_geotiff(scl_path, "SCL")
            scl = scl_profile.array.astype(np.float64)
            if scl.shape != profile.array.shape[:2]:
                # Resample SCL onto the reflectance grid by nearest neighbour.
                scl = self._nearest_resample(
                    scl,
                    scl_profile.transform,
                    profile.transform,
                    (profile.height, profile.width),
                )

        return profile, scl, meta

    @staticmethod
    def _read_response_geotiff(path: Path, identifier: str) -> RasterProfile:
        """
        Read a GeoTIFF from a Process API response, converting decoder failures into a
        domain error.

        A truncated, empty, or mislabelled body must not surface as a raw GDAL error:
        callers handle AcquisitionError, and an unparseable response is an upstream
        fault rather than a programming error.
        """
        try:
            return read_geotiff(path)
        except Exception as e:  # rasterio.RasterioIOError, OSError, ValueError
            size = path.stat().st_size if path.exists() else 0
            raise AcquisitionError(
                f"Process API returned an unreadable {identifier} GeoTIFF "
                f"({size} bytes): {e}"
            ) from e

    @staticmethod
    def _nearest_resample(
        source: np.ndarray,
        src_transform: GeoTransform,
        dst_transform: GeoTransform,
        shape_hw: Tuple[int, int],
    ) -> np.ndarray:
        """
        Nearest-neighbour resample of a single-band raster onto another grid.

        Nearest neighbour, not bilinear: the Scene Classification Layer holds integer
        class codes, and interpolating between code 4 (vegetation) and code 9 (cloud)
        would invent class 6 (water), silently corrupting the cloud mask.
        """
        height, width = shape_hw
        src = np.asarray(source)
        if src.ndim != 2:
            raise ValueError(f"Expected a single-band source raster, got {src.shape}")

        cols = np.arange(width, dtype=np.float64)
        rows = np.arange(height, dtype=np.float64)

        # Forward-map destination pixel indices to geographic coordinates.
        xs = dst_transform.a * cols + dst_transform.c
        ys = dst_transform.e * rows + dst_transform.f

        # Invert the source affine analytically over the whole grid at once.
        det = src_transform.a * src_transform.e - src_transform.b * src_transform.d
        if abs(det) < 1e-20:
            raise ValueError("Degenerate source geotransform: cannot resample.")
        dx = xs[None, :] - src_transform.c
        dy = ys[:, None] - src_transform.f
        src_cols = (src_transform.e * dx - src_transform.b * dy) / det
        src_rows = (-src_transform.d * dx + src_transform.a * dy) / det

        src_cols = np.clip(np.round(src_cols).astype(np.int64), 0, src.shape[1] - 1)
        src_rows = np.clip(np.round(src_rows).astype(np.int64), 0, src.shape[0] - 1)
        return src[src_rows, src_cols]

    @staticmethod
    def _extract_metadata(parts: Dict[str, bytes]) -> Dict[str, Any]:
        """Pull acquisition metadata out of the response's JSON part, when present."""
        import json

        for key, value in parts.items():
            if not key.lower().endswith((".json", "metadata")) and "json" not in key.lower():
                continue
            try:
                data = json.loads(value.decode("utf-8", errors="ignore"))
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            meta = dict(data)
            # Normalise the several shapes the service uses for acquisition time.
            for candidate in ("startDate", "acquisitionTime", "time", "date"):
                if candidate in data:
                    meta["acquisition_time"] = data[candidate]
                    break
            if "properties" in data and isinstance(data["properties"], dict):
                for candidate in ("datetime", "startDate"):
                    if candidate in data["properties"]:
                        meta["acquisition_time"] = data["properties"][candidate]
                        break
                if "eo:cloud_cover" in data["properties"]:
                    meta["cloud_cover"] = data["properties"]["eo:cloud_cover"]
            meta.setdefault("epsg", 4326)
            return meta
        return {"epsg": 4326}

    @staticmethod
    def _parse_acquisition_time(meta: Dict[str, Any], fallback: datetime) -> datetime:
        raw = meta.get("acquisition_time") or meta.get("startDate")
        if not raw:
            return fallback
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return fallback
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")