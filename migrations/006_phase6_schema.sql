-- ============================================================
-- SATGUARD Phase 6 Database Migration: Government Alert & Decision Support
-- ============================================================

CREATE TABLE IF NOT EXISTS alerts (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    risk_assessment_id VARCHAR(100) NOT NULL REFERENCES risk_assessments(id) ON DELETE CASCADE,
    analyst_report_id VARCHAR(100) REFERENCES analyst_reports(id) ON DELETE SET NULL,
    alert_level VARCHAR(50) NOT NULL,
    priority VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_references TEXT NOT NULL DEFAULT '{}',
    contributing_factors TEXT NOT NULL DEFAULT '[]',
    uncertainty TEXT NOT NULL DEFAULT '[]',
    recommended_action TEXT NOT NULL,
    fingerprint VARCHAR(100) NOT NULL,
    escalation_history TEXT NOT NULL DEFAULT '[]',
    acknowledgement_details TEXT,
    resolution_details TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    alert_version VARCHAR(50) NOT NULL DEFAULT 'alert_engine_v1',
    source_engine_versions TEXT NOT NULL DEFAULT '{}',
    disclaimer VARCHAR(255) NOT NULL DEFAULT 'Operational decision-support alert. Does not constitute a disaster declaration, structural damage confirmation, or evacuation order.'
);

CREATE INDEX IF NOT EXISTS idx_alerts_location ON alerts(location_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_level ON alerts(alert_level);
CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint ON alerts(fingerprint);

CREATE TABLE IF NOT EXISTS alert_events (
    id VARCHAR(100) PRIMARY KEY,
    alert_id VARCHAR(100) NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    previous_status VARCHAR(50),
    new_status VARCHAR(50) NOT NULL,
    previous_level VARCHAR(50),
    new_level VARCHAR(50),
    actor VARCHAR(100) DEFAULT 'system',
    reason TEXT NOT NULL,
    event_metadata TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_events_alert ON alert_events(alert_id, created_at DESC);
