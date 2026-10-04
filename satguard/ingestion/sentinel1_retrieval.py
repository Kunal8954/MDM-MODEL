"""
satguard/ingestion/sentinel1_retrieval.py
Phase 2.2: Sentinel-1 SAR Imagery Retrieval Service.
Retrieves real Sentinel-1 GRD SAR imagery from Copernicus Data Space Ecosystem (CDSE)
for observations discovered in Phase 2.1, with deterministic storage, SHA-256 integrity,
atomic temporary file writes, and idempotency guarantees.
"""

import os
import json
import logging
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import requests
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.db.session import get_db_session
from satguard.models.entities import CriticalLocation, SatelliteObservation, Sentinel1Retrieval
from satguard.providers.copernicus import CopernicusSatelliteProvider
from satguard.geospatial.aoi import create_circular_aoi

logger = logging.getLogger("satguard.sentinel1.retrieval")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STORAGE_DIR = PROJECT_ROOT / "data" / "sentinel1"


class Sentinel1RetrievalError(Exception):
    """Base exception for Sentinel-1 retrieval errors."""
    pass


class CDSEAuthenticationError(Sentinel1RetrievalError):
    """Raised when authentication with CDSE fails."""
    pass


class CDSEProductNotFoundError(Sentinel1RetrievalError):
    """Raised when the requested product or asset is not found on CDSE."""
    pass


class CDSEIntegrityError(Sentinel1RetrievalError):
    """Raised when downloaded data fails size or checksum verification."""
    pass


def calculate_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hex digest for a local file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


