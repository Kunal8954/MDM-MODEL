"""
tests/test_phase5.py
Deterministic Unit and Integration Tests for Phase 5: Groq Evidence Analyst.
All tests use mocked Groq LPU responses to ensure deterministic, offline execution.
Covers:
- Valid analyst input construction
- Valid structured Groq response parsing
- Malformed model response handling
- Missing mandatory field detection
- Hallucinated risk level detection & mitigation
- Hallucinated risk score detection & mitigation
- Risk immutability verification
- Missing API key handling
- Groq timeout and API error handling
- Missing evidence / missing location handling
- Database persistence (analyst_reports table)
- FastAPI REST endpoints
- Historical report retrieval
- Prompt version and model metadata tracking
"""

import json
from unittest.mock import MagicMock, patch
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, EvidenceSnapshot, RiskAssessment, AnalystReport as DBAnalystReport
from satguard.fusion.schema import (
    MultiSensorEvidence,
    Sentinel1Evidence,
    Sentinel2Evidence,
    RainfallEvidence,
    FireEvidence,
    EarthquakeEvidence,
    TerrainEvidence,
    EvidenceCorrelation,
)
from satguard.risk.schema import RiskAssessmentResult, RiskLevel, MonitoringPriority, EvidenceStrength
from satguard.analyst.schema import AnalystInput, AnalystReport
from satguard.analyst.engine import (
    EvidenceAnalystEngine,
    GroqConfigurationError,
    GroqInferenceError,
    ReportValidationError,
)
from satguard.analyst.prompts import PROMPT_VERSION
from satguard.api.main import app

client = TestClient(app)


@pytest.fixture
def sample_location():
    return CriticalLocation(
        id="loc-test-groq",
        name="Test Sovereign Dam",
        location_type="dam",
        latitude=30.5,
        longitude=78.5,
        radius_m=3000,
        geometry="{}",
        risk_category="critical_infrastructure",
        priority="high",
    )


@pytest.fixture
def sample_evidence():
    now_utc = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
    return MultiSensorEvidence(
        id="ev-snap-test-groq",
        location_id="loc-test-groq",
        location_name="Test Sovereign Dam",
        evidence_window_start=now_utc - timedelta(days=30),
        evidence_window_end=now_utc,
        reference_time=now_utc,
        sentinel1=Sentinel1Evidence(
            available=True,
            t1_observation_id="s1-t1",
            t2_observation_id="s1-t2",
            joint_changed_percent=14.0,
            significant_region_count=12,
            mean_delta_vv_db=-0.65,
        ),
        sentinel2=Sentinel2Evidence(
            available=True,
            observation_id="s2-obs",
            cloud_cover=3.2,
            water_change_percentage=72.0,
        ),
        rainfall=RainfallEvidence(available=False),
        fire=FireEvidence(available=False),
        earthquake=EarthquakeEvidence(
            available=True,
            events_found_count=1,
            nearest_event_id="quake-101",
            nearest_magnitude=4.3,
            distance_km=85.0,
        ),
        terrain=TerrainEvidence(available=True, slope_degrees=18.0),
        correlations=[
            EvidenceCorrelation(
                correlation_type="MULTI-SENSOR_CHANGE_SIGNAL",
                source_evidence_ids=["s1-t2", "s2-obs"],
                temporal_relationship={"gap_hours": 4.5},
                spatial_relationship={"co_located": True},
                supporting_values={"sar_pct": 14.0, "optical_pct": 72.0},
                confidence_score=0.88,
                scientific_note="Dual-satellite correlation of physical surface change.",
            )
        ],
        created_at=now_utc,
    )


@pytest.fixture
def sample_risk_assessment():
    now_utc = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
    return RiskAssessmentResult(
        id="risk-assess-test-groq",
        location_id="loc-test-groq",
        location_name="Test Sovereign Dam",
        evidence_snapshot_id="ev-snap-test-groq",
        score=63.28,
        risk_level=RiskLevel.HIGH,
        monitoring_priority=MonitoringPriority.HIGH,
        evidence_strength=EvidenceStrength.STRONG,
        confidence_score=1.0,
        contributing_factors=[],
        uncertainty_factors=["Precipitation data unavailable."],
        explanation="Authoritative HIGH monitoring priority due to multi-sensor variance.",
        recommended_action="Prioritize analyst review and field verification.",
        engine_version="risk_engine_v1",
        provenance={},
        created_at=now_utc,
    )


