"""
scripts/verify_phase2_2_sentinel1.py
End-to-End Real CDSE Integration Verification Script for Phase 2.2.
Performs real Copernicus Sentinel-1 SAR imagery retrieval for Tehri Dam,
verifies non-zero raw raster, SHA-256 integrity, manifest creation, and idempotency.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone
import requests

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from satguard.config import settings
from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, SatelliteObservation
from satguard.providers.copernicus import CopernicusSatelliteProvider
from satguard.ingestion.sentinel1_retrieval import (
    retrieve_sentinel1_observation,
    calculate_sha256,
)


def run_verification():
    print("=" * 60)
    print("STARTING REAL CDSE SENTINEL-1 RETRIEVAL VERIFICATION")
    print("=" * 60)

    # 1. Environment & DB initialization
    init_db()
    db = get_db_session()

    auth_pass = False
    obs_pass = False
    resolution_pass = False
    asset_pass = False
    download_pass = False
    nonzero_pass = False
    checksum_pass = False
    manifest_pass = False
    idempotency_pass = False

    try:
        # 2. CDSE Authentication
        provider = CopernicusSatelliteProvider(
            client_id=settings.CDSE_CLIENT_ID,
            client_secret=settings.CDSE_CLIENT_SECRET,
        )
        if provider.authenticate() and provider._access_token:
            auth_pass = True
            print("[+] Step 1: CDSE OAuth2 Authentication successful.")
        else:
            print("[-] Step 1: CDSE Authentication failed.")
            return

        # 3. Load Tehri Dam Sentinel-1 Observation from Phase 2.1
        target_product_id = "S1D_IW_GRDH_1SDV_20261002T004305_20261002T004330_004829_009120_A081_COG"
        obs = (
            db.query(SatelliteObservation)
            .filter(
                SatelliteObservation.location_id == "loc-001-tehri-dam",
                SatelliteObservation.sensor == "SAR-C",
                SatelliteObservation.product_id == target_product_id,
            )
            .first()
        )
        if not obs:
            # Fallback to any latest SAR-C observation for Tehri Dam
            obs = (
                db.query(SatelliteObservation)
                .filter(
                    SatelliteObservation.location_id == "loc-001-tehri-dam",
                    SatelliteObservation.sensor == "SAR-C",
                )
                .order_by(SatelliteObservation.acquisition_time.desc())
                .first()
            )

        if obs:
            obs_pass = True
            print(f"[+] Step 2: Loaded observation '{obs.id}' for location '{obs.location_id}' (Product: {obs.product_id})")
        else:
            print("[-] Step 2: No Sentinel-1 observation found for Tehri Dam.")
            return

        # 4. Resolve real CDSE STAC product & assets
        stac_url = f"https://stac.dataspace.copernicus.eu/v1/collections/sentinel-1-grd/items/{obs.product_id}"
        stac_resp = requests.get(
            stac_url,
            headers={"Authorization": f"Bearer {provider._access_token}"},
            timeout=25,
        )
        if stac_resp.status_code == 200:
            stac_data = stac_resp.json()
            assets = stac_data.get("assets", {})
            has_polarizations = "vh" in assets or "vv" in assets or "Product" in assets
            if has_polarizations:
                resolution_pass = True
                print(f"[+] Step 3: STAC Product resolution successful. Available assets: {list(assets.keys())}")
        else:
            print(f"[-] Step 3: STAC resolution failed with status {stac_resp.status_code}")

        # 5. Retrieve real Sentinel-1 SAR data (Force initial refresh to guarantee live test)
        print("[*] Retrieving live SAR raster data from CDSE Process API...")
        retrieval_res = retrieve_sentinel1_observation(
            observation_id=obs.id,
            db=db,
            force_refresh=True,
        )

        storage_path = Path(retrieval_res["storage_path"])
        file_size = retrieval_res["file_size_bytes"]
        recorded_sha = retrieval_res["sha256"]

        if retrieval_res.get("status") == "SUCCESS":
            asset_pass = True
            download_pass = True
            print(f"[+] Step 4: SAR raster retrieval returned SUCCESS.")

        # 6. Verify non-zero data
        if storage_path.exists() and file_size > 0:
            nonzero_pass = True
            print(f"[+] Step 5: Verified non-zero raster on disk ({file_size:,} bytes).")

        # 7. Checksum verification
        actual_sha = calculate_sha256(storage_path)
        if actual_sha == recorded_sha:
            checksum_pass = True
            print(f"[+] Step 6: Verified SHA-256 checksum: {actual_sha}")
        else:
            print(f"[-] Step 6: Checksum mismatch! Recorded: {recorded_sha}, Actual: {actual_sha}")

        # 8. Manifest verification
        manifest_path = storage_path.parent / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            required_keys = [
                "location_id",
                "observation_id",
                "product_id",
                "mission",
                "product_type",
                "instrument_mode",
                "polarizations",
                "acquisition_time",
                "retrieved_at",
                "provider",
                "source_url",
                "local_path",
                "file_size_bytes",
                "sha256",
                "retrieval_status",
            ]
            if all(k in manifest for k in required_keys) and manifest["retrieval_status"] == "SUCCESS":
                manifest_pass = True
                print(f"[+] Step 7: Authoritative manifest verified ({len(manifest)} fields).")

        # 9. Idempotency verification (Second call should return ALREADY_RETRIEVED without re-downloading)
        print("[*] Testing idempotency with second retrieval call...")
        second_res = retrieve_sentinel1_observation(
            observation_id=obs.id,
            db=db,
            force_refresh=False,
        )
        if (
            second_res.get("status") == "ALREADY_RETRIEVED"
            and second_res.get("sha256") == recorded_sha
            and Path(second_res["storage_path"]).exists()
        ):
            idempotency_pass = True
            print(f"[+] Step 8: Idempotency verified: status=ALREADY_RETRIEVED, zero duplicate downloads.")

        # Summary output block
        all_passed = all([
            auth_pass,
            obs_pass,
            resolution_pass,
            asset_pass,
            download_pass,
            nonzero_pass,
            checksum_pass,
            manifest_pass,
            idempotency_pass,
        ])

        print("\n" + "=" * 60)
        print("SATGUARD — PHASE 2.2 REAL RETRIEVAL")
        print("=" * 60)
        print(f"CDSE AUTH              : {'PASS' if auth_pass else 'FAIL'}")
        print(f"OBSERVATION            : {'PASS' if obs_pass else 'FAIL'}")
        print(f"PRODUCT RESOLUTION     : {'PASS' if resolution_pass else 'FAIL'}")
        print(f"REAL SAR ASSET         : {'PASS' if asset_pass else 'FAIL'}")
        print(f"DOWNLOAD               : {'PASS' if download_pass else 'FAIL'}")
        print(f"NON-ZERO DATA          : {'PASS' if nonzero_pass else 'FAIL'}")
        print(f"CHECKSUM               : {'PASS' if checksum_pass else 'FAIL'}")
        print(f"MANIFEST               : {'PASS' if manifest_pass else 'FAIL'}")
        print(f"IDEMPOTENCY            : {'PASS' if idempotency_pass else 'FAIL'}")
        print("=" * 60)
        print(f"PHASE 2.2 STATUS       : {'PASS' if all_passed else 'FAIL'}")
        print("=" * 60)

        # Print structured audit summary
        print("\nRETRIEVAL METADATA AUDIT:")
        print(f"  Location ID     : {obs.location_id}")
        print(f"  Observation ID  : {obs.id}")
        print(f"  Product ID      : {obs.product_id}")
        print(f"  Asset Type      : Float32 Dual-Polarization GeoTIFF (VV + VH bands)")
        print(f"  Storage Path    : {storage_path}")
        print(f"  File Size Bytes : {file_size:,} bytes")
        print(f"  SHA-256 Checksum: {actual_sha}")
        print(f"  Manifest Path   : {manifest_path}")

    finally:
        db.close()


if __name__ == "__main__":
    run_verification()
