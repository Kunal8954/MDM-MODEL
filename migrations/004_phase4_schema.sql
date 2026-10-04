-- ============================================================
-- SATGUARD Phase 4 Database Migration: Risk Assessment Engine
-- ============================================================

-- Create or update risk_assessments table
CREATE TABLE IF NOT EXISTS risk_assessments (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    evidence_snapshot_id VARCHAR(100) NOT NULL REFERENCES evidence_snapshots(id) ON DELETE CASCADE,
    score REAL NOT NULL,
    risk_level VARCHAR(50) NOT NULL,
    monitoring_priority VARCHAR(50) NOT NULL,
    evidence_strength VARCHAR(50) NOT NULL,
    confidence_score REAL NOT NULL DEFAULT 1.0,
    contributing_factors TEXT NOT NULL DEFAULT '[]',
    uncertainty_factors TEXT NOT NULL DEFAULT '[]',
    explanation TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    engine_version VARCHAR(50) NOT NULL DEFAULT 'risk_engine_v1',
    provenance TEXT NOT NULL DEFAULT '{}',
    score_interpretation VARCHAR(255) NOT NULL DEFAULT 'Monitoring risk score (0-100 scale). This is NOT a probability of disaster or confirmation of damage.',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_risk_assessments_location ON risk_assessments(location_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_snapshot ON risk_assessments(evidence_snapshot_id);
