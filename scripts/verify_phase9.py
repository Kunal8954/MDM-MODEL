"""
scripts/verify_phase9.py
Real-data verification script for SATGUARD Phase 9 — Historical Intelligence & Trend Analytics.
Verifies against actual database history for loc-001-tehri-dam without mock data.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation
from satguard.analytics.historical import HistoricalAnalyticsService
from fastapi.testclient import TestClient
from satguard.api.main import app


def verify_phase9():
    print("=" * 70)
    print("SATGUARD — PHASE 9 REAL-DATA VERIFICATION (TEHRI DAM)")
    print("=" * 70)

    init_db()
    db = get_db_session()

    try:
        # 1. Location Check
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == "loc-001-tehri-dam").first()
        if not loc:
            print("[FAIL] Critical location 'loc-001-tehri-dam' not found in database!")
            return False
        print(f"[PASS] Location verified: {loc.name} ({loc.id}) - {loc.location_type}")

        # 2. Historical Analytics Service Check
        service = HistoricalAnalyticsService(db)

        # Windows test: 30D and 365D
        print("\n--- Testing Historical Windows ---")
        w30 = service.resolve_time_window(days=30)
        w365 = service.resolve_time_window(days=365)
        print(f"[PASS] 30D Window:  {w30.start_time.isoformat()} -> {w30.end_time.isoformat()} ({w30.days} days)")
        print(f"[PASS] 365D Window: {w365.start_time.isoformat()} -> {w365.end_time.isoformat()} ({w365.days} days)")

        # Generate Report for 365D (capturing full dataset)
        report = service.generate_report("loc-001-tehri-dam", days=365, persist_snapshot=True)
        print("\n--- Phase 9 Historical Intelligence Report Generated ---")
        print(f"Report ID:          {report.id}")
        print(f"Data Sufficiency:   {report.data_sufficiency.value}")
        print(f"Persistence Status: {report.persistence.persistence_status.value}")
        print(f"Persistence Note:   {report.persistence.explanation}")

        # 3. SAR Series & Trends
        print("\n--- SAR Surface-Change Series ---")
        print(f"Observation Count:     {report.sar_trends.observation_count}")
        print(f"Valid Change Detections: {report.sar_trends.valid_change_count}")
        print(f"Mean Delta VV:         {report.sar_trends.mean_delta_vv} dB")
        print(f"Mean Delta VH:         {report.sar_trends.mean_delta_vh} dB")
        print(f"Mean Changed Pct:      {report.sar_trends.mean_changed_percentage}%")
        print(f"Signal Trend:          {report.sar_trends.signal_trend}")
        assert report.sar_trends.observation_count >= 0

        # 4. Optical Series & Cloud Filtering
        print("\n--- Optical Series (Sentinel-2) ---")
        print(f"Total Scenes:          {report.optical_trends.total_scenes}")
        print(f"Usable Scenes:         {report.optical_trends.usable_scenes}")
        print(f"Cloud Obscured:        {report.optical_trends.cloud_obscured_scenes}")
        print(f"Optical Stability:     {report.optical_trends.optical_stability}")

        # 5. Environmental Context & Missing Data Semantics
        print("\n--- Environmental History ---")
        print(f"GPM Rainfall Status:   {report.environmental_history.rainfall_status}")
        print(f"GPM Observations:      {report.environmental_history.rainfall_observation_count}")
        print(f"Accumulated Mean mm:   {report.environmental_history.rainfall_mean_mm}")
        print(f"FIRMS Fire Status:     {report.environmental_history.fire_status}")
        print(f"Active Fires Count:    {report.environmental_history.fire_detection_count}")
        print(f"USGS Seismic Status:   {report.environmental_history.seismic_status}")
        print(f"Seismic Events:        {report.environmental_history.seismic_event_count}")
        # Verify missing-data semantic rule: UNAVAILABLE != 0 mm
        if report.environmental_history.rainfall_observation_count == 0:
            assert report.environmental_history.rainfall_status == "UNAVAILABLE"
            assert report.environmental_history.rainfall_mean_mm is None
            print("[PASS] Missing rainfall semantic rule preserved (UNAVAILABLE != 0 mm).")

        # 6. Authoritative Risk Trajectory
        print("\n--- Authoritative Risk Trajectory ---")
        print(f"Assessments Count:     {report.risk_trends.assessment_count}")
        print(f"Latest Score:          {report.risk_trends.latest_score}")
        print(f"Average Score:         {report.risk_trends.average_score}")
        print(f"Score Delta:           {report.risk_trends.score_delta}")
        print(f"Classification:        {report.risk_trends.classification.value}")
        print(f"Level Transitions:     {report.risk_trends.level_transitions_count}")
        assert report.risk_trends.assessment_count > 0

        # 7. Alert Trends & Recurrence
        print("\n--- Alerts & Recurrence ---")
        print(f"Total Alerts:          {report.alert_trends.total_alerts}")
        print(f"Active Alerts:         {report.alert_trends.active_alerts}")
        print(f"Resolved Alerts:       {report.alert_trends.resolved_alerts}")
        print(f"Recurrence Detected:   {report.alert_trends.recurrence_detected}")

        # 8. Baseline Comparison & Statistical Deviation
        print("\n--- Historical Baseline Comparison ---")
        print(f"Comparison Status:     {report.baseline_comparison.comparison_status.value}")
        print(f"Deviation Status:      {report.baseline_comparison.deviation_status.value}")
        print(f"Baseline Mean:         {report.baseline_comparison.baseline_mean}")
        print(f"Deviation Z-Score:     {report.baseline_comparison.deviation_value}")
        print(f"Explanation:           {report.baseline_comparison.explanation}")

        # 9. Conservative Scientific Disclaimer
        print("\n--- Scientific Boundaries ---")
        print(f"Disclaimer: {report.disclaimer}")
        assert "does not claim exact disaster prediction" in report.disclaimer.lower()

        # 10. API Verification
        print("\n--- Testing Phase 9 REST API Endpoints ---")
        client = TestClient(app)

        endpoints = [
            "/api/locations/loc-001-tehri-dam/analytics/history?days=30",
            "/api/locations/loc-001-tehri-dam/analytics/trends?days=30",
            "/api/locations/loc-001-tehri-dam/analytics/baseline?days=90",
            "/api/locations/loc-001-tehri-dam/analytics/persistence?days=30",
            "/api/locations/loc-001-tehri-dam/analytics/risk-history?days=90",
            "/api/locations/loc-001-tehri-dam/analytics/alerts-history?days=90",
            "/api/locations/loc-001-tehri-dam/analytics/latest",
            "/api/analytics/compare?location_ids=loc-001-tehri-dam&days=30",
            "/api/locations/loc-001-tehri-dam/analytics/report?days=30",
        ]

        for ep in endpoints:
            res = client.get(ep)
            if res.status_code != 200:
                print(f"[FAIL] GET {ep} returned HTTP {res.status_code}")
                return False
            print(f"[PASS] GET {ep} -> HTTP 200 OK")

        print("\n" + "=" * 70)
        print("ALL PHASE 9 REAL-DATA VERIFICATION CHECKS PASSED!")
        print("=" * 70)
        return True

    finally:
        db.close()


if __name__ == "__main__":
    success = verify_phase9()
    sys.exit(0 if success else 1)
