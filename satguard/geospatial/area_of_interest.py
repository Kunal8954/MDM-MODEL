"""
satguard/geospatial/area_of_interest.py
Universal Area of Interest (AOI) abstraction and sensor-selection strategy.

The AOI is the single entry point for every downstream operation. Nothing in the
detection pipeline may depend on a hard-coded coordinate, radius or named location:
an AOI is built from whatever the operator selected (a map click, a drawn rectangle,
a drawn polygon, GeoJSON, a coordinate pair, or a place-name lookup) and everything
downstream consumes the AOI object.

Canonical AOI schema::

    {
      "id": "...",
      "geometry": <GeoJSON geometry in EPSG:4326>,
      "bbox": [minx, miny, maxx, maxy],
      "center_lat": ...,
      "center_lon": ...,
      "area_km2": ...,
      "crs": "EPSG:4326",
      "user_label": "...",
      "monitoring_mode": "..."
    }
"""

from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import requests
from shapely.geometry import (
    GeometryCollection,
    LinearRing,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
    shape,
)
from shapely.geometry import box as shapely_box
from shapely.ops import unary_union
from shapely.validation import make_valid

from satguard.geospatial.raster import (
    GEOGRAPHIC_CRS,
    GeoTransform,
    geographic_area_m2,
    rasterize_geometry,
    transform_geometry_to_crs,
    utm_crs_for,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AOIError(Exception):
    """Base error for AOI construction."""

    error_code = "INVALID_AOI"


class InvalidGeometryError(AOIError):
    error_code = "INVALID_GEOMETRY"


class UnsupportedAOIInputError(AOIError):
    error_code = "UNSUPPORTED_AOI_INPUT"


class PlaceNotFoundError(AOIError):
    error_code = "PLACE_NOT_FOUND"


class PlaceLookupError(AOIError):
    error_code = "PLACE_LOOKUP_FAILED"


class AOITooLargeError(AOIError):
    error_code = "AOI_TOO_LARGE"


# ---------------------------------------------------------------------------
# Monitoring modes
# ---------------------------------------------------------------------------

class MonitoringMode(str, Enum):
    """
    Monitoring domains. Each mode selects an index set and a sensor strategy; it is
    data-driven configuration rather than a hard-coded per-location branch.
    """
    GENERAL = "general"
    INFRASTRUCTURE = "infrastructure"
    GLACIER = "glacier"
    WATER_BODY = "water_body"
    VEGETATION = "vegetation"
    FLOOD = "flood"


class SensorStrategy(str, Enum):
    """Which satellite sources are appropriate for a monitoring mode."""
    OPTICAL = "OPTICAL"
    SAR = "SAR"
    OPTICAL_AND_SAR = "OPTICAL + SAR"


# Per-mode configuration: indices to compute, sensors, and the spectral bands each
# index requires. Kept declarative so adding a domain does not touch detection code.
@dataclass(frozen=True)
class ModeProfile:
    mode: MonitoringMode
    label: str
    strategy: SensorStrategy
    indices: Tuple[str, ...]
    required_bands: Tuple[str, ...]
    description: str


MODE_PROFILES: Dict[MonitoringMode, ModeProfile] = {
    MonitoringMode.GENERAL: ModeProfile(
        mode=MonitoringMode.GENERAL,
        label="General anomaly / change monitoring",
        strategy=SensorStrategy.OPTICAL_AND_SAR,
        indices=("ndvi", "ndwi", "mndwi", "ndsi"),
        required_bands=("B02", "B03", "B04", "B08", "B11"),
        description=(
            "Broad multi-index change detection with independent SAR confirmation, "
            "so that persistent cloud cover does not block monitoring."
        ),
    ),
    MonitoringMode.INFRASTRUCTURE: ModeProfile(
        mode=MonitoringMode.INFRASTRUCTURE,
        label="Infrastructure / building monitoring",
        strategy=SensorStrategy.OPTICAL_AND_SAR,
        indices=("ndbi", "ndvi", "brightness", "ndwi"),
        required_bands=("B02", "B03", "B04", "B08", "B11", "B12"),
        description=(
            "Built-up change via NDBI plus spectral brightness and SAR backscatter, "
            "which together separate new structures from shadows and illumination change."
        ),
    ),
    MonitoringMode.GLACIER: ModeProfile(
        mode=MonitoringMode.GLACIER,
        label="Glacier / snow / ice monitoring",
        strategy=SensorStrategy.OPTICAL_AND_SAR,
        indices=("ndsi", "ndvi", "ndwi", "brightness"),
        required_bands=("B02", "B03", "B04", "B08", "B11"),
        description=(
            "Snow/ice extent via NDSI with water-exposure detection, cross-checked "
            "against SAR, which sees through cloud."
        ),
    ),
    MonitoringMode.WATER_BODY: ModeProfile(
        mode=MonitoringMode.WATER_BODY,
        label="Water body monitoring",
        strategy=SensorStrategy.OPTICAL_AND_SAR,
        indices=("ndwi", "mndwi", "ndvi"),
        required_bands=("B03", "B04", "B08", "B11"),
        description=(
            "Open-water extent via NDWI/MNDWI, with SAR used when optical is "
            "cloud-obscured."
        ),
    ),
    MonitoringMode.VEGETATION: ModeProfile(
        mode=MonitoringMode.VEGETATION,
        label="Vegetation / land-cover monitoring",
        strategy=SensorStrategy.OPTICAL,
        indices=("ndvi", "ndre", "nbr"),
        required_bands=("B04", "B05", "B06", "B08"),
        description=(
            "Vegetation condition and loss via NDVI with red-edge and burned-area "
            "indices. Optical only: SAR backscatter adds little for canopy condition."
        ),
    ),
    MonitoringMode.FLOOD: ModeProfile(
        mode=MonitoringMode.FLOOD,
        label="Flood / water change monitoring",
        strategy=SensorStrategy.OPTICAL_AND_SAR,
        indices=("ndwi", "mndwi"),
        required_bands=("B03", "B04", "B08", "B11"),
        description=(
            "Flood extent detection. SAR leads because it is independent of cloud and "
            "daylight; optical confirms the water signature where available."
        ),
    ),
}


def get_mode_profile(mode: Union[MonitoringMode, str]) -> ModeProfile:
    """Resolve a monitoring mode (accepts enum or string)."""
    if isinstance(mode, ModeProfile):
        return mode
    if isinstance(mode, MonitoringMode):
        return MODE_PROFILES[mode]
    try:
        return MODE_PROFILES[MonitoringMode(str(mode).strip().lower())]
    except (ValueError, KeyError):
        valid = ", ".join(m.value for m in MonitoringMode)
        raise UnsupportedAOIInputError(
            f"Unknown monitoring_mode '{mode}'. Valid modes: {valid}"
        ) from None


# ---------------------------------------------------------------------------
# Size limits
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AOIConstraints:
    """Operational limits. Exceeding these must fail loudly rather than silently degrade."""
    max_area_km2: float = 900.0
    max_dimension_m: float = 60_000.0
    min_dimension_m: float = 30.0
    # Above this area the pipeline must switch to windowed/tiled processing.
    large_aoi_threshold_km2: float = 100.0


DEFAULT_CONSTRAINTS = AOIConstraints()


# ---------------------------------------------------------------------------
# The AOI
# ---------------------------------------------------------------------------

@dataclass
class AOI:
    """
    A user-selected, fully-specified monitoring geometry.

    Always expressed in EPSG:4326 (WGS84 geographic) with geodesic areas, so that
    coordinates returned to the operator are directly usable as lon/lat.
    """
    id: str
    geometry: Polygon | MultiPolygon
    user_label: str = ""
    monitoring_mode: MonitoringMode = MonitoringMode.GENERAL
    crs: str = GEOGRAPHIC_CRS
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "manual"
    constraints: AOIConstraints = DEFAULT_CONSTRAINTS
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- derived, always consistent with `geometry` -------------------------

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        """(min_lon, min_lat, max_lon, max_lat)."""
        return tuple(float(v) for v in self.geometry.bounds)  # type: ignore[return-value]

    @property
    def centroid(self) -> Point:
        return self.geometry.centroid

    @property
    def center_lon(self) -> float:
        return float(self.centroid.x)

    @property
    def center_lat(self) -> float:
        return float(self.centroid.y)

    @property
    def area_m2(self) -> float:
        return geographic_area_m2(self.geometry)

    @property
    def area_km2(self) -> float:
        return self.area_m2 / 1e6

    @property
    def profile(self) -> ModeProfile:
        return get_mode_profile(self.monitoring_mode)

    @property
    def sensor_strategy(self) -> SensorStrategy:
        return self.profile.strategy

    @property
    def dimension_m(self) -> Tuple[float, float]:
        """
        (east-west, north-south) extent in metres.

        Measured by reprojecting the bbox corners into the local UTM zone, which avoids
        the degree-to-metre approximation error that grows with AOI size.
        """
        minx, miny, maxx, maxy = self.bbox
        crs = self.utm_crs()
        projected = transform_geometry_to_crs(self.geometry, crs)
        pxmin, pymin, pxmax, pymax = projected.bounds
        # geodesic measure for reliability on very large AOIs
        ew_geodesic = geographic_area_m2(shapely_box(minx, self.center_lat, maxx, self.center_lat))
        ns_geodesic = geographic_area_m2(shapely_box(self.center_lon, miny, self.center_lon, maxy))
        ew = max(abs(pxmax - pxmin), ew_geodesic)
        ns = max(abs(pymax - pymin), ns_geodesic)
        return (round(ew, 2), round(ns, 2))

    @property
    def is_large(self) -> bool:
        return self.area_km2 > self.constraints.large_aoi_threshold_km2

    def utm_crs(self) -> str:
        """Local metric CRS for this AOI, so pixel areas are exact."""
        return utm_crs_for(self.center_lon, self.center_lat)

    # -- raster helpers ----------------------------------------------------

    def transform_for(
        self,
        resolution_m: float,
        crs: Optional[str] = None,
    ) -> Tuple[GeoTransform, int, int]:
        """
        Build a geotransform and grid size covering this AOI at a target ground
        resolution. This is what replaces the previous hard-coded 256x256 resize:
        the grid is derived from real bounds and the requested resolution, so native
        Sentinel-2 10 m detail is preserved.
        """
        target_crs = crs or GEOGRAPHIC_CRS
        if target_crs == GEOGRAPHIC_CRS:
            minx, miny, maxx, maxy = self.bbox
            width_m, height_m = self.dimension_m
            width_px = max(1, int(math.ceil(width_m / resolution_m)))
            height_px = max(1, int(math.ceil(height_m / resolution_m)))
            return GeoTransform.from_bounds((minx, miny, maxx, maxy), width_px, height_px), width_px, height_px

        projected = transform_geometry_to_crs(self.geometry, target_crs)
        minx, miny, maxx, maxy = projected.bounds
        width_px = max(1, int(math.ceil((maxx - minx) / resolution_m)))
        height_px = max(1, int(math.ceil((maxy - miny) / resolution_m)))
        return (
            GeoTransform.from_bounds((minx, miny, maxx, maxy), width_px, height_px),
            width_px,
            height_px,
        )

    def mask_for(
        self,
        transform: GeoTransform,
        shape_hw: Tuple[int, int],
        all_touched: bool = False,
    ) -> np.ndarray:
        """Rasterize this AOI into a boolean mask on the given grid."""
        return rasterize_geometry(self.geometry, transform, shape_hw, all_touched=all_touched)

    def validate(self) -> None:
        """Enforce operational limits. Raises AOIError subclasses on violation."""
        if self.geometry is None or self.geometry.is_empty:
            raise InvalidGeometryError("AOI geometry is empty.")

        minx, miny, maxx, maxy = self.bbox
        if not (-180 <= minx <= 180 and -90 <= miny <= 90 and -180 <= maxx <= 180 and -90 <= maxy <= 90):
            raise InvalidGeometryError(
                f"AOI extends outside valid WGS84 bounds: {self.bbox}"
            )

        width_m, height_m = self.dimension_m
        c = self.constraints
        if max(width_m, height_m) > c.max_dimension_m:
            raise AOITooLargeError(
                f"AOI extent {max(width_m, height_m):,.0f} m exceeds the maximum "
                f"single-scene dimension of {c.max_dimension_m:,.0f} m. "
                f"Select a smaller area or enable tiled processing."
            )
        if self.area_km2 > c.max_area_km2:
            raise AOITooLargeError(
                f"AOI area {self.area_km2:,.2f} km² exceeds the maximum of "
                f"{c.max_area_km2:,.0f} km²."
            )
        if min(width_m, height_m) < c.min_dimension_m:
            raise InvalidGeometryError(
                f"AOI is too small ({min(width_m, height_m):.1f} m); the minimum "
                f"monitoring extent is {c.min_dimension_m:.0f} m."
            )

    # -- serialisation -----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Canonical schema required by the platform contract."""
        return {
            "id": self.id,
            "geometry": mapping(self.geometry),
            "bbox": list(self.bbox),
            "center_lat": round(self.center_lat, 7),
            "center_lon": round(self.center_lon, 7),
            "area_km2": round(self.area_km2, 6),
            "area_m2": round(self.area_m2, 2),
            "crs": self.crs,
            "user_label": self.user_label,
            "monitoring_mode": self.monitoring_mode.value,
            "monitoring_mode_label": self.profile.label,
            "sensor_strategy": self.sensor_strategy.value,
            "required_indices": list(self.profile.indices),
            "required_bands": list(self.profile.required_bands),
            "source": self.source,
            "is_large": self.is_large,
            "dimension_m": list(self.dimension_m),
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    def to_geojson(self) -> Dict[str, Any]:
        """AOI as a GeoJSON Feature, suitable for direct map display."""
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": mapping(self.geometry),
            "properties": {
                "id": self.id,
                "user_label": self.user_label,
                "monitoring_mode": self.monitoring_mode.value,
                "area_km2": round(self.area_km2, 6),
                "center_lat": round(self.center_lat, 7),
                "center_lon": round(self.center_lon, 7),
                "crs": self.crs,
            },
        }


# ---------------------------------------------------------------------------
# Construction helpers
# ---------------------------------------------------------------------------

def _normalize_polygonal(geom: Any, context: str) -> Polygon | MultiPolygon:
    """
    Coerce input into a valid polygonal geometry.

    Accepts Polygon/MultiPolygon directly, and LineString / point collections by
    buffering into a polygon, so a drawn boundary line still yields a usable AOI.
    """
    if geom is None or geom.is_empty:
        raise InvalidGeometryError(f"{context}: geometry is empty.")

    if isinstance(geom, (Polygon, MultiPolygon)):
        candidate = geom
    elif isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if not polys:
            raise InvalidGeometryError(f"{context}: no polygonal component found.")
        candidate = unary_union(polys)
    elif isinstance(geom, LineString):
        candidate = geom.buffer(0)
    elif isinstance(geom, Point):
        raise InvalidGeometryError(
            f"{context}: a bare point has zero area. Provide a radius or a polygon."
        )
    else:
        raise InvalidGeometryError(f"{context}: unsupported geometry {geom.geom_type}.")

    if not candidate.is_valid:
        candidate = make_valid(candidate)
        if isinstance(candidate, GeometryCollection):
            polys = [g for g in candidate.geoms if isinstance(g, (Polygon, MultiPolygon))]
            if not polys:
                raise InvalidGeometryError(f"{context}: geometry is invalid after repair.")
            candidate = unary_union(polys)

    if isinstance(candidate, Polygon):
        if candidate.area <= 0:
            raise InvalidGeometryError(f"{context}: polygon has zero area.")
    elif isinstance(candidate, MultiPolygon):
        if not any(p.area > 0 for p in candidate.geoms):
            raise InvalidGeometryError(f"{context}: all polygon parts have zero area.")
    else:
        raise InvalidGeometryError(f"{context}: could not derive a polygonal geometry.")

    return candidate


def _deterministic_id(
    geometry: Any,
    monitoring_mode: MonitoringMode,
    label: str = "",
) -> str:
    """
    Build a stable id from the geometry so that re-submitting the same AOI is
    idempotent rather than creating unbounded duplicates.
    """
    payload = (
        f"{label}|{monitoring_mode.value}|"
        + ",".join(f"{round(v, 7)}" for v in geometry.bounds)
        + f"|{geometry.geom_type}|{geometry.area:.9f}"
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"aoi-{digest}"


def _radius_polygon(lat: float, lon: float, radius_m: float, points: int = 64) -> Polygon:
    """
    Circle of `radius_m` around a coordinate, on the WGS84 ellipsoid.

    Uses local metres-per-degree at the given latitude so the radius is correct in
    both axes (the previous implementation used the equatorial radius for both, which
    overstates the north-south radius by ~0.4%).
    """
    lat_rad = math.radians(lat)
    m_per_deg_lat = 111132.92 - 559.82 * math.cos(2 * lat_rad) + 1.175 * math.cos(4 * lat_rad)
    m_per_deg_lon = 111412.84 * math.cos(lat_rad) - 93.5 * math.cos(3 * lat_rad)

    coords = []
    for i in range(points):
        angle = 2.0 * math.pi * i / points
        dx = radius_m * math.cos(angle)
        dy = radius_m * math.sin(angle)
        coords.append((lon + dx / m_per_deg_lon, lat + dy / m_per_deg_lat))
    coords.append(coords[0])
    return Polygon(coords)


def aoi_from_point(
    latitude: float,
    longitude: float,
    radius_m: float = 1000.0,
    monitoring_mode: Union[MonitoringMode, str] = MonitoringMode.GENERAL,
    user_label: str = "",
    validate: bool = True,
) -> AOI:
    """AOI from a map click: a coordinate plus a radius."""
    if not (-90 <= latitude <= 90):
        raise InvalidGeometryError(f"latitude {latitude} out of range [-90, 90].")
    if not (-180 <= longitude <= 180):
        raise InvalidGeometryError(f"longitude {longitude} out of range [-180, 180].")
    if radius_m <= 0:
        raise InvalidGeometryError(f"radius_m must be positive, got {radius_m}.")

    geom = _radius_polygon(latitude, longitude, float(radius_m))
    profile = get_mode_profile(monitoring_mode)
    aoi = AOI(
        id=_deterministic_id(geom, profile.mode, user_label or f"{latitude},{longitude}"),
        geometry=geom,  # type: ignore[arg-type]
        user_label=user_label,
        monitoring_mode=profile.mode,
        source="point",
        metadata={"latitude": latitude, "longitude": longitude, "radius_m": radius_m},
    )
    if validate:
        aoi.validate()
    return aoi


def aoi_from_bbox(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    monitoring_mode: Union[MonitoringMode, str] = MonitoringMode.GENERAL,
    user_label: str = "",
    validate: bool = True,
) -> AOI:
    """AOI from a drawn or supplied rectangle."""
    if min_lon > max_lon:
        min_lon, max_lon = max_lon, min_lon
    if min_lat > max_lat:
        min_lat, max_lat = max_lat, min_lat

    geom = _normalize_polygonal(shapely_box(min_lon, min_lat, max_lon, max_lat), "bbox")
    profile = get_mode_profile(monitoring_mode)
    aoi = AOI(
        id=_deterministic_id(geom, profile.mode, user_label or "bbox"),
        geometry=geom,  # type: ignore[arg-type]
        user_label=user_label,
        monitoring_mode=profile.mode,
        source="bbox",
        metadata={"min_lon": min_lon, "min_lat": min_lat, "max_lon": max_lon, "max_lat": max_lat},
    )
    if validate:
        aoi.validate()
    return aoi


def aoi_from_polygon(
    coordinates: Sequence[Sequence[float]],
    monitoring_mode: Union[MonitoringMode, str] = MonitoringMode.GENERAL,
    user_label: str = "",
    validate: bool = True,
) -> AOI:
    """
    AOI from a drawn polygon.

    `coordinates` may be a single ring (list of [lon, lat]) or a list of rings
    (polygon with holes), in GeoJSON axis order.
    """
    if not coordinates:
        raise InvalidGeometryError("Polygon coordinate list is empty.")

    def _ring(seq: Sequence[Sequence[float]]) -> List[Tuple[float, float]]:
        ring: List[Tuple[float, float]] = []
        for pt in seq:
            if len(pt) < 2:
                raise InvalidGeometryError(f"Invalid coordinate pair: {pt!r}")
            ring.append((float(pt[0]), float(pt[1])))
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return ring

    if isinstance(coordinates[0][0], (int, float)):
        polygon = Polygon(_ring(coordinates))  # type: ignore[arg-type]
    else:
        polygon = Polygon(_ring(coordinates[0]), [_ring(r) for r in coordinates[1:]])  # type: ignore[index,arg-type]

    geom = _normalize_polygonal(polygon, "polygon")
    profile = get_mode_profile(monitoring_mode)
    aoi = AOI(
        id=_deterministic_id(geom, profile.mode, user_label or "polygon"),
        geometry=geom,  # type: ignore[arg-type]
        user_label=user_label,
        monitoring_mode=profile.mode,
        source="polygon",
        metadata={"vertex_count": len(coordinates)},
    )
    if validate:
        aoi.validate()
    return aoi


def aoi_from_geojson(
    geojson: Union[Dict[str, Any], str],
    monitoring_mode: Union[MonitoringMode, str] = MonitoringMode.GENERAL,
    user_label: str = "",
    validate: bool = True,
) -> AOI:
    """AOI from a GeoJSON Feature, FeatureCollection, or bare geometry object."""
    import json as _json

    if isinstance(geojson, str):
        try:
            geojson = _json.loads(geojson)
        except ValueError as e:
            raise InvalidGeometryError(f"Invalid GeoJSON string: {e}") from e

    if not isinstance(geojson, dict):
        raise InvalidGeometryError("GeoJSON must be an object.")

    gtype = geojson.get("type")
    source = "geojson"

    if gtype == "FeatureCollection":
        feats = geojson.get("features") or []
        polys = []
        for feat in feats:
            g = feat.get("geometry") if isinstance(feat, dict) else None
            if not g:
                continue
            try:
                polys.append(_normalize_polygonal(shape(g), "geojson"))
            except AOIError:
                continue
        if not polys:
            raise InvalidGeometryError("FeatureCollection contains no polygonal features.")
        geom = _normalize_polygonal(unary_union(polys), "geojson")
    elif gtype == "Feature":
        if not geojson.get("geometry"):
            raise InvalidGeometryError("Feature has no geometry member.")
        geom = _normalize_polygonal(shape(geojson["geometry"]), "geojson")
        props = geojson.get("properties") or {}
        if not user_label and isinstance(props, dict):
            user_label = str(props.get("name") or props.get("label") or "")
    elif gtype in ("Polygon", "MultiPolygon"):
        geom = _normalize_polygonal(shape(geojson), "geojson")
    else:
        raise UnsupportedAOIInputError(
            f"Unsupported GeoJSON type '{gtype}'. Expected Feature, FeatureCollection, "
            f"Polygon or MultiPolygon."
        )

    profile = get_mode_profile(monitoring_mode)
    aoi = AOI(
        id=_deterministic_id(geom, profile.mode, user_label or "geojson"),
        geometry=geom,  # type: ignore[arg-type]
        user_label=user_label,
        monitoring_mode=profile.mode,
        source=source,
        metadata={"geojson_type": gtype},
    )
    if validate:
        aoi.validate()
    return aoi


def aoi_from_place_name(
    query: str,
    monitoring_mode: Union[MonitoringMode, str] = MonitoringMode.GENERAL,
    radius_m: float = 3000.0,
    user_label: str = "",
    validate: bool = True,
    timeout: float = 15.0,
    limit: int = 1,
) -> AOI:
    """
    AOI from a place-name search, via the OpenStreetMap Nominatim service.

    Requires network access. Raises PlaceNotFoundError rather than guessing a
    location when the query cannot be resolved.
    """
    if not query or not query.strip():
        raise InvalidGeometryError("Place-name query is empty.")

    from satguard.config import settings

    params = {
        "q": query.strip(),
        "format": "jsonv2",
        "limit": max(1, int(limit)),
        "polygon_geojson": 1,
    }
    headers = {"User-Agent": settings.OSM_USER_AGENT}

    try:
        resp = requests.get(
            settings.OSM_OVERPASS_URL.replace("/api/interpreter", "") + "/search",
            params=params,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as e:
        raise PlaceLookupError(
            f"Place lookup for '{query}' failed: {e}"
        ) from e

    if not results:
        raise PlaceNotFoundError(
            f"No place found for '{query}'. Provide coordinates or draw an AOI instead."
        )

    best = results[0]
    label = user_label or best.get("display_name", query)
    geojson = {
        "type": "Feature",
        "geometry": best.get("geojson"),
        "properties": {"name": label},
    }
    if not geojson["geometry"]:
        # Fall back to a radius around the returned point.
        lat = float(best["lat"])
        lon = float(best["lon"])
        aoi = aoi_from_point(
            latitude=lat,
            longitude=lon,
            radius_m=radius_m,
            monitoring_mode=monitoring_mode,
            user_label=label,
            validate=False,
        )
        aoi.source = "place_name"
        aoi.metadata.update({
            "place_query": query,
            "osm_class": best.get("class"),
            "osm_type": best.get("type"),
            "display_name": best.get("display_name"),
        })
        if validate:
            aoi.validate()
        return aoi

    aoi = aoi_from_geojson(
        geojson,
        monitoring_mode=monitoring_mode,
        user_label=label,
        validate=False,
    )
    aoi.source = "place_name"
    aoi.metadata.update({
        "place_query": query,
        "osm_class": best.get("class"),
        "osm_type": best.get("type"),
        "display_name": best.get("display_name"),
    })
    if validate:
        aoi.validate()
    return aoi


def build_aoi(
    geometry: Optional[Dict[str, Any]] = None,
    point: Optional[Dict[str, Any]] = None,
    bbox: Optional[Sequence[float]] = None,
    polygon: Optional[Sequence[Sequence[float]]] = None,
    geojson: Optional[Union[Dict[str, Any], str]] = None,
    place_name: Optional[str] = None,
    monitoring_mode: Union[MonitoringMode, str] = MonitoringMode.GENERAL,
    user_label: str = "",
    validate: bool = True,
) -> AOI:
    """
    Universal AOI factory: accepts any supported input form and returns a validated AOI.

    Exactly one of `geometry`, `point`, `bbox`, `polygon`, `geojson`, `place_name`
    must be supplied. This is the single entry point used by the API, so no caller
    needs to know which input form the operator used on the map.
    """
    provided = [
        name for name, value in (
            ("geometry", geometry),
            ("point", point),
            ("bbox", bbox),
            ("polygon", polygon),
            ("geojson", geojson),
            ("place_name", place_name),
        ) if value is not None
    ]

    if len(provided) == 0:
        raise UnsupportedAOIInputError(
            "No AOI input supplied. Provide one of: geometry, point, bbox, polygon, "
            "geojson, place_name."
        )
    if len(provided) > 1:
        raise UnsupportedAOIInputError(
            f"Multiple AOI inputs supplied ({', '.join(provided)}). Supply exactly one."
        )

    if point is not None:
        try:
            aoi = aoi_from_point(
                latitude=float(point["latitude"]),
                longitude=float(point["longitude"]),
                radius_m=float(point.get("radius_m", 1000.0)),
                monitoring_mode=monitoring_mode,
                user_label=user_label,
                validate=False,
            )
        except KeyError as e:
            raise InvalidGeometryError(f"point input missing required key: {e}") from e
    elif bbox is not None:
        if len(bbox) != 4:
            raise InvalidGeometryError(f"bbox must have 4 values, got {len(bbox)}.")
        aoi = aoi_from_bbox(
            min_lon=float(bbox[0]), min_lat=float(bbox[1]),
            max_lon=float(bbox[2]), max_lat=float(bbox[3]),
            monitoring_mode=monitoring_mode, user_label=user_label, validate=False,
        )
    elif polygon is not None:
        aoi = aoi_from_polygon(
            polygon, monitoring_mode=monitoring_mode, user_label=user_label, validate=False
        )
    elif geojson is not None:
        aoi = aoi_from_geojson(
            geojson, monitoring_mode=monitoring_mode, user_label=user_label, validate=False
        )
    elif place_name is not None:
        aoi = aoi_from_place_name(
            place_name,
            monitoring_mode=monitoring_mode,
            user_label=user_label,
            validate=False,
            radius_m=float((point or {}).get("radius_m", 3000.0)) if point else 3000.0,
        )
    else:  # geometry
        aoi = aoi_from_geojson(
            {"type": "Feature", "geometry": geometry, "properties": {}},
            monitoring_mode=monitoring_mode, user_label=user_label, validate=False,
        )

    if validate:
        aoi.validate()
    return aoi


# ---------------------------------------------------------------------------
# Legacy bridge
# ---------------------------------------------------------------------------

def aoi_from_critical_location(location: Any) -> AOI:
    """
    Build an AOI from a `CriticalLocation` record.

    This keeps the repository's configured sample locations working unchanged while
    routing them through the generic AOI abstraction, so seeded locations and
    user-drawn AOIs follow an identical downstream code path.
    """
    radius = float(getattr(location, "radius_m", 1000) or 1000)

    # Prefer the stored boundary polygon when present.
    geometry_wkt = getattr(location, "geometry", None)
    if geometry_wkt:
        try:
            import shapely.wkt
            geom = _normalize_polygonal(shapely.wkt.loads(geometry_wkt), "critical_location")
            aoi = AOI(
                id=str(getattr(location, "id")),
                geometry=geom,  # type: ignore[arg-type]
                user_label=str(getattr(location, "name", "") or ""),
                monitoring_mode=MonitoringMode.GENERAL,
                source="critical_location",
                metadata={
                    "location_type": getattr(location, "location_type", None),
                    "risk_category": getattr(location, "risk_category", None),
                    "priority": getattr(location, "priority", None),
                    "radius_m": radius,
                },
            )
            return aoi
        except Exception:
            pass  # fall through to centre+radius

    return AOI(
        id=str(getattr(location, "id")),
        geometry=_radius_polygon(  # type: ignore[arg-type]
            float(getattr(location, "latitude")),
            float(getattr(location, "longitude")),
            radius,
        ),
        user_label=str(getattr(location, "name", "") or ""),
        monitoring_mode=MonitoringMode.GENERAL,
        source="critical_location",
        metadata={
            "location_type": getattr(location, "location_type", None),
            "risk_category": getattr(location, "risk_category", None),
            "priority": getattr(location, "priority", None),
            "radius_m": radius,
        },
    )
