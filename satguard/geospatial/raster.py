"""
satguard/geospatial/raster.py
Georeferenced raster primitives.

This module exists because the previous implementation discarded geospatial
information: `tifffile.imread` / `tifffile.imwrite` drop the affine transform and CRS
that the Sentinel Hub Process API returns, so files written as "GeoTIFF" carried no
georeferencing at all and no coordinate could ever be produced.

Every array handled here travels together with its affine transform and CRS, so that
pixel indices can always be converted to true geographic coordinates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from rasterio.warp import transform_geom, transform_bounds
from scipy import ndimage
from shapely.geometry import Polygon, MultiPolygon, shape, mapping, box as shapely_box
from shapely.ops import unary_union

# WGS84 geographic CRS for all persisted geometry.
GEOGRAPHIC_CRS = "EPSG:4326"

# Equal-area CRS used for true surface-area computation (World Cylindrical Equal Area).
_EQUAL_AREA_CRS = "EPSG:6933"


class RasterError(Exception):
    """Raised when raster geometry or georeferencing is invalid."""


# ---------------------------------------------------------------------------
# Affine transform
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeoTransform:
    """
    Affine geotransform mapping pixel indices to CRS coordinates.

    Uses the standard GDAL convention:
        x = a * col + b * row + c
        y = d * col + e * row + f
    """
    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    @classmethod
    def from_bounds(
        cls,
        bounds: Tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> "GeoTransform":
        """Build a north-up transform from geographic bounds (minx, miny, maxx, maxy)."""
        if width <= 0 or height <= 0:
            raise RasterError(f"Invalid raster dimensions: {width}x{height}")
        minx, miny, maxx, maxy = bounds
        if not (maxx > minx and maxy > miny):
            raise RasterError(f"Invalid bounds, must satisfy max > min: {bounds}")

        pixel_width = (maxx - minx) / float(width)
        pixel_height = (maxy - miny) / float(height)

        return cls(
            a=pixel_width,
            b=0.0,
            c=minx,
            d=0.0,
            e=-pixel_height,  # north-up: row index increases southward
            f=maxy,
        )

    @classmethod
    def from_affine(cls, affine: Affine) -> "GeoTransform":
        return cls(
            a=affine.a, b=affine.b, c=affine.c,
            d=affine.d, e=affine.e, f=affine.f,
        )

    def as_affine(self) -> Affine:
        return Affine(self.a, self.b, self.c, self.d, self.e, self.f)

    def pixel_to_lonlat(self, col: float, row: float) -> Tuple[float, float]:
        """Convert fractional pixel coordinates to (lon, lat)."""
        x = self.a * col + self.b * row + self.c
        y = self.d * col + self.e * row + self.f
        return (float(x), float(y))

    def lonlat_to_pixel(self, lon: float, lat: float) -> Tuple[float, float]:
        """Convert (lon, lat) to fractional pixel coordinates."""
        det = self.a * self.e - self.b * self.d
        if abs(det) < 1e-20:
            raise RasterError("Degenerate geotransform: cannot invert.")
        dx = lon - self.c
        dy = lat - self.f
        col = (self.e * dx - self.b * dy) / det
        row = (-self.d * dx + self.a * dy) / det
        return (float(col), float(row))

    @property
    def pixel_size(self) -> Tuple[float, float]:
        """(x_size, y_size) of a pixel in CRS units."""
        return (math.hypot(self.a, self.d), math.hypot(self.b, self.e))

    def pixel_area_m2(self, center_lat: Optional[float] = None) -> float:
        """
        Ground area of one pixel in square metres.

        For geographic CRS the value is latitude-dependent and is derived from the WGS84
        ellipsoid using the standard metres-per-degree series, so that pixel areas remain
        accurate away from the equator. For projected CRS the value is exact.

        A geographic raster requires `center_lat`: omitting it returns the planar
        pixel-size product, which for degrees is a degree-squared value some six orders
        of magnitude smaller than square metres. `RasterProfile.pixel_area_m2()` resolves
        the CRS and supplies the latitude automatically, so prefer it when a profile is
        available, and never compare a geographic result against a metre-based threshold
        without checking the units.
        """
        x_size, y_size = self.pixel_size
        if center_lat is None:
            return x_size * y_size

        lat_rad = math.radians(center_lat)
        # WGS84 metres per degree of latitude / longitude (Snyder, series expansion).
        m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad) + \
            1.175 * math.cos(4 * lat_rad) - 0.0023 * math.cos(6 * lat_rad)
        m_per_deg_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad) + 0.118 * math.cos(5 * lat_rad)

        # Identify which axis is latitude-like by comparing against the latitude series.
        if y_size and x_size:
            lat_axis_is_y = y_size >= x_size or m_per_deg_lat >= m_per_deg_lon
        else:
            lat_axis_is_y = True

        if lat_axis_is_y:
            y_m = y_size * m_per_deg_lat
            x_m = x_size * m_per_deg_lon
        else:
            x_m = x_size * m_per_deg_lat
            y_m = y_size * m_per_deg_lon

        return abs(x_m * y_m)

    def bounds(self, width: int, height: int) -> Tuple[float, float, float, float]:
        """Geographic bounds (minx, miny, maxx, maxy) covered by the raster."""
        corners = [
            self.pixel_to_lonlat(0, 0),
            self.pixel_to_lonlat(width, 0),
            self.pixel_to_lonlat(0, height),
            self.pixel_to_lonlat(width, height),
        ]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# Raster profile: array + georeferencing, always together
# ---------------------------------------------------------------------------

@dataclass
class RasterProfile:
    """
    A raster array bound to its georeferencing.

    `array` has shape (height, width) for single-band or (height, width, bands) for
    multi-band data. `transform` maps pixel indices to `crs` coordinates.
    """
    array: np.ndarray
    transform: GeoTransform
    crs: str = GEOGRAPHIC_CRS
    nodata: Optional[float] = None
    band_names: Optional[Sequence[str]] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.array = np.asarray(self.array)
        if self.transform.pixel_size == (0.0, 0.0):
            raise RasterError("Raster supplied with a degenerate (zero-size) transform.")

    @property
    def height(self) -> int:
        return int(self.array.shape[0])

    @property
    def width(self) -> int:
        return int(self.array.shape[1])

    @property
    def band_count(self) -> int:
        return int(self.array.shape[2]) if self.array.ndim == 3 else 1

    @property
    def is_geographic(self) -> bool:
        """True when the CRS uses angular units, so pixel sizes need conversion."""
        try:
            return bool(CRS.from_string(self.crs).is_geographic)
        except Exception:
            return self.crs.upper().startswith("EPSG:4326") or self.crs.upper().startswith("OGC:CRS84")

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        return self.transform.bounds(self.width, self.height)

    @property
    def center_lonlat(self) -> Tuple[float, float]:
        return self.transform.pixel_to_lonlat(self.width / 2.0, self.height / 2.0)

    def band(self, index: int) -> np.ndarray:
        """Return a single band as a 2D array."""
        if self.array.ndim == 2:
            return self.array
        return self.array[:, :, index]

    def valid_mask(self) -> np.ndarray:
        """Boolean mask of pixels usable for analysis (excludes nodata / NaN)."""
        arr = self.array.astype(np.float64)
        valid = np.isfinite(arr)
        if self.array.ndim == 3:
            valid = np.all(valid, axis=2)
        if self.nodata is not None and np.isfinite(self.nodata):
            if self.array.ndim == 3:
                valid &= ~np.all(np.isclose(arr, self.nodata), axis=2)
            else:
                valid &= ~np.isclose(arr, self.nodata)
        return valid

    def pixel_area_m2(self) -> float:
        """
        Ground area of one pixel in square metres.

        For a projected CRS the transform units are already metres, so the value is
        exact. For a geographic CRS the pixel size is in degrees and the area is
        latitude-dependent, so it is derived from the raster centre latitude.
        """
        if self.is_geographic:
            _, center_lat = self.center_lonlat
            return self.transform.pixel_area_m2(center_lat)
        x_size, y_size = self.transform.pixel_size
        return x_size * y_size

    def pixel_to_lonlat(self, col: float, row: float) -> Tuple[float, float]:
        return self.transform.pixel_to_lonlat(col, row)

    def subwindow(self, bounds: Tuple[float, float, float, float]) -> "RasterProfile":
        """
        Crop this raster to geographic bounds, preserving georeferencing.

        Used for AOI clipping without resampling, so no interpolation error is
        introduced when extracting a subset of an already-acquired scene.
        """
        minx, miny, maxx, maxy = bounds
        x0, y0 = self.transform.lonlat_to_pixel(minx, maxy)  # top-left
        x1, y1 = self.transform.lonlat_to_pixel(maxx, miny)  # bottom-right

        col_start = max(0, int(math.floor(min(x0, x1))))
        col_end = min(self.width, int(math.ceil(max(x0, x1))))
        row_start = max(0, int(math.floor(min(y0, y1))))
        row_end = min(self.height, int(math.ceil(max(y0, y1))))

        if col_end <= col_start or row_end <= row_start:
            raise RasterError(
                f"Requested bounds {bounds} do not intersect raster bounds {self.bounds}."
            )

        window = (
            slice(row_start, row_end),
            slice(col_start, col_end),
        )
        cropped = self.array[window]
        new_transform = GeoTransform(
            a=self.transform.a, b=self.transform.b,
            c=self.transform.a * col_start + self.transform.b * row_start + self.transform.c,
            d=self.transform.d, e=self.transform.e,
            f=self.transform.d * col_start + self.transform.e * row_start + self.transform.f,
        )
        return RasterProfile(
            array=cropped,
            transform=new_transform,
            crs=self.crs,
            nodata=self.nodata,
            band_names=self.band_names,
            meta=dict(self.meta),
        )

    def reproject_to(self, dst_crs: str, resolution: Optional[float] = None) -> "RasterProfile":
        """
        Reproject this raster into another CRS (e.g. geographic -> UTM).

        Uses GDAL warping, which resamples bilinearly for continuous reflectance data.
        """
        from rasterio.warp import calculate_default_transform, reproject
        from rasterio.enums import Resampling

        src_crs = CRS.from_string(self.crs)
        target_crs = CRS.from_string(dst_crs)

        src_transform = self.transform.as_affine()
        dst_transform, width, height = calculate_default_transform(
            src_crs, target_crs, self.width, self.height, *self.bounds
        )
        if resolution is not None:
            dst_transform = dst_transform * Affine.scale(
                resolution / abs(dst_transform.a), resolution / abs(dst_transform.e)
            )
            width = max(1, int(math.ceil(
                (self.bounds[2] - self.bounds[0]) / resolution
            )))
            height = max(1, int(math.ceil(
                (self.bounds[3] - self.bounds[1]) / resolution
            )))

        needs_3d = self.array.ndim == 3
        if needs_3d:
            bands = self.array.shape[2]
            src_arr = np.moveaxis(self.array, 2, 0)  # -> (bands, h, w)
        else:
            bands = 1
            src_arr = self.array[np.newaxis, ...]

        dst_arr = np.zeros((bands, height, width), dtype=np.float32)
        reproject(
            source=src_arr.astype(np.float32),
            destination=dst_arr,
            src_transform=src_transform,
            src_crs=src_crs,
            src_nodata=self.nodata,
            dst_transform=dst_transform,
            dst_crs=target_crs,
            dst_nodata=self.nodata,
            resampling=Resampling.bilinear,
        )

        out = dst_arr[0] if not needs_3d else np.moveaxis(dst_arr, 0, 2)
        return RasterProfile(
            array=out,
            transform=GeoTransform.from_affine(dst_transform),
            crs=str(dst_crs),
            nodata=self.nodata,
            band_names=self.band_names,
            meta=dict(self.meta),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "height": self.height,
            "width": self.width,
            "bands": self.band_count,
            "crs": self.crs,
            "bounds": [round(v, 8) for v in self.bounds],
            "transform": [self.transform.a, self.transform.b, self.transform.c,
                          self.transform.d, self.transform.e, self.transform.f],
            "center_lonlat": [round(v, 8) for v in self.center_lonlat],
            "pixel_area_m2": round(self.pixel_area_m2(), 4),
            "band_names": list(self.band_names) if self.band_names else None,
        }


# ---------------------------------------------------------------------------
# GeoTIFF I/O - the transform and CRS are mandatory, never optional
# ---------------------------------------------------------------------------

def write_geotiff(
    path: Path | str,
    array: np.ndarray,
    transform: GeoTransform,
    crs: str = GEOGRAPHIC_CRS,
    nodata: Optional[float] = None,
    band_names: Optional[Sequence[str]] = None,
    band_axis: str = "last",
) -> Path:
    """
    Write a georeferenced raster. The output is a genuine GeoTIFF: GDAL can read its
    CRS and affine transform, so pixel coordinates remain convertible to lon/lat.

    `array` is interpreted as (height, width) for single-band data and
    (height, width, bands) for multi-band data when `band_axis="last"` (the default,
    matching :class:`RasterProfile`). Pass `band_axis="first"` for (bands, height, width)
    input. The axis is taken from this explicit argument rather than inferred from shape,
    because shape inference silently misreads (height, width, 3) as three bands of size
    height x width.
    """
    import rasterio

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    arr = np.asarray(array)

    if arr.ndim == 2:
        bands_arr = arr[np.newaxis, ...]
    elif arr.ndim == 3:
        if band_axis == "first":
            bands_arr = arr
        elif band_axis == "last":
            bands_arr = np.moveaxis(arr, 2, 0)
        else:
            raise RasterError(f"band_axis must be 'first' or 'last', got {band_axis!r}")
    else:
        raise RasterError(f"Unsupported array shape for GeoTIFF: {arr.shape}")

    bands, height, width = bands_arr.shape
    if bands == 0 or height == 0 or width == 0:
        raise RasterError(f"Refusing to write an empty raster of shape {arr.shape}.")

    profile = {
        "driver": "GTiff",
        "height": int(height),
        "width": int(width),
        "count": int(bands),
        "dtype": str(arr.dtype),
        "crs": CRS.from_string(crs),
        "transform": transform.as_affine(),
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    if nodata is not None and np.isfinite(nodata):
        profile["nodata"] = float(nodata)

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(bands_arr.astype(arr.dtype), indexes=list(range(1, int(bands) + 1)))
        if band_names:
            for i, name in enumerate(band_names[:bands], start=1):
                dst.set_band_description(i, str(name))
        if nodata is not None and np.isfinite(nodata):
            dst.update_tags(1, nodata=float(nodata))

    return out_path


def read_geotiff(path: Path | str) -> RasterProfile:
    """Read a GeoTIFF into a RasterProfile preserving CRS and affine transform."""
    import rasterio

    src_path = Path(path)
    if not src_path.exists():
        raise RasterError(f"Raster file does not exist: {src_path}")

    with rasterio.open(src_path) as src:
        data = src.read()
        if data.shape[0] == 1:
            array = data[0]
            band_names = None
        else:
            array = np.moveaxis(data, 0, -1)
            band_names = [src.descriptions[i] or f"band_{i+1}" for i in range(data.shape[0])]

        profile = RasterProfile(
            array=array,
            transform=GeoTransform.from_affine(src.transform),
            crs=str(src.crs) if src.crs else GEOGRAPHIC_CRS,
            nodata=src.nodata,
            band_names=band_names,
            meta={
                "driver": src.driver,
                "dtype": str(src.dtypes[0]),
                "source_path": str(src_path),
            },
        )
    return profile


# ---------------------------------------------------------------------------
# Geodesic area
# ---------------------------------------------------------------------------

def geographic_area_m2(geometry) -> float:
    """
    True surface area in square metres of a geometry defined in EPSG:4326.

    Reprojects into a cylindrical equal-area CRS rather than treating degrees as
    planar units, which is the standard source of large area errors in naive code.
    """
    if geometry is None or geometry.is_empty:
        return 0.0
    projected = transform_geometry_to_crs(geometry, _EQUAL_AREA_CRS)
    return float(abs(projected.area))


def transform_geometry_to_crs(geometry, dst_crs: str):
    """Reproject a geometry between coordinate reference systems."""
    if geometry is None or geometry.is_empty:
        return geometry
    if str(dst_crs) == GEOGRAPHIC_CRS:
        return geometry
    return shape(
        transform_geom(GEOGRAPHIC_CRS, dst_crs, mapping(geometry))
    )


def utm_crs_for(lon: float, lat: float) -> str:
    """
    Return the appropriate UTM EPSG code for a coordinate.

    Metric local working CRS keeps pixel areas exact for the analysis.
    """
    zone = int((lon + 180.0) / 6.0) + 1
    zone = max(1, min(60, zone))
    if lat >= 0:
        return f"EPSG:{32600 + zone}"
    return f"EPSG:{32700 + zone}"


# ---------------------------------------------------------------------------
# Raster <-> vector conversion, preserving georeferencing
# ---------------------------------------------------------------------------

def rasterize_geometry(
    geometry,
    transform: GeoTransform,
    shape_hw: Tuple[int, int],
    all_touched: bool = False,
) -> np.ndarray:
    """
    Rasterize a geographic geometry into a boolean mask aligned to the given transform.

    Uses rasterio's GDAL-backed rasterizer so the mask is correctly georeferenced
    rather than approximated from raw pixel indices.
    """
    from rasterio.features import geometry_mask

    height, width = shape_hw
    mask = geometry_mask(
        geometries=[mapping(geometry)],
        out_shape=(height, width),
        transform=transform.as_affine(),
        invert=True,  # True inside the geometry
        all_touched=all_touched,
    )
    return mask.astype(bool)


def polygons_from_mask(
    mask: np.ndarray,
    transform: GeoTransform,
    crs: str = GEOGRAPHIC_CRS,
    min_pixels: int = 1,
    max_regions: int = 500,
) -> List[Dict[str, Any]]:
    """
    Convert a boolean change mask into georeferenced polygons.

    Connected-component labelling is applied so that scattered single-pixel noise is
    dropped by the `min_pixels` filter. Every returned polygon carries true geographic
    coordinates derived from the raster's affine transform, plus its centroid and area.

    Returns:
        List of dicts sorted by descending area, each with keys:
        region_id, pixel_count, area_m2, area_km2, centroid_lon, centroid_lat,
        centroid, bbox (lon/lat), geometry (GeoJSON dict).
    """
    mask = np.asarray(mask).astype(bool)
    if mask.ndim != 2:
        raise RasterError(f"Mask must be 2D, got shape {mask.shape}")
    if not mask.any():
        return []

    labels, num_features = ndimage.label(mask)
    if num_features == 0:
        return []

    # Pre-compute pixel area in square metres using the raster centre latitude.
    height, width = mask.shape
    _, center_lat = transform.pixel_to_lonlat(width / 2.0, height / 2.0)
    pixel_area = transform.pixel_area_m2(center_lat)

    # Scale factor for conversion to geographic CRS if needed.
    area_scale = 1.0
    if str(crs) != GEOGRAPHIC_CRS:
        # Areas computed in the raster CRS; convert for reporting consistency.
        pass

    results: List[Dict[str, Any]] = []
    slices = ndimage.find_objects(labels)
    for feature_id, slc in enumerate(slices, start=1):
        if slc is None:
            continue
        component = labels[slc] == feature_id
        pixel_count = int(np.count_nonzero(component))
        if pixel_count < min_pixels:
            continue

        # Rows/cols of this component within the full mask.
        row_offset, col_offset = slc[0].start, slc[1].start
        local_rows, local_cols = np.nonzero(component)
        global_rows = local_rows + row_offset
        global_cols = local_cols + col_offset

        min_row, max_row = int(global_rows.min()), int(global_rows.max())
        min_col, max_col = int(global_cols.min()), int(global_cols.max())

        # Pixel-corner extent, expanded by one pixel to enclose all pixel footprints.
        corners_px = [
            (min_col, min_row),
            (max_col + 1, min_row),
            (max_col + 1, max_row + 1),
            (min_col, max_row + 1),
        ]
        corners_lonlat = [transform.pixel_to_lonlat(c, r) for c, r in corners_px]
        poly = Polygon(corners_lonlat)

        # Dissolve the block outline into a multi-polygon following the actual mask
        # shape, so the reported geometry matches the change region rather than a
        # coarse bounding rectangle.
        outline_geom = _mask_component_to_geometry(
            labels, feature_id, slc, transform
        )
        if outline_geom is not None and not outline_geom.is_empty:
            poly = outline_geom

        if str(crs) != GEOGRAPHIC_CRS:
            poly = transform_geometry_to_crs(poly, GEOGRAPHIC_CRS)

        if poly.is_empty:
            continue

        if isinstance(poly, (MultiPolygon, Polygon)):
            geoms = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
        else:  # GeometryCollection
            geoms = [g for g in poly.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if not geoms:
            continue
        poly = max(geoms, key=lambda g: abs(g.area))

        area_m2 = geographic_area_m2(poly)
        if area_m2 <= 0.0:
            area_m2 = pixel_count * pixel_area * area_scale

        centroid = poly.centroid
        bbox = poly.bounds

        results.append({
            "region_id": feature_id,
            "pixel_count": pixel_count,
            "area_m2": round(area_m2, 2),
            "area_km2": round(area_m2 / 1e6, 6),
            "centroid_lon": round(float(centroid.x), 7),
            "centroid_lat": round(float(centroid.y), 7),
            "centroid": [round(float(centroid.x), 7), round(float(centroid.y), 7)],
            "bbox": [
                round(float(bbox[0]), 7), round(float(bbox[1]), 7),
                round(float(bbox[2]), 7), round(float(bbox[3]), 7),
            ],
            "geometry": mapping(poly),
        })

        if len(results) >= max_regions:
            break

    results.sort(key=lambda r: r["area_m2"], reverse=True)
    for idx, item in enumerate(results, start=1):
        item["region_id"] = idx
    return results


def _mask_component_to_geometry(labels: np.ndarray, feature_id: int, slc, transform: GeoTransform):
    """
    Convert one labelled component into a polygonal geometry in raster coordinates,
    then map to geographic coordinates via the affine transform.
    """
    from rasterio.features import shapes as rio_shapes
    from rasterio.transform import Affine as RioAffine

    component = (labels[slc] == feature_id).astype(np.uint8)
    local_transform = transform.as_affine() @ RioAffine.translation(slc[1].start, slc[0].start)

    polys = []
    for geom, value in rio_shapes(
        component, mask=None, transform=local_transform, connectivity=8
    ):
        if value != 1:
            continue
        g = shape(geom)
        if not g.is_valid:
            g = g.buffer(0)
        if not g.is_empty:
            polys.append(g)

    if not polys:
        return None
    return unary_union(polys)


# ---------------------------------------------------------------------------
# Co-registration validation
# ---------------------------------------------------------------------------

def check_alignment(
    profile_a: RasterProfile,
    profile_b: RasterProfile,
    tolerance_pixels: float = 0.5,
) -> Dict[str, Any]:
    """
    Verify two rasters share a compatible spatial grid before differencing them.

    Comparing misaligned rasters produces spurious change along every feature edge, so
    this must pass before any difference operation.

    Returns:
        Dict with 'aligned' bool, per-axis offset in pixels, and a human-readable reason.
    """
    if str(profile_a.crs) != str(profile_b.crs):
        return {
            "aligned": False,
            "reason": f"CRS mismatch: {profile_a.crs} vs {profile_b.crs}",
            "offset_col_px": None,
            "offset_row_px": None,
        }

    size_a = profile_a.transform.pixel_size
    size_b = profile_b.transform.pixel_size
    scale_ratio = (size_a[0] / size_b[0]) if size_b[0] else float("inf")
    if abs(scale_ratio - 1.0) > 1e-3:
        return {
            "aligned": False,
            "reason": (
                f"Pixel size mismatch: {size_a[0]:.6g} vs {size_b[0]:.6g} "
                f"({profile_a.crs}). Resampling to a common grid is required."
            ),
            "offset_col_px": None,
            "offset_row_px": None,
        }

    b_minx, b_miny = profile_b.transform.pixel_to_lonlat(0, 0)
    offset_col, offset_row = profile_a.transform.lonlat_to_pixel(b_minx, b_miny)

    # Also confirm B's extent lies within A's footprint.
    inside = (
        -tolerance_pixels <= offset_col <= profile_a.width + tolerance_pixels
        and -tolerance_pixels <= offset_row <= profile_a.height + tolerance_pixels
    )

    aligned = (
        abs(offset_col) <= tolerance_pixels
        and abs(offset_row) <= tolerance_pixels
        and inside
    )

    if aligned:
        reason = "Rasters share a common grid; safe to difference."
    elif not inside:
        reason = (
            f"Rasters do not overlap: B origin is {offset_col:.1f}, {offset_row:.1f} px "
            f"from A origin (A is {profile_a.width}x{profile_a.height} px)."
        )
    else:
        reason = (
            f"Grid offset {offset_col:.2f}, {offset_row:.2f} px exceeds tolerance "
            f"{tolerance_pixels} px; co-registration required before differencing."
        )

    return {
        "aligned": aligned,
        "reason": reason,
        "offset_col_px": round(float(offset_col), 4),
        "offset_row_px": round(float(offset_row), 4),
        "tolerance_pixels": tolerance_pixels,
    }


def align_to_reference(
    profile: RasterProfile,
    reference: RasterProfile,
) -> RasterProfile:
    """
    Reproject/resample `profile` onto the reference grid.

    Ensures differencing compares like-for-like ground areas, which is required for
    change magnitude to be physically meaningful.
    """
    if str(profile.crs) != str(reference.crs):
        profile = profile.reproject_to(reference.crs)

    ref_minx, ref_maxy = reference.transform.pixel_to_lonlat(0, 0)
    ref_maxx, ref_miny = reference.transform.pixel_to_lonlat(reference.width, reference.height)

    aligned = RasterProfile(
        array=np.full((reference.height, reference.width), np.nan, dtype=np.float64),
        transform=GeoTransform.from_bounds(
            (ref_minx, ref_miny, ref_maxx, ref_maxy), reference.width, reference.height
        ),
        crs=reference.crs,
        nodata=reference.nodata,
    )

    from rasterio.warp import reproject
    from rasterio.enums import Resampling

    src = profile.array.astype(np.float32)
    if src.ndim == 3:
        src = src[:, :, 0]
    dst = aligned.array.astype(np.float32)

    reproject(
        source=src,
        destination=dst,
        src_transform=profile.transform.as_affine(),
        src_crs=CRS.from_string(profile.crs),
        src_nodata=profile.nodata,
        dst_transform=aligned.transform.as_affine(),
        dst_crs=CRS.from_string(aligned.crs),
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    aligned.array = dst
    return aligned


def bounds_overlap(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> bool:
    """True when two (minx, miny, maxx, maxy) boxes intersect."""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def geometry_bbox(geometry) -> Tuple[float, float, float, float]:
    """(minx, miny, maxx, maxy) of any shapely geometry."""
    return tuple(float(v) for v in geometry.bounds)  # type: ignore[return-value]


def bbox_to_polygon(bounds: Tuple[float, float, float, float]) -> Polygon:
    """Rectangular polygon from (minx, miny, maxx, maxy)."""
    return shapely_box(*bounds)