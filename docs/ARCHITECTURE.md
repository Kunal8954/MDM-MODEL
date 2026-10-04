# SATGUARD Architecture, Data Storage & Provider Adapter Design

## Document Overview
This document specifies the software architecture, database schema, spatial indexing, object storage design, and provider abstraction layer for **SATGUARD**.

---

## 1. System Architecture Overview

SATGUARD is structured as a decoupled, microservice-ready modular architecture:

```
+----------------------------------------------------------------------------------------------------+
|                                    SATGUARD HIGH-LEVEL ARCHITECTURE                                |
+----------------------------------------------------------------------------------------------------+

       +------------------------------------+        +------------------------------------+
       |  Temporal Scheduler & Dispatcher   |        |   Emergency Seismic/Fire Trigger   |
       |  (Cron / Celery Beat / RQ Worker)  |        |   (Webhooks / High-Freq Listeners) |
       +-----------------+------------------+        +-----------------+------------------+
                         |                                             |
                         +----------------------+----------------------+
                                                |
                                                v
       +----------------------------------------------------------------------------------+
       |                           PROVIDER ABSTRACTION LAYER                             |
       |                                                                                  |
       |  +---------------------------+  +--------------------------+  +----------------+ |
       |  |  SatelliteProvider (CDSE) |  |  RainfallProvider (GPM)  |  | FireProvider   | |
       |  +---------------------------+  +--------------------------+  +----------------+ |
       |  +---------------------------+  +--------------------------+  +----------------+ |
       |  |  EarthquakeProvider(USGS) |  |  MapDataProvider (OSM)   |  | LLMProvider    | |
       |  +---------------------------+  +--------------------------+  +----------------+ |
       +----------------------------------------+-----------------------------------------+
                                                |
                                                v
       +----------------------------------------------------------------------------------+
       |                          SCIENTIFIC PROCESSING ENGINE                            |
       |                                                                                  |
       |   • SAR Backscatter Calibration & Coherence Delta ($\Delta\sigma_{VV}^0$)        |
       |   • Optical Spectral Indices ($\Delta\text{NDWI}$, $\Delta\text{NDVI}$, MNDWI)   |
       |   • DEM Topographic Gradient & Flow Routing (Slope, Aspect, Inundation)         |
       |   • Multi-Sensor Anomaly Fusion & Empirical Hazard Thresholding                  |
       +----------------------------------------+-----------------------------------------+
                                                |
                                                v
       +----------------------------------------------------------------------------------+
       |                       PERSISTENCE & OBJECT STORAGE LAYER                         |
       |                                                                                  |
       |   +------------------------------------+   +----------------------------------+  |
       |   |      PostgreSQL 16 + PostGIS 3.4   |   |   S3-Compatible Object Store     |  |
       |   |  • Spatial Geometries (Points/Poly)|   |   • Analysis Ready COGs          |  |
       |   |  • Temporal Observations & Indices |   |   • Water / Displacement Masks   |  |
       |   |  • Audit Logs & Alert History      |   |   • Generated GeoTIFF / NetCDF   |  |
       |   +------------------------------------+   +----------------------------------+  |
       +----------------------------------------------------------------------------------+
```

---

## 2. PostgreSQL + PostGIS Database Schema Design

The relational database acts as the single source of truth for location definitions, observation catalogs, execution states, change deltas, and generated intelligence reports.

### 2.1 Complete PostGIS DDL

