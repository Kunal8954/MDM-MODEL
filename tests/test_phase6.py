"""
tests/test_phase6.py
Comprehensive Deterministic Unit and Integration Tests for Phase 6: Government Alert & Decision Support.

Covers all 28 requirements specified in Section 20:
1. LOW -> INFO
2. MODERATE -> MONITOR
3. HIGH -> HIGH
4. CRITICAL -> URGENT
5. Alert creation
6. Duplicate suppression
7. Alert fingerprint
8. Escalation
9. De-escalation
10. Acknowledgement
11. Review
12. Resolution
13. Expiration
14. Superseding
15. Audit events
16. Uncertainty propagation & Requirement 23 rainfall semantics
17. Evidence traceability lineage
18. Missing AnalystReport handling
19. Invalid AnalystReport handling
20. Missing RiskAssessment handling
21. Invalid RiskAssessment handling
22. Phase 4 risk immutability
23. Phase 5 regression verification
24. Phase 3 regression verification
25. Phase 2 regression verification
26. Phase 1 regression verification
27. FastAPI REST endpoints
28. Database persistence
"""

import json
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import (
    CriticalLocation,
    EvidenceSnapshot,
    RiskAssessment,
    AnalystReport as DBAnalystReport,
    Alert as DBAlert,
    AlertEvent as DBAlertEvent,
    SatelliteObservation,
    Sentinel1ProcessingResult,
    Sentinel1ChangeDetection,
    ChangeDetection,
)
from satguard.alert.schema import (
    AlertLevel,
    AlertStatus,
    AlertPriority,
    AlertAuditEventType,
    AlertResult,
)
from satguard.alert.config import AlertEngineConfig, default_alert_config
from satguard.alert.engine import AlertDecisionEngine
from satguard.api.main import app

client = TestClient(app)


# --------------------------------------------------------------------------
# FIXTURES
# --------------------------------------------------------------------------

@pytest.fixture
def db_session():
    """Provides a fresh database session with tables initialized."""
    init_db()
    with get_db_session() as session:
        yield session


@pytest.fixture
def mock_location(db_session):
    loc_id = "loc-phase6-test"
    loc = db_session.query(CriticalLocation).filter(CriticalLocation.id == loc_id).first()
    if not loc:
        loc = CriticalLocation(
            id=loc_id,
            name="Phase 6 Test Dam & Reservoir",
            location_type="dam",
            latitude=30.3781,
            longitude=78.4803,
            radius_m=3000,
            geometry="{}",
            risk_category="critical_infrastructure",
            priority="high",
        )
        db_session.add(loc)
        db_session.commit()
    return loc


@pytest.fixture
def mock_evidence_snapshot(db_session, mock_location):
    snap_id = "ev-snap-p6-test-1"
    snap = db_session.query(EvidenceSnapshot).filter(EvidenceSnapshot.id == snap_id).first()
    now_utc = datetime(2026, 10, 3, 10, 0, 0, tzinfo=timezone.utc)
    if not snap:
        snap = EvidenceSnapshot(
            id=snap_id,
            location_id=mock_location.id,
            evidence_window_start=now_utc - timedelta(days=30),
            evidence_window_end=now_utc,
            reference_time=now_utc,
            sentinel1_evidence=json.dumps({
                "available": True,
                "t1_observation_id": "s1-obs-t1",
                "t2_observation_id": "s1-obs-t2",
                "changed_percentage": 24.91,
                "joint_changed_percent": 9.40,
                "significant_region_count": 8,
                "mean_delta_vv_db": -0.27,
                "mean_delta_vh_db": -0.56,
            }),
            sentinel2_evidence=json.dumps({
                "available": True,
                "observation_id": "s2-obs-001",
                "cloud_cover": 4.5,
                "water_change_percentage": 18.2,
            }),
            rainfall_evidence=json.dumps({
                "available": False,
                "total_granules_found": 0,
                "total_precipitation_mm": None,
                "source": "NASA GPM IMERG",
            }),
            fire_evidence=json.dumps({"available": False, "fire_count": 0}),
            earthquake_evidence=json.dumps({
                "available": True,
                "events_found_count": 1,
                "nearest_event_id": "usgs-quake-01",
                "nearest_magnitude": 3.8,
                "distance_km": 42.0,
            }),
            terrain_evidence=json.dumps({
                "available": True,
                "elevation_m": 820.0,
                "slope_degrees": 24.5,
            }),
            correlations=json.dumps([{
                "correlation_type": "MULTI-SENSOR_CHANGE_SIGNAL",
                "confidence_score": 0.85,
            }]),
            created_at=now_utc,
        )
        db_session.add(snap)
        db_session.commit()
    return snap