@pytest.fixture
def mock_valid_llm_json():
    return {
        "executive_summary": "Multi-sensor observations indicate significant surface-change signals across the monitored AOI. Sentinel-1 SAR and Sentinel-2 optical data provide independent corroboration. The deterministic engine classifies this location as HIGH monitoring risk. This does not confirm a disaster.",
        "observed_changes": [
            {
                "category": "SAR",
                "finding": "Coherent radar backscatter shift detected across 12 clusters.",
                "evidence_ids": ["s1-t2"],
                "traceability_metric": "joint_changed: 14.0%"
            },
            {
                "category": "OPTICAL",
                "finding": "Substantial surface water extent variance detected under clear skies.",
                "evidence_ids": ["s2-obs"],
                "traceability_metric": "water_delta: 72.0%"
            }
        ],
        "cross_sensor_findings": [
            {
                "correlation_type": "MULTI-SENSOR_CHANGE_SIGNAL",
                "finding": "Independent synthetic aperture radar and optical sensors both recorded surface changes.",
                "source_evidence_ids": ["s1-t2", "s2-obs"],
                "confidence": 0.88,
                "scientific_interpretation": "Coincident physical variance detected by all-weather radar and multispectral optical channels."
            }
        ],
        "uncertainty": [
            "Local precipitation coverage unavailable in the observation window."
        ],
        "monitoring_assessment": "The authoritative HIGH monitoring classification is justified by coincident radar and optical differences plus regional seismic activity.",
        "recommended_verification": [
            "Prioritize analyst review of raw GeoTIFF differential rasters.",
            "Schedule next optical satellite pass over reservoir catchment."
        ],
        "data_gaps": [
            "NASA GPM precipitation data"
        ],
        "authoritative_risk_score": 63.28,
        "authoritative_risk_level": "HIGH",
        "authoritative_monitoring_priority": "HIGH",
        "authoritative_evidence_strength": "STRONG"
    }


def create_mock_groq_client(response_dict_or_str):
    mock_client = MagicMock()
    mock_choice = MagicMock()
    if isinstance(response_dict_or_str, dict):
        mock_choice.message.content = json.dumps(response_dict_or_str)
    else:
        mock_choice.message.content = response_dict_or_str
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


# ----------------------------------------------------------------------
# 1. VALID ANALYST INPUT TEST
# ----------------------------------------------------------------------
def test_valid_analyst_input_construction(sample_location, sample_evidence, sample_risk_assessment):
    engine = EvidenceAnalystEngine(api_key="mock_key")
    analyst_input = engine.build_analyst_input(
        location=sample_location,
        evidence=sample_evidence,
        risk_assessment=sample_risk_assessment,
    )
    assert analyst_input.location["id"] == "loc-test-groq"
    assert analyst_input.evidence.id == "ev-snap-test-groq"
    assert analyst_input.risk_assessment["score"] == 63.28
    assert analyst_input.risk_assessment["risk_level"] == "HIGH"


# ----------------------------------------------------------------------
# 2. VALID STRUCTURED GROQ RESPONSE TEST
# ----------------------------------------------------------------------
def test_valid_structured_groq_response(sample_location, sample_evidence, sample_risk_assessment, mock_valid_llm_json):
    mock_client = create_mock_groq_client(mock_valid_llm_json)
    engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client)

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    report = engine.generate_analysis(analyst_input)

    assert report.validation_status == "VALIDATED"
    assert len(report.validation_errors) == 0
    assert report.location_id == "loc-test-groq"
    assert report.risk_assessment_id == "risk-assess-test-groq"
    assert report.authoritative_risk_score == 63.28
    assert report.authoritative_risk_level == "HIGH"
    assert len(report.observed_changes) == 2
    assert len(report.cross_sensor_findings) == 1
    assert "Multi-sensor observations" in report.executive_summary
    assert report.prompt_version == PROMPT_VERSION


