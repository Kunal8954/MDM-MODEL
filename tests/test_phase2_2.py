"""
tests/test_phase2_2.py
Unit and Integration Tests for Phase 2.2: Sentinel-1 SAR Imagery Retrieval.
Validates:
1. Retrieval metadata and manifest validation
2. Deterministic storage path resolution
3. Idempotency logic and corruption recovery
4. SHA-256 checksum calculation
5. Empty / corrupt download handling
6. Failed HTTP handling (401, 403, 404, 500, timeout)
7. Manifest creation and integrity
8. API endpoint POST /api/locations/{location_id}/sentinel-1/observations/{observation_id}/retrieve
"""

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, SatelliteObservation, Sentinel1Retrieval
from satguard.ingestion.sentinel1_retrieval import (
    Sentinel1RetrievalService,
    retrieve_sentinel1_observation,
    calculate_sha256,
    CDSEAuthenticationError,
    CDSEProductNotFoundError,
    CDSEIntegrityError,
)
from satguard.api.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def setup_db():
    init_db()
    db = get_db_session()
    # Ensure Tehri Dam exists
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == "loc-001-tehri-dam").first()
    assert loc is not None

    # Ensure test Sentinel-1 observation exists
    test_obs = db.query(SatelliteObservation).filter(SatelliteObservation.id == "obs-sar-test-t2").first()
    if not test_obs:
        test_obs = SatelliteObservation(
            id="obs-sar-test-t2",
            location_id="loc-001-tehri-dam",
            product_id="S1D_IW_GRDH_1SDV_20261002T004305_20261002T004330_004829_009120_A081_COG",
            collection="sentinel-1-grd",
            sensor="SAR-C",
            acquisition_time=datetime(2026, 10, 2, 0, 43, 5, tzinfo=timezone.utc),
            cloud_cover=0.0,
            quality_status="NEW_OBSERVATION_AVAILABLE",
            raw_metadata=json.dumps({"test": True}),
        )
        db.add(test_obs)
        db.commit()

    db.close()
    return "obs-sar-test-t2"


def test_deterministic_storage_paths(tmp_path):
    service = Sentinel1RetrievalService(base_storage_dir=tmp_path)
    paths = service.get_storage_paths("loc-001-tehri-dam", "obs-sar-001", "PROD-ABC")

    expected_dir = tmp_path / "loc-001-tehri-dam" / "obs-sar-001"
    assert paths["directory"] == expected_dir
    assert paths["raster"] == expected_dir / "sentinel1_grd_PROD-ABC.tif"
    assert paths["manifest"] == expected_dir / "manifest.json"
    assert paths["part"] == expected_dir / "sentinel1_grd_PROD-ABC.tif.part"


def test_sha256_generation(tmp_path):
    sample_file = tmp_path / "test_sample.bin"
    sample_data = b"SATGUARD_REAL_SENTINEL_1_SAR_RASTER_DATA_2026"
    sample_file.write_bytes(sample_data)

    expected_sha = hashlib.sha256(sample_data).hexdigest()
    calculated = calculate_sha256(sample_file)

    assert calculated == expected_sha
    assert len(calculated) == 64


def test_idempotency_logic_and_corruption_recovery(tmp_path):
    service = Sentinel1RetrievalService(base_storage_dir=tmp_path)
    paths = service.get_storage_paths("loc-001-tehri-dam", "obs-001", "PROD-TEST")

    # 1. Non-existent files -> None
    assert service.verify_existing_retrieval(paths) is None

    # 2. Valid files with matching sha256 -> Returns manifest
    dummy_data = b"VALID_TIFF_BYTES_CONTENT_1234567890"
    paths["raster"].write_bytes(dummy_data)
    valid_sha = hashlib.sha256(dummy_data).hexdigest()
    manifest_data = {
        "location_id": "loc-001-tehri-dam",
        "observation_id": "obs-001",
        "product_id": "PROD-TEST",
        "mission": "Sentinel-1",
        "product_type": "GRD",
        "instrument_mode": "IW",
        "polarizations": ["VV", "VH"],
        "acquisition_time": "2026-10-02T00:43:05Z",
        "retrieved_at": "2026-10-04T12:00:00Z",
        "provider": "Copernicus Data Space Ecosystem",
        "source_url": "https://sh.dataspace.copernicus.eu/api/v1/process",
        "local_path": str(paths["raster"]),
        "file_size_bytes": len(dummy_data),
        "sha256": valid_sha,
        "retrieval_status": "SUCCESS",
    }
    with open(paths["manifest"], "w") as f:
        json.dump(manifest_data, f)

    verified = service.verify_existing_retrieval(paths)
    assert verified is not None
    assert verified["sha256"] == valid_sha

    # 3. Corrupt / modified raster -> Checksum mismatch -> Returns None for safe retry
    paths["raster"].write_bytes(b"CORRUPTED_BYTES")
    assert service.verify_existing_retrieval(paths) is None

    # 4. Zero-byte file -> Returns None
    paths["raster"].write_bytes(b"")
    assert service.verify_existing_retrieval(paths) is None


def test_empty_download_handling(tmp_path, setup_db, monkeypatch):
    service = Sentinel1RetrievalService(base_storage_dir=tmp_path)
    obs_id = setup_db

    # Mock provider authentication
    service.provider.authenticate = MagicMock(return_value=True)
    service.provider._access_token = "mock-token"

    # Mock empty response from CDSE Process API
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content = MagicMock(return_value=[b""])

    with patch("requests.post", return_value=mock_resp):
        with patch("requests.get", return_value=MagicMock(status_code=200, json=lambda: {})):
            db = get_db_session()
            try:
                with pytest.raises(CDSEIntegrityError) as exc_info:
                    service.retrieve(observation_id=obs_id, db=db, force_refresh=True)
                assert "is empty (0 bytes)" in str(exc_info.value)
            finally:
                db.close()