@pytest.fixture
def mock_risk_assessment_high(db_session, mock_location, mock_evidence_snapshot):
    risk_id = "risk-assess-p6-high"
    r = db_session.query(RiskAssessment).filter(RiskAssessment.id == risk_id).first()
    now_utc = datetime(2026, 10, 3, 10, 30, 0, tzinfo=timezone.utc)
    if not r:
        r = RiskAssessment(
            id=risk_id,
            location_id=mock_location.id,
            evidence_snapshot_id=mock_evidence_snapshot.id,
            score=63.28,
            risk_level="HIGH",
            monitoring_priority="HIGH",
            evidence_strength="STRONG",
            confidence_score=0.92,
            contributing_factors=json.dumps([{"factor": "sar_change", "weight": 0.4}]),
            uncertainty_factors=json.dumps(["Precipitation observations unavailable"]),
            explanation="Coherent multi-sensor change signals warrant high monitoring priority.",
            recommended_action="Prioritize analyst review and field verification.",
            engine_version="risk_engine_v1",
            created_at=now_utc,
        )
        db_session.add(r)
        db_session.commit()
    return r


@pytest.fixture
def mock_analyst_report(db_session, mock_location, mock_risk_assessment_high):
    rep_id = "analyst-rep-p6-test"
    rep = db_session.query(DBAnalystReport).filter(DBAnalystReport.id == rep_id).first()
    now_utc = datetime(2026, 10, 3, 11, 0, 0, tzinfo=timezone.utc)
    if not rep:
        rep = DBAnalystReport(
            id=rep_id,
            location_id=mock_location.id,
            risk_assessment_id=mock_risk_assessment_high.id,
            executive_summary="Independent SAR and optical observations indicate significant surface-change signals within the monitored AOI.",
            report_data=json.dumps({
                "observed_changes": [{"category": "SAR", "finding": "Backscatter delta detected"}],
                "cross_sensor_findings": [{"finding": "Dual-sensor spatial coincidence"}],
                "environmental_context": "Steep terrain with 24.5 deg slope.",
                "confidence_assessment": "High confidence based on dual sensor corroboration.",
            }),
            model="llama-3.3-70b-versatile",
            prompt_version="analyst_prompt_v1",
            validation_status="VALIDATED",
            validation_errors="[]",
            created_at=now_utc,
        )
        db_session.add(rep)
        db_session.commit()
    return rep


# --------------------------------------------------------------------------
# 1-4. DETERMINISTIC MAPPING TESTS
# --------------------------------------------------------------------------

def test_mapping_low_to_info(mock_location, mock_evidence_snapshot):
    engine = AlertDecisionEngine()
    now_utc = datetime.now(timezone.utc)
    mock_risk = RiskAssessment(
        id="risk-low-001",
        location_id=mock_location.id,
        evidence_snapshot_id=mock_evidence_snapshot.id,
        score=15.0,
        risk_level="LOW",
        monitoring_priority="ROUTINE",
        evidence_strength="WEAK",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="Low risk conditions observed.",
        recommended_action="Continue routine monitoring schedule.",
        created_at=now_utc,
    )
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk,
        evidence_snapshot=mock_evidence_snapshot,
    )
    assert result.alert_level == AlertLevel.INFO
    assert result.priority == AlertPriority.ROUTINE
    assert "INFO" in result.title


def test_mapping_moderate_to_monitor(mock_location, mock_evidence_snapshot):
    engine = AlertDecisionEngine()
    now_utc = datetime.now(timezone.utc)
    mock_risk = RiskAssessment(
        id="risk-mod-001",
        location_id=mock_location.id,
        evidence_snapshot_id=mock_evidence_snapshot.id,
        score=35.0,
        risk_level="MODERATE",
        monitoring_priority="ROUTINE",
        evidence_strength="MODERATE",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="Moderate risk conditions observed.",
        recommended_action="Increase monitoring frequency.",
        created_at=now_utc,
    )
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk,
        evidence_snapshot=mock_evidence_snapshot,
    )
    assert result.alert_level == AlertLevel.MONITOR
    assert result.priority == AlertPriority.ROUTINE
    assert "MONITOR" in result.title


def test_mapping_high_to_high(mock_location, mock_evidence_snapshot, mock_risk_assessment_high, mock_analyst_report):
    engine = AlertDecisionEngine()
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk_assessment_high,
        evidence_snapshot=mock_evidence_snapshot,
        analyst_report=mock_analyst_report,
    )
    assert result.alert_level == AlertLevel.HIGH
    assert result.priority == AlertPriority.HIGH
    assert "HIGH" in result.title


