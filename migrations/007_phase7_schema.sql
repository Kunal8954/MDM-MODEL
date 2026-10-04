-- ====================================================================
-- SATGUARD: Phase 7 Schema Migration
-- Continuous Monitoring & Automated Reassessment Engine
-- ====================================================================

-- 1. Extend critical_locations with monitoring scheduling and status fields
ALTER TABLE critical_locations
    ADD COLUMN IF NOT EXISTS monitoring_interval_hours DOUBLE PRECISION DEFAULT 24.0,
    ADD COLUMN IF NOT EXISTS last_successful_run TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_attempted_run TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS next_scheduled_run TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_observation_check TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS monitoring_status VARCHAR(50) DEFAULT 'ACTIVE';

-- 2. Create monitoring_runs table
CREATE TABLE IF NOT EXISTS monitoring_runs (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    trigger_type VARCHAR(50) NOT NULL DEFAULT 'SCHEDULED',
    triggered_by VARCHAR(100) NOT NULL DEFAULT 'scheduler',
    current_stage VARCHAR(50) NOT NULL DEFAULT 'INITIALIZING',
    stage_history TEXT NOT NULL DEFAULT '[]',
    observations_checked INTEGER NOT NULL DEFAULT 0,
    observations_processed INTEGER NOT NULL DEFAULT 0,
    new_observations_found INTEGER NOT NULL DEFAULT 0,
    evidence_snapshot_id VARCHAR(100) REFERENCES evidence_snapshots(id) ON DELETE SET NULL,
    risk_assessment_id VARCHAR(100) REFERENCES risk_assessments(id) ON DELETE SET NULL,
    analyst_report_id VARCHAR(100) REFERENCES analyst_reports(id) ON DELETE SET NULL,
    alert_id VARCHAR(100) REFERENCES alerts(id) ON DELETE SET NULL,
    alert_action VARCHAR(50),
    outcome_code VARCHAR(50),
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    run_metadata TEXT NOT NULL DEFAULT '{}',
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. Indexes for rapid operational queries and concurrency control
CREATE INDEX IF NOT EXISTS idx_monitoring_runs_location_status ON monitoring_runs(location_id, status);
CREATE INDEX IF NOT EXISTS idx_monitoring_runs_started_at ON monitoring_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_monitoring_runs_outcome_code ON monitoring_runs(outcome_code);
CREATE INDEX IF NOT EXISTS idx_critical_locations_due ON critical_locations(monitoring_enabled, next_scheduled_run);
