"""
tests/test_phase9.py
Comprehensive Verification & Regression Suite for:
PHASE 9 — HISTORICAL INTELLIGENCE & TREND ANALYTICS

Validates all 26 required criteria:
1. Historical window calculation
2. Timestamp normalization
3. SAR historical series
4. Optical historical series
5. Risk historical series
6. Alert historical series
7. Persistence detection
8. Isolated signal detection
9. Intermittent signal detection
10. Persistent signal detection
11. Baseline calculation
12. Current vs baseline
13. Statistical deviation
14. Data sufficiency
15. Missing rainfall semantics
16. Missing fire semantics
17. Missing seismic semantics
18. Risk immutability
19. Alert lifecycle history
20. API tests
21. Dashboard historical rendering compatibility
22. Missing historical observations
23. Sparse-data behavior
24. No fabricated trends
25. No disaster-probability claims
26. Real Tehri Dam verification
"""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from satguard.api.main import app
from satguard.db.session import get_db_session
from satguard.models.entities import (
    CriticalLocation,
    SatelliteObservation,
    Sentinel1ChangeDetection,
    RiskAssessment,
    Alert as DBAlert,
    EvidenceSnapshot,
)
from satguard.analytics.schemas import (
    HistoricalWindow,
    DataSufficiencyEnum,
    PersistenceStatusEnum,
    RiskTrendClassificationEnum,
    BaselineComparisonStatusEnum,
    DeviationStatusEnum,
    SARHistoricalPoint,
    OpticalHistoricalPoint,
    RiskHistoricalPoint,
    AlertHistoricalPoint,
)
from satguard.analytics.historical import HistoricalAnalyticsService
from satguard.analytics.baseline import calculate_descriptive_stats, compare_value_to_baseline
from satguard.analytics.persistence import evaluate_persistence
from satguard.analytics.trends import (
    analyze_sar_trends,
    analyze_optical_trends,
    analyze_risk_trends,
    analyze_alert_trends,
)

client = TestClient(app)


# ==============================================================================
# 1. Historical Window Calculation
# ==============================================================================
def test_historical_window_calculation():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        
        # Test 30 days default
        w30 = service.resolve_time_window(days=30)
        assert w30.days == 30
        assert (w30.end_time - w30.start_time).days == 30
        assert w30.start_time.tzinfo is not None
        assert w30.end_time.tzinfo is not None

        # Test custom 90 days
        w90 = service.resolve_time_window(days=90)
        assert w90.days == 90
        assert (w90.end_time - w90.start_time).days == 90

        # Test explicit custom range
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 15, 0, 0, tzinfo=timezone.utc)
        w_custom = service.resolve_time_window(start_time=start, end_time=end)
        assert w_custom.start_time == start
        assert w_custom.end_time == end
        assert w_custom.days == 14


# ==============================================================================
# 2. Timestamp Normalization
# ==============================================================================
def test_timestamp_normalization():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=365)
        
        sar_pts = service.get_sar_series("loc-001-tehri-dam", window)
        for pt in sar_pts:
            if pt.t2_acquisition_time:
                # Acquisition timestamp preserved and timezone-aware
                assert isinstance(pt.t2_acquisition_time, datetime)
                assert pt.t2_acquisition_time.year in [2025, 2026]


# ==============================================================================
# 3. SAR Historical Series
# ==============================================================================
def test_sar_historical_series():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=365)
        sar_pts = service.get_sar_series("loc-001-tehri-dam", window)
        
        assert isinstance(sar_pts, list)
        if len(sar_pts) > 0:
            p = sar_pts[0]
            assert p.observation_id is not None
            assert p.changed_percentage is not None
            assert isinstance(p.is_significant_change, bool)


# ==============================================================================
# 4. Optical Historical Series & Cloud Filtering
# ==============================================================================
def test_optical_historical_series_cloud_filtering():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=365)
        optical_pts = service.get_optical_series("loc-001-tehri-dam", window)
        
        assert isinstance(optical_pts, list)
        for opt in optical_pts:
            assert isinstance(opt.acquisition_time, datetime)
            if opt.cloud_cover is not None and opt.cloud_cover > 50.0:
                assert opt.is_cloud_obscured is True
                assert opt.quality_status == "CLOUD_OBSCURED"


# ==============================================================================
# 5. Risk Historical Series
# ==============================================================================
def test_risk_historical_series():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=365)
        risk_pts = service.get_risk_series("loc-001-tehri-dam", window)
        
        assert isinstance(risk_pts, list)
        assert len(risk_pts) > 0
        r = risk_pts[0]
        assert r.score >= 0.0 and r.score <= 100.0
        assert r.risk_level in ["LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL", "URGENT"]
        assert r.engine_version is not None