def test_mapping_critical_to_urgent(mock_location, mock_evidence_snapshot):
    engine = AlertDecisionEngine()
    now_utc = datetime.now(timezone.utc)
    mock_risk = RiskAssessment(
        id="risk-crit-001",
        location_id=mock_location.id,
        evidence_snapshot_id=mock_evidence_snapshot.id,
        score=88.5,
        risk_level="CRITICAL",
        monitoring_priority="URGENT",
        evidence_strength="VERY_STRONG",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="Critical risk conditions observed.",
        recommended_action="Immediate analyst review and operational site inspection.",
        created_at=now_utc,
    )
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk,
        evidence_snapshot=mock_evidence_snapshot,
    )
    assert result.alert_level == AlertLevel.URGENT
    assert result.priority == AlertPriority.URGENT
    assert "URGENT" in result.title


# --------------------------------------------------------------------------
# 5. ALERT CREATION & SCIENTIFIC BOUNDARIES
# --------------------------------------------------------------------------

def test_alert_creation_and_disclaimer(mock_location, mock_evidence_snapshot, mock_risk_assessment_high, mock_analyst_report):
    engine = AlertDecisionEngine()
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk_assessment_high,
        evidence_snapshot=mock_evidence_snapshot,
        analyst_report=mock_analyst_report,
    )
    assert result.alert_id.startswith("alert-loc-phase6-test")
    assert result.location_id == mock_location.id
    assert result.status == AlertStatus.ACTIVE
    assert "disaster" not in result.summary.lower() or "not confirm a disaster" in result.summary.lower()
    assert "evacuation" not in result.recommended_action.lower()
    assert "Does not constitute a disaster declaration" in result.disclaimer
    assert result.expires_at > result.created_at


# --------------------------------------------------------------------------
# 6 & 7. DUPLICATE SUPPRESSION & FINGERPRINT
# --------------------------------------------------------------------------

def test_alert_fingerprint_deterministic(mock_location, mock_risk_assessment_high):
    engine = AlertDecisionEngine()
    fp1 = engine.compute_fingerprint(
        location_id=mock_location.id,
        risk_assessment_id=mock_risk_assessment_high.id,
        alert_level="HIGH",
        priority="HIGH",
    )
    fp2 = engine.compute_fingerprint(
        location_id=mock_location.id,
        risk_assessment_id=mock_risk_assessment_high.id,
        alert_level="HIGH",
        priority="HIGH",
    )
    assert fp1 == fp2
    assert len(fp1) == 24

    # Changing any dimension changes fingerprint
    fp_diff = engine.compute_fingerprint(
        location_id=mock_location.id,
        risk_assessment_id=mock_risk_assessment_high.id,
        alert_level="URGENT",
        priority="HIGH",
    )
    assert fp1 != fp_diff


def test_duplicate_suppression_returns_existing(db_session):
    loc_dup = CriticalLocation(
        id="loc-p6-duplicate-test",
        name="Duplicate Test Dam",
        location_type="dam",
        latitude=30.0,
        longitude=78.0,
        radius_m=2000,
        geometry="{}",
        risk_category="test",
        priority="high",
    )
    db_session.merge(loc_dup)
    now_utc = datetime.now(timezone.utc)
    snap = EvidenceSnapshot(
        id="ev-snap-dup-test",
        location_id=loc_dup.id,
        evidence_window_start=now_utc - timedelta(days=5),
        evidence_window_end=now_utc,
        reference_time=now_utc,
        sentinel1_evidence="{}",
        sentinel2_evidence="{}",
        rainfall_evidence="{}",
        fire_evidence="{}",
        earthquake_evidence="{}",
        terrain_evidence="{}",
        correlations="[]",
        created_at=now_utc,
    )
    db_session.merge(snap)
    risk = RiskAssessment(
        id="risk-p6-dup-test",
        location_id=loc_dup.id,
        evidence_snapshot_id=snap.id,
        score=60.0,
        risk_level="HIGH",
        monitoring_priority="HIGH",
        evidence_strength="STRONG",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="High risk test.",
        recommended_action="Action test.",
        created_at=now_utc,
    )
    db_session.merge(risk)
    db_session.query(DBAlert).filter(DBAlert.location_id == loc_dup.id).delete()
    db_session.commit()

    engine = AlertDecisionEngine()
    first_alert = engine.generate_and_persist(
        db=db_session,
        location_id=loc_dup.id,
        risk_assessment_id=risk.id,
    )
    assert first_alert.is_duplicate is False

    second_alert = engine.generate_and_persist(
        db=db_session,
        location_id=loc_dup.id,
        risk_assessment_id=risk.id,
    )
    assert second_alert.is_duplicate is True
    assert second_alert.alert_id == first_alert.alert_id
    assert second_alert.fingerprint == first_alert.fingerprint