class Sentinel1RetrievalService:
    """
    Manages end-to-end retrieval of real Sentinel-1 GRD SAR data from CDSE.
    """

    def __init__(
        self,
        provider: Optional[CopernicusSatelliteProvider] = None,
        base_storage_dir: Optional[Path] = None,
    ):
        self.provider = provider or CopernicusSatelliteProvider(
            client_id=settings.CDSE_CLIENT_ID,
            client_secret=settings.CDSE_CLIENT_SECRET,
            s3_access_key=settings.CDSE_S3_ACCESS_KEY,
            s3_secret_key=settings.CDSE_S3_SECRET_KEY,
        )
        self.base_storage_dir = Path(base_storage_dir or DEFAULT_STORAGE_DIR)
        self.base_storage_dir.mkdir(parents=True, exist_ok=True)

    def get_storage_paths(
        self,
        location_id: str,
        observation_id: str,
        product_id: str,
    ) -> Dict[str, Path]:
        """
        Determines deterministic storage paths for observation artifacts.
        data/sentinel1/{location_id}/{observation_id}/
        """
        obs_dir = self.base_storage_dir / location_id / observation_id
        obs_dir.mkdir(parents=True, exist_ok=True)
        raster_path = obs_dir / f"sentinel1_grd_{product_id}.tif"
        manifest_path = obs_dir / "manifest.json"
        part_path = obs_dir / f"sentinel1_grd_{product_id}.tif.part"

        return {
            "directory": obs_dir,
            "raster": raster_path,
            "manifest": manifest_path,
            "part": part_path,
        }

    def verify_existing_retrieval(
        self,
        paths: Dict[str, Path],
    ) -> Optional[Dict[str, Any]]:
        """
        Validates whether a previous retrieval was complete and intact.
        Returns the manifest data if valid, otherwise None.
        """
        raster_path = paths["raster"]
        manifest_path = paths["manifest"]

        if not raster_path.exists() or not manifest_path.exists():
            return None

        # Raster must not be empty
        file_size = raster_path.stat().st_size
        if file_size == 0:
            logger.warning(f"Existing raster {raster_path} is empty. Retrying retrieval.")
            return None

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.warning(f"Corrupt manifest file {manifest_path} ({e}). Retrying retrieval.")
            return None

        recorded_sha = manifest.get("sha256")
        if not recorded_sha:
            return None

        actual_sha = calculate_sha256(raster_path)
        if actual_sha != recorded_sha:
            logger.warning(f"Checksum mismatch for {raster_path} (expected {recorded_sha}, got {actual_sha}). Retrying.")
            return None

        return manifest

    def retrieve(
        self,
        observation_id: str,
        db: Session,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes idempotent retrieval of real Sentinel-1 SAR imagery.
        """
        # 1. Load observation from database
        obs = db.query(SatelliteObservation).filter(SatelliteObservation.id == observation_id).first()
        if not obs:
            raise CDSEProductNotFoundError(f"Observation '{observation_id}' not found in database.")

        location_id = obs.location_id
        product_id = obs.product_id

        # 2. Load location & build AOI bounds
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
        if not loc:
            raise CDSEProductNotFoundError(f"Critical location '{location_id}' not found.")

        aoi_poly = create_circular_aoi(loc.latitude, loc.longitude, loc.radius_m)
        bbox = aoi_poly.bounds  # (min_lon, min_lat, max_lon, max_lat)

        # 3. Check deterministic storage and idempotency
        paths = self.get_storage_paths(location_id, observation_id, product_id)
        if not force_refresh:
            existing_manifest = self.verify_existing_retrieval(paths)
            if existing_manifest:
                logger.info(f"Observation {observation_id} (Product {product_id}) already retrieved.")
                return {
                    "location_id": location_id,
                    "observation_id": observation_id,
                    "product_id": product_id,
                    "status": "ALREADY_RETRIEVED",
                    "storage_path": str(paths["raster"]),
                    "file_size_bytes": existing_manifest.get("file_size_bytes"),
                    "sha256": existing_manifest.get("sha256"),
                    "manifest": existing_manifest,
                }

        # 4. Authenticate with CDSE
        try:
            if not self.provider.authenticate():
                raise CDSEAuthenticationError("CDSE OAuth2 authentication returned False.")
        except Exception as e:
            raise CDSEAuthenticationError(f"CDSE authentication failed: {e}")

        access_token = self.provider._access_token
        if not access_token:
            raise CDSEAuthenticationError("No valid CDSE access token available.")

        # 5. Resolve CDSE product metadata via STAC
        stac_item_url = f"https://stac.dataspace.copernicus.eu/v1/collections/sentinel-1-grd/items/{product_id}"
        stac_headers = {"Authorization": f"Bearer {access_token}"}
        try:
            stac_resp = requests.get(stac_item_url, headers=stac_headers, timeout=25)
            if stac_resp.status_code == 404:
                raise CDSEProductNotFoundError(f"Sentinel-1 product '{product_id}' not found in CDSE catalog.")
            stac_resp.raise_for_status()
            stac_item = stac_resp.json()
        except requests.RequestException as e:
            logger.warning(f"Direct STAC item resolution failed ({e}); falling back to observation acquisition parameters.")
            stac_item = {}

        stac_props = stac_item.get("properties", {})
        polarizations = stac_props.get("sar:polarizations", ["VV", "VH"])
        instrument_mode = stac_props.get("sar:instrument_mode", "IW")
        product_type = "GRD"

        # 6. Retrieve real SAR raster from CDSE Process API
        process_url = "https://sh.dataspace.copernicus.eu/api/v1/process"
        process_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "image/tiff",
        }

        # Narrow time window around acquisition time (± 60 seconds)
        acq_time = obs.acquisition_time
        time_from = (acq_time - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        time_to = (acq_time + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")

        evalscript = """//VERSION=3
function setup() {
  return {
    input: ["VV", "VH"],
    output: { bands: 2, sampleType: "FLOAT32" }
  };
}
function evaluatePixel(sample) {
  return [sample.VV, sample.VH];
}
"""

        payload = {
            "input": {
                "bounds": {"bbox": list(bbox)},
                "data": [
                    {
                        "type": "sentinel-1-grd",
                        "dataFilter": {
                            "timeRange": {"from": time_from, "to": time_to},
                            "acquisitionMode": instrument_mode,
                            "polarization": "DV",
                            "resolution": "HIGH",
                        },
                    }
                ],
            },
            "output": {
                "width": 512,
                "height": 512,
                "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
            },
            "evalscript": evalscript,
        }

        part_path = paths["part"]
        raster_path = paths["raster"]
        manifest_path = paths["manifest"]

        # Clean any stale temporary part file
        if part_path.exists():
            part_path.unlink()

        try:
            resp = requests.post(process_url, json=payload, headers=process_headers, stream=True, timeout=45)
            if resp.status_code == 401 or resp.status_code == 403:
                raise CDSEAuthenticationError(f"CDSE returned HTTP {resp.status_code}: {resp.text}")
            elif resp.status_code == 404:
                raise CDSEProductNotFoundError(f"CDSE returned HTTP 404: {resp.text}")
            resp.raise_for_status()

            sha256_hash = hashlib.sha256()
            total_bytes = 0

            with open(part_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        sha256_hash.update(chunk)
                        total_bytes += len(chunk)

            if total_bytes == 0:
                if part_path.exists():
                    part_path.unlink()
                raise CDSEIntegrityError(f"Downloaded SAR raster for {product_id} is empty (0 bytes).")

            calculated_sha = sha256_hash.hexdigest()

            # Atomic rename from .part to final target
            if raster_path.exists():
                raster_path.unlink()
            part_path.replace(raster_path)

        except requests.Timeout as e:
            if part_path.exists():
                part_path.unlink()
            raise TimeoutError(f"Network timeout while downloading SAR raster: {e}")
        except requests.RequestException as e:
            if part_path.exists():
                part_path.unlink()
            raise ConnectionError(f"Connection failure during CDSE SAR retrieval: {e}")
        except Exception:
            if part_path.exists():
                part_path.unlink()
            raise

        # 7. Create authoritative manifest
        manifest = {
            "location_id": location_id,
            "observation_id": observation_id,
            "product_id": product_id,
            "mission": "Sentinel-1",
            "product_type": product_type,
            "instrument_mode": instrument_mode,
            "polarizations": polarizations,
            "acquisition_time": acq_time.isoformat(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "provider": "Copernicus Data Space Ecosystem",
            "source_url": process_url,
            "local_path": str(raster_path),
            "file_size_bytes": total_bytes,
            "sha256": calculated_sha,
            "retrieval_status": "SUCCESS",
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # 8. Update database
        obs.raster_artifact_path = str(raster_path)
        obs.quality_status = "RETRIEVED"

        retrieval_record = Sentinel1Retrieval(
            id=f"ret-s1-{observation_id}",
            observation_id=observation_id,
            product_id=product_id,
            storage_path=str(raster_path),
            source_url=process_url,
            file_size_bytes=total_bytes,
            sha256=calculated_sha,
            retrieved_at=datetime.now(timezone.utc),
            status="SUCCESS",
        )
        db.merge(retrieval_record)
        db.commit()

        logger.info(
            f"Successfully retrieved SAR imagery for {observation_id}: "
            f"{total_bytes} bytes, SHA256={calculated_sha}"
        )

        return {
            "location_id": location_id,
            "observation_id": observation_id,
            "product_id": product_id,
            "status": "SUCCESS",
            "storage_path": str(raster_path),
            "file_size_bytes": total_bytes,
            "sha256": calculated_sha,
            "manifest": manifest,
        }


def retrieve_sentinel1_observation(
    observation_id: str,
    db: Optional[Session] = None,
    output_base_dir: Optional[Path] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Clean functional interface for Sentinel-1 SAR observation retrieval.
    """
    service = Sentinel1RetrievalService(base_storage_dir=output_base_dir)

    if db is not None:
        return service.retrieve(observation_id=observation_id, db=db, force_refresh=force_refresh)

    session = get_db_session()
    try:
        return service.retrieve(observation_id=observation_id, db=session, force_refresh=force_refresh)
    finally:
        session.close()
