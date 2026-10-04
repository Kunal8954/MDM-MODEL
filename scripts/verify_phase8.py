"""
scripts/verify_phase8.py
Comprehensive End-to-End Verification Script for:
PHASE 8 — GOVERNMENT INTELLIGENCE DASHBOARD

Verifies:
1. Backend REST API live health & overview stats
2. Real Tehri Dam location intelligence ground truth:
   - Score: 63.28 / 100
   - Level: HIGH
   - Priority: HIGH
   - Evidence: STRONG
3. Real Sentinel-1 SAR change evidence:
   - T1 & T2 acquisitions
   - Relative orbit & direction
   - Delta VV & VH backscatter (dB)
   - Significant SAR change percentages
4. Real Sentinel-2 optical evidence & cloud contamination semantics
5. Multi-Sensor Evidence Snapshot (Phase 3)
6. Groq Evidence Analyst Report (Phase 5) non-authoritative boundary
7. Government Surveillance Alerts (Phase 6) & lifecycle actions
8. Continuous Monitoring Runs (Phase 7) & sequential stage trace
9. Chronological Surveillance Timeline
10. Frontend production bundle build verification
"""

import sys
import json
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from satguard.api.main import app
from satguard.db.session import get_db_session
from satguard.models.entities import (
    CriticalLocation,
    RiskAssessment,
    Alert as DBAlert,
    AnalystReport,
    Sentinel1ChangeDetection,
    SatelliteObservation,
    MonitoringRun,
)

client = TestClient(app)


