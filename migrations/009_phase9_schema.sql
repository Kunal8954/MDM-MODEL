-- ============================================================
-- SATGUARD Phase 9 Database Migration: Historical Intelligence & Trend Analytics
-- ============================================================

CREATE TABLE IF NOT EXISTS historical_analytics_reports (
    id VARCHAR(100) PRIMARY KEY,
    location_id VARCHAR(100) NOT NULL REFERENCES critical_locations(id) ON DELETE CASCADE,
    window_days INTEGER NOT NULL DEFAULT 30,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    data_sufficiency VARCHAR(50) NOT NULL DEFAULT 'INSUFFICIENT',
    persistence_status VARCHAR(50) NOT NULL DEFAULT 'INSUFFICIENT_DATA',
    risk_trend VARCHAR(50) NOT NULL DEFAULT 'INSUFFICIENT_DATA',
    baseline_comparison VARCHAR(50) NOT NULL DEFAULT 'INSUFFICIENT_DATA',
    deviation_status VARCHAR(50) NOT NULL DEFAULT 'NORMAL',
    sar_summary TEXT,
    optical_summary TEXT,
    environmental_summary TEXT,
    risk_summary TEXT,
    alert_summary TEXT,
    persistence_summary TEXT,
    baseline_summary TEXT,
    deviation_summary TEXT,
    engine_version VARCHAR(50) NOT NULL DEFAULT 'analytics_v1',
    explanation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hist_analytics_loc ON historical_analytics_reports(location_id, window_days, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hist_analytics_time ON historical_analytics_reports(created_at DESC);