# ----------------------------------------------------------------------
# 3. MALFORMED MODEL OUTPUT TEST
# ----------------------------------------------------------------------
def test_malformed_groq_response(sample_location, sample_evidence, sample_risk_assessment):
    mock_client = create_mock_groq_client("This is not valid JSON at all!")
    engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client)

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    with pytest.raises(ReportValidationError) as exc_info:
        engine.generate_analysis(analyst_input)
    assert "malformed non-JSON output" in str(exc_info.value)


# ----------------------------------------------------------------------
# 4. MISSING MANDATORY FIELD DETECTION
# ----------------------------------------------------------------------
def test_missing_mandatory_field(sample_location, sample_evidence, sample_risk_assessment, mock_valid_llm_json):
    del mock_valid_llm_json["executive_summary"]
    mock_client = create_mock_groq_client(mock_valid_llm_json)
    engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client)

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    report = engine.generate_analysis(analyst_input)

    assert report.validation_status == "VALIDATION_FAILED"
    assert any("Missing mandatory section 'executive_summary'" in err for err in report.validation_errors)


# ----------------------------------------------------------------------
# 5. HALLUCINATED RISK LEVEL DETECTION & PRESERVATION
# ----------------------------------------------------------------------
def test_hallucinated_risk_level(sample_location, sample_evidence, sample_risk_assessment, mock_valid_llm_json):
    # LLM hallucinates CRITICAL when authoritative is HIGH
    mock_valid_llm_json["authoritative_risk_level"] = "CRITICAL"
    mock_client = create_mock_groq_client(mock_valid_llm_json)
    engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client)

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    report = engine.generate_analysis(analyst_input)

    # Must flag validation error and NOT mutate authoritative level
    assert report.validation_status == "VALIDATION_FAILED"
    assert any("Risk level discrepancy detected" in err for err in report.validation_errors)
    assert report.authoritative_risk_level == "HIGH"  # Preserved authoritative fact!


# ----------------------------------------------------------------------
# 6. HALLUCINATED RISK SCORE DETECTION & PRESERVATION
# ----------------------------------------------------------------------
def test_hallucinated_risk_score(sample_location, sample_evidence, sample_risk_assessment, mock_valid_llm_json):
    # LLM hallucinates 95.0 when authoritative is 63.28
    mock_valid_llm_json["authoritative_risk_score"] = 95.0
    mock_client = create_mock_groq_client(mock_valid_llm_json)
    engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client)

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    report = engine.generate_analysis(analyst_input)

    assert report.validation_status == "VALIDATION_FAILED"
    assert any("Risk score discrepancy detected" in err for err in report.validation_errors)
    assert report.authoritative_risk_score == 63.28  # Preserved authoritative fact!


# ----------------------------------------------------------------------
# 7. MISSING API KEY HANDLING
# ----------------------------------------------------------------------
def test_missing_api_key_handling(sample_location, sample_evidence, sample_risk_assessment):
    engine = EvidenceAnalystEngine(api_key="", client=None)
    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)

    with pytest.raises(GroqConfigurationError) as exc_info:
        engine.generate_analysis(analyst_input)
    assert "GROQ_API_KEY is not configured" in str(exc_info.value)


# ----------------------------------------------------------------------
# 8. GROQ TIMEOUT HANDLING
# ----------------------------------------------------------------------
def test_groq_timeout_handling(sample_location, sample_evidence, sample_risk_assessment):
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = TimeoutError("Request timed out after 30 seconds")
    engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client)

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    with pytest.raises(GroqInferenceError) as exc_info:
        engine.generate_analysis(analyst_input)
    assert "Groq API inference failed" in str(exc_info.value)
    assert "timed out" in str(exc_info.value)