```sql
-- Enable PostGIS and UUID Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- ENUM Types
CREATE TYPE location_priority_enum AS ENUM ('routine', 'elevated', 'critical', 'emergency');
CREATE TYPE location_type_enum AS ENUM (
    'dam',
    'reservoir',
    'glacier',
    'glacial_lake',
    'mountain_slope',
    'landslide_prone_area',
    'bridge',
    'critical_infrastructure',
    'coastal_zone',
    'forest',
    'mine',
    'urban_construction'
);
CREATE TYPE monitoring_frequency_enum AS ENUM (
    'continuous_pass',      -- Every available satellite overpass
    'daily_check',
    'bi_weekly',
    'monthly_baseline'
);
CREATE TYPE observation_quality_status_enum AS ENUM (
    'NO_NEW_OBSERVATION',
    'NEW_OBSERVATION_AVAILABLE',
    'QUALITY_REJECTED',
    'PROCESSING',
    'PROCESSING_FAILED',
    'ANALYSIS_COMPLETE',
    'DATA_UNAVAILABLE'
);
CREATE TYPE alert_severity_enum AS ENUM ('info', 'advisory', 'warning', 'critical_danger');

-- =====================================================================
-- TABLE 1: critical_locations
-- Defines monitored sovereign zones with geometric boundaries
-- =====================================================================
CREATE TABLE critical_locations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    location_type location_type_enum NOT NULL,
    priority location_priority_enum NOT NULL DEFAULT 'routine',
    monitoring_frequency monitoring_frequency_enum NOT NULL DEFAULT 'continuous_pass',
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    radius_meters INTEGER NOT NULL CHECK (radius_meters > 0),
    -- Spatial geometry: Polygon or MultiPolygon representing the exact monitored perimeter or buffer
    boundary GEOMETRY(Polygon, 4326) NOT NULL,
    risk_category VARCHAR(100) NOT NULL,
    description TEXT,
    country_code VARCHAR(3) DEFAULT 'IND',
    administrative_region VARCHAR(255),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_critical_locations_boundary ON critical_locations USING GIST (boundary);
CREATE INDEX idx_critical_locations_active_priority ON critical_locations (active, priority);

-- =====================================================================
-- TABLE 2: data_sources
-- Catalogs registered spaceborne and terrestrial data feeds
-- =====================================================================
CREATE TABLE data_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR(50) UNIQUE NOT NULL, -- e.g., 'CDSE_SENTINEL1', 'NASA_GPM', 'USGS_SEISMIC'
    name VARCHAR(255) NOT NULL,
    provider_organization VARCHAR(255) NOT NULL,
    api_endpoint VARCHAR(500) NOT NULL,
    auth_type VARCHAR(50) NOT NULL, -- 'oauth2', 'api_key', 'none'
    spatial_resolution_meters DOUBLE PRECISION,
    temporal_resolution_hours DOUBLE PRECISION,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================================
-- TABLE 3: satellite_products
-- Raw external catalog products discovered via STAC/OData
-- =====================================================================
CREATE TABLE satellite_products (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    data_source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE RESTRICT,
    external_product_id VARCHAR(255) UNIQUE NOT NULL, -- e.g. S2A_MSIL2A_20261001T052651_...
    constellation VARCHAR(50) NOT NULL, -- 'Sentinel-1', 'Sentinel-2'
    instrument VARCHAR(50) NOT NULL, -- 'SAR-C', 'MSI'
    processing_level VARCHAR(50) NOT NULL, -- 'L1C', 'L2A', 'GRD', 'SLC'
    cloud_cover_percentage REAL,
    acquisition_timestamp TIMESTAMPTZ NOT NULL,
    footprint GEOMETRY(Polygon, 4326) NOT NULL,
    s3_uri VARCHAR(1000), -- Direct S3 path e.g. s3://eodata/Sentinel-2/...
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_satellite_products_footprint ON satellite_products USING GIST (footprint);
CREATE INDEX idx_satellite_products_acq_time ON satellite_products (acquisition_timestamp);

-- =====================================================================
-- TABLE 4: satellite_observations
-- Distinct observation lifecycle instance for a specific Critical Location
-- =====================================================================
CREATE TABLE satellite_observations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    product_id UUID REFERENCES satellite_products(id) ON DELETE SET NULL,
    quality_status observation_quality_status_enum NOT NULL DEFAULT 'NEW_OBSERVATION_AVAILABLE',
    rejection_reason VARCHAR(255),
    acquisition_time TIMESTAMPTZ NOT NULL,
    processing_time TIMESTAMPTZ,
    sensor VARCHAR(50) NOT NULL,
    resolution_meters REAL NOT NULL,
    cloud_cover REAL,
    processing_level VARCHAR(50),
    raw_metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_location_acquisition_sensor UNIQUE (location_id, acquisition_time, sensor)
);

CREATE INDEX idx_observations_location_acq ON satellite_observations (location_id, acquisition_time DESC);
CREATE INDEX idx_observations_status ON satellite_observations (quality_status);

-- =====================================================================
-- TABLE 5: processing_jobs
-- Execution queue and audit ledger for spatial matrix crunching
-- =====================================================================
CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    observation_id UUID NOT NULL REFERENCES satellite_observations(id) ON DELETE CASCADE,
    job_type VARCHAR(100) NOT NULL, -- 'SAR_BACKSCATTER_DELTA', 'WATER_EXTENT_NDWI', 'TERRAIN_SLOPE_FUSION'
    status VARCHAR(50) NOT NULL DEFAULT 'QUEUED', -- 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'
    retry_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    execution_host VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_processing_jobs_status ON processing_jobs (status);

-- =====================================================================
-- TABLE 6: change_detections
-- Quantified physical delta comparing Observation T_n against Baseline T_0/T_{n-1}
-- =====================================================================
CREATE TABLE change_detections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    current_observation_id UUID NOT NULL REFERENCES satellite_observations(id) ON DELETE RESTRICT,
    baseline_observation_id UUID NOT NULL REFERENCES satellite_observations(id) ON DELETE RESTRICT,
    metric_type VARCHAR(100) NOT NULL, -- 'SURFACE_WATER_AREA_DELTA_M2', 'COHERENCE_LOSS', 'NDVI_LOSS_M2'
    baseline_value DOUBLE PRECISION NOT NULL,
    current_value DOUBLE PRECISION NOT NULL,
    percentage_change DOUBLE PRECISION NOT NULL,
    confidence_score REAL NOT NULL CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    change_mask_s3_path VARCHAR(1000), -- GeoTIFF raster mask stored in S3
    change_geometry GEOMETRY(MultiPolygon, 4326), -- Vectorized polygon of altered surface
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_change_detections_location ON change_detections (location_id, created_at DESC);
CREATE INDEX idx_change_detections_geom ON change_detections USING GIST (change_geometry);

-- =====================================================================
-- TABLE 7: risk_assessments
-- Multi-modal fused risk evaluation combining EO metrics with rainfall, DEM & seismic
-- =====================================================================
CREATE TABLE risk_assessments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    change_detection_id UUID REFERENCES change_detections(id) ON DELETE SET NULL,
    computed_hazard_score REAL NOT NULL CHECK (computed_hazard_score >= 0.0 AND computed_hazard_score <= 100.0),
    antecedent_rainfall_72h_mm REAL NOT NULL DEFAULT 0.0,
    dem_mean_slope_deg REAL NOT NULL DEFAULT 0.0,
    max_seismic_magnitude_50km REAL DEFAULT 0.0,
    active_thermal_anomalies_count INTEGER DEFAULT 0,
    scientific_model_version VARCHAR(50) NOT NULL,
    llm_synthesized_sitrep JSONB, -- Strict JSON situation report produced by Groq LPU
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_risk_assessments_location ON risk_assessments (location_id, created_at DESC);

-- =====================================================================
-- TABLE 8: alerts
-- Actionable government alerts issued to authorized monitoring channels
-- =====================================================================
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    risk_assessment_id UUID NOT NULL REFERENCES risk_assessments(id) ON DELETE CASCADE,
    severity alert_severity_enum NOT NULL,
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_by VARCHAR(255),
    acknowledged_at TIMESTAMPTZ,
    dispatched_channels JSONB DEFAULT '["DASHBOARD"]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alerts_unacknowledged ON alerts (location_id, acknowledged, severity);
```

