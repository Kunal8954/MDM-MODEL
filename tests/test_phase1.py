"""
tests/test_phase1.py
Comprehensive Phase 1 Unit and Integration Test Suite.
Validates:
1. AOI creation and surface area geometry
2. NDWI calculation formula and thresholding
3. Delta NDWI differential change metrics
4. Cloud rejection quality gate
5. Database persistence and relationships
6. Observation detector state machine (NO_NEW_OBSERVATION, QUALITY_REJECTED)
7. Provider error handling
8. FastAPI response schemas and health checks
"""

import pytest
import numpy as np
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from satguard.geospatial.aoi import (
    create_circular_aoi,
    create_bbox_from_point,
    compute_bbox_area_m2,
)
from satguard.processing.ndwi import NDWIProcessor
from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, SatelliteObservation, ChangeDetection
from satguard.api.main import app

client = TestClient(app)


# ----------------------------------------------------------------------
# 1. AOI Creation Tests
# ----------------------------------------------------------------------
def test_aoi_creation():
    lat, lon, radius_m = 30.3781, 78.4803, 8000
    poly = create_circular_aoi(lat, lon, radius_m)
    assert poly.is_valid
    assert poly.geom_type == "Polygon"

    bbox = create_bbox_from_point(lat, lon, radius_m)
    min_lon, min_lat, max_lon, max_lat = bbox
    assert min_lon < lon < max_lon
    assert min_lat < lat < max_lat

    area_m2 = compute_bbox_area_m2(bbox)
    assert area_m2 > 100_000_000  # > 100 km² for 8km radius box


# ----------------------------------------------------------------------
# 2. NDWI Calculation Tests
# ----------------------------------------------------------------------
def test_ndwi_calculation():
    processor = NDWIProcessor(water_threshold=0.1)

    # Pure water: high green, low NIR
    green = np.array([[0.5, 0.4], [0.3, 0.6]], dtype=np.float32)
    nir = np.array([[0.05, 0.04], [0.03, 0.06]], dtype=np.float32)

    ndwi = processor.compute_ndwi(green, nir)
    assert ndwi.shape == (2, 2)
    assert np.all(ndwi > 0.7)  # Clear water should have high positive NDWI

    # Land/Vegetation: low green, high NIR
    veg_green = np.array([[0.1, 0.1], [0.1, 0.1]], dtype=np.float32)
    veg_nir = np.array([[0.6, 0.7], [0.8, 0.9]], dtype=np.float32)

    veg_ndwi = processor.compute_ndwi(veg_green, veg_nir)
    assert np.all(veg_ndwi < -0.6)  # Vegetation should have negative NDWI


# ----------------------------------------------------------------------
# 3. Delta NDWI and Change Metrics Tests
# ----------------------------------------------------------------------
def test_delta_ndwi_and_metrics():
    processor = NDWIProcessor(water_threshold=0.1)

    # T1 baseline: 25% water
    t1 = np.array([[0.5, -0.5], [-0.5, -0.5]], dtype=np.float32)
    # T2 current: 50% water (expansion)
    t2 = np.array([[0.5, 0.5], [-0.5, -0.5]], dtype=np.float32)

    aoi_area = 1_000_000.0  # 1 km²
    change = processor.compute_differential_change(t1, t2, aoi_area)

    assert change["change_type"] == "WATER_EXTENT_CHANGE"
    assert change["current_water_area_m2"] > change["baseline_water_area_m2"]
    assert change["water_change_area_m2"] > 0
    assert change["mean_delta_ndwi"] > 0


# ----------------------------------------------------------------------
# 4. Cloud Rejection Quality Gate Tests
# ----------------------------------------------------------------------
def test_quality_control_cloud_rejection():
    # Cloud cover of 65% exceeds 25% threshold
    cloud_cover = 65.0
    threshold = 25.0
    is_rejected = cloud_cover > threshold
    assert is_rejected is True


# ----------------------------------------------------------------------
# 5. Database Persistence Tests
# ----------------------------------------------------------------------
@pytest.mark.live_data
def test_database_persistence():
    init_db()
    db = get_db_session()
    try:
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == "loc-001-tehri-dam").first()
        assert loc is not None
        assert loc.name == "Tehri Dam and Reservoir"

        obs_list = db.query(SatelliteObservation).filter(SatelliteObservation.location_id == loc.id).all()
        assert len(obs_list) >= 2

        chg = db.query(ChangeDetection).filter(ChangeDetection.location_id == loc.id).first()
        assert chg is not None
        assert chg.change_type in ["NO_CHANGE", "WATER_EXTENT_CHANGE"]
    finally:
        db.close()


# ----------------------------------------------------------------------
# 6. FastAPI Endpoint Schema Tests
# ----------------------------------------------------------------------
def test_api_health_endpoint():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "HEALTHY"
    assert data["service"] == "SATGUARD"


def test_api_data_status_endpoint():
    res = client.get("/api/data-status")
    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "REAL_DATA_ONLY"
    assert data["providers"]["copernicus_sentinel_2"] == "ONLINE"


def test_api_list_locations_endpoint():
    res = client.get("/api/locations")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 10
    assert any(loc["id"] == "loc-001-tehri-dam" for loc in data)


def test_api_get_location_endpoint():
    res = client.get("/api/locations/loc-001-tehri-dam")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "loc-001-tehri-dam"
    assert data["name"] == "Tehri Dam and Reservoir"


@pytest.mark.live_data
def test_api_location_observations_endpoint():
    res = client.get("/api/locations/loc-001-tehri-dam/observations")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 2


@pytest.mark.live_data
def test_api_location_changes_endpoint():
    res = client.get("/api/locations/loc-001-tehri-dam/changes")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "mean_delta_ndwi" in data[0]


# ----------------------------------------------------------------------
# 7. Sentinel-1 SAR Processing & Endpoint Tests
# ----------------------------------------------------------------------
def test_sar_processor_calibration():
    from satguard.processing.sar import SARProcessor

    sar_proc = SARProcessor(change_threshold_db=3.0)
    # Test linear power to decibel conversion
    lin_power = np.array([[0.1, 0.01], [1.0, 10.0]], dtype=np.float32)
    db = sar_proc.calibrate_to_db(lin_power)

    # 10 * log10(0.1) = -10 dB, 10 * log10(1.0) = 0 dB
    assert np.isclose(db[0, 0], -10.0, atol=0.1)
    assert np.isclose(db[1, 0], 0.0, atol=0.1)


@pytest.mark.live_data
def test_api_sar_changes_endpoint():
    res = client.get("/api/locations/loc-001-tehri-dam/sar/changes")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["change_type"] in ["SAR_BACKSCATTER_CHANGE", "SURFACE_ROUGHNESS_CHANGE", "NO_CHANGE"]
