-- ==============================================================================
-- SATGUARD PostgreSQL 16 + PostGIS 3.4 Production DDL Migration
-- Phase 1: Core Critical Location Surveillance & Temporal Observation Registry
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- 1. Critical Locations
CREATE TABLE IF NOT EXISTS critical_locations (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    location_type VARCHAR(100) NOT NULL,
    priority VARCHAR(50) NOT NULL DEFAULT 'routine',
    monitoring_frequency VARCHAR(50) NOT NULL DEFAULT 'continuous_pass',
    monitoring_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    radius_m INTEGER NOT NULL CHECK (radius_m > 0),
    geometry TEXT NOT NULL, -- Stored as WKT / GeoJSON text, with PostGIS geometry column below
    geom GEOMETRY(Polygon, 4326),
    risk_category VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_critical_locations_geom ON critical_locations USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_critical_locations_enabled ON critical_locations (monitoring_enabled);

-- 2. Satellite Observations
CREATE TABLE IF NOT EXISTS satellite_observations (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    product_id VARCHAR(255) NOT NULL,
    collection VARCHAR(100) NOT NULL, -- e.g. sentinel-2-l2a, sentinel-1-grd
    sensor VARCHAR(50) NOT NULL, -- MSI, SAR-C
    acquisition_time TIMESTAMPTZ NOT NULL,
    processing_time TIMESTAMPTZ,
    cloud_cover REAL,
    quality_status VARCHAR(50) NOT NULL DEFAULT 'NEW_OBSERVATION_AVAILABLE',
    rejection_reason VARCHAR(255),
    raw_metadata TEXT DEFAULT '{}',
    raster_artifact_path VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_location_product UNIQUE (location_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_observations_loc_time ON satellite_observations (location_id, acquisition_time DESC);
CREATE INDEX IF NOT EXISTS idx_observations_status ON satellite_observations (quality_status);

-- 3. Processing Jobs
CREATE TABLE IF NOT EXISTS processing_jobs (
    id VARCHAR(100) PRIMARY KEY,
    observation_id VARCHAR(100) NOT NULL REFERENCES satellite_observations(id) ON DELETE CASCADE,
    job_type VARCHAR(100) NOT NULL, -- NDWI_BASELINE, WATER_DELTA, SAR_BACKSCATTER
    status VARCHAR(50) NOT NULL DEFAULT 'QUEUED', -- QUEUED, RUNNING, COMPLETED, FAILED
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Change Detections
CREATE TABLE IF NOT EXISTS change_detections (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    current_observation_id VARCHAR(100) NOT NULL REFERENCES satellite_observations(id) ON DELETE RESTRICT,
    baseline_observation_id VARCHAR(100) NOT NULL REFERENCES satellite_observations(id) ON DELETE RESTRICT,
    change_type VARCHAR(100) NOT NULL DEFAULT 'WATER_EXTENT_CHANGE', -- WATER_EXTENT_CHANGE, NO_CHANGE, SURFACE_CHANGE
    baseline_water_area_m2 DOUBLE PRECISION NOT NULL,
    current_water_area_m2 DOUBLE PRECISION NOT NULL,
    water_change_area_m2 DOUBLE PRECISION NOT NULL,
    water_change_percentage DOUBLE PRECISION NOT NULL,
    mean_delta_ndwi DOUBLE PRECISION NOT NULL,
    max_delta_ndwi DOUBLE PRECISION NOT NULL,
    change_mask_path VARCHAR(500),
    summary_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_changes_location ON change_detections (location_id, created_at DESC);

-- 5. Risk Assessments (Ready for later phases)
CREATE TABLE IF NOT EXISTS risk_assessments (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    change_detection_id VARCHAR(100) REFERENCES change_detections(id) ON DELETE SET NULL,
    hazard_score REAL NOT NULL DEFAULT 0.0,
    rainfall_72h_mm REAL DEFAULT 0.0,
    dem_slope_deg REAL DEFAULT 0.0,
    seismic_proximity_km REAL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Alerts (Ready for later phases)
CREATE TABLE IF NOT EXISTS alerts (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    severity VARCHAR(50) NOT NULL DEFAULT 'advisory',
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
