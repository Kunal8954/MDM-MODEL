"""
scripts/verify_phase6.py
End-to-End Real Integration Verification Script for Phase 6: Government Alert & Decision Support.
Verifies alert generation over real Tehri Dam authoritative Phase 4 RiskAssessment (Score 63.28, HIGH)
and validated Phase 5 AnalystReport.
"""

import sys
import json
from pathlib import Path
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import (
    CriticalLocation,
    EvidenceSnapshot,
    RiskAssessment,
    AnalystReport as DBAnalystReport,
    Alert as DBAlert,
    AlertEvent as DBAlertEvent,
)
from satguard.alert.schema import AlertLevel, AlertPriority, AlertStatus
from satguard.alert.engine import AlertDecisionEngine
from satguard.api.main import app

client = TestClient(app)


def run_phase6_verification():
    print("=" * 75)
    print("SATGUARD — PHASE 6 GOVERNMENT ALERT & DECISION SUPPORT VERIFICATION")
    print("=" * 75)

    init_db()
    db = get_db_session()

    try:
        location_id = "loc-001-tehri-dam"

        # 1. Verify existence of authoritative Phase 4 and Phase 5 records
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
        assert loc is not None, f"Location '{location_id}' not found!"

        risk_rec = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.location_id == location_id)
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
        assert risk_rec is not None, f"No RiskAssessment found for '{location_id}'!"

        analyst_rec = (
            db.query(DBAnalystReport)
            .filter(DBAnalystReport.location_id == location_id)
            .order_by(DBAnalystReport.created_at.desc())
            .first()
        )
        assert analyst_rec is not None, f"No AnalystReport found for '{location_id}'!"

        print(f"[*] Target Location                : {loc.name} ({loc.id})")
        print(f"[*] Loaded Stored Phase 4 Assessment: {risk_rec.id}")
        print(f"[*] Authoritative Risk Score       : {risk_rec.score:.2f} / 100.0")
        print(f"[*] Authoritative Risk Level       : {risk_rec.risk_level}")
        print(f"[*] Authoritative Priority         : {risk_rec.monitoring_priority}")
        print(f"[*] Authoritative Evidence Strength: {risk_rec.evidence_strength}")
        print(f"[*] Loaded Stored Phase 5 Report   : {analyst_rec.id} (Status: {analyst_rec.validation_status})")

        # 2. Invoke Alert Decision Engine
        print("\n[*] Invoking Deterministic Alert Decision Engine...")
        engine = AlertDecisionEngine()
        alert_res = engine.generate_and_persist(
            db=db,
            location_id=location_id,
            risk_assessment_id=risk_rec.id,
            analyst_report_id=analyst_rec.id,
        )

        # 3. Verify Deterministic Alert Properties
        print("\n" + "-" * 75)
        print("ALERT SPECIFICATION AUDIT")
        print("-" * 75)
        print(f"ALERT ID                : {alert_res.alert_id}")
        print(f"LOCATION ID             : {alert_res.location_id}")
        print(f"RISK ASSESSMENT ID      : {alert_res.risk_assessment_id}")
        print(f"ANALYST REPORT ID       : {alert_res.analyst_report_id}")
        print(f"ALERT LEVEL             : {alert_res.alert_level.value}")
        print(f"OPERATIONAL PRIORITY    : {alert_res.priority.value}")
        print(f"STATUS                  : {alert_res.status.value}")
        print(f"FINGERPRINT             : {alert_res.fingerprint}")
        print(f"TITLE                   : {alert_res.title}")
        print(f"EXPIRES AT              : {alert_res.expires_at.isoformat()}")
        print(f"DUPLICATE SUPPRESSED?   : {alert_res.is_duplicate}")

        assert alert_res.alert_level == AlertLevel.HIGH, f"Expected alert level HIGH, got {alert_res.alert_level}"
        assert alert_res.priority == AlertPriority.HIGH, f"Expected priority HIGH, got {alert_res.priority}"

        # 4. Strict Risk Immutability Audit
        print("\n" + "-" * 75)
        print("RISK & REPORT IMMUTABILITY AUDIT")
        print("-" * 75)
        db.refresh(risk_rec)
        assert risk_rec.score == 63.28, f"Authoritative risk score altered: {risk_rec.score}"
        assert risk_rec.risk_level == "HIGH", f"Authoritative risk level altered: {risk_rec.risk_level}"
        assert risk_rec.monitoring_priority == "HIGH", f"Authoritative priority altered: {risk_rec.monitoring_priority}"
        assert risk_rec.evidence_strength == "STRONG", f"Authoritative evidence strength altered: {risk_rec.evidence_strength}"
        assert analyst_rec.validation_status == "VALIDATED", f"Analyst report status altered: {analyst_rec.validation_status}"
        print("[+] Phase 4 Risk Score strictly preserved at 63.28/100")
        print("[+] Phase 4 Risk Level strictly preserved at HIGH")
        print("[+] Phase 4 Monitoring Priority strictly preserved at HIGH")
        print("[+] Phase 4 Evidence Strength strictly preserved at STRONG")
        print("[+] Phase 5 Analyst Report validation status strictly preserved as VALIDATED")

        # 5. Evidence Lineage Traceability & Rainfall Semantics
        print("\n" + "-" * 75)
        print("EVIDENCE TRACEABILITY & UNCERTAINTY AUDIT")
        print("-" * 75)
        refs = alert_res.evidence_references
        print(f"Evidence Snapshot ID    : {refs.get('evidence_snapshot_id')}")
        print(f"Sentinel-1 Traceability : Available={refs['sentinel1']['available']}, T1={refs['sentinel1']['t1_observation_id']}, T2={refs['sentinel1']['t2_observation_id']}")
        print(f"Sentinel-2 Traceability : Available={refs['sentinel2']['available']}, ObsID={refs['sentinel2']['observation_id']}")
        print(f"Rainfall Traceability   : Status={refs['rainfall']['status']}, Granules={refs['rainfall']['granules_found']}")
        print(f"Earthquake Traceability : Available={refs['earthquake']['available']}, Events={refs['earthquake']['events_count']}")
        print(f"Terrain Traceability    : Slope={refs['terrain']['slope_deg']} deg")

        assert refs.get("evidence_snapshot_id") is not None
        assert refs.get("risk_assessment_id") == risk_rec.id
        assert refs.get("analyst_report_id") == analyst_rec.id

        # Requirement 23 check
        assert refs["rainfall"]["status"] == "UNAVAILABLE"
        assert any("Precipitation data unavailable in observation window" in u for u in alert_res.uncertainty)
        print("[+] Requirement 23 Rainfall Semantics strictly observed (UNAVAILABLE != 0.0 mm)")

        # 6. Database Persistence & Audit Trail
        print("\n" + "-" * 75)
        print("PERSISTENCE & AUDIT EVENT VERIFICATION")
        print("-" * 75)
        db_alert = db.query(DBAlert).filter(DBAlert.id == alert_res.alert_id).first()
        assert db_alert is not None, "Alert record not persisted in database!"
        print(f"[+] Alert record persisted in 'alerts' table: ID={db_alert.id}")

        audit_events = db.query(DBAlertEvent).filter(DBAlertEvent.alert_id == alert_res.alert_id).all()
        assert len(audit_events) >= 1, "No audit events recorded for alert!"
        print(f"[+] {len(audit_events)} audit event(s) recorded in 'alert_events' table:")
        for ev in audit_events:
            print(f"    - Event: {ev.event_type} | Transition: {ev.previous_status} -> {ev.new_status} | Reason: {ev.reason}")

        # 7. FastAPI Endpoints Verification
        print("\n" + "-" * 75)
        print("FASTAPI REST ENDPOINT VERIFICATION")
        print("-" * 75)

        # GET /api/locations/{location_id}/alerts
        r_hist = client.get(f"/api/locations/{location_id}/alerts")
        assert r_hist.status_code == 200
        print(f"[+] GET /api/locations/{location_id}/alerts: {len(r_hist.json())} alerts found")

        # GET /api/locations/{location_id}/alerts/active
        r_act = client.get(f"/api/locations/{location_id}/alerts/active")
        assert r_act.status_code == 200
        print(f"[+] GET /api/locations/{location_id}/alerts/active: {len(r_act.json())} active alerts found")

        # GET /api/locations/{location_id}/alerts/latest
        r_lat = client.get(f"/api/locations/{location_id}/alerts/latest")
        assert r_lat.status_code == 200
        print(f"[+] GET /api/locations/{location_id}/alerts/latest: Latest ID={r_lat.json()['id']}")

        # 8. Human Acknowledgement Lifecycle API Check
        print("\n" + "-" * 75)
        print("HUMAN ACKNOWLEDGEMENT LIFECYCLE API")
        print("-" * 75)
        r_ack = client.post(
            f"/api/alerts/{alert_res.alert_id}/acknowledge",
            json={"actor": "Director_NDMA", "note": "Operational monitoring alert acknowledged by directorate."},
        )
        assert r_ack.status_code == 200
        ack_data = r_ack.json()
        assert ack_data["status"] == "ACKNOWLEDGED"
        print(f"[+] POST /api/alerts/{alert_res.alert_id}/acknowledge: Status={ack_data['status']}")
        print(f"    Acknowledged by: {ack_data['acknowledgement_details']['actor']} at {ack_data['acknowledged_at']}")

        print("\n" + "=" * 75)
        print("PHASE 6 STATUS: PASS")
        print("=" * 75)
        return True

    finally:
        db.close()


if __name__ == "__main__":
    success = run_phase6_verification()
    sys.exit(0 if success else 1)
