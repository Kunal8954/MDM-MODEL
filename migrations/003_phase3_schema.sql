-- ============================================================
-- SATGUARD Phase 3 Database Migration: Multi-Sensor Evidence Fusion
-- ============================================================

CREATE TABLE IF NOT EXISTS evidence_snapshots (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    evidence_window_start TIMESTAMPTZ NOT NULL,
    evidence_window_end TIMESTAMPTZ NOT NULL,
    reference_time TIMESTAMPTZ NOT NULL,
    sentinel1_evidence TEXT NOT NULL DEFAULT '{}',
    sentinel2_evidence TEXT NOT NULL DEFAULT '{}',
    rainfall_evidence TEXT NOT NULL DEFAULT '{}',
    fire_evidence TEXT NOT NULL DEFAULT '{}',
    earthquake_evidence TEXT NOT NULL DEFAULT '{}',
    terrain_evidence TEXT NOT NULL DEFAULT '{}',
    correlations TEXT NOT NULL DEFAULT '[]',
    provenance TEXT NOT NULL DEFAULT '{}',
    processing_metadata TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_snapshots_location ON evidence_snapshots(location_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_snapshots_ref_time ON evidence_snapshots(reference_time DESC);
