"""
tests/test_phase4.py
Comprehensive Deterministic Unit and Integration Tests for Phase 4: Risk Assessment Engine.
Covers:
- Empty evidence
- SAR-only evidence
- Optical-only evidence
- SAR + Optical multi-sensor corroboration
- SAR + Rainfall association
- Fire thermal anomaly evidence
- Earthquake seismic evidence
- Multiple independent sensors
- Stale evidence & damping
- Missing & invalid evidence (cloud rejection)
- Evidence strength levels (WEAK, MODERATE, STRONG)
- Score boundaries & classifications (LOW, MODERATE, HIGH, CRITICAL)
- Monitoring priorities (ROUTINE, ELEVATED, HIGH, URGENT)
- Uncertainty factor generation
- Contributing factor taxonomy & auditability
- Database persistence (risk_assessments table)
- FastAPI REST endpoints
- Engine versioning and scientific disclaimers
"""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, EvidenceSnapshot, RiskAssessment
from satguard.fusion.schema import (
    MultiSensorEvidence,
    Sentinel1Evidence,
    Sentinel2Evidence,
    RainfallEvidence,
    FireEvidence,
    EarthquakeEvidence,
    TerrainEvidence,
    EvidenceCorrelation,
    TemporalAlignment,
    SpatialAlignment,
)
from satguard.risk.schema import (
    RiskLevel,
    MonitoringPriority,
    EvidenceStrength,
    FactorType,
)
from satguard.risk.config import RiskEngineConfig
from satguard.risk.engine import RiskAssessmentEngine
from satguard.api.main import app

client = TestClient(app)


@pytest.fixture
def base_time():
    return datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def empty_evidence(base_time):
    return MultiSensorEvidence(
        id="snap-empty-test",
        location_id="loc-test-01",
        location_name="Test Critical Location",
        evidence_window_start=base_time - timedelta(days=30),
        evidence_window_end=base_time,
        reference_time=base_time,
        sentinel1=Sentinel1Evidence(available=False),
        sentinel2=Sentinel2Evidence(available=False),
        rainfall=RainfallEvidence(available=False),
        fire=FireEvidence(available=False),
        earthquake=EarthquakeEvidence(available=False),
        terrain=TerrainEvidence(available=False),
        correlations=[],
        created_at=base_time,
    )


# ----------------------------------------------------------------------
# 1. EMPTY EVIDENCE TEST
# ----------------------------------------------------------------------
def test_empty_evidence(empty_evidence):
    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    assert result.score == 0.0
    assert result.risk_level == RiskLevel.LOW
    assert result.monitoring_priority == MonitoringPriority.ROUTINE
    assert result.evidence_strength == EvidenceStrength.WEAK
    assert len(result.contributing_factors) == 0
    assert len(result.uncertainty_factors) >= 3
    assert "Routine monitoring" in result.recommended_action or "routine monitoring" in result.recommended_action
    assert "LOW" in result.explanation


# ----------------------------------------------------------------------
# 2. SAR-ONLY EVIDENCE TEST
# ----------------------------------------------------------------------
def test_sar_only_evidence(empty_evidence, base_time):
    empty_evidence.sentinel1 = Sentinel1Evidence(
        available=True,
        t1_observation_id="t1-obs",
        t2_observation_id="t2-obs",
        joint_changed_percent=12.5,
        significant_region_count=5,
        mean_delta_vv_db=-0.8,
        temporal_alignment=TemporalAlignment(
            observation_time=base_time,
            reference_time=base_time,
            temporal_distance_hours=0.0,
            status="ALIGNED",
        ),
        spatial_alignment=SpatialAlignment(
            location_id="loc-test-01",
            latitude=30.0,
            longitude=78.0,
            aoi_radius_m=3000.0,
            spatial_relation="INSIDE_AOI",
        ),
    )

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    assert result.score > 0.0
    sar_factor = next((f for f in result.contributing_factors if f.factor == FactorType.SAR_CHANGE.value), None)
    assert sar_factor is not None
    assert sar_factor.contribution >= 15.0
    assert sar_factor.evidence_id == "t2-obs"

    # Single-sensor uncertainty should be recorded
    assert any("Single-sensor SAR" in u for u in result.uncertainty_factors)