---

## 3. Object Storage Hierarchy (Cloud-Native Raster Caching)

While vector geometries and numerical indices reside in PostgreSQL, heavy scientific arrays, intermediate GeoTIFF rasters, and differential binary masks are persisted in S3-compatible Object Storage (MinIO or AWS S3):

```text
satguard-storage/
├── raw-cache/                                 # Temporary windowed bands pulled from CDSE S3
│   └── {location_id}/
│       └── {observation_id}/
│           ├── B04_red.tif
│           ├── B08_nir.tif
│           ├── B11_swir.tif
│           └── VV_backscatter.tif
├── derived-products/                          # Computed Analysis-Ready Data
│   └── {location_id}/
│       └── {observation_id}/
│           ├── ndwi.tif                       # Normalized Difference Water Index (32-bit float)
│           ├── ndvi.tif                       # Normalized Difference Vegetation Index
│           └── sar_amplitude_db.tif           # Calibrated $\sigma^0$ backscatter
├── change-masks/                              # Binary and categorical difference rasters
│   └── {location_id}/
│       └── {current_obs_id}_vs_{baseline_obs_id}/
│           ├── water_expansion_mask.tif       # Pixel delta mask
│           └── deformation_vector.geojson     # Vectorized perimeter shift
└── reports/                                   # Archived government intelligence briefs
    └── {location_id}/
        └── SITREP_{location_id}_{YYYYMMDD}.json
```

