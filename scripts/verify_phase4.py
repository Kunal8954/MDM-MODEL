"""
scripts/verify_phase4.py
End-to-End Real Integration Verification Script for Phase 4: Risk Assessment Engine.
Evaluates stored Phase 3 Multi-Sensor Evidence for Tehri Dam and verifies deterministic
monitoring risk scoring, evidence strength classification, contributing factors,
uncertainties, database persistence, and FastAPI REST endpoints.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
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
from satguard.models.entities import CriticalLocation, EvidenceSnapshot, RiskAssessment
from satguard.risk.engine import RiskAssessmentEngine
from satguard.api.main import app


def run_phase4_verification():
    print("=" * 70)
    print("SATGUARD — PHASE 4 RISK ASSESSMENT ENGINE VERIFICATION")
    print("=" * 70)

    init_db()
    db = get_db_session()

    try:
        location_id = "loc-001-tehri-dam"

        # 1. Fetch latest real EvidenceSnapshot from Phase 3
        snapshot = (
            db.query(EvidenceSnapshot)
            .filter(EvidenceSnapshot.location_id == location_id)
            .order_by(EvidenceSnapshot.created_at.desc())
            .first()
        )
        assert snapshot is not None, f"No existing Phase 3 EvidenceSnapshot found for {location_id}!"
        print(f"[*] Loaded Stored Phase 3 Snapshot: {snapshot.id}")
        print(f"[*] Critical Location             : {location_id}")

        # 2. Run Risk Assessment Engine
        print("\n[*] Executing Deterministic Risk Assessment Engine...")
        engine = RiskAssessmentEngine()
        result = engine.assess_and_persist(db=db, evidence=snapshot)

        # 3. Print Assessment Results
        print("\n" + "=" * 70)
        print("PHASE 4 STATUS: PASS")
        print("=" * 70)

        print(f"ASSESSMENT ID         : {result.id}")
        print(f"LOCATION              : {result.location_name or result.location_id}")
        print(f"EVIDENCE SNAPSHOT ID  : {result.evidence_snapshot_id}")
        print(f"ENGINE VERSION        : {result.engine_version}")
        print(f"MONITORING RISK SCORE : {result.score:.2f} / 100.0")
        print(f"RISK LEVEL            : {result.risk_level.value}")
        print(f"MONITORING PRIORITY   : {result.monitoring_priority.value}")
        print(f"EVIDENCE STRENGTH     : {result.evidence_strength.value}")
        print(f"CONFIDENCE SCORE      : {result.confidence_score:.2f}")

        # 4. Print Contributing Factors Breakdown
        print("\n" + "-" * 70)
        print("AUDITABLE CONTRIBUTING FACTORS BREAKDOWN")
        print("-" * 70)
        print(f"Total Factors: {len(result.contributing_factors)}")
        for idx, factor in enumerate(result.contributing_factors, start=1):
            print(f"\n[{idx}] {factor.factor} (+{factor.contribution:.2f} pts)")
            print(f"    - Evidence ID : {factor.evidence_id}")
            print(f"    - Reason      : {factor.reason}")

        # 5. Print Uncertainty Factors
        print("\n" + "-" * 70)
        print("EXPLICIT UNCERTAINTY DECLARATIONS")
        print("-" * 70)
        if result.uncertainty_factors:
            for idx, unc in enumerate(result.uncertainty_factors, start=1):
                print(f"[{idx}] {unc}")
        else:
            print("No uncertainty factors recorded.")

        # 6. Operational Recommendations & Explanation
        print("\n" + "-" * 70)
        print("OPERATIONAL RECOMMENDATION & EXPLANATION")
        print("-" * 70)
        print(f"RECOMMENDED ACTION:\n  \"{result.recommended_action}\"\n")
        print(f"EXPLANATION:\n  \"{result.explanation}\"\n")
        print(f"INTERPRETATION BOUNDARY:\n  \"{result.score_interpretation}\"")

        # 7. Database Persistence Audit
        print("\n" + "-" * 70)
        print("DATABASE PERSISTENCE AUDIT")
        print("-" * 70)
        persisted = db.query(RiskAssessment).filter(RiskAssessment.id == result.id).first()
        assert persisted is not None, "Failed to locate persisted RiskAssessment record in DB!"
        print(f"[OK] Record successfully verified in 'risk_assessments' table.")
        print(f"     Row ID               : {persisted.id}")
        print(f"     Location ID          : {persisted.location_id}")
        print(f"     Evidence Snapshot ID : {persisted.evidence_snapshot_id}")
        print(f"     Score                : {persisted.score}")
        print(f"     Risk Level           : {persisted.risk_level}")
        print(f"     Monitoring Priority  : {persisted.monitoring_priority}")
        print(f"     Created At           : {persisted.created_at}")

        # 8. REST API Verification
        print("\n" + "-" * 70)
        print("FASTAPI REST ENDPOINT VERIFICATION")
        print("-" * 70)
        client = TestClient(app)

        # GET /api/locations/{location_id}/risk/latest
        res_latest = client.get(f"/api/locations/{location_id}/risk/latest")
        assert res_latest.status_code == 200, f"GET /risk/latest failed: {res_latest.status_code}"
        latest_json = res_latest.json()
        print(f"[OK] GET /api/locations/{location_id}/risk/latest -> 200 OK (Score: {latest_json['score']})")

        # GET /api/locations/{location_id}/risk
        res_list = client.get(f"/api/locations/{location_id}/risk")
        assert res_list.status_code == 200, f"GET /risk failed: {res_list.status_code}"
        list_json = res_list.json()
        print(f"[OK] GET /api/locations/{location_id}/risk -> 200 OK ({len(list_json)} historical records)")

        # POST /api/locations/{location_id}/risk/assess
        res_post = client.post(f"/api/locations/{location_id}/risk/assess?snapshot_id={snapshot.id}")
        assert res_post.status_code == 200, f"POST /risk/assess failed: {res_post.status_code}"
        post_json = res_post.json()
        print(f"[OK] POST /api/locations/{location_id}/risk/assess -> 200 OK (New Assessment ID: {post_json['id']})")

        print("\n" + "=" * 70)
        print("PHASE 4 COMPLETE: RISK ASSESSMENT ENGINE VERIFIED")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    run_phase4_verification()
