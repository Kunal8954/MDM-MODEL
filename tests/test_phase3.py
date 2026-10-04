"""
tests/test_phase3.py
Unit and Integration Tests for Phase 3: Multi-Sensor Evidence Fusion.
Covers:
1. Unified Evidence Schema validation (Pydantic & SQLAlchemy EvidenceSnapshot)
2. Deterministic Temporal Alignment calculation and status
3. Deterministic Spatial Alignment and distance calculation
4. Evidence correlation rules (MULTI-SENSOR_CHANGE_SIGNAL, SAR_RAINFALL_ASSOCIATION, etc.)
5. MultiSensorEvidence object assembly and snapshot persistence
6. FastAPI endpoints for evidence fusion and snapshot retrieval
7. Scientific boundary verification (strictly NO disaster predictions)
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import (
    CriticalLocation,
    SatelliteObservation,
    ChangeDetection,
    Sentinel1ChangeDetection,
    EvidenceSnapshot,
)
from satguard.fusion.schema import (
    TemporalAlignment,
    SpatialAlignment,
    Sentinel1Evidence,
    Sentinel2Evidence,
    RainfallEvidence,
    FireEvidence,
    EarthquakeEvidence,
    TerrainEvidence,
    EvidenceCorrelation,
    MultiSensorEvidence,
)
from satguard.fusion.engine import EvidenceFusionEngine, haversine_distance_km
from satguard.api.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def setup_fusion_db():
    init_db()
    db = get_db_session()
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == "loc-001-tehri-dam").first()
    assert loc is not None
    db.close()
    return "loc-001-tehri-dam"


def test_haversine_and_spatial_alignment():
    # Tehri Dam (30.3781, 78.4803) to a point ~10 km away
    d_km = haversine_distance_km(30.3781, 78.4803, 30.4681, 78.4803)
    assert 9.0 < d_km < 11.0

    engine = EvidenceFusionEngine()
    loc = CriticalLocation(
        id="loc-test",
        name="Test Dam",
        location_type="Dam",
        latitude=30.3781,
        longitude=78.4803,
        radius_m=3000,
        geometry="{}",
        risk_category="Dam",
    )

    # Co-located point -> INSIDE_AOI
    align_inside = engine.build_spatial_alignment(loc, 30.3781, 78.4803)
    assert align_inside.spatial_relation == "INSIDE_AOI"
    assert align_inside.distance_km == 0.0

    # Point 50 km away -> PROXIMATE
    align_prox = engine.build_spatial_alignment(loc, 30.8, 78.4803)
    assert align_prox.spatial_relation == "PROXIMATE"
    assert 40.0 < align_prox.distance_km < 60.0


def test_temporal_alignment():
    engine = EvidenceFusionEngine()
    ref_time = datetime(2026, 10, 2, 0, 43, 5, tzinfo=timezone.utc)
    w_start = ref_time - timedelta(days=30)
    w_end = ref_time + timedelta(days=1)

    # 1. Observation 24 hours prior -> ALIGNED
    obs_time = ref_time - timedelta(hours=24)
    align_aligned = engine.build_temporal_alignment(obs_time, ref_time, w_start, w_end)
    assert align_aligned.status == "ALIGNED"
    assert align_aligned.temporal_distance_hours == 24.0

    # 2. Observation 60 days prior -> OUTSIDE_WINDOW
    obs_old = ref_time - timedelta(days=60)
    align_outside = engine.build_temporal_alignment(obs_old, ref_time, w_start, w_end)
    assert align_outside.status == "OUTSIDE_WINDOW"

    # 3. Missing observation -> UNAVAILABLE
    align_none = engine.build_temporal_alignment(None, ref_time, w_start, w_end)
    assert align_none.status == "UNAVAILABLE"
    assert align_none.temporal_distance_hours is None


def test_evidence_correlation_rules():
    engine = EvidenceFusionEngine()
    ref_time = datetime(2026, 10, 2, 0, 43, 5, tzinfo=timezone.utc)

    # 1. Setup active SAR change (24.9% changed)
    s1 = Sentinel1Evidence(
        available=True,
        t1_observation_id="t1",
        t2_observation_id="t2",
        t2_acquisition_time=ref_time,
        changed_percentage=24.9,
        mean_delta_vv_db=-0.27,
        significant_region_count=10,
        temporal_alignment=TemporalAlignment(reference_time=ref_time, status="ALIGNED"),
    )

    # 2. Setup active Optical change (water extent delta = 8.5%)
    s2 = Sentinel2Evidence(
        available=True,
        observation_id="s2_obs",
        water_change_percentage=8.5,
        optical_change_status="WATER_EXTENT_CHANGE",
        temporal_alignment=TemporalAlignment(reference_time=ref_time, temporal_distance_hours=48.0, status="ALIGNED"),
    )

    # 3. Setup Rainfall (granules found)
    rain = RainfallEvidence(
        available=True,
        total_granules_found=12,
        estimated_rainfall_mm=21.6,
        temporal_alignment=TemporalAlignment(reference_time=ref_time, status="ALIGNED"),
    )

    # 4. Setup Fire (none)
    fire = FireEvidence(available=False)

    # 5. Setup Earthquake (M4.2 at 35 km)
    quake = EarthquakeEvidence(
        available=True,
        events_found_count=1,
        nearest_event_id="usp001",
        nearest_magnitude=4.2,
        distance_km=35.0,
        nearest_event_time=ref_time - timedelta(hours=12),
        temporal_alignment=TemporalAlignment(reference_time=ref_time, temporal_distance_hours=12.0, status="ALIGNED"),
    )

    # 6. Setup Terrain (high slope = 24.5 deg)
    dem = TerrainEvidence(
        available=True,
        slope_degrees=24.5,
        elevation_m=840.0,
        tile_name="Copernicus_DEM_N30_E078",
    )

    correlations = engine.compute_evidence_correlations(s1, s2, rain, fire, quake, dem)
    corr_types = [c.correlation_type for c in correlations]

    assert "MULTI-SENSOR_CHANGE_SIGNAL" in corr_types
    assert "SAR_RAINFALL_ASSOCIATION" in corr_types
    assert "EARTHQUAKE_SAR_ASSOCIATION" in corr_types
    assert "TERRAIN_SLOPE_ASSOCIATION" in corr_types

    # Ensure no disaster prediction or speculative wording exists
    for c in correlations:
        note_lower = c.scientific_note.lower()
        assert "landslide prediction" not in note_lower
        assert "disaster" not in note_lower
        assert "structural failure" not in note_lower


def test_fuse_location_evidence_persistence(setup_fusion_db):
    loc_id = setup_fusion_db
    engine = EvidenceFusionEngine()
    db = get_db_session()
    try:
        evidence = engine.fuse_location_evidence(
            db=db,
            location_id=loc_id,
            window_days=45,
            force_recompute=True,
        )
        assert evidence.location_id == loc_id
        assert evidence.sentinel1.available is True
        assert len(evidence.correlations) > 0
        assert evidence.terrain.available is True

        # Check DB persistence
        persisted = db.query(EvidenceSnapshot).filter(EvidenceSnapshot.id == evidence.id).first()
        assert persisted is not None
        d = persisted.to_dict()
        assert d["location_id"] == loc_id
        assert "sentinel1_evidence" in d
        assert "correlations" in d
    finally:
        db.close()


def test_api_fusion_endpoints(setup_fusion_db):
    loc_id = setup_fusion_db

    # 1. POST /api/locations/{location_id}/evidence/fuse
    resp = client.post(f"/api/locations/{loc_id}/evidence/fuse?window_days=40")
    assert resp.status_code == 200
    data = resp.json()
    assert data["location_id"] == loc_id
    assert "sentinel1" in data
    assert "correlations" in data
    snapshot_id = data["id"]

    # 2. GET /api/locations/{location_id}/evidence/snapshots
    resp_list = client.get(f"/api/locations/{loc_id}/evidence/snapshots")
    assert resp_list.status_code == 200
    snaps = resp_list.json()
    assert isinstance(snaps, list)
    assert any(s["id"] == snapshot_id for s in snaps)

    # 3. GET /api/locations/{location_id}/evidence/snapshots/{snapshot_id}
    resp_detail = client.get(f"/api/locations/{loc_id}/evidence/snapshots/{snapshot_id}")
    assert resp_detail.status_code == 200
    snap_obj = resp_detail.json()
    assert snap_obj["id"] == snapshot_id
    assert snap_obj["location_id"] == loc_id