# ==============================================================================
# 6. Alert Historical Series
# ==============================================================================
def test_alert_historical_series():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=365)
        alerts = service.get_alert_series("loc-001-tehri-dam", window)
        
        assert isinstance(alerts, list)
        for a in alerts:
            assert a.alert_id is not None
            assert a.priority in ["ROUTINE", "ELEVATED", "HIGH", "URGENT"]
            assert a.status in ["ACTIVE", "ACKNOWLEDGED", "IN_REVIEW", "RESOLVED", "EXPIRED", "SUPERSEDED"]


# ==============================================================================
# 7, 8, 9, 10. Persistence Detection (Isolated, Intermittent, Persistent)
# ==============================================================================
def test_persistence_detection_isolated_signal():
    pts = [
        SARHistoricalPoint(observation_id="obs1", changed_percentage=1.0, is_significant_change=False),
        SARHistoricalPoint(observation_id="obs2", changed_percentage=12.0, is_significant_change=True),
        SARHistoricalPoint(observation_id="obs3", changed_percentage=1.5, is_significant_change=False),
    ]
    res = evaluate_persistence(pts)
    assert res.persistence_status == PersistenceStatusEnum.ISOLATED_SIGNAL
    assert res.significant_observations_count == 1
    assert res.total_evaluated_observations == 3


def test_persistence_detection_intermittent_signal():
    pts = [
        SARHistoricalPoint(observation_id="obs1", changed_percentage=10.0, is_significant_change=True),
        SARHistoricalPoint(observation_id="obs2", changed_percentage=1.0, is_significant_change=False),
        SARHistoricalPoint(observation_id="obs3", changed_percentage=11.0, is_significant_change=True),
        SARHistoricalPoint(observation_id="obs4", changed_percentage=0.5, is_significant_change=False),
    ]
    res = evaluate_persistence(pts)
    assert res.persistence_status == PersistenceStatusEnum.INTERMITTENT_SIGNAL
    assert res.significant_observations_count == 2
    assert res.consecutive_significant_count == 1


def test_persistence_detection_persistent_signal():
    pts = [
        SARHistoricalPoint(observation_id="obs1", changed_percentage=15.0, is_significant_change=True),
        SARHistoricalPoint(observation_id="obs2", changed_percentage=18.0, is_significant_change=True),
        SARHistoricalPoint(observation_id="obs3", changed_percentage=14.0, is_significant_change=True),
    ]
    res = evaluate_persistence(pts)
    assert res.persistence_status == PersistenceStatusEnum.PERSISTENT_SIGNAL
    assert res.significant_observations_count == 3
    assert res.consecutive_significant_count == 3
    assert res.signal_ratio == 1.0


def test_persistence_detection_no_signal_and_insufficient():
    # Empty -> insufficient
    res_empty = evaluate_persistence([])
    assert res_empty.persistence_status == PersistenceStatusEnum.INSUFFICIENT_DATA

    # All clear -> NO_SIGNAL
    pts = [
        SARHistoricalPoint(observation_id="obs1", changed_percentage=0.5, is_significant_change=False),
        SARHistoricalPoint(observation_id="obs2", changed_percentage=0.8, is_significant_change=False),
    ]
    res_clear = evaluate_persistence(pts)
    assert res_clear.persistence_status == PersistenceStatusEnum.NO_SIGNAL


# ==============================================================================
# 11. Baseline Calculation
# ==============================================================================
def test_baseline_calculation():
    scores = [45.0, 50.0, 52.0, 48.0, 55.0, 60.0]
    stats = calculate_descriptive_stats(scores, "risk_score")
    
    assert stats.sample_count == 6
    assert stats.mean == 51.6667
    assert stats.min_val == 45.0
    assert stats.max_val == 60.0
    assert stats.median == 51.0
    assert stats.iqr is not None
    assert stats.std is not None


