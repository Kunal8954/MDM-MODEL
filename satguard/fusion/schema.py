"""
satguard/fusion/schema.py
Pydantic Models and Normalized Schemas for Multi-Sensor Evidence Fusion (Phase 3).
Supports Sentinel-1 SAR, Sentinel-2 Optical, NASA GPM Rainfall, NASA FIRMS Thermal,
USGS Earthquake, and Copernicus DEM Elevation/Slope evidence channels.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class TemporalAlignment(BaseModel):
    """
    Records deterministic temporal alignment of an evidence source relative to a reference time.
    """
    observation_time: Optional[datetime] = None
    observation_window_start: Optional[datetime] = None
    observation_window_end: Optional[datetime] = None
    reference_time: datetime
    temporal_distance_hours: Optional[float] = None
    status: str = Field(..., description="ALIGNED, STALE, UNAVAILABLE, or OUTSIDE_WINDOW")


class SpatialAlignment(BaseModel):
    """
    Records deterministic spatial relationship of an evidence source relative to the monitored AOI.
    """
    location_id: str
    latitude: float
    longitude: float
    aoi_radius_m: float
    spatial_relation: str = Field(..., description="INSIDE_AOI, PROXIMATE, INTERSECTS, or EXTERNAL")
    distance_km: float = 0.0


class Sentinel1Evidence(BaseModel):
    """
    Normalized SAR backscatter change evidence from Sentinel-1 (Phase 2).
    """
    available: bool = False
    t1_observation_id: Optional[str] = None
    t2_observation_id: Optional[str] = None
    t1_product_id: Optional[str] = None
    t2_product_id: Optional[str] = None
    t1_acquisition_time: Optional[datetime] = None
    t2_acquisition_time: Optional[datetime] = None
    orbit_direction: Optional[str] = None
    relative_orbit: Optional[int] = None
    mean_delta_vv_db: Optional[float] = None
    mean_delta_vh_db: Optional[float] = None
    vv_changed_percent: Optional[float] = None
    vh_changed_percent: Optional[float] = None
    joint_changed_percent: Optional[float] = None
    changed_percentage: Optional[float] = None
    significant_region_count: int = 0
    largest_region: Optional[Dict[str, Any]] = None
    change_designation: str = "NO_DATA"
    change_raster_path: Optional[str] = None
    temporal_alignment: Optional[TemporalAlignment] = None
    spatial_alignment: Optional[SpatialAlignment] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class Sentinel2Evidence(BaseModel):
    """
    Normalized optical / NDWI surface water extent evidence from Sentinel-2 (Phase 1).
    """
    available: bool = False
    observation_id: Optional[str] = None
    product_id: Optional[str] = None
    acquisition_time: Optional[datetime] = None
    cloud_cover: Optional[float] = None
    baseline_observation_id: Optional[str] = None
    mean_ndwi: Optional[float] = None
    water_area_m2: Optional[float] = None
    water_change_area_m2: Optional[float] = None
    water_change_percentage: Optional[float] = None
    optical_change_status: str = "NO_DATA"
    ndwi_raster_path: Optional[str] = None
    temporal_alignment: Optional[TemporalAlignment] = None
    spatial_alignment: Optional[SpatialAlignment] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class RainfallEvidence(BaseModel):
    """
    Normalized precipitation evidence from NASA GPM / IMERG.
    """
    available: bool = False
    source: str = "NASA GPM IMERG"
    observation_window_start: Optional[datetime] = None
    observation_window_end: Optional[datetime] = None
    total_granules_found: int = 0
    estimated_rainfall_mm: float = 0.0
    latest_granule_title: Optional[str] = None
    latest_granule_time: Optional[str] = None
    temporal_alignment: Optional[TemporalAlignment] = None
    spatial_alignment: Optional[SpatialAlignment] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class FireEvidence(BaseModel):
    """
    Normalized thermal anomaly / active fire evidence from NASA FIRMS.
    """
    available: bool = False
    source: str = "NASA FIRMS (VIIRS/MODIS)"
    observation_window_start: Optional[datetime] = None
    observation_window_end: Optional[datetime] = None
    fire_count: int = 0
    max_frp_mw: float = 0.0
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    temporal_alignment: Optional[TemporalAlignment] = None
    spatial_alignment: Optional[SpatialAlignment] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class EarthquakeEvidence(BaseModel):
    """
    Normalized seismic hazard proximity evidence from USGS FDSN.
    """
    available: bool = False
    source: str = "USGS Earthquake Hazards Program"
    events_found_count: int = 0
    nearest_event_id: Optional[str] = None
    nearest_event_time: Optional[datetime] = None
    nearest_magnitude: Optional[float] = None
    nearest_depth_km: Optional[float] = None
    distance_km: Optional[float] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)
    temporal_alignment: Optional[TemporalAlignment] = None
    spatial_alignment: Optional[SpatialAlignment] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class TerrainEvidence(BaseModel):
    """
    Normalized digital elevation and slope evidence from Copernicus DEM (GLO-30).
    """
    available: bool = False
    source: str = "Copernicus DEM (GLO-30)"
    tile_name: Optional[str] = None
    elevation_m: Optional[float] = None
    slope_degrees: Optional[float] = None
    terrain_metadata: Dict[str, Any] = Field(default_factory=dict)
    spatial_alignment: Optional[SpatialAlignment] = None
    provenance: Dict[str, Any] = Field(default_factory=dict)


class EvidenceCorrelation(BaseModel):
    """
    Deterministic correlation between independent sensor observations.
    """
    correlation_type: str = Field(
        ...,
        description="MULTI-SENSOR_CHANGE_SIGNAL, SAR_RAINFALL_ASSOCIATION, FIRE_OPTICAL_ASSOCIATION, EARTHQUAKE_SAR_ASSOCIATION, TERRAIN_SLOPE_ASSOCIATION"
    )
    source_evidence_ids: List[str]
    temporal_relationship: Dict[str, Any]
    spatial_relationship: Dict[str, Any]
    supporting_values: Dict[str, Any]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    scientific_note: str
    provenance: Dict[str, Any] = Field(default_factory=dict)


class MultiSensorEvidence(BaseModel):
    """
    Unified multi-sensor evidence snapshot for a critical sovereign location.
    """
    id: str
    location_id: str
    location_name: str
    evidence_window_start: datetime
    evidence_window_end: datetime
    reference_time: datetime
    sentinel1: Sentinel1Evidence
    sentinel2: Sentinel2Evidence
    rainfall: RainfallEvidence
    fire: FireEvidence
    earthquake: EarthquakeEvidence
    terrain: TerrainEvidence
    correlations: List[EvidenceCorrelation] = Field(default_factory=list)
    summary_designations: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    processing_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
