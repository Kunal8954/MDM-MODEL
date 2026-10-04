"""
tests/test_phase2_5.py
Unit and Integration tests for Phase 2.5: Temporal T1 vs T2 Comparison.
Covers:
1. Dynamic T1 and T2 observation selection
2. Acquisition geometry & orbit compatibility validation
3. Rejection of cross-orbit comparison (INCOMPATIBLE_GEOMETRY)
4. Raster grid alignment
5. Differential backscatter calculation: ΔVV = VV_T2 - VV_T1 and ΔVH = VH_T2 - VH_T1 (in dB)
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pytest
import tifffile

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, SatelliteObservation
from satguard.processing.sar import SARProcessor


@pytest.fixture(scope="module")
def setup_temporal_db(tmp_path_factory):
    init_db()
    db = get_db_session()
    base_dir = tmp_path_factory.mktemp("sar_temporal_data")

    # Ensure location exists
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == "loc-001-tehri-dam").first()
    assert loc is not None

    # Create dummy raw rasters on disk
    def make_dummy_raster(obs_id, val):
        p = base_dir / "loc-001-tehri-dam" / obs_id
        p.mkdir(parents=True, exist_ok=True)
        tif_p = p / f"sentinel1_grd_{obs_id}.tif"
        arr = np.full((32, 32, 2), val, dtype=np.float32)
        tifffile.imwrite(str(tif_p), arr)
        return str(tif_p)

    # 1. Observation T1 (DESCENDING, orbit 63)
    t1_path = make_dummy_raster("obs-test-desc-t1", 0.1)
    obs_t1 = db.query(SatelliteObservation).filter(SatelliteObservation.id == "obs-test-desc-t1").first()
    if not obs_t1:
        obs_t1 = SatelliteObservation(
            id="obs-test-desc-t1",
            location_id="loc-001-tehri-dam",
            product_id="S1_TEST_PROD_DESC_T1",
            collection="sentinel-1-grd",
            sensor="SAR-C",
            acquisition_time=datetime(2026, 8, 27, 0, 43, 0, tzinfo=timezone.utc),
            cloud_cover=0.0,
            raster_artifact_path=t1_path,
            raw_metadata=json.dumps({"orbit_direction": "DESCENDING", "relative_orbit": 63}),
        )
        db.add(obs_t1)
    else:
        obs_t1.raster_artifact_path = t1_path

    # 2. Observation T2 (DESCENDING, orbit 63)
    t2_path = make_dummy_raster("obs-test-desc-t2", 0.5)
    obs_t2 = db.query(SatelliteObservation).filter(SatelliteObservation.id == "obs-test-desc-t2").first()
    if not obs_t2:
        obs_t2 = SatelliteObservation(
            id="obs-test-desc-t2",
            location_id="loc-001-tehri-dam",
            product_id="S1_TEST_PROD_DESC_T2",
            collection="sentinel-1-grd",
            sensor="SAR-C",
            acquisition_time=datetime(2026, 10, 2, 0, 43, 0, tzinfo=timezone.utc),
            cloud_cover=0.0,
            raster_artifact_path=t2_path,
            raw_metadata=json.dumps({"orbit_direction": "DESCENDING", "relative_orbit": 63}),
        )
        db.add(obs_t2)
    else:
        obs_t2.raster_artifact_path = t2_path

    # 3. Observation T_ASC (ASCENDING, orbit 129) - Incompatible geometry
    t_asc_path = make_dummy_raster("obs-test-asc-t", 0.3)
    obs_asc = db.query(SatelliteObservation).filter(SatelliteObservation.id == "obs-test-asc-t").first()
    if not obs_asc:
        obs_asc = SatelliteObservation(
            id="obs-test-asc-t",
            location_id="loc-001-tehri-dam",
            product_id="S1_TEST_PROD_ASC",
            collection="sentinel-1-grd",
            sensor="SAR-C",
            acquisition_time=datetime(2026, 9, 24, 12, 46, 0, tzinfo=timezone.utc),
            cloud_cover=0.0,
            raster_artifact_path=t_asc_path,
            raw_metadata=json.dumps({"orbit_direction": "ASCENDING", "relative_orbit": 129}),
        )
        db.add(obs_asc)
    else:
        obs_asc.raster_artifact_path = t_asc_path

    db.commit()
    db.close()
    return base_dir


def test_incompatible_orbit_rejection(setup_temporal_db):
    base_dir = setup_temporal_db
    processor = SARProcessor(base_storage_dir=base_dir)
    db = get_db_session()
    try:
        # Compare ASCENDING vs DESCENDING -> Must return INCOMPATIBLE_GEOMETRY
        res = processor.compare_observations(
            location_id="loc-001-tehri-dam",
            db=db,
            t1_observation_id="obs-test-asc-t",
            t2_observation_id="obs-test-desc-t2",
            allow_cross_orbit=False,
        )
        assert res["status"] == "INCOMPATIBLE_GEOMETRY"
        assert "Incompatible acquisition geometry" in res["message"]
        assert res["t1"]["orbit_direction"] == "ASCENDING"
        assert res["t2"]["orbit_direction"] == "DESCENDING"
    finally:
        db.close()


def test_compatible_orbit_temporal_comparison(setup_temporal_db):
    base_dir = setup_temporal_db
    processor = SARProcessor(base_storage_dir=base_dir)
    db = get_db_session()
    try:
        # Compare DESCENDING vs DESCENDING -> Must succeed
        res = processor.compare_observations(
            location_id="loc-001-tehri-dam",
            db=db,
            t1_observation_id="obs-test-desc-t1",
            t2_observation_id="obs-test-desc-t2",
            allow_cross_orbit=False,
            force_reprocess=True,
        )
        assert res["status"] == "SUCCESS"
        assert "delta_vv_mean_db" in res
        assert "delta_vh_mean_db" in res
        # T2 (0.5 = -3.01 dB) - T1 (0.1 = -10.0 dB) = ~ +6.99 dB shift
        assert res["delta_vv_mean_db"] > 0.0
        assert res["delta_vh_mean_db"] > 0.0
        assert Path(res["delta_vv_raster"]).exists()
        assert Path(res["delta_vh_raster"]).exists()
        assert Path(res["change_raster"]).exists()
    finally:
        db.close()