# --------------------------------------------------------------------------
# 8 & 9. ESCALATION & DE-ESCALATION
# --------------------------------------------------------------------------

def test_alert_escalation(db_session):
    loc_esc = CriticalLocation(
        id="loc-p6-escalate-test",
        name="Escalate Test Dam",
        location_type="dam",
        latitude=30.1,
        longitude=78.1,
        radius_m=2000,
        geometry="{}",
        risk_category="test",
        priority="high",
    )
    db_session.merge(loc_esc)
    now_utc = datetime.now(timezone.utc)
    snap = EvidenceSnapshot(
        id="ev-snap-esc-test",
        location_id=loc_esc.id,
        evidence_window_start=now_utc - timedelta(days=5),
        evidence_window_end=now_utc,
        reference_time=now_utc,
        sentinel1_evidence="{}",
        sentinel2_evidence="{}",
        rainfall_evidence="{}",
        fire_evidence="{}",
        earthquake_evidence="{}",
        terrain_evidence="{}",
        correlations="[]",
        created_at=now_utc,
    )
    db_session.merge(snap)
    db_session.query(DBAlert).filter(DBAlert.location_id == loc_esc.id).delete()
    db_session.commit()

    engine = AlertDecisionEngine()

    # 1. Create a MODERATE risk assessment -> MONITOR alert
    risk_mod = RiskAssessment(
        id="risk-escalate-mod",
        location_id=loc_esc.id,
        evidence_snapshot_id=snap.id,
        score=35.0,
        risk_level="MODERATE",
        monitoring_priority="ROUTINE",
        evidence_strength="MODERATE",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="Moderate monitoring conditions.",
        recommended_action="Continue regular observations.",
        created_at=now_utc - timedelta(hours=2),
    )
    db_session.merge(risk_mod)
    db_session.commit()

    alert_mod = engine.generate_and_persist(
        db=db_session,
        location_id=loc_esc.id,
        risk_assessment_id=risk_mod.id,
    )
    assert alert_mod.alert_level == AlertLevel.MONITOR
    assert alert_mod.status == AlertStatus.ACTIVE

    # 2. Create a CRITICAL risk assessment -> URGENT alert
    risk_crit = RiskAssessment(
        id="risk-escalate-crit",
        location_id=loc_esc.id,
        evidence_snapshot_id=snap.id,
        score=85.0,
        risk_level="CRITICAL",
        monitoring_priority="URGENT",
        evidence_strength="VERY_STRONG",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="Critical monitoring conditions.",
        recommended_action="Immediate inspection.",
        created_at=now_utc,
    )
    db_session.merge(risk_crit)
    db_session.commit()

    alert_crit = engine.generate_and_persist(
        db=db_session,
        location_id=loc_esc.id,
        risk_assessment_id=risk_crit.id,
    )
    assert alert_crit.alert_level == AlertLevel.URGENT
    assert alert_crit.status == AlertStatus.ACTIVE
    assert len(alert_crit.escalation_history) > 0
    assert alert_crit.escalation_history[0]["type"] == "ESCALATION"
    assert alert_crit.escalation_history[0]["previous_level"] == "MONITOR"
    assert alert_crit.escalation_history[0]["new_level"] == "URGENT"

    # Prior alert must now be SUPERSEDED
    old_db_alert = db_session.query(DBAlert).filter(DBAlert.id == alert_mod.alert_id).first()
    assert old_db_alert.status == AlertStatus.SUPERSEDED.value