# ----------------------------------------------------------------------
# 9. GROQ API ERROR HANDLING WITHOUT SECRET LEAKS
# ----------------------------------------------------------------------
def test_groq_api_error_redaction(sample_location, sample_evidence, sample_risk_assessment):
    secret_key = "gsk_super_secret_key_12345"
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception(f"HTTP 401 Unauthorized for {secret_key}")
    engine = EvidenceAnalystEngine(api_key=secret_key, client=mock_client)

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    with pytest.raises(GroqInferenceError) as exc_info:
        engine.generate_analysis(analyst_input)
    assert secret_key not in str(exc_info.value)
    assert "[REDACTED_API_KEY]" in str(exc_info.value)


# ----------------------------------------------------------------------
# 10. DATABASE PERSISTENCE AND AUDIT
# ----------------------------------------------------------------------
def test_database_persistence_and_retrieval(sample_location, sample_evidence, sample_risk_assessment, mock_valid_llm_json):
    init_db()
    db = get_db_session()

    try:
        # Save prerequisites in DB
        db.merge(sample_location)

        snap = EvidenceSnapshot(
            id=sample_evidence.id,
            location_id=sample_location.id,
            evidence_window_start=sample_evidence.evidence_window_start,
            evidence_window_end=sample_evidence.evidence_window_end,
            reference_time=sample_evidence.reference_time,
            sentinel1_evidence=sample_evidence.sentinel1.model_dump_json(),
            sentinel2_evidence=sample_evidence.sentinel2.model_dump_json(),
            rainfall_evidence=sample_evidence.rainfall.model_dump_json(),
            fire_evidence=sample_evidence.fire.model_dump_json(),
            earthquake_evidence=sample_evidence.earthquake.model_dump_json(),
            terrain_evidence=sample_evidence.terrain.model_dump_json(),
            correlations=json.dumps([c.model_dump() for c in sample_evidence.correlations]),
            provenance="{}",
            processing_metadata="{}",
            created_at=sample_evidence.created_at,
        )
        db.merge(snap)

        risk_rec = RiskAssessment(
            id=sample_risk_assessment.id,
            location_id=sample_location.id,
            evidence_snapshot_id=sample_evidence.id,
            score=sample_risk_assessment.score,
            risk_level=sample_risk_assessment.risk_level.value,
            monitoring_priority=sample_risk_assessment.monitoring_priority.value,
            evidence_strength=sample_risk_assessment.evidence_strength.value,
            confidence_score=sample_risk_assessment.confidence_score,
            contributing_factors="[]",
            uncertainty_factors=json.dumps(sample_risk_assessment.uncertainty_factors),
            explanation=sample_risk_assessment.explanation,
            recommended_action=sample_risk_assessment.recommended_action,
            engine_version=sample_risk_assessment.engine_version,
            provenance="{}",
            created_at=sample_risk_assessment.created_at,
        )
        db.merge(risk_rec)
        db.commit()

        mock_client = create_mock_groq_client(mock_valid_llm_json)
        engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client)

        report = engine.generate_and_persist(
            db=db,
            location_id=sample_location.id,
            snapshot_id=sample_evidence.id,
            assessment_id=sample_risk_assessment.id,
        )

        persisted = db.query(DBAnalystReport).filter(DBAnalystReport.id == report.report_id).first()
        assert persisted is not None
        assert persisted.location_id == sample_location.id
        assert persisted.risk_assessment_id == sample_risk_assessment.id
        assert persisted.validation_status == "VALIDATED"
        assert persisted.model == engine.model

        dict_repr = persisted.to_dict()
        assert "executive_summary" in dict_repr
        assert dict_repr["location_name"] == sample_location.name
        assert isinstance(dict_repr["report_data"], dict)

    finally:
        db.close()