# ----------------------------------------------------------------------
# 3. OPTICAL-ONLY EVIDENCE TEST
# ----------------------------------------------------------------------
def test_optical_only_evidence(empty_evidence, base_time):
    empty_evidence.sentinel2 = Sentinel2Evidence(
        available=True,
        observation_id="s2-obs-101",
        cloud_cover=5.0,
        water_change_percentage=32.0,
        optical_change_status="SIGNIFICANT_EXPANSION",
        temporal_alignment=TemporalAlignment(
            observation_time=base_time,
            reference_time=base_time,
            temporal_distance_hours=2.0,
            status="ALIGNED",
        ),
    )

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    assert result.score > 0.0
    opt_factor = next((f for f in result.contributing_factors if f.factor == FactorType.OPTICAL_CHANGE.value), None)
    assert opt_factor is not None
    assert opt_factor.contribution >= 15.0
    assert any("Single-sensor optical" in u for u in result.uncertainty_factors)


# ----------------------------------------------------------------------
# 4. SAR + OPTICAL MULTI-SENSOR CORROBORATION
# ----------------------------------------------------------------------
def test_sar_plus_optical_corroboration(empty_evidence, base_time):
    empty_evidence.sentinel1 = Sentinel1Evidence(
        available=True,
        t2_observation_id="s1-obs",
        joint_changed_percent=15.0,
        significant_region_count=8,
        temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"),
    )
    empty_evidence.sentinel2 = Sentinel2Evidence(
        available=True,
        observation_id="s2-obs",
        cloud_cover=2.0,
        water_change_percentage=28.0,
        temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"),
    )
    empty_evidence.correlations = [
        EvidenceCorrelation(
            correlation_type="MULTI-SENSOR_CHANGE_SIGNAL",
            source_evidence_ids=["s1-obs", "s2-obs"],
            temporal_relationship={"gap_hours": 3.0},
            spatial_relationship={"co_located": True},
            supporting_values={"sar_pct": 15.0, "optical_pct": 28.0},
            confidence_score=0.90,
            scientific_note="Dual-satellite corroboration of physical surface change.",
        )
    ]

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    assert result.evidence_strength == EvidenceStrength.STRONG
    corr_factor = next((f for f in result.contributing_factors if f.factor == FactorType.MULTI_SENSOR_CORRELATION.value), None)
    assert corr_factor is not None
    assert corr_factor.contribution >= 12.0
    assert result.score >= 40.0


# ----------------------------------------------------------------------
# 5. SAR + RAINFALL ASSOCIATION
# ----------------------------------------------------------------------
def test_sar_plus_rainfall_association(empty_evidence, base_time):
    empty_evidence.sentinel1 = Sentinel1Evidence(
        available=True,
        t2_observation_id="s1-obs",
        joint_changed_percent=8.0,
        significant_region_count=2,
        temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"),
    )
    empty_evidence.rainfall = RainfallEvidence(
        available=True,
        total_granules_found=5,
        estimated_rainfall_mm=62.0,
        temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"),
    )
    empty_evidence.correlations = [
        EvidenceCorrelation(
            correlation_type="SAR_RAINFALL_ASSOCIATION",
            source_evidence_ids=["s1-obs", "NASA_GPM"],
            temporal_relationship={"window": "coincident"},
            spatial_relationship={"co_located": True},
            supporting_values={"rainfall_mm": 62.0},
            confidence_score=0.85,
            scientific_note="SAR change temporally coincident with intense precipitation.",
        )
    ]

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    rain_factor = next((f for f in result.contributing_factors if f.factor == FactorType.RAINFALL.value), None)
    assert rain_factor is not None
    assert rain_factor.contribution == 10.0


# ----------------------------------------------------------------------
# 6. FIRE THERMAL ANOMALY EVIDENCE
# ----------------------------------------------------------------------
def test_fire_evidence(empty_evidence):
    empty_evidence.fire = FireEvidence(
        available=True,
        fire_count=6,
        max_frp_mw=78.5,
    )

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    fire_factor = next((f for f in result.contributing_factors if f.factor == FactorType.FIRE.value), None)
    assert fire_factor is not None
    assert fire_factor.contribution == 10.0


