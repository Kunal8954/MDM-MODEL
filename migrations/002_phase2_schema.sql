-- ============================================================
-- SATGUARD Phase 2 Database Migration: Sentinel-1 SAR Engine
-- ============================================================

CREATE TABLE IF NOT EXISTS sentinel1_retrievals (
    id VARCHAR(100) PRIMARY KEY,
    observation_id VARCHAR(100) NOT NULL REFERENCES satellite_observations(id) ON DELETE CASCADE,
    product_id VARCHAR(255) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    source_url VARCHAR(500) NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(50) NOT NULL DEFAULT 'SUCCESS'
);

CREATE INDEX IF NOT EXISTS idx_s1_retrievals_obs ON sentinel1_retrievals(observation_id);
CREATE INDEX IF NOT EXISTS idx_s1_retrievals_prod ON sentinel1_retrievals(product_id);

CREATE TABLE IF NOT EXISTS sentinel1_processing_results (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    observation_id VARCHAR(100) NOT NULL REFERENCES satellite_observations(id) ON DELETE CASCADE,
    product_id VARCHAR(255) NOT NULL,
    acquisition_time TIMESTAMPTZ NOT NULL,
    vv_statistics TEXT NOT NULL DEFAULT '{}',
    vh_statistics TEXT NOT NULL DEFAULT '{}',
    vv_raster_path VARCHAR(500) NOT NULL,
    vh_raster_path VARCHAR(500) NOT NULL,
    processing_version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'SUCCESS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_s1_proc_loc_time ON sentinel1_processing_results(location_id, acquisition_time DESC);
CREATE INDEX IF NOT EXISTS idx_s1_proc_obs ON sentinel1_processing_results(observation_id);

CREATE TABLE IF NOT EXISTS sentinel1_change_detections (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    t1_observation_id VARCHAR(100) NOT NULL REFERENCES satellite_observations(id),
    t2_observation_id VARCHAR(100) NOT NULL REFERENCES satellite_observations(id),
    t1_product_id VARCHAR(255) NOT NULL,
    t2_product_id VARCHAR(255) NOT NULL,
    t1_acquisition_time TIMESTAMPTZ NOT NULL,
    t2_acquisition_time TIMESTAMPTZ NOT NULL,
    orbit_information TEXT NOT NULL DEFAULT '{}',
    delta_vv_statistics TEXT NOT NULL DEFAULT '{}',
    delta_vh_statistics TEXT NOT NULL DEFAULT '{}',
    changed_percentage REAL NOT NULL DEFAULT 0.0,
    thresholds TEXT NOT NULL DEFAULT '{}',
    change_raster_path VARCHAR(500),
    status VARCHAR(50) NOT NULL DEFAULT 'SUCCESS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_s1_changes_loc_time ON sentinel1_change_detections(location_id, created_at DESC);
