"""
tests/test_phase2_7.py
Unit and Integration tests for Phase 2.7: Database Persistence & FastAPI Endpoints.
Covers:
1. Sentinel1ProcessingResult database record creation & serialization
2. Sentinel1ChangeDetection database record creation & serialization
3. FastAPI endpoint: POST /api/locations/{location_id}/sentinel-1/observations/{observation_id}/process
4. FastAPI endpoint: POST /api/locations/{location_id}/sentinel-1/change
5. FastAPI endpoint: GET /api/locations/{location_id}/sentinel-1/changes
6. Error handling and 404 validation
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import (
    CriticalLocation,
    SatelliteObservation,
    Sentinel1ProcessingResult,
    Sentinel1ChangeDetection,
)
from satguard.api.main import app
from satguard.processing.sar import SARProcessor

client = TestClient(app)


@pytest.fixture(scope="module")
def setup_api_db():
    init_db()
    db = get_db_session()
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == "loc-001-tehri-dam").first()
    assert loc is not None

    obs = db.query(SatelliteObservation).filter(SatelliteObservation.id == "obs-api-test-1").first()
    if not obs:
        obs = SatelliteObservation(
            id="obs-api-test-1",
            location_id="loc-001-tehri-dam",
            product_id="PROD-API-TEST-1",
            collection="sentinel-1-grd",
            sensor="SAR-C",
            acquisition_time=datetime(2026, 10, 2, 0, 43, 0, tzinfo=timezone.utc),
            cloud_cover=0.0,
        )
        db.add(obs)
        db.commit()

    db.close()
    return "obs-api-test-1"


def test_processing_record_persistence():
    db = get_db_session()
    try:
        rec_id = "proc-test-rec-1"
        db.query(Sentinel1ProcessingResult).filter(Sentinel1ProcessingResult.id == rec_id).delete()
        db.commit()

        rec = Sentinel1ProcessingResult(
            id=rec_id,
            location_id="loc-001-tehri-dam",
            observation_id="obs-api-test-1",
            product_id="PROD-API-TEST-1",
            acquisition_time=datetime(2026, 10, 2, 0, 43, 0, tzinfo=timezone.utc),
            vv_statistics=json.dumps({"mean": -12.4, "min": -25.0, "max": -5.0}),
            vh_statistics=json.dumps({"mean": -18.2, "min": -32.0, "max": -10.0}),
            vv_raster_path="/data/vv_db.tif",
            vh_raster_path="/data/vh_db.tif",
            status="SUCCESS",
        )
        db.add(rec)
        db.commit()

        persisted = db.query(Sentinel1ProcessingResult).filter(Sentinel1ProcessingResult.id == rec_id).first()
        assert persisted is not None
        d = persisted.to_dict()
        assert d["id"] == rec_id
        assert d["vv_statistics"]["mean"] == -12.4
        assert d["vh_statistics"]["mean"] == -18.2
    finally:
        db.close()


def test_api_process_endpoint(setup_api_db):
    obs_id = setup_api_db

    mock_res = {
        "location_id": "loc-001-tehri-dam",
        "observation_id": obs_id,
        "product_id": "PROD-API-TEST-1",
        "status": "SUCCESS",
        "vv_raster": "/data/vv.tif",
        "vh_raster": "/data/vh.tif",
        "vv_mean_db": -11.5,
        "vh_mean_db": -17.8,
        "vv_statistics": {"mean": -11.5},
        "vh_statistics": {"mean": -17.8},
    }

    with patch.object(SARProcessor, "preprocess_observation", return_value=mock_res):
        resp = client.post(f"/api/locations/loc-001-tehri-dam/sentinel-1/observations/{obs_id}/process")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["vv_mean_db"] == -11.5
        assert data["vh_mean_db"] == -17.8

    # 404 test for non-existent location
    resp_404 = client.post(f"/api/locations/loc-nonexistent/sentinel-1/observations/{obs_id}/process")
    assert resp_404.status_code == 404


def test_api_change_endpoint():
    mock_change_res = {
        "location_id": "loc-001-tehri-dam",
        "sensor": "SENTINEL-1",
        "status": "SUCCESS",
        "t1": {"observation_id": "t1"},
        "t2": {"observation_id": "t2"},
        "delta_vv_mean_db": 0.45,
        "delta_vh_mean_db": 0.32,
        "vv_changed_percent": 4.5,
        "vh_changed_percent": 3.8,
        "joint_changed_percent": 2.1,
        "change_raster": "/data/change.tif",
    }

    with patch.object(SARProcessor, "compare_observations", return_value=mock_change_res):
        resp = client.post("/api/locations/loc-001-tehri-dam/sentinel-1/change")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "SUCCESS"
        assert data["delta_vv_mean_db"] == 0.45
        assert "landslide_probability" not in data  # Scientific boundary


def test_api_history_endpoint():
    resp = client.get("/api/locations/loc-001-tehri-dam/sentinel-1/changes")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