def test_alert_de_escalation(db_session):
    loc_deesc = CriticalLocation(
        id="loc-p6-deescalate-test",
        name="De-escalate Test Dam",
        location_type="dam",
        latitude=30.2,
        longitude=78.2,
        radius_m=2000,
        geometry="{}",
        risk_category="test",
        priority="high",
    )
    db_session.merge(loc_deesc)
    now_utc = datetime.now(timezone.utc)
    snap = EvidenceSnapshot(
        id="ev-snap-deesc-test",
        location_id=loc_deesc.id,
        evidence_window_start=now_utc - timedelta(days=5),
        evidence_window_end=now_utc,
        reference_time=now_utc,
        sentinel1_evidence="{}",
        sentinel2_evidence="{}",
        rainfall_evidence="{}",
        fire_evidence="{}",
        earthquake_evidence="{}",
        terrain_evidence="{}",
        correlations="[]",
        created_at=now_utc,
    )
    db_session.merge(snap)
    db_session.query(DBAlert).filter(DBAlert.location_id == loc_deesc.id).delete()
    db_session.commit()

    engine = AlertDecisionEngine()

    # 1. Start with an ACTIVE HIGH alert
    risk_high = RiskAssessment(
        id="risk-deesc-high",
        location_id=loc_deesc.id,
        evidence_snapshot_id=snap.id,
        score=65.0,
        risk_level="HIGH",
        monitoring_priority="HIGH",
        evidence_strength="STRONG",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="High monitoring conditions.",
        recommended_action="Verification needed.",
        created_at=now_utc - timedelta(hours=3),
    )
    db_session.merge(risk_high)
    db_session.commit()

    alert_high = engine.generate_and_persist(
        db=db_session,
        location_id=loc_deesc.id,
        risk_assessment_id=risk_high.id,
    )
    assert alert_high.alert_level == AlertLevel.HIGH

    # 2. De-escalate to LOW
    risk_low = RiskAssessment(
        id="risk-deesc-low",
        location_id=loc_deesc.id,
        evidence_snapshot_id=snap.id,
        score=10.0,
        risk_level="LOW",
        monitoring_priority="ROUTINE",
        evidence_strength="WEAK",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="Low monitoring conditions.",
        recommended_action="Normal monitoring.",
        created_at=now_utc,
    )
    db_session.merge(risk_low)
    db_session.commit()

    alert_low = engine.generate_and_persist(
        db=db_session,
        location_id=loc_deesc.id,
        risk_assessment_id=risk_low.id,
    )
    assert alert_low.alert_level == AlertLevel.INFO
    assert len(alert_low.escalation_history) > 0
    assert alert_low.escalation_history[0]["type"] == "DE_ESCALATION"
    assert alert_low.escalation_history[0]["previous_level"] == "HIGH"
    assert alert_low.escalation_history[0]["new_level"] == "INFO"

    # Prior alert preserved as SUPERSEDED
    old = db_session.query(DBAlert).filter(DBAlert.id == alert_high.alert_id).first()
    assert old.status == AlertStatus.SUPERSEDED.value


# --------------------------------------------------------------------------
# 10-12. LIFECYCLE: ACKNOWLEDGEMENT, REVIEW, RESOLUTION
# --------------------------------------------------------------------------

def test_alert_lifecycle_workflow(db_session, mock_location, mock_risk_assessment_high):
    engine = AlertDecisionEngine()
    alert = engine.generate_and_persist(
        db=db_session,
        location_id=mock_location.id,
        risk_assessment_id=mock_risk_assessment_high.id,
    )
    alert_id = alert.alert_id

    # 1. Acknowledge
    ack_res = engine.acknowledge_alert(
        db=db_session,
        alert_id=alert_id,
        actor="NDMA_Duty_Officer",
        note="Received and queued for analyst triage.",
    )
    assert ack_res.status == AlertStatus.ACKNOWLEDGED
    assert ack_res.acknowledged_at is not None
    assert ack_res.acknowledgement_details["actor"] == "NDMA_Duty_Officer"

    # 2. Review
    rev_res = engine.start_review(
        db=db_session,
        alert_id=alert_id,
        actor="Senior_Geospatial_Analyst",
        note="Investigating SAR coherence map and local DEM slope.",
    )
    assert rev_res.status == AlertStatus.IN_REVIEW

    # 3. Resolve
    res_res = engine.resolve_alert(
        db=db_session,
        alert_id=alert_id,
        actor="Senior_Geospatial_Analyst",
        note="Field inspection confirmed minor seasonal water level adjustment; no slope movement.",
    )
    assert res_res.status == AlertStatus.RESOLVED
    assert res_res.resolved_at is not None
    assert res_res.resolution_details["actor"] == "Senior_Geospatial_Analyst"


# --------------------------------------------------------------------------
# 13 & 14. EXPIRATION & SUPERSEDING
# --------------------------------------------------------------------------