# ==============================================================================
# 12 & 13. Current vs Baseline & Statistical Deviation
# ==============================================================================
def test_current_vs_baseline_comparison():
    scores = [50.0, 52.0, 51.0, 49.0, 53.0]
    stats = calculate_descriptive_stats(scores, "risk_score")

    # Within baseline
    res_normal = compare_value_to_baseline(51.0, stats)
    assert res_normal.comparison_status == BaselineComparisonStatusEnum.WITHIN_BASELINE
    assert res_normal.deviation_status == DeviationStatusEnum.NORMAL

    # High outlier -> Above historical range
    res_extreme = compare_value_to_baseline(95.0, stats)
    assert res_extreme.comparison_status == BaselineComparisonStatusEnum.ABOVE_BASELINE
    assert res_extreme.deviation_status in [DeviationStatusEnum.UNUSUAL_RELATIVE_TO_BASELINE, DeviationStatusEnum.ABOVE_HISTORICAL_RANGE]


# ==============================================================================
# 14. Data Sufficiency
# ==============================================================================
def test_data_sufficiency():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        
        # Sufficient: >= 5 total
        assert service.evaluate_data_sufficiency(2, 2, 2) == DataSufficiencyEnum.SUFFICIENT
        # Limited: 2-4 total
        assert service.evaluate_data_sufficiency(1, 1, 0) == DataSufficiencyEnum.LIMITED
        # Insufficient: < 2 total
        assert service.evaluate_data_sufficiency(0, 0, 1) == DataSufficiencyEnum.INSUFFICIENT


# ==============================================================================
# 15. Missing Rainfall Semantics (UNAVAILABLE, never 0 mm)
# ==============================================================================
def test_missing_rainfall_semantics():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=7)
        env = service.get_environmental_history("loc-001-tehri-dam", window)
        
        # If rainfall is not available, status must be UNAVAILABLE and mean mm must be None, never 0.0
        if env.rainfall_observation_count == 0:
            assert env.rainfall_status == "UNAVAILABLE"
            assert env.rainfall_mean_mm is None


# ==============================================================================
# 16 & 17. Missing Fire & Seismic Semantics
# ==============================================================================
def test_missing_fire_and_seismic_semantics():
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=30)
        env = service.get_environmental_history("loc-001-tehri-dam", window)
        
        assert env.fire_status in ["VALID_ZERO_OBSERVATION", "FIRE_DETECTED", "UNAVAILABLE"]
        assert env.seismic_status in ["NO_EVENTS_DETECTED", "EVENTS_DETECTED"]


# ==============================================================================
# 18. Risk Immutability
# ==============================================================================
def test_risk_immutability():
    """Verify historical risk assessments are read directly without recomputation."""
    with get_db_session() as db:
        old_risk = db.query(RiskAssessment).filter(RiskAssessment.location_id == "loc-001-tehri-dam").first()
        assert old_risk is not None
        original_score = old_risk.score

        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=365)
        pts = service.get_risk_series("loc-001-tehri-dam", window)

        matched = [p for p in pts if p.risk_assessment_id == old_risk.id]
        assert len(matched) == 1
        assert matched[0].score == round(original_score, 2)


# ==============================================================================
# 19. Alert Lifecycle History
# ==============================================================================
def test_alert_lifecycle_history():
    pts = [
        AlertHistoricalPoint(
            alert_id="a1",
            created_at=datetime.now(timezone.utc) - timedelta(days=20),
            priority="HIGH",
            status="RESOLVED",
            title="Resolved High Alert",
        ),
        AlertHistoricalPoint(
            alert_id="a2",
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
            priority="HIGH",
            status="ACTIVE",
            title="Active High Alert",
        ),
    ]
    summary = analyze_alert_trends(pts)
    assert summary.total_alerts == 2
    assert summary.active_alerts == 1
    assert summary.resolved_alerts == 1
    assert summary.recurrence_detected is True
    assert "RECURRING_ALERT_PATTERN" in summary.recurrence_pattern


# ==============================================================================
# 20. API Tests
# ==============================================================================
def test_api_analytics_endpoints():
    # 1. Full History Report
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/history?days=30")
    assert res.status_code == 200
    data = res.json()
    assert data["location_id"] == "loc-001-tehri-dam"
    assert "window" in data
    assert "persistence" in data
    assert "sar_trends" in data
    assert "risk_trends" in data
    assert "baseline_comparison" in data
    assert "disclaimer" in data

    # 2. Trends
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/trends?days=30")
    assert res.status_code == 200
    assert "sar_trends" in res.json()

    # 3. Baseline
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/baseline?days=90")
    assert res.status_code == 200
    assert "baseline_comparison" in res.json()

    # 4. Persistence
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/persistence?days=30")
    assert res.status_code == 200
    assert "persistence" in res.json()

    # 5. Risk History
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/risk-history?days=90")
    assert res.status_code == 200
    assert "risk_trends" in res.json()

    # 6. Alerts History
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/alerts-history?days=90")
    assert res.status_code == 200
    assert "alert_trends" in res.json()

    # 7. Latest Snapshot
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/latest")
    assert res.status_code == 200
    assert "persistence_status" in res.json()

    # 8. Compare Locations
    res = client.get("/api/analytics/compare?location_ids=loc-001-tehri-dam&days=30")
    assert res.status_code == 200
    assert res.json()["comparison_count"] >= 1

    # 9. Structured Report Export
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/report?days=30")
    assert res.status_code == 200
    assert res.json()["report_type"] == "SATGUARD_HISTORICAL_INTELLIGENCE_REPORT"


