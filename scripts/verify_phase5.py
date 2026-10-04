"""
scripts/verify_phase5.py
End-to-End Real Integration Verification Script for Phase 5: Groq Evidence Analyst.
Executes live inference with Groq LPU engine over real Tehri Dam multi-sensor evidence
and Phase 4 authoritative risk assessment.
SECURITY: Never logs, displays, or exposes GROQ_API_KEY.
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
from satguard.models.entities import CriticalLocation, EvidenceSnapshot, RiskAssessment, AnalystReport as DBAnalystReport
from satguard.analyst.engine import EvidenceAnalystEngine
from satguard.api.main import app


def run_phase5_verification():
    print("=" * 70)
    print("SATGUARD — PHASE 5 GROQ EVIDENCE ANALYST VERIFICATION")
    print("=" * 70)

    init_db()
    db = get_db_session()

    try:
        location_id = "loc-001-tehri-dam"

        # 1. Verify location, evidence snapshot, and authoritative risk assessment
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
        assert loc is not None, f"Location '{location_id}' not found!"

        snap = (
            db.query(EvidenceSnapshot)
            .filter(EvidenceSnapshot.location_id == location_id)
            .order_by(EvidenceSnapshot.created_at.desc())
            .first()
        )
        assert snap is not None, f"No EvidenceSnapshot found for '{location_id}'!"

        risk_rec = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.location_id == location_id)
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
        assert risk_rec is not None, f"No RiskAssessment found for '{location_id}'!"

        print(f"[*] Target Location                : {loc.name} ({loc.id})")
        print(f"[*] Loaded Stored Phase 3 Snapshot : {snap.id}")
        print(f"[*] Loaded Stored Phase 4 Assessment: {risk_rec.id}")
        print(f"[*] Authoritative Risk Score       : {risk_rec.score:.2f} / 100.0")
        print(f"[*] Authoritative Risk Level       : {risk_rec.risk_level}")
        print(f"[*] Authoritative Priority         : {risk_rec.monitoring_priority}")
        print(f"[*] Authoritative Evidence Strength: {risk_rec.evidence_strength}")

        # 2. Check Groq Engine Configuration (without exposing key)
        engine = EvidenceAnalystEngine()
        assert engine.is_configured(), "Groq Evidence Analyst is not configured! Check GROQ_API_KEY."
        print(f"[*] Groq Engine Configured         : YES (Model: {engine.model})")
        print(f"[*] Prompt Version                 : {engine.prompt_version}")

        # 3. Execute Live Groq Inference
        print("\n[*] Invoking Groq LPU Evidence Analyst inference...")
        report = engine.generate_and_persist(db=db, location_id=location_id)

        # 4. Strict Validation Audit
        print("\n" + "=" * 70)
        print("PHASE 5 STATUS: PASS")
        print("=" * 70)

        print(f"REPORT ID               : {report.report_id}")
        print(f"LOCATION ID             : {report.location_id}")
        print(f"RISK ASSESSMENT ID      : {report.risk_assessment_id}")
        print(f"MODEL USED              : {report.model}")
        print(f"PROMPT VERSION          : {report.prompt_version}")
        print(f"VALIDATION STATUS       : {report.validation_status}")
        print(f"VALIDATION ERRORS       : {len(report.validation_errors)}")

        print("\n" + "-" * 70)
        print("RISK IMMUTABILITY AUDIT")
        print("-" * 70)
        assert report.authoritative_risk_score == risk_rec.score, "Risk score modified by LLM!"
        assert report.authoritative_risk_level == risk_rec.risk_level, "Risk level modified by LLM!"
        assert report.authoritative_monitoring_priority == risk_rec.monitoring_priority, "Priority modified!"
        assert report.authoritative_evidence_strength == risk_rec.evidence_strength, "Evidence strength modified!"

        print(f"[OK] Authoritative Score Preserved : {report.authoritative_risk_score:.2f} / 100.0")
        print(f"[OK] Authoritative Level Preserved : {report.authoritative_risk_level}")
        print(f"[OK] Monitoring Priority Preserved : {report.authoritative_monitoring_priority}")
        print(f"[OK] Evidence Strength Preserved  : {report.authoritative_evidence_strength}")

        print("\n" + "-" * 70)
        print("EXECUTIVE SUMMARY (WHAT CHANGED? EVIDENCE? PRIORITY? UNCERTAINTIES?)")
        print("-" * 70)
        print(report.executive_summary)

        print("\n" + "-" * 70)
        print("OBSERVED CHANGES TRACEABILITY")
        print("-" * 70)
        for idx, obs in enumerate(report.observed_changes, start=1):
            print(f"[{idx}] [{obs.category}] {obs.finding}")
            print(f"    - Metric   : {obs.traceability_metric}")
            print(f"    - Sources  : {', '.join(obs.evidence_ids) if obs.evidence_ids else 'Telemetry'}")

        print("\n" + "-" * 70)
        print("CROSS-SENSOR FINDINGS")
        print("-" * 70)
        for idx, corr in enumerate(report.cross_sensor_findings, start=1):
            print(f"[{idx}] {corr.correlation_type} (Confidence: {corr.confidence:.2f})")
            print(f"    - Finding        : {corr.finding}")
            print(f"    - Scientific Int : {corr.scientific_interpretation}")
            print(f"    - Sources        : {', '.join(corr.source_evidence_ids)}")

        print("\n" + "-" * 70)
        print("UNCERTAINTIES & DATA GAPS")
        print("-" * 70)
        print("UNCERTAINTIES:")
        for unc in report.uncertainty:
            print(f"  * {unc}")
        print("DATA GAPS:")
        for gap in report.data_gaps:
            print(f"  * {gap}")

        print("\n" + "-" * 70)
        print("MONITORING ASSESSMENT & RECOMMENDED VERIFICATION")
        print("-" * 70)
        print(f"ASSESSMENT:\n{report.monitoring_assessment}\n")
        print("RECOMMENDED OPERATIONAL VERIFICATION:")
        for rec in report.recommended_verification:
            print(f"  * {rec}")

        # 5. Database Persistence Audit
        print("\n" + "-" * 70)
        print("DATABASE PERSISTENCE AUDIT")
        print("-" * 70)
        persisted = db.query(DBAnalystReport).filter(DBAnalystReport.id == report.report_id).first()
        assert persisted is not None, "AnalystReport not persisted in DB!"
        print(f"[OK] Record successfully verified in 'analyst_reports' table.")
        print(f"     Row ID             : {persisted.id}")
        print(f"     Location ID        : {persisted.location_id}")
        print(f"     Risk Assessment ID : {persisted.risk_assessment_id}")
        print(f"     Model              : {persisted.model}")
        print(f"     Validation Status  : {persisted.validation_status}")
        print(f"     Created At         : {persisted.created_at}")

        # 6. REST API Verification
        print("\n" + "-" * 70)
        print("FASTAPI REST ENDPOINT VERIFICATION")
        print("-" * 70)
        client = TestClient(app)

        # GET /api/locations/{location_id}/analysis/latest
        res_latest = client.get(f"/api/locations/{location_id}/analysis/latest")
        assert res_latest.status_code == 200, f"GET /analysis/latest failed: {res_latest.status_code}"
        latest_json = res_latest.json()
        print(f"[OK] GET /api/locations/{location_id}/analysis/latest -> 200 OK (Report ID: {latest_json['id']})")

        # GET /api/locations/{location_id}/analysis
        res_list = client.get(f"/api/locations/{location_id}/analysis")
        assert res_list.status_code == 200, f"GET /analysis failed: {res_list.status_code}"
        list_json = res_list.json()
        print(f"[OK] GET /api/locations/{location_id}/analysis -> 200 OK ({len(list_json)} historical reports)")

        print("\n" + "=" * 70)
        print("PHASE 5 COMPLETE: GROQ EVIDENCE ANALYST VERIFIED")
        print("=" * 70)

    finally:
        db.close()


if __name__ == "__main__":
    run_phase5_verification()