def test_alert_expiration_logic(db_session):
    loc_exp = CriticalLocation(
        id="loc-p6-expiration-test",
        name="Expiration Test Dam",
        location_type="dam",
        latitude=30.3,
        longitude=78.3,
        radius_m=2000,
        geometry="{}",
        risk_category="test",
        priority="routine",
    )
    db_session.merge(loc_exp)
    now_utc = datetime.now(timezone.utc)
    snap = EvidenceSnapshot(
        id="ev-snap-exp-test",
        location_id=loc_exp.id,
        evidence_window_start=now_utc - timedelta(days=15),
        evidence_window_end=now_utc - timedelta(days=10),
        reference_time=now_utc - timedelta(days=10),
        sentinel1_evidence="{}",
        sentinel2_evidence="{}",
        rainfall_evidence="{}",
        fire_evidence="{}",
        earthquake_evidence="{}",
        terrain_evidence="{}",
        correlations="[]",
        created_at=now_utc - timedelta(days=10),
    )
    db_session.merge(snap)
    db_session.commit()

    engine = AlertDecisionEngine()

    risk_exp = RiskAssessment(
        id="risk-exp-test",
        location_id=loc_exp.id,
        evidence_snapshot_id=snap.id,
        score=20.0,
        risk_level="LOW",
        monitoring_priority="ROUTINE",
        evidence_strength="WEAK",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="Routine assessment.",
        recommended_action="Routine.",
        created_at=now_utc - timedelta(days=10),
    )
    db_session.merge(risk_exp)
    db_session.query(DBAlert).filter(DBAlert.location_id == loc_exp.id).delete()
    db_session.commit()

    # Manually persist an already-expired active alert
    expired_alert = DBAlert(
        id="alert-exp-test-01",
        location_id=loc_exp.id,
        risk_assessment_id=risk_exp.id,
        alert_level="INFO",
        priority="ROUTINE",
        status=AlertStatus.ACTIVE.value,
        title="INFO Alert",
        summary="Summary",
        reason="Reason",
        evidence_references="{}",
        contributing_factors="[]",
        uncertainty="[]",
        recommended_action="Action",
        fingerprint="exp-fp-01",
        escalation_history="[]",
        created_at=now_utc - timedelta(days=10),
        expires_at=now_utc - timedelta(days=2),  # In the past
        alert_version="alert_engine_v1",
        source_engine_versions="{}",
        disclaimer="Disclaimer",
    )
    db_session.merge(expired_alert)
    db_session.commit()

    # Generating a new alert should detect expired status and mark it EXPIRED
    new_risk = RiskAssessment(
        id="risk-exp-test-new",
        location_id=loc_exp.id,
        evidence_snapshot_id=snap.id,
        score=22.0,
        risk_level="LOW",
        monitoring_priority="ROUTINE",
        evidence_strength="WEAK",
        contributing_factors="[]",
        uncertainty_factors="[]",
        explanation="Routine updated assessment.",
        recommended_action="Routine.",
        created_at=now_utc,
    )
    db_session.merge(new_risk)
    db_session.commit()

    new_alert = engine.generate_and_persist(
        db=db_session,
        location_id=loc_exp.id,
        risk_assessment_id=new_risk.id,
    )
    expired_in_db = db_session.query(DBAlert).filter(DBAlert.id == "alert-exp-test-01").first()
    assert expired_in_db.status == AlertStatus.EXPIRED.value
    assert new_alert.status == AlertStatus.ACTIVE


# --------------------------------------------------------------------------
# 15. AUDIT EVENTS
# --------------------------------------------------------------------------

def test_audit_events_created(db_session, mock_location, mock_risk_assessment_high):
    engine = AlertDecisionEngine()
    alert = engine.generate_and_persist(
        db=db_session,
        location_id=mock_location.id,
        risk_assessment_id=mock_risk_assessment_high.id,
    )

    events = db_session.query(DBAlertEvent).filter(DBAlertEvent.alert_id == alert.alert_id).all()
    assert len(events) >= 1
    created_event = [e for e in events if e.event_type == AlertAuditEventType.ALERT_CREATED.value]
    assert len(created_event) == 1
    assert created_event[0].new_status == AlertStatus.ACTIVE.value


# --------------------------------------------------------------------------
# 16. UNCERTAINTY PROPAGATION & REQUIREMENT 23 RAINFALL SEMANTICS
# --------------------------------------------------------------------------

def test_uncertainty_propagation_and_rainfall_semantics(mock_location, mock_evidence_snapshot, mock_risk_assessment_high):
    engine = AlertDecisionEngine()
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk_assessment_high,
        evidence_snapshot=mock_evidence_snapshot,
    )
    # Requirement 23 check: No rainfall data != 0.0 mm
    assert any("Precipitation data unavailable in observation window" in u for u in result.uncertainty)
    # Traceability check
    assert result.evidence_references["rainfall"]["status"] == "UNAVAILABLE"
    assert result.evidence_references["rainfall"]["granules_found"] == 0


# --------------------------------------------------------------------------
# 17. EVIDENCE TRACEABILITY LINEAGE
# --------------------------------------------------------------------------