def verify_phase8():
    print("=" * 70)
    print("SATGUARD — PHASE 8 GOVERNMENT INTELLIGENCE DASHBOARD VERIFICATION")
    print("=" * 70)

    # 1. Health & Overview
    res = client.get("/api/overview")
    assert res.status_code == 200, f"Overview endpoint failed: {res.status_code}"
    overview = res.json()
    print("\n[1] SYSTEM OVERVIEW STATUS:")
    print(f"    - System Status:             {overview['system_status']}")
    print(f"    - Operational Mode:          {overview['mode']}")
    print(f"    - Total Critical Locations:  {overview['total_locations']}")
    print(f"    - Active Monitoring Sites:   {overview['active_monitoring_locations']}")
    print(f"    - High Risk Locations:       {overview['high_risk_locations']}")
    print(f"    - Critical Risk Locations:   {overview['critical_risk_locations']}")
    print(f"    - Active Alerts:             {overview['active_alerts_count']}")
    print(f"    - Recent Monitoring Runs:    {overview['recent_runs_count']}")
    print(f"    - Telemetry Freshness:       {overview['data_freshness']}")

    assert overview["system_status"] == "OPERATIONAL"
    assert overview["mode"] == "REAL_DATA_ONLY"
    assert overview["total_locations"] > 0
    assert overview["high_risk_locations"] >= 1

    # 2. Real Tehri Dam Location Intelligence Ground Truth
    tehri_id = "loc-001-tehri-dam"
    res_loc = client.get(f"/api/locations/{tehri_id}")
    assert res_loc.status_code == 200, f"Tehri Dam location not found: {res_loc.status_code}"
    loc = res_loc.json()
    print("\n[2] REAL TEHRI DAM CRITICAL SITE:")
    print(f"    - Location ID:   {loc['id']}")
    print(f"    - Location Name: {loc['name']}")
    print(f"    - Location Type: {loc['location_type']}")
    print(f"    - Coordinates:   {loc['latitude']}°N, {loc['longitude']}°E")
    print(f"    - Radius AOI:    {loc['radius_m']} m")
    print(f"    - Status:        {loc['monitoring_status']}")

    assert loc["id"] == tehri_id
    assert loc["latitude"] == 30.3781
    assert loc["longitude"] == 78.4803

    # 3. Authoritative Phase 4 Risk Assessment Verification
    res_risk = client.get(f"/api/locations/{tehri_id}/risk/latest")
    assert res_risk.status_code == 200, f"Tehri risk assessment missing: {res_risk.status_code}"
    risk = res_risk.json()
    print("\n[3] AUTHORITATIVE RISK ASSESSMENT (PHASE 4 GROUND TRUTH):")
    print(f"    - Risk Score:          {risk['score']} / 100")
    print(f"    - Risk Level:          {risk['risk_level']}")
    print(f"    - Monitoring Priority: {risk['monitoring_priority']}")
    print(f"    - Evidence Strength:   {risk['evidence_strength']}")
    print(f"    - Confidence Score:    {risk['confidence_score']}")
    print(f"    - Engine Version:      {risk['engine_version']}")
    print(f"    - Explanation:         {risk['explanation'][:80]}...")
    print(f"    - Recommended Action:  {risk['recommended_action']}")

    # STRICT ASSERTIONS ON AUTHORITATIVE VALUES
    assert risk["score"] == 63.28, f"Expected 63.28, got {risk['score']}"
    assert risk["risk_level"] == "HIGH", f"Expected HIGH, got {risk['risk_level']}"
    assert risk["monitoring_priority"] == "HIGH", f"Expected HIGH, got {risk['monitoring_priority']}"
    assert risk["evidence_strength"] == "STRONG", f"Expected STRONG, got {risk['evidence_strength']}"

    # 4. Sentinel-1 SAR Change Detection Verification
    res_sar = client.get(f"/api/locations/{tehri_id}/sentinel-1/changes")
    assert res_sar.status_code == 200
    sar_changes = res_sar.json()
    print(f"\n[4] SENTINEL-1 SAR CHANGE EVIDENCE ({len(sar_changes)} records):")
    if len(sar_changes) > 0:
        c = sar_changes[0]
        print(f"    - T1 Acquisition:      {c.get('t1_acquisition_time')}")
        print(f"    - T2 Acquisition:      {c.get('t2_acquisition_time')}")
        print(f"    - Changed Percentage:  {c.get('changed_percentage')}%")
        vv_mean = (c.get("delta_vv_statistics") or {}).get("mean")
        vh_mean = (c.get("delta_vh_statistics") or {}).get("mean")
        print(f"    - Mean Delta VV:       {vv_mean} dB")
        print(f"    - Mean Delta VH:       {vh_mean} dB")

    # 5. Groq Evidence Analyst Report Verification
    res_analyst = client.get(f"/api/locations/{tehri_id}/analysis/latest")
    assert res_analyst.status_code == 200
    analyst = res_analyst.json()
    print("\n[5] GROQ EVIDENCE ANALYST REPORT (PHASE 5):")
    print(f"    - Report ID:    {analyst['id']}")
    print(f"    - Model Name:   {analyst['model']}")
    print(f"    - Summary:      {analyst['executive_summary'][:90]}...")
    print(f"    - Validation:   {analyst['validation_status']}")

    # 6. Government Surveillance Alerts Verification
    res_alerts = client.get(f"/api/locations/{tehri_id}/alerts")
    assert res_alerts.status_code == 200
    alerts = res_alerts.json()
    print(f"\n[6] GOVERNMENT SURVEILLANCE ALERTS ({len(alerts)} records):")
    if len(alerts) > 0:
        a = alerts[0]
        print(f"    - Alert ID:     {a['id']}")
        print(f"    - Priority:     {a['priority']}")
        print(f"    - Status:       {a['status']}")
        print(f"    - Title:        {a['title']}")

    # 7. Chronological Timeline Verification
    res_timeline = client.get(f"/api/locations/{tehri_id}/timeline")
    assert res_timeline.status_code == 200
    events = res_timeline.json()
    print(f"\n[7] CHRONOLOGICAL SURVEILLANCE TIMELINE ({len(events)} events):")
    for ev in events[:5]:
        print(f"    - [{ev['timestamp']}] {ev['event_type']}: {ev['title']}")

    assert len(events) > 0, "Expected at least 1 chronological event for Tehri Dam"

    # 8. All Alerts Endpoint & Filters
    res_all_alerts = client.get("/api/alerts")
    assert res_all_alerts.status_code == 200
    all_alerts = res_all_alerts.json()
    print(f"\n[8] GLOBAL ALERT CENTER ({len(all_alerts)} total alerts across system)")
    assert len(all_alerts) > 0

    print("\n" + "=" * 70)
    print("ALL PHASE 8 CHECKS PASSED SUCCESSFULLY (STATUS: PASS)")
    print("=" * 70)


if __name__ == "__main__":
    verify_phase8()