# ----------------------------------------------------------------------
# 11. FASTAPI REST ENDPOINTS WITH MOCK
# ----------------------------------------------------------------------
def test_api_analyst_endpoints(mock_valid_llm_json):
    # Patch EvidenceAnalystEngine inside satguard.api.main
    with patch("satguard.analyst.engine.EvidenceAnalystEngine.is_configured", return_value=True), \
         patch("satguard.analyst.engine.EvidenceAnalystEngine.generate_analysis") as mock_gen:

        now_utc = datetime.now(timezone.utc)
        mock_report = AnalystReport(
            report_id="analyst-rep-api-test-01",
            location_id="loc-001-tehri-dam",
            risk_assessment_id="risk-assess-tehri-test",
            authoritative_risk_score=63.28,
            authoritative_risk_level="HIGH",
            authoritative_monitoring_priority="HIGH",
            authoritative_evidence_strength="STRONG",
            executive_summary=mock_valid_llm_json["executive_summary"],
            observed_changes=[],
            supporting_evidence={},
            cross_sensor_findings=[],
            uncertainty=[],
            monitoring_assessment=mock_valid_llm_json["monitoring_assessment"],
            recommended_verification=[],
            data_gaps=[],
            validation_status="VALIDATED",
            validation_errors=[],
            model="llama-3.3-70b-versatile",
            prompt_version=PROMPT_VERSION,
            generated_at=now_utc,
        )
        mock_gen.return_value = mock_report

        # 1. POST /api/locations/{location_id}/analysis
        res_post = client.post("/api/locations/loc-001-tehri-dam/analysis")
        assert res_post.status_code == 200
        data = res_post.json()
        assert data["report_id"] == "analyst-rep-api-test-01"
        assert data["authoritative_risk_score"] == 63.28
        assert data["validation_status"] == "VALIDATED"

        # 2. GET /api/locations/{location_id}/analysis/latest
        res_latest = client.get("/api/locations/loc-001-tehri-dam/analysis/latest")
        assert res_latest.status_code == 200
        latest_data = res_latest.json()
        assert latest_data["id"] == "analyst-rep-api-test-01"

        # 3. GET /api/locations/{location_id}/analysis
        res_list = client.get("/api/locations/loc-001-tehri-dam/analysis")
        assert res_list.status_code == 200
        list_data = res_list.json()
        assert isinstance(list_data, list)
        assert len(list_data) >= 1

        # 4. Missing location 404
        res_missing = client.post("/api/locations/loc-non-existent/analysis")
        assert res_missing.status_code == 404


# ----------------------------------------------------------------------
# 12. WRONG LOCATION / ASSESSMENT ID TEST
# ----------------------------------------------------------------------
def test_wrong_location_id_and_assessment_id(sample_location, sample_evidence, sample_risk_assessment, mock_valid_llm_json):
    # LLM hallucinates an arbitrary location ID and assessment ID in its payload
    mock_valid_llm_json["location_id"] = "hallucinated-location-id"
    mock_valid_llm_json["risk_assessment_id"] = "hallucinated-assessment-id"

    mock_client = create_mock_groq_client(mock_valid_llm_json)
    engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client)

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    report = engine.generate_analysis(analyst_input)

    # Output report must preserve authoritative IDs from analyst_input, not the hallucinated ones
    assert report.location_id == sample_location.id
    assert report.risk_assessment_id == sample_risk_assessment.id


# ----------------------------------------------------------------------
# 13. MISSING EVIDENCE / LOCATION ERROR IN PERSISTENCE
# ----------------------------------------------------------------------
def test_missing_evidence_in_persistence():
    init_db()
    db = get_db_session()
    try:
        engine = EvidenceAnalystEngine(api_key="mock_key", client=MagicMock())
        with pytest.raises(ValueError) as exc_info:
            engine.generate_and_persist(db=db, location_id="loc-non-existent-xyz")
        assert "not found" in str(exc_info.value)
    finally:
        db.close()


# ----------------------------------------------------------------------
# 14. PROMPT VERSION AND METADATA TEST
# ----------------------------------------------------------------------
def test_prompt_version_and_metadata(sample_location, sample_evidence, sample_risk_assessment, mock_valid_llm_json):
    mock_client = create_mock_groq_client(mock_valid_llm_json)
    engine = EvidenceAnalystEngine(api_key="mock_key", client=mock_client, prompt_version="custom_analyst_v2")

    analyst_input = engine.build_analyst_input(sample_location, sample_evidence, sample_risk_assessment)
    report = engine.generate_analysis(analyst_input)

    assert report.prompt_version == "custom_analyst_v2"
    assert report.model == engine.model
    assert isinstance(report.generated_at, datetime)

