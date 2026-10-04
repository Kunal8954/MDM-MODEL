-- ============================================================
-- SATGUARD Phase 10 Database Migration: Security, RBAC & Audit
-- ============================================================

-- 1. Government Operators and Role Registry
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(100) PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    department VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'VIEWER', -- VIEWER, ANALYST, OPERATOR, SUPERVISOR, ADMIN
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- 2. Immutable Forensics & Security Audit Logs
CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(100) PRIMARY KEY,
    event_id VARCHAR(100) UNIQUE NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL,
    action VARCHAR(100) NOT NULL,
    resource VARCHAR(100) NOT NULL,
    resource_id VARCHAR(100),
    result VARCHAR(50) NOT NULL DEFAULT 'SUCCESS',
    ip_address VARCHAR(100),
    request_id VARCHAR(100),
    event_metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor ON audit_logs(actor);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);

-- 3. Production High-Frequency Query Optimizations
CREATE INDEX IF NOT EXISTS idx_monitoring_runs_loc_time ON monitoring_runs(location_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_loc_status ON alerts(location_id, status);
CREATE INDEX IF NOT EXISTS idx_risk_assessments_level ON risk_assessments(risk_level);
CREATE INDEX IF NOT EXISTS idx_sat_obs_loc_time ON satellite_observations(location_id, acquisition_time DESC);
