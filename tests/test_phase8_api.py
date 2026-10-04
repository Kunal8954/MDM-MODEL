"""
tests/test_phase8_api.py
Comprehensive Verification & Regression Suite for:
PHASE 8 — GOVERNMENT INTELLIGENCE DASHBOARD BACKEND API ENDPOINTS

Tests:
1. GET /api/overview live statistics & operational health
2. GET /api/alerts unified alerts across critical locations
3. GET /api/alerts filtering by status and priority
4. GET /api/alerts/{alert_id} detail & audit events history
5. GET /api/locations/{location_id}/timeline chronological multi-sensor timeline
6. Real Tehri Dam authoritative values preservation (63.28 / 100, HIGH, STRONG)
7. Missing-data semantics verification
"""

import pytest
from fastapi.testclient import TestClient

from satguard.api.main import app
from satguard.db.session import get_db_session
from satguard.models.entities import CriticalLocation, RiskAssessment, Alert as DBAlert

client = TestClient(app)


def test_overview_endpoint():
    """Verify GET /api/overview returns live, non-mock operational metrics."""
    res = client.get("/api/overview")
    assert res.status_code == 200
    data = res.json()

    assert "total_locations" in data
    assert "active_monitoring_locations" in data
    assert "high_risk_locations" in data
    assert "critical_risk_locations" in data
    assert "active_alerts_count" in data
    assert "total_alerts_count" in data
    assert "recent_runs_count" in data
    assert data["system_status"] in ["OPERATIONAL", "DEGRADED", "ERROR"]
    assert data["mode"] == "REAL_DATA_ONLY"
    assert "data_freshness" in data

    # Cross-reference with database directly
    with get_db_session() as db:
        actual_count = db.query(CriticalLocation).count()
        assert data["total_locations"] == actual_count


def test_all_alerts_endpoint():
    """Verify GET /api/alerts returns government alerts enriched with location names."""
    res = client.get("/api/alerts")
    assert res.status_code == 200
    alerts = res.json()
    assert isinstance(alerts, list)

    if len(alerts) > 0:
        first = alerts[0]
        assert "id" in first
        assert "location_id" in first
        assert "location_name" in first
        assert "priority" in first
        assert "status" in first
        assert "title" in first


def test_alerts_filter_by_status_and_priority():
    """Verify GET /api/alerts query parameters filter correctly."""
    # Filter by status=ACTIVE
    res_active = client.get("/api/alerts?status=ACTIVE")
    assert res_active.status_code == 200
    for a in res_active.json():
        assert a["status"] == "ACTIVE"

    # Filter by priority=HIGH
    res_high = client.get("/api/alerts?priority=HIGH")
    assert res_high.status_code == 200
    for a in res_high.json():
        assert a["priority"] == "HIGH"


def test_alert_detail_endpoint():
    """Verify GET /api/alerts/{alert_id} returns alert details with event history."""
    with get_db_session() as db:
        alert = db.query(DBAlert).first()
        if not alert:
            pytest.skip("No alert in DB to test detail endpoint")
        alert_id = alert.id

    res = client.get(f"/api/alerts/{alert_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == alert_id
    assert "location_name" in data
    assert "events" in data
    assert isinstance(data["events"], list)

    # 404 on nonexistent alert
    res_404 = client.get("/api/alerts/nonexistent-alert-id-999")
    assert res_404.status_code == 404


def test_location_timeline_endpoint():
    """Verify GET /api/locations/{location_id}/timeline returns chronological audit stream."""
    # Tehri Dam timeline
    res = client.get("/api/locations/loc-001-tehri-dam/timeline")
    assert res.status_code == 200
    events = res.json()
    assert isinstance(events, list)

    if len(events) > 1:
        # Check that events are sorted chronologically descending
        for i in range(len(events) - 1):
            assert events[i]["timestamp"] >= events[i + 1]["timestamp"]

    # 404 on nonexistent location
    res_404 = client.get("/api/locations/nonexistent-loc-id/timeline")
    assert res_404.status_code == 404


@pytest.mark.live_data
def test_real_tehri_authoritative_values():
    """
    Verify Tehri Dam (loc-001-tehri-dam) risk assessment preserves exact authoritative values:
    Score: 63.28, Level: HIGH, Priority: HIGH, Strength: STRONG.
    """
    res = client.get("/api/locations/loc-001-tehri-dam/risk/latest")
    assert res.status_code == 200
    data = res.json()

    assert data["score"] == 63.28
    assert data["risk_level"] == "HIGH"
    assert data["monitoring_priority"] == "HIGH"
    assert data["evidence_strength"] == "STRONG"
    assert "explanation" in data
    assert "recommended_action" in data
    assert "engine_version" in data


def test_data_status_mode():
    """Verify data providers and REAL_DATA_ONLY mode."""
    res = client.get("/api/data-status")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "REAL_DATA_ONLY"
    assert "providers" in data
    assert data["providers"]["copernicus_sentinel_1"] == "ONLINE"
    assert data["providers"]["copernicus_sentinel_2"] == "ONLINE"