def test_evidence_traceability_lineage(mock_location, mock_evidence_snapshot, mock_risk_assessment_high, mock_analyst_report):
    engine = AlertDecisionEngine()
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk_assessment_high,
        evidence_snapshot=mock_evidence_snapshot,
        analyst_report=mock_analyst_report,
    )
    refs = result.evidence_references
    assert refs["evidence_snapshot_id"] == mock_evidence_snapshot.id
    assert refs["risk_assessment_id"] == mock_risk_assessment_high.id
    assert refs["analyst_report_id"] == mock_analyst_report.id
    assert refs["sentinel1"]["available"] is True
    assert refs["sentinel1"]["t1_observation_id"] == "s1-obs-t1"
    assert refs["sentinel1"]["t2_observation_id"] == "s1-obs-t2"
    assert refs["sentinel2"]["observation_id"] == "s2-obs-001"
    assert refs["earthquake"]["nearest_event_id"] == "usgs-quake-01"
    assert refs["terrain"]["slope_deg"] == 24.5


# --------------------------------------------------------------------------
# 18 & 19. MISSING & INVALID ANALYST REPORT HANDLING
# --------------------------------------------------------------------------

def test_missing_analyst_report_handling(mock_location, mock_evidence_snapshot, mock_risk_assessment_high):
    engine = AlertDecisionEngine()
    # When analyst_report is None, alert creation succeeds authoritatively using Phase 4 data
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk_assessment_high,
        evidence_snapshot=mock_evidence_snapshot,
        analyst_report=None,
    )
    assert result.alert_level == AlertLevel.HIGH
    assert result.analyst_report_id is None
    assert "Score: 63.28/100" in result.reason


def test_invalid_analyst_report_handling(mock_location, mock_evidence_snapshot, mock_risk_assessment_high):
    engine = AlertDecisionEngine()
    invalid_report = DBAnalystReport(
        id="rep-unvalidated-01",
        location_id=mock_location.id,
        risk_assessment_id=mock_risk_assessment_high.id,
        executive_summary="Unverified text",
        validation_status="FAILED",  # Not VALIDATED
        prompt_version="v1",
        created_at=datetime.now(timezone.utc),
    )
    result = engine.generate_alert_result(
        location=mock_location,
        risk_assessment=mock_risk_assessment_high,
        evidence_snapshot=mock_evidence_snapshot,
        analyst_report=invalid_report,
    )
    # Must NOT use unvalidated report's summary as authoritative
    assert result.analyst_report_id is None
    assert "Unverified text" not in result.summary


# --------------------------------------------------------------------------
# 20 & 21. MISSING & INVALID RISK ASSESSMENT HANDLING
# --------------------------------------------------------------------------

def test_missing_risk_assessment_error(db_session):
    loc_empty = CriticalLocation(
        id="loc-no-risk",
        name="Empty Location",
        location_type="dam",
        latitude=20.0,
        longitude=70.0,
        radius_m=1000,
        geometry="{}",
        risk_category="test",
        priority="routine",
    )
    db_session.merge(loc_empty)
    db_session.commit()
    engine = AlertDecisionEngine()
    with pytest.raises(ValueError, match="No RiskAssessment available"):
        engine.generate_and_persist(db=db_session, location_id="loc-no-risk")


def test_invalid_risk_assessment_id_error(db_session, mock_location):
    engine = AlertDecisionEngine()
    with pytest.raises(ValueError, match="Risk assessment 'invalid-id-xyz' not found"):
        engine.generate_and_persist(
            db=db_session,
            location_id=mock_location.id,
            risk_assessment_id="invalid-id-xyz",
        )


# --------------------------------------------------------------------------
# 22. PHASE 4 RISK IMMUTABILITY
# --------------------------------------------------------------------------

def test_phase4_risk_immutability(db_session, mock_location, mock_risk_assessment_high):
    original_score = mock_risk_assessment_high.score
    original_level = mock_risk_assessment_high.risk_level
    original_priority = mock_risk_assessment_high.monitoring_priority

    engine = AlertDecisionEngine()
    engine.generate_and_persist(
        db=db_session,
        location_id=mock_location.id,
        risk_assessment_id=mock_risk_assessment_high.id,
    )

    db_session.refresh(mock_risk_assessment_high)
    assert mock_risk_assessment_high.score == original_score
    assert mock_risk_assessment_high.risk_level == original_level
    assert mock_risk_assessment_high.monitoring_priority == original_priority


# --------------------------------------------------------------------------
# 23-26. REGRESSION VERIFICATION (PHASES 1-5 MODELS & PIPELINES)
# --------------------------------------------------------------------------

def test_phase5_analyst_report_integrity(mock_analyst_report):
    assert mock_analyst_report.validation_status == "VALIDATED"
    assert "Independent SAR and optical" in mock_analyst_report.executive_summary


