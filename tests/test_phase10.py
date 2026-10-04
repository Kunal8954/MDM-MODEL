"""
tests/test_phase10.py
Phase 10 Production Hardening, Security, RBAC, Audit Logging, and Observability Test Suite.
"""

import pytest
from fastapi.testclient import TestClient

from satguard.api.main import app
from satguard.config import settings
from satguard.security.auth import (
    authenticate_user,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from satguard.security.rbac import RoleEnum, has_sufficient_role, has_required_role
from satguard.security.audit import record_audit_event, query_audit_logs
from satguard.db.session import get_db_session

client = TestClient(app)


# ==============================================================================
# 1. AUTHENTICATION & TOKEN TESTS
# ==============================================================================

def test_password_hashing_and_verification():
    raw = "GovTopSecret#2026"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_jwt_token_creation_and_decoding():
    token = create_access_token(
        data={"sub": "operator.sharma", "role": "OPERATOR"},
        expires_minutes=15,
    )
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "operator.sharma"
    assert payload["role"] == "OPERATOR"


def test_api_login_success():
    res = client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "Operator@2026!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["role"] == "OPERATOR"
    assert data["username"] == "operator"


def test_api_login_invalid_password():
    res = client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "WrongPassword!"},
    )
    assert res.status_code == 401
    assert "Incorrect username or password" in res.json()["detail"]