---

## 4. API Provider Abstraction Architecture

To enforce clean decoupling and ensure SATGUARD is never locked into a single provider or vendor, all external ingestion layers inherit from strict abstract interfaces.

```
                            +--------------------------+
                            |       BaseProvider       |
                            +------------+-------------+
                                         |
         +-------------------------------+-------------------------------+
         |                               |                               |
         v                               v                               v
+------------------+           +------------------+            +-------------------+
| SatelliteProvider|           | RainfallProvider |            |  EarthquakeProvider|
+--------+---------+           +--------+---------+            +---------+---------+
         |                              |                                |
         v                              v                                v
+--------------------------+   +-------------------+           +-------------------+
|CopernicusSatelliteProvider|  |GPMRainfallProvider|           |USGSEarthquakeProvider|
+--------------------------+   +-------------------+           +-------------------+
```

### 4.1 Python Interface Signatures

```python
"""
satguard/providers/base.py
Formal abstract interfaces defining the provider adapter contract.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from shapely.geometry import Polygon


class ObservationHeader(BaseModel):
    product_id: str
    sensor: str
    acquisition_time: datetime
    cloud_cover: Optional[float] = None
    footprint: Dict[str, Any]
    s3_uri: Optional[str] = None
    processing_level: str


class SatelliteProvider(ABC):
    """Abstract interface for spaceborne Earth observation discovery and retrieval."""

    @abstractmethod
    def authenticate(self) -> bool:
        """Establishes or refreshes provider authentication credentials."""
        pass

    @abstractmethod
    def search_observations(
        self,
        geometry: Polygon,
        start_time: datetime,
        end_time: datetime,
        max_cloud_cover: float = 30.0,
        sensor: Optional[str] = None
    ) -> List[ObservationHeader]:
        """Queries product catalog for available observations within the spatio-temporal envelope."""
        pass

    @abstractmethod
    def fetch_windowed_band(
        self,
        product_header: ObservationHeader,
        band_name: str,
        target_geometry: Polygon
    ) -> Any:
        """Streams a spatial crop of a single spectral band without downloading the full archive."""
        pass


class RainfallProvider(ABC):
    """Abstract interface for precipitation data retrieval."""

    @abstractmethod
    def get_accumulated_rainfall(
        self,
        latitude: float,
        longitude: float,
        hours_lookback: int = 72
    ) -> float:
        """Returns total precipitation accumulation in millimeters over the lookback window."""
        pass


class FireProvider(ABC):
    """Abstract interface for active thermal anomaly detection."""

    @abstractmethod
    def get_active_fires(
        self,
        bbox: tuple[float, float, float, float],
        days_lookback: int = 1
    ) -> List[Dict[str, Any]]:
        """Returns list of active thermal anomalies with Fire Radiative Power (MW)."""
        pass


class EarthquakeProvider(ABC):
    """Abstract interface for seismic event correlation."""

    @abstractmethod
    def get_seismic_events(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 100.0,
        min_magnitude: float = 3.5,
        start_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Returns seismic events intersecting the structural impact radius."""
        pass


class MapDataProvider(ABC):
    """Abstract interface for vector infrastructure extraction."""

    @abstractmethod
    def get_infrastructure_features(
        self,
        geometry: Polygon,
        feature_types: List[str]
    ) -> Dict[str, Any]:
        """Extracts vector geometries of dams, reservoirs, roads, and bridges in GeoJSON."""
        pass


class LLMProvider(ABC):
    """Abstract interface for evidence synthesis and briefing generation."""

    @abstractmethod
    def synthesize_situation_report(
        self,
        location_name: str,
        location_type: str,
        computed_metrics: Dict[str, Any],
        environmental_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Synthesizes physical telemetry into a structured intelligence briefing."""
        pass
```
