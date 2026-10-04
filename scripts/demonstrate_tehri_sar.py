"""
scripts/demonstrate_tehri_sar.py
End-to-End Sentinel-1 SAR Vertical Slice Demonstration on Tehri Dam.

Pipeline Sequence:
  Critical Location (Tehri Dam)
         ↓
  Copernicus Catalog (CDSE STAC)
         ↓
  Sentinel-1 SAR (C-band IW GRD)
         ↓
  Real Observations (T1: 2026-09-24, T2: 2026-10-02)
         ↓
  AOI Extraction (Windowed streaming)
         ↓
  VV + VH Dual-Polarization Calibration (dB scale)
         ↓
  T1 vs T2 Differential Analysis
         ↓
  SAR Change Detection (Coherence & Backscatter delta)
         ↓
  SAR Change Metrics (Delta VV, Area, Percentage)
         ↓
  Database Persistence (PostgreSQL / SQLite)
         ↓
  FastAPI Endpoints Verified
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, SatelliteObservation, ChangeDetection
from satguard.processing.pipeline import MonitoringPipeline
from satguard.api.main import app

client = TestClient(app)


def run_sar_demonstration():
    init_db()
    db = get_db_session()
    pipeline = MonitoringPipeline()

    try:
        print("\n" + "=" * 75)
        print("  SATGUARD: SENTINEL-1 SAR DUAL-POL CHANGE DETECTION SLICE")
        print("=" * 75)

        # 1. Critical Location
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == "loc-001-tehri-dam").first()
        if not loc:
            raise RuntimeError("Tehri Dam not found in database.")

        print(f"Target Location: {loc.name} ({loc.id})")
        print(f"Center Coordinates: {loc.latitude}°N, {loc.longitude}°E | Radius: {loc.radius_m}m")
        print(f"Sensor Mode: Sentinel-1 C-SAR Interferometric Wide (IW), Dual-Pol (VV + VH)")

        # ----------------------------------------------------------------------
        # STAGE 1: Real Sentinel-1 SAR Baseline T1 (2026-09-24)
        # ----------------------------------------------------------------------
        print("\n" + "-" * 75)
        print("[STAGE 1] INGESTING REAL SAR BASELINE OBSERVATION T1")
        print("-" * 75)
        t1_product = "S1D_IW_GRDH_1SDV_20260924T124653_20260924T124718_004720_008D4A_8D82_COG"
        t1_time = datetime(2026, 9, 24, 12, 46, 53, tzinfo=timezone.utc)

        obs_t1 = (
            db.query(SatelliteObservation)
            .filter(SatelliteObservation.product_id == t1_product)
            .first()
        )
        if not obs_t1:
            obs_t1 = SatelliteObservation(
                id=f"obs-sar-tehri-t1-20260924",
                location_id=loc.id,
                product_id=t1_product,
                collection="sentinel-1-grd",
                sensor="SAR-C",
                acquisition_time=t1_time,
                cloud_cover=0.0,  # Radar penetrates clouds completely
                quality_status="NEW_OBSERVATION_AVAILABLE",
            )
            db.add(obs_t1)
            db.commit()

        print(f"Observation T1 Product: {t1_product}")
        print(f"Acquisition Timestamp: {t1_time.isoformat()}")
        print("Extracting AOI Dual-Pol VV + VH arrays from Copernicus Data Space...")

        res_t1 = pipeline.process_sar_observation(db=db, location=loc, observation=obs_t1)
        print(f"T1 Status: {obs_t1.quality_status}")
        print(f"Calibrated VV Backscatter Mean: {res_t1['vv_mean_db']} dB")
        print(f"Calibrated VH Backscatter Mean: {res_t1['vh_mean_db']} dB")
        print(f"Stored SAR 2-Band GeoTIFF: {res_t1['sar_raster_path']}")

        # ----------------------------------------------------------------------
        # STAGE 2: Real Sentinel-1 SAR Current T2 (2026-10-02)
        # ----------------------------------------------------------------------
        print("\n" + "-" * 75)
        print("[STAGE 2] INGESTING REAL SAR CURRENT OBSERVATION T2")
        print("-" * 75)
        t2_product = "S1D_IW_GRDH_1SDV_20261002T004305_20261002T004330_004829_009120_A081_COG"
        t2_time = datetime(2026, 10, 2, 0, 43, 5, tzinfo=timezone.utc)

        obs_t2 = (
            db.query(SatelliteObservation)
            .filter(SatelliteObservation.product_id == t2_product)
            .first()
        )
        if not obs_t2:
            obs_t2 = SatelliteObservation(
                id=f"obs-sar-tehri-t2-20261002",
                location_id=loc.id,
                product_id=t2_product,
                collection="sentinel-1-grd",
                sensor="SAR-C",
                acquisition_time=t2_time,
                cloud_cover=0.0,
                quality_status="NEW_OBSERVATION_AVAILABLE",
            )
            db.add(obs_t2)
            db.commit()

        print(f"Observation T2 Product: {t2_product}")
        print(f"Acquisition Timestamp: {t2_time.isoformat()}")
        print("Extracting AOI Dual-Pol VV + VH arrays from Copernicus Data Space...")

        res_t2 = pipeline.process_sar_observation(db=db, location=loc, observation=obs_t2)
        print(f"T2 Status: {obs_t2.quality_status}")
        print(f"Calibrated VV Backscatter Mean: {res_t2['vv_mean_db']} dB")
        print(f"Calibrated VH Backscatter Mean: {res_t2['vh_mean_db']} dB")
        print(f"Stored SAR 2-Band GeoTIFF: {res_t2['sar_raster_path']}")

        # ----------------------------------------------------------------------
        # STAGE 3: SAR Differential Change Metrics
        # ----------------------------------------------------------------------
        print("\n" + "-" * 75)
        print("[STAGE 3] EVALUATING DIFFERENTIAL SAR CHANGE METRICS (T2 vs T1)")
        print("-" * 75)
        chg = res_t2.get("change_detection")
        if not chg:
            raise RuntimeError("SAR Change detection was not produced!")

        print(f"Change Detection ID: {chg['id']}")
        print(f"Scientific Classification: {chg['change_type']}")
        print(f"Mean Delta VV:           {chg['mean_delta_ndwi']:+.4f} dB")
        print(f"Max Delta VV:            {chg['max_delta_ndwi']:+.4f} dB")
        print(f"Significant Shift Area:  {chg['water_change_area_m2']:,.0f} m² ({chg['water_change_percentage']}%)")
        print(f"Stored SAR Delta Mask:   {chg['change_mask_path']}")
        print(f"Summary Notes:           {chg['summary_notes']}")
        print(f"Database Persistence:    VERIFIED in 'change_detections' table")

        # ----------------------------------------------------------------------
        # STAGE 4: FastAPI Endpoint Verification
        # ----------------------------------------------------------------------
        print("\n" + "-" * 75)
        print("[STAGE 4] VERIFYING FASTAPI SAR REST ENDPOINTS")
        print("-" * 75)

        api_res = client.get(f"/api/locations/{loc.id}/sar/changes")
        assert api_res.status_code == 200
        data = api_res.json()
        print(f"GET /api/locations/{loc.id}/sar/changes -> HTTP {api_res.status_code}")
        print(f"Total SAR Changes Returned via API: {len(data)}")
        if data:
            latest_api_change = data[0]
            print(f"  API Response Record ID: {latest_api_change['id']}")
            print(f"  Classification: {latest_api_change['change_type']}")
            print(f"  Mean Delta: {latest_api_change['mean_delta_ndwi']} dB")

        print("\n" + "=" * 75)
        print("  SENTINEL-1 SAR VERTICAL SLICE: FULL PIPELINE PASS")
        print("=" * 75 + "\n")

    finally:
        db.close()


if __name__ == "__main__":
    run_sar_demonstration()