def test_api_auth_me():
    # Login to get token
    login_res = client.post(
        "/api/auth/login",
        json={"username": "analyst", "password": "Analyst@2026!"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    
    # Check /api/auth/me with Bearer token
    res = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "analyst"
    assert data["role"] == "ANALYST"


# ==============================================================================
# 2. ROLE-BASED ACCESS CONTROL (RBAC) TESTS
# ==============================================================================

def test_role_hierarchy():
    assert has_required_role(RoleEnum.ADMIN, RoleEnum.VIEWER) is True
    assert has_required_role(RoleEnum.SUPERVISOR, RoleEnum.OPERATOR) is True
    assert has_required_role(RoleEnum.OPERATOR, RoleEnum.SUPERVISOR) is False
    assert has_required_role(RoleEnum.VIEWER, RoleEnum.ANALYST) is False
    assert has_required_role(RoleEnum.ANALYST, RoleEnum.ANALYST) is True


def test_user_management_rbac_enforcement():
    # Admin can list users
    admin_login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SatguardAdmin@2026!"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]
    
    res_admin = client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200
    users = res_admin.json()
    assert len(users) >= 5

    # Viewer token should be forbidden (403)
    viewer_login = client.post(
        "/api/auth/login",
        json={"username": "viewer", "password": "Viewer@2026!"},
    )
    assert viewer_login.status_code == 200
    viewer_token = viewer_login.json()["access_token"]
    
    res_viewer = client.get(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert res_viewer.status_code == 403


def test_alert_actions_rbac_protection():
    from satguard.models.entities import Alert as DBAlert
    from datetime import datetime, timezone
    import uuid

    db = get_db_session()
    test_alert_id = f"alt-rbac-{uuid.uuid4().hex[:6]}"
    try:
        alert = DBAlert(
            id=test_alert_id,
            location_id="loc-001-tehri-dam",
            risk_assessment_id="risk-rbac-test",
            alert_level="HIGH",
            priority="HIGH",
            status="ACTIVE",
            title="RBAC Alert Test",
            summary="RBAC test alert for authorization verification",
            reason="Test authorization flow",
            recommended_action="Verify operator privileges",
            fingerprint="fp-rbac-test",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc),
        )
        db.add(alert)
        db.commit()
    finally:
        db.close()


    # 1. Viewer token trying to acknowledge -> 403 Forbidden
    viewer_login = client.post(
        "/api/auth/login",
        json={"username": "viewer", "password": "Viewer@2026!"},
    )
    viewer_token = viewer_login.json()["access_token"]
    res_ack_viewer = client.post(
        f"/api/alerts/{test_alert_id}/acknowledge",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"notes": "Unauthorized attempt by viewer"},
    )
    assert res_ack_viewer.status_code == 403

    # 2. Operator token trying to acknowledge -> 200 OK
    operator_login = client.post(
        "/api/auth/login",
        json={"username": "operator", "password": "Operator@2026!"},
    )
    operator_token = operator_login.json()["access_token"]
    res_ack_operator = client.post(
        f"/api/alerts/{test_alert_id}/acknowledge",
        headers={"Authorization": f"Bearer {operator_token}"},
        json={"notes": "Authorized acknowledgment by operator"},
    )
    assert res_ack_operator.status_code == 200

    # 3. Operator token trying to resolve -> 403 Forbidden (requires SUPERVISOR)
    res_resolve_operator = client.post(
        f"/api/alerts/{test_alert_id}/resolve",
        headers={"Authorization": f"Bearer {operator_token}"},
        json={"notes": "Operator cannot resolve alerts"},
    )
    assert res_resolve_operator.status_code == 403

    # 4. Supervisor token trying to resolve -> 200 OK
    supervisor_login = client.post(
        "/api/auth/login",
        json={"username": "supervisor", "password": "Supervisor@2026!"},
    )
    supervisor_token = supervisor_login.json()["access_token"]
    res_resolve_supervisor = client.post(
        f"/api/alerts/{test_alert_id}/resolve",
        headers={"Authorization": f"Bearer {supervisor_token}"},
        json={"notes": "Authorized resolution by supervisor"},
    )
    assert res_resolve_supervisor.status_code == 200



# ==============================================================================
# 3. IMMUTABLE AUDIT LOGGING TESTS
# ==============================================================================

def test_audit_event_recording():
    db = get_db_session()
    try:
        log_entry = record_audit_event(
            db=db,
            actor="test.supervisor",
            role=RoleEnum.SUPERVISOR.value,
            action="ALERT_REVIEW",
            resource="alert",
            resource_id="alt-test-001",
            result="SUCCESS",
            metadata={"notes": "Satellite confirmation reviewed and approved."},
        )
        assert log_entry is not None
        assert log_entry.event_id is not None
        assert log_entry.actor == "test.supervisor"
        assert log_entry.action == "ALERT_REVIEW"
        
        # Verify query
        logs, total = query_audit_logs(db, resource_id="alt-test-001")
        assert len(logs) >= 1
        assert logs[0].resource_id == "alt-test-001"
    finally:
        db.close()


def test_api_audit_logs_rbac_protection():
    # Admin can query audit logs
    admin_login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "SatguardAdmin@2026!"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]
    
    res = client.get(
        "/api/audit/logs?limit=5",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    assert isinstance(data["logs"], list)
    assert data["total"] >= 1


# ==============================================================================
# 4. SECURITY HEADERS & REQUEST CORRELATION
# ==============================================================================

def test_security_headers_present():
    res = client.get("/api/health")
    assert res.status_code == 200
    headers = res.headers
    
    # Check OWASP security headers
    assert "x-content-type-options" in headers
    assert headers["x-content-type-options"] == "nosniff"
    assert "x-frame-options" in headers
    assert headers["x-frame-options"] in ["DENY", "SAMEORIGIN"]
    assert "referrer-policy" in headers
    
    # Request Correlation ID
    assert "x-request-id" in headers
    assert "x-process-time-ms" in headers


# ==============================================================================
# 5. HEALTH & OBSERVABILITY ENDPOINTS
# ==============================================================================

def test_liveness_endpoints():
    res_root = client.get("/live")
    assert res_root.status_code == 200
    data = res_root.json()
    assert data["status"] == "LIVE"
    assert data["service"] == "SATGUARD"

    res_api = client.get("/api/health/live")
    assert res_api.status_code == 200
    assert res_api.json()["status"] == "LIVE"


def test_readiness_endpoints():
    res_root = client.get("/ready")
    assert res_root.status_code == 200
    data = res_root.json()
    assert data["status"] in ["READY", "DEGRADED"]
    assert "database" in data["dependencies"]
    assert "scheduler" in data["dependencies"]
    assert "providers" in data["dependencies"]

    res_api = client.get("/api/health/ready")
    assert res_api.status_code == 200


def test_metrics_endpoint():
    res = client.get("/api/metrics")
    assert res.status_code == 200
    data = res.json()
    assert "uptime_seconds" in data
    assert "api_metrics" in data
    assert "requests_total" in data["api_metrics"]
    assert "monitoring_pipeline_metrics" in data


# ==============================================================================
# 6. RATE LIMITING MIDDLEWARE
# ==============================================================================

def test_rate_limiting_tracks_requests():
    # Make several fast requests to trigger request counters
    for _ in range(5):
        r = client.get("/api/health")
        assert r.status_code == 200
    
    # Verify metrics tracked these requests
    metrics_res = client.get("/api/metrics")
    assert metrics_res.status_code == 200
    metrics = metrics_res.json()
    assert metrics["api_metrics"]["requests_total"] >= 5
