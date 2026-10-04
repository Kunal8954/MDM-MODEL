"""
satguard/providers/base.py
Abstract base interfaces and data models for all SATGUARD data and service providers.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pydantic import BaseModel, Field
from shapely.geometry import Polygon


class ObservationHeader(BaseModel):
    product_id: str
    collection: str
    sensor: str
    acquisition_time: datetime
    cloud_cover: Optional[float] = None
    footprint: Dict[str, Any]
    s3_uri: Optional[str] = None
    processing_level: str
    quicklook_url: Optional[str] = None
    assets: Dict[str, Any] = Field(default_factory=dict)


class SeismicEvent(BaseModel):
    id: str
    magnitude: float
    place: str
    timestamp: datetime
    latitude: float
    longitude: float
    depth_km: float
    distance_km: float
    mmi: Optional[float] = None
    alert: Optional[str] = None


class ThermalAnomaly(BaseModel):
    latitude: float
    longitude: float
    brightness: float
    confidence: str
    acq_date: str
    acq_time: str
    frp_mw: float
    sensor: str


class SatelliteProvider(ABC):
    @abstractmethod
    def authenticate(self) -> bool:
        pass

    @abstractmethod
    def search_observations(
        self,
        geometry: Polygon,
        start_time: datetime,
        end_time: datetime,
        collection: str = "sentinel-2-l2a",
        max_cloud_cover: float = 30.0,
        limit: int = 20,
    ) -> List[ObservationHeader]:
        pass


class RainfallProvider(ABC):
    @abstractmethod
    def get_accumulated_rainfall(
        self,
        latitude: float,
        longitude: float,
        hours_lookback: int = 72,
    ) -> Dict[str, Any]:
        pass


class FireProvider(ABC):
    @abstractmethod
    def get_active_fires(
        self,
        bbox: Tuple[float, float, float, float],
        days_lookback: int = 2,
    ) -> List[ThermalAnomaly]:
        pass


class EarthquakeProvider(ABC):
    @abstractmethod
    def get_seismic_events(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 100.0,
        min_magnitude: float = 3.5,
        start_time: Optional[datetime] = None,
    ) -> List[SeismicEvent]:
        pass


class MapDataProvider(ABC):
    @abstractmethod
    def get_infrastructure_features(
        self,
        bbox: Tuple[float, float, float, float],
        feature_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        pass


class ElevationProvider(ABC):
    @abstractmethod
    def check_dem_tile_availability(
        self,
        latitude: float,
        longitude: float,
    ) -> Dict[str, Any]:
        pass


class LLMProvider(ABC):
    @abstractmethod
    def synthesize_situation_report(
        self,
        location_name: str,
        location_type: str,
        computed_metrics: Dict[str, Any],
        environmental_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        pass