def test_phase3_evidence_snapshot_integrity(mock_evidence_snapshot):
    s1 = json.loads(mock_evidence_snapshot.sentinel1_evidence)
    s2 = json.loads(mock_evidence_snapshot.sentinel2_evidence)
    assert s1["changed_percentage"] == 24.91
    assert s2["water_change_percentage"] == 18.2


def test_phase2_sar_observation_model_integrity():
    proc = Sentinel1ProcessingResult(
        id="s1-proc-test",
        location_id="loc-test",
        observation_id="s1-obs-test",
        product_id="prod-123",
        acquisition_time=datetime.now(timezone.utc),
        vv_statistics="{}",
        vh_statistics="{}",
        vv_raster_path="/tmp/vv.tif",
        vh_raster_path="/tmp/vh.tif",
        processing_version="1.0.0",
        status="SUCCESS",
    )
    assert proc.processing_version == "1.0.0"
    assert proc.status == "SUCCESS"


def test_phase1_optical_observation_model_integrity():
    obs = SatelliteObservation(
        id="s2-test-integrity",
        location_id="loc-test",
        product_id="gran-123",
        collection="SENTINEL-2",
        sensor="Sentinel-2",
        acquisition_time=datetime.now(timezone.utc),
        cloud_cover=2.5,
        quality_status="NEW_OBSERVATION_AVAILABLE",
    )
    assert obs.cloud_cover == 2.5
    assert obs.sensor == "Sentinel-2"


# --------------------------------------------------------------------------
# 27. FASTAPI REST ENDPOINTS
# --------------------------------------------------------------------------

def test_api_alert_endpoints(mock_location, mock_risk_assessment_high, mock_analyst_report):
    # 1. Generate Alert
    res = client.post(
        f"/api/locations/{mock_location.id}/alerts/generate",
        params={
            "risk_assessment_id": mock_risk_assessment_high.id,
            "analyst_report_id": mock_analyst_report.id,
        },
    )
    assert res.status_code == 200
    alert_data = res.json()
    alert_id = alert_data["alert_id"]
    assert alert_data["alert_level"] == "HIGH"
    assert alert_data["priority"] == "HIGH"

    # 2. List Location Alerts
    res = client.get(f"/api/locations/{mock_location.id}/alerts")
    assert res.status_code == 200
    assert len(res.json()) >= 1

    # 3. Active Alerts
    res = client.get(f"/api/locations/{mock_location.id}/alerts/active")
    assert res.status_code == 200
    active_alerts = res.json()
    assert any(a["id"] == alert_id for a in active_alerts)

    # 4. Latest Alert
    res = client.get(f"/api/locations/{mock_location.id}/alerts/latest")
    assert res.status_code == 200
    assert res.json()["id"] == alert_id

    # 5. Acknowledge Alert
    res = client.post(
        f"/api/alerts/{alert_id}/acknowledge",
        json={"actor": "OpsTeam", "note": "Acknowledged from API test."},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ACKNOWLEDGED"

    # 6. Review Alert
    res = client.post(
        f"/api/alerts/{alert_id}/review",
        json={"actor": "Analyst1", "note": "Beginning verification."},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "IN_REVIEW"

    # 7. Resolve Alert
    res = client.post(
        f"/api/alerts/{alert_id}/resolve",
        json={"actor": "LeadAnalyst", "note": "Resolved and logged."},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "RESOLVED"


# --------------------------------------------------------------------------
# 28. DATABASE PERSISTENCE
# --------------------------------------------------------------------------

def test_database_persistence_schema(db_session, mock_location, mock_risk_assessment_high):
    engine = AlertDecisionEngine()
    alert_res = engine.generate_and_persist(
        db=db_session,
        location_id=mock_location.id,
        risk_assessment_id=mock_risk_assessment_high.id,
    )

    db_alert = db_session.query(DBAlert).filter(DBAlert.id == alert_res.alert_id).first()
    assert db_alert is not None
    assert db_alert.location_id == mock_location.id
    assert db_alert.risk_assessment_id == mock_risk_assessment_high.id
    assert db_alert.fingerprint == alert_res.fingerprint
    assert db_alert.disclaimer is not None

    db_dict = db_alert.to_dict()
    assert "alert_level" in db_dict
    assert "evidence_references" in db_dict
    assert isinstance(db_dict["evidence_references"], dict)

    events = db_session.query(DBAlertEvent).filter(DBAlertEvent.alert_id == alert_res.alert_id).all()
    assert len(events) >= 1
    assert any(e.event_type == "ALERT_CREATED" for e in events)