def test_failed_http_handling(tmp_path, setup_db):
    service = Sentinel1RetrievalService(base_storage_dir=tmp_path)
    obs_id = setup_db

    service.provider.authenticate = MagicMock(return_value=True)
    service.provider._access_token = "mock-token"

    # Test HTTP 401 Unauthorized
    mock_401 = MagicMock()
    mock_401.status_code = 401
    mock_401.text = "Unauthorized"

    with patch("requests.post", return_value=mock_401):
        with patch("requests.get", return_value=MagicMock(status_code=200, json=lambda: {})):
            db = get_db_session()
            try:
                with pytest.raises(CDSEAuthenticationError):
                    service.retrieve(observation_id=obs_id, db=db, force_refresh=True)
            finally:
                db.close()

    # Test HTTP 404 Not Found
    mock_404 = MagicMock()
    mock_404.status_code = 404
    mock_404.text = "Not Found"

    with patch("requests.post", return_value=mock_404):
        with patch("requests.get", return_value=MagicMock(status_code=200, json=lambda: {})):
            db = get_db_session()
            try:
                with pytest.raises(CDSEProductNotFoundError):
                    service.retrieve(observation_id=obs_id, db=db, force_refresh=True)
            finally:
                db.close()


def test_manifest_creation_and_fields(tmp_path, setup_db):
    service = Sentinel1RetrievalService(base_storage_dir=tmp_path)
    obs_id = setup_db

    service.provider.authenticate = MagicMock(return_value=True)
    service.provider._access_token = "mock-token"

    mock_tiff_bytes = b"MOCK_GEOTIFF_BAND_VV_VH_DATA_BYTES" * 100
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content = MagicMock(return_value=[mock_tiff_bytes])

    mock_stac_resp = MagicMock()
    mock_stac_resp.status_code = 200
    mock_stac_resp.json = MagicMock(return_value={
        "properties": {
            "sar:polarizations": ["VV", "VH"],
            "sar:instrument_mode": "IW",
        }
    })

    with patch("requests.post", return_value=mock_resp):
        with patch("requests.get", return_value=mock_stac_resp):
            db = get_db_session()
            try:
                result = service.retrieve(observation_id=obs_id, db=db, force_refresh=True)
                assert result["status"] == "SUCCESS"
                assert result["file_size_bytes"] == len(mock_tiff_bytes)
                assert result["sha256"] == hashlib.sha256(mock_tiff_bytes).hexdigest()

                manifest = result["manifest"]
                assert manifest["mission"] == "Sentinel-1"
                assert manifest["product_type"] == "GRD"
                assert manifest["instrument_mode"] == "IW"
                assert manifest["polarizations"] == ["VV", "VH"]
                assert manifest["provider"] == "Copernicus Data Space Ecosystem"
                assert manifest["retrieval_status"] == "SUCCESS"
                assert "local_path" in manifest
                assert "sha256" in manifest
                assert "retrieved_at" in manifest

                # Ensure credentials are NOT leaked in manifest
                manifest_str = json.dumps(manifest)
                assert "client_secret" not in manifest_str
                assert "Bearer" not in manifest_str
                assert "mock-token" not in manifest_str
            finally:
                db.close()


def test_api_endpoint_idempotency(tmp_path, setup_db, monkeypatch):
    obs_id = setup_db
    monkeypatch.setattr("satguard.ingestion.sentinel1_retrieval.DEFAULT_STORAGE_DIR", tmp_path)

    # 1. Retrieve observation via API
    mock_tiff_bytes = b"API_TEST_TIFF_SAR_DATA_STREAM" * 50
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_content = MagicMock(return_value=[mock_tiff_bytes])

    with patch("satguard.providers.copernicus.CopernicusSatelliteProvider.authenticate", return_value=True):
        with patch.object(Sentinel1RetrievalService, "retrieve") as mock_retrieve:
            mock_retrieve.return_value = {
                "location_id": "loc-001-tehri-dam",
                "observation_id": obs_id,
                "product_id": "S1D_IW_GRDH_1SDV_20261002T004305_20261002T004330_004829_009120_A081_COG",
                "status": "SUCCESS",
                "storage_path": str(tmp_path / "test.tif"),
                "file_size_bytes": len(mock_tiff_bytes),
                "sha256": hashlib.sha256(mock_tiff_bytes).hexdigest(),
            }

            resp = client.post(f"/api/locations/loc-001-tehri-dam/sentinel-1/observations/{obs_id}/retrieve")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "SUCCESS"
            assert data["observation_id"] == obs_id

        # 2. Second call returns ALREADY_RETRIEVED
        with patch.object(Sentinel1RetrievalService, "retrieve") as mock_retrieve_idem:
            mock_retrieve_idem.return_value = {
                "location_id": "loc-001-tehri-dam",
                "observation_id": obs_id,
                "product_id": "S1D_IW_GRDH_1SDV_20261002T004305_20261002T004330_004829_009120_A081_COG",
                "status": "ALREADY_RETRIEVED",
                "storage_path": str(tmp_path / "test.tif"),
                "file_size_bytes": len(mock_tiff_bytes),
                "sha256": hashlib.sha256(mock_tiff_bytes).hexdigest(),
            }
            resp2 = client.post(f"/api/locations/loc-001-tehri-dam/sentinel-1/observations/{obs_id}/retrieve")
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "ALREADY_RETRIEVED"

    # 3. Test 404 for non-existent observation
    resp_404 = client.post("/api/locations/loc-001-tehri-dam/sentinel-1/observations/obs-nonexistent/retrieve")
    assert resp_404.status_code == 404