# ----------------------------------------------------------------------
# 7. EARTHQUAKE SEISMIC EVIDENCE
# ----------------------------------------------------------------------
def test_earthquake_evidence(empty_evidence):
    empty_evidence.earthquake = EarthquakeEvidence(
        available=True,
        events_found_count=2,
        nearest_event_id="usquake-771",
        nearest_magnitude=5.4,
        distance_km=28.0,
    )

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    quake_factor = next((f for f in result.contributing_factors if f.factor == FactorType.EARTHQUAKE.value), None)
    assert quake_factor is not None
    assert quake_factor.contribution == 10.0
    assert "M5.4 at 28.0 km" in quake_factor.reason


# ----------------------------------------------------------------------
# 8. MULTIPLE INDEPENDENT SENSORS
# ----------------------------------------------------------------------
def test_multiple_independent_sensors(empty_evidence, base_time):
    empty_evidence.sentinel1 = Sentinel1Evidence(available=True, joint_changed_percent=5.0, temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"))
    empty_evidence.sentinel2 = Sentinel2Evidence(available=True, water_change_percentage=10.0, cloud_cover=1.0, temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"))
    empty_evidence.earthquake = EarthquakeEvidence(available=True, events_found_count=1, nearest_magnitude=4.2, distance_km=80.0)
    empty_evidence.terrain = TerrainEvidence(available=True, slope_degrees=28.0, elevation_m=1200.0)

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    assert result.evidence_strength == EvidenceStrength.STRONG
    assert len(result.contributing_factors) >= 3


# ----------------------------------------------------------------------
# 9. STALE EVIDENCE AND DAMPING
# ----------------------------------------------------------------------
def test_stale_evidence_damping(empty_evidence, base_time):
    # Stale SAR
    empty_evidence.sentinel1 = Sentinel1Evidence(
        available=True,
        joint_changed_percent=25.0,
        temporal_alignment=TemporalAlignment(
            reference_time=base_time,
            temporal_distance_hours=450.0,
            status="STALE",
        ),
    )

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    sar_factor = next((f for f in result.contributing_factors if f.factor == FactorType.SAR_CHANGE.value), None)
    assert sar_factor is not None
    # 18.0 pts damped by 0.5 = 9.0 pts
    assert sar_factor.contribution == 9.0
    assert any("STALE" in u for u in result.uncertainty_factors)


# ----------------------------------------------------------------------
# 10. MISSING & INVALID EVIDENCE (CLOUD REJECTION)
# ----------------------------------------------------------------------
def test_cloud_rejection(empty_evidence, base_time):
    empty_evidence.sentinel2 = Sentinel2Evidence(
        available=True,
        cloud_cover=85.0,  # Heavy clouds
        water_change_percentage=60.0,
        temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"),
    )

    engine = RiskAssessmentEngine()
    result = engine.assess(empty_evidence)

    # Cloud cover > 50% must yield 0 optical points
    opt_factor = next((f for f in result.contributing_factors if f.factor == FactorType.OPTICAL_CHANGE.value), None)
    assert opt_factor is None
    assert any("cloud cover (85.0%) exceeds quality threshold" in u for u in result.uncertainty_factors)


# ----------------------------------------------------------------------
# 11. EVIDENCE STRENGTH LEVELS
# ----------------------------------------------------------------------
def test_evidence_strength_levels(empty_evidence, base_time):
    engine = RiskAssessmentEngine()

    # 1. WEAK: empty
    assert engine.assess(empty_evidence).evidence_strength == EvidenceStrength.WEAK

    # 2. MODERATE: Only 1 primary sensor
    empty_evidence.sentinel1 = Sentinel1Evidence(available=True, temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"))
    assert engine.assess(empty_evidence).evidence_strength == EvidenceStrength.MODERATE

    # 3. STRONG: Dual primary sensors aligned
    empty_evidence.sentinel2 = Sentinel2Evidence(available=True, cloud_cover=5.0, temporal_alignment=TemporalAlignment(reference_time=base_time, status="ALIGNED"))
    assert engine.assess(empty_evidence).evidence_strength == EvidenceStrength.STRONG


# ----------------------------------------------------------------------
# 12. SCORE BOUNDARIES AND CLASSIFICATIONS
# ----------------------------------------------------------------------
def test_score_boundaries():
    engine = RiskAssessmentEngine()

    assert engine._classify_risk_level(0.0) == RiskLevel.LOW
    assert engine._classify_risk_level(24.99) == RiskLevel.LOW
    assert engine._assign_monitoring_priority(RiskLevel.LOW) == MonitoringPriority.ROUTINE

    assert engine._classify_risk_level(25.0) == RiskLevel.MODERATE
    assert engine._classify_risk_level(49.99) == RiskLevel.MODERATE
    assert engine._assign_monitoring_priority(RiskLevel.MODERATE) == MonitoringPriority.ELEVATED

    assert engine._classify_risk_level(50.0) == RiskLevel.HIGH
    assert engine._classify_risk_level(74.99) == RiskLevel.HIGH
    assert engine._assign_monitoring_priority(RiskLevel.HIGH) == MonitoringPriority.HIGH

    assert engine._classify_risk_level(75.0) == RiskLevel.CRITICAL
    assert engine._classify_risk_level(100.0) == RiskLevel.CRITICAL
    assert engine._assign_monitoring_priority(RiskLevel.CRITICAL) == MonitoringPriority.URGENT


# ----------------------------------------------------------------------
# 13. DATABASE PERSISTENCE TEST
# ----------------------------------------------------------------------
def test_database_persistence_and_to_dict(empty_evidence, base_time):
    init_db()
    db = get_db_session()

    try:
        # Create dummy CriticalLocation and EvidenceSnapshot in test DB
        loc = CriticalLocation(
            id="loc-test-persist",
            name="Persistence Test Reservoir",
            location_type="reservoir",
            latitude=31.0,
            longitude=77.0,
            radius_m=2000,
            geometry="{}",
            risk_category="dam_reservoir",
            priority="routine",
        )
        db.merge(loc)

        snap = EvidenceSnapshot(
            id="snap-test-persist",
            location_id="loc-test-persist",
            evidence_window_start=base_time - timedelta(days=10),
            evidence_window_end=base_time,
            reference_time=base_time,
            sentinel1_evidence=empty_evidence.sentinel1.model_dump_json(),
            sentinel2_evidence=empty_evidence.sentinel2.model_dump_json(),
            rainfall_evidence=empty_evidence.rainfall.model_dump_json(),
            fire_evidence=empty_evidence.fire.model_dump_json(),
            earthquake_evidence=empty_evidence.earthquake.model_dump_json(),
            terrain_evidence=empty_evidence.terrain.model_dump_json(),
            correlations="[]",
            provenance="{}",
            processing_metadata="{}",
            created_at=base_time,
        )
        db.merge(snap)
        db.commit()

        engine = RiskAssessmentEngine()
        result = engine.assess_and_persist(db=db, evidence=snap, location_name=loc.name)

        persisted = db.query(RiskAssessment).filter(RiskAssessment.id == result.id).first()
        assert persisted is not None
        assert persisted.location_id == "loc-test-persist"
        assert persisted.evidence_snapshot_id == "snap-test-persist"
        assert persisted.risk_level == "LOW"
        assert persisted.monitoring_priority == "ROUTINE"

        dict_repr = persisted.to_dict()
        assert isinstance(dict_repr["contributing_factors"], list)
        assert isinstance(dict_repr["uncertainty_factors"], list)
        assert dict_repr["engine_version"] == "risk_engine_v1"
        assert "probability of disaster" in dict_repr["score_interpretation"].lower()

    finally:
        db.close()


# ----------------------------------------------------------------------
# 14. FASTAPI API ENDPOINTS TEST
# ----------------------------------------------------------------------
def test_api_risk_endpoints():
    # 1. Trigger assessment on Tehri Dam
    res_post = client.post("/api/locations/loc-001-tehri-dam/risk/assess")
    assert res_post.status_code == 200
    data = res_post.json()
    assert "score" in data
    assert data["risk_level"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    assert data["monitoring_priority"] in ["ROUTINE", "ELEVATED", "HIGH", "URGENT"]
    assert data["engine_version"] == "risk_engine_v1"

    # 2. Get latest assessment
    res_latest = client.get("/api/locations/loc-001-tehri-dam/risk/latest")
    assert res_latest.status_code == 200
    latest_data = res_latest.json()
    assert latest_data["id"] == data["id"]
    assert latest_data["location_id"] == "loc-001-tehri-dam"

    # 3. List historical assessments
    res_list = client.get("/api/locations/loc-001-tehri-dam/risk")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert isinstance(list_data, list)
    assert len(list_data) >= 1

    # 4. Unknown location error
    res_unknown = client.get("/api/locations/loc-unknown-999/risk")
    assert res_unknown.status_code == 404
