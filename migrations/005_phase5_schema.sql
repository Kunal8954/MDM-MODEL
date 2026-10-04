-- ============================================================
-- SATGUARD Phase 5 Database Migration: Groq Evidence Analyst
-- ============================================================

CREATE TABLE IF NOT EXISTS analyst_reports (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    risk_assessment_id VARCHAR(100) NOT NULL REFERENCES risk_assessments(id) ON DELETE CASCADE,
    executive_summary TEXT NOT NULL,
    report_data TEXT NOT NULL DEFAULT '{}',
    model VARCHAR(100) NOT NULL,
    prompt_version VARCHAR(50) NOT NULL DEFAULT 'evidence_analyst_v1',
    validation_status VARCHAR(50) NOT NULL DEFAULT 'VALIDATED',
    validation_errors TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analyst_reports_location ON analyst_reports(location_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyst_reports_assessment ON analyst_reports(risk_assessment_id);