# ==============================================================================
# 21. Dashboard Historical Rendering Compatibility
# ==============================================================================
def test_dashboard_rendering_compatibility():
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/history?days=30")
    assert res.status_code == 200
    data = res.json()
    
    # Required keys for HistoricalIntelligencePanel UI
    assert "window" in data
    assert "days" in data["window"]
    assert "persistence" in data
    assert "persistence_status" in data["persistence"]
    assert "explanation" in data["persistence"]
    assert "sar_trends" in data
    assert "points" in data["sar_trends"]
    assert "risk_trends" in data
    assert "points" in data["risk_trends"]
    assert "baseline_comparison" in data
    assert "comparison_status" in data["baseline_comparison"]
    assert "deviation_status" in data["baseline_comparison"]


# ==============================================================================
# 22 & 23. Missing Observations & Sparse Data Behavior
# ==============================================================================
def test_sparse_data_and_missing_observations():
    # Empty points must gracefully return insufficient data
    empty_sar = analyze_sar_trends([])
    assert empty_sar.signal_trend == "INSUFFICIENT_DATA"
    assert empty_sar.observation_count == 0

    empty_risk = analyze_risk_trends([])
    assert empty_risk.classification == RiskTrendClassificationEnum.INSUFFICIENT_DATA
    assert empty_risk.assessment_count == 0


# ==============================================================================
# 24. No Fabricated Trends
# ==============================================================================
def test_no_fabricated_trends():
    """Verify that points in SAR/Risk series match database records with no interpolation."""
    with get_db_session() as db:
        service = HistoricalAnalyticsService(db)
        window = service.resolve_time_window(days=365)
        sar_pts = service.get_sar_series("loc-001-tehri-dam", window)
        
        # Count in db
        actual_db_count = (
            db.query(Sentinel1ChangeDetection)
            .filter(
                Sentinel1ChangeDetection.location_id == "loc-001-tehri-dam",
                Sentinel1ChangeDetection.t2_acquisition_time >= window.start_time,
                Sentinel1ChangeDetection.t2_acquisition_time <= window.end_time,
            )
            .count()
        )
        assert len(sar_pts) == actual_db_count


# ==============================================================================
# 25. Conservative Semantics (No Disaster-Probability Claims)
# ==============================================================================
def test_conservative_scientific_semantics():
    res = client.get("/api/locations/loc-001-tehri-dam/analytics/history")
    assert res.status_code == 200
    content = str(res.json())

    # Prohibited claims
    assert "disaster predicted" not in content.lower()
    assert "dam failure predicted" not in content.lower()
    assert "landslide probability =" not in content.lower()

    # Allowed and required scientific terminology
    assert "disclaimer" in res.json()
    assert "does not claim exact disaster prediction" in res.json()["disclaimer"].lower()


# ==============================================================================
# 26. Real Tehri Dam Verification
# ==============================================================================
def test_real_tehri_dam_historical_verification():
    with get_db_session() as db:
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == "loc-001-tehri-dam").first()
        assert loc is not None
        assert loc.name == "Tehri Dam and Reservoir"

        service = HistoricalAnalyticsService(db)
        report = service.generate_report("loc-001-tehri-dam", days=365)
        
        assert report.location_id == "loc-001-tehri-dam"
        assert report.location_name == "Tehri Dam and Reservoir"
        assert report.data_sufficiency in [DataSufficiencyEnum.SUFFICIENT, DataSufficiencyEnum.LIMITED]
        assert report.persistence.persistence_status in [
            PersistenceStatusEnum.NO_SIGNAL,
            PersistenceStatusEnum.ISOLATED_SIGNAL,
            PersistenceStatusEnum.INTERMITTENT_SIGNAL,
            PersistenceStatusEnum.PERSISTENT_SIGNAL,
        ]
        assert len(report.risk_trends.points) > 0
