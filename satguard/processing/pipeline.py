"""
satguard/processing/pipeline.py
End-to-End Critical Location Observation Ingestion & Differential Change Pipeline.
Coordinates:
  Location -> Observation Ingestion -> Quality Gating -> NDWI Processing -> Baseline Comparison -> Persistence
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import numpy as np
import tifffile
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.models.entities import CriticalLocation, SatelliteObservation, ChangeDetection, ProcessingJob
from satguard.providers.copernicus import CopernicusSatelliteProvider
from satguard.geospatial.aoi import create_bbox_from_point, compute_bbox_area_m2
from satguard.processing.ndwi import NDWIProcessor
from satguard.processing.sar import SARProcessor
from satguard.processing.storage import storage

logger = logging.getLogger("satguard.pipeline")


class MonitoringPipeline:
    """
    Executes the scientific processing vertical slice for critical sovereign locations.
    Supports both Sentinel-2 Multispectral (NDWI) and Sentinel-1 SAR (Dual-Pol VV/VH).
    """

    def __init__(
        self,
        provider: Optional[CopernicusSatelliteProvider] = None,
        ndwi_processor: Optional[NDWIProcessor] = None,
        sar_processor: Optional[SARProcessor] = None,
    ):
        self.provider = provider or CopernicusSatelliteProvider(
            client_id=settings.CDSE_CLIENT_ID,
            client_secret=settings.CDSE_CLIENT_SECRET,
            s3_access_key=settings.CDSE_S3_ACCESS_KEY,
            s3_secret_key=settings.CDSE_S3_SECRET_KEY,
        )
        self.ndwi_processor = ndwi_processor or NDWIProcessor()
        self.sar_processor = sar_processor or SARProcessor()

    def process_observation(
        self,
        db: Session,
        location: CriticalLocation,
        observation: SatelliteObservation,
    ) -> Dict[str, Any]:
        """
        Processes a single observation: streams AOI Green & NIR bands, computes NDWI,
        stores GeoTIFF artifact, and compares with previous baseline if available.
        """
        logger.info(f"Processing observation {observation.id} for location {location.name}")

        # 1. Register processing job
        now = datetime.now(timezone.utc)
        job = ProcessingJob(
            id=f"job-{observation.id[:30]}-{int(now.timestamp())}",
            observation_id=observation.id,
            job_type="NDWI_WATER_BASELINE",
            status="RUNNING",
            started_at=now,
        )
        db.add(job)
        db.commit()

        # 2. Derive AOI bounding box and surface area
        bbox = create_bbox_from_point(location.latitude, location.longitude, location.radius_m)
        aoi_area_m2 = compute_bbox_area_m2(bbox)

        try:
            # 3. Stream real Green (B03) and NIR (B08) spectral bands from CDSE
            band_data = self.provider.retrieve_aoi_bands(
                bbox=bbox,
                acquisition_time=observation.acquisition_time,
                resolution_pixels=256,
            )
            green_arr = band_data["green_band"]
            nir_arr = band_data["nir_band"]

            # 4. Compute scientific NDWI matrix
            ndwi_arr = self.ndwi_processor.compute_ndwi(green_arr, nir_arr)

            # 5. Persist NDWI raster artifact to storage
            ndwi_path = storage.save_ndwi_raster(location.id, observation.id, ndwi_arr)
            observation.raster_artifact_path = ndwi_path
            observation.quality_status = "ANALYSIS_COMPLETE"
            observation.processing_time = datetime.now(timezone.utc)

            extent_metrics = self.ndwi_processor.calculate_water_extent(ndwi_arr, aoi_area_m2)

            # 6. Look for previous processed baseline observation (T_prev)
            previous_obs = (
                db.query(SatelliteObservation)
                .filter(
                    SatelliteObservation.location_id == location.id,
                    SatelliteObservation.id != observation.id,
                    SatelliteObservation.quality_status == "ANALYSIS_COMPLETE",
                    SatelliteObservation.acquisition_time < observation.acquisition_time,
                    SatelliteObservation.raster_artifact_path.isnot(None),
                )
                .order_by(SatelliteObservation.acquisition_time.desc())
                .first()
            )

            change_result = None

            if previous_obs and previous_obs.raster_artifact_path:
                logger.info(f"Comparing Current {observation.id} with Baseline {previous_obs.id}")
                
                # Load baseline NDWI from storage
                baseline_ndwi = tifffile.imread(previous_obs.raster_artifact_path)

                # Compute physical differential change
                change_metrics = self.ndwi_processor.compute_differential_change(
                    ndwi_t1=baseline_ndwi,
                    ndwi_t2=ndwi_arr,
                    total_aoi_area_m2=aoi_area_m2,
                )

                # Save differential mask GeoTIFF
                mask_path = storage.save_change_mask(
                    location_id=location.id,
                    baseline_id=previous_obs.id,
                    current_id=observation.id,
                    change_mask=change_metrics["delta_ndwi_array"],
                )

                # Persist change detection record
                change_record = ChangeDetection(
                    id=f"chg-{observation.id[:20]}-{previous_obs.id[:20]}",
                    location_id=location.id,
                    current_observation_id=observation.id,
                    baseline_observation_id=previous_obs.id,
                    change_type=change_metrics["change_type"],
                    baseline_water_area_m2=change_metrics["baseline_water_area_m2"],
                    current_water_area_m2=change_metrics["current_water_area_m2"],
                    water_change_area_m2=change_metrics["water_change_area_m2"],
                    water_change_percentage=change_metrics["water_change_percentage"],
                    mean_delta_ndwi=change_metrics["mean_delta_ndwi"],
                    max_delta_ndwi=change_metrics["max_delta_ndwi"],
                    change_mask_path=mask_path,
                    summary_notes=f"Calculated from real Sentinel-2 MSI L2A bands. Total AOI Area: {aoi_area_m2/1e6:.2f} km².",
                )
                db.add(change_record)
                change_result = change_record.to_dict()

            # Mark job complete
            job.status = "COMPLETED"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            return {
                "status": "SUCCESS",
                "observation_id": observation.id,
                "location_id": location.id,
                "water_extent": extent_metrics,
                "ndwi_raster_path": ndwi_path,
                "change_detection": change_result,
            }

        except Exception as e:
            logger.error(f"Processing failed for observation {observation.id}: {e}")
            job.status = "FAILED"
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            observation.quality_status = "PROCESSING_FAILED"
            observation.rejection_reason = str(e)
            db.commit()
            raise e

    def process_sar_observation(
        self,
        db: Session,
        location: CriticalLocation,
        observation: SatelliteObservation,
    ) -> Dict[str, Any]:
        """
        Processes a real Sentinel-1 SAR observation: streams dual-pol VV & VH bands,
        calibrates to decibels, saves 2-band GeoTIFF, and compares with baseline SAR observation if available.
        """
        logger.info(f"Processing Sentinel-1 SAR observation {observation.id} for location {location.name}")

        now = datetime.now(timezone.utc)
        job = ProcessingJob(
            id=f"job-sar-{observation.id[:30]}-{int(now.timestamp())}",
            observation_id=observation.id,
            job_type="SAR_DUAL_POL_BASELINE",
            status="RUNNING",
            started_at=now,
        )
        db.add(job)
        db.commit()

        bbox = create_bbox_from_point(location.latitude, location.longitude, location.radius_m)
        aoi_area_m2 = compute_bbox_area_m2(bbox)

        try:
            # 1. Retrieve real dual-polarization SAR arrays from CDSE
            sar_data = self.provider.retrieve_sar_bands(
                bbox=bbox,
                acquisition_time=observation.acquisition_time,
                resolution_pixels=256,
            )
            vv_linear = sar_data["vv_band"]
            vh_linear = sar_data["vh_band"]

            # 2. Calibrate backscatter to decibel scale
            vv_db = self.sar_processor.calibrate_to_db(vv_linear)
            vh_db = self.sar_processor.calibrate_to_db(vh_linear)

            # 3. Save calibrated dual-polarization GeoTIFF
            sar_raster_path = storage.save_sar_raster(location.id, observation.id, vv_db, vh_db)
            observation.raster_artifact_path = sar_raster_path
            observation.quality_status = "ANALYSIS_COMPLETE"
            observation.processing_time = datetime.now(timezone.utc)

            # 4. Search for prior processed baseline SAR observation
            previous_obs = (
                db.query(SatelliteObservation)
                .filter(
                    SatelliteObservation.location_id == location.id,
                    SatelliteObservation.id != observation.id,
                    SatelliteObservation.sensor == "SAR-C",
                    SatelliteObservation.quality_status == "ANALYSIS_COMPLETE",
                    SatelliteObservation.acquisition_time < observation.acquisition_time,
                    SatelliteObservation.raster_artifact_path.isnot(None),
                )
                .order_by(SatelliteObservation.acquisition_time.desc())
                .first()
            )

            change_result = None

            if previous_obs and previous_obs.raster_artifact_path:
                logger.info(f"Comparing Current SAR {observation.id} with Baseline SAR {previous_obs.id}")
                
                # Load baseline SAR 2-band raster (shape: 2, 256, 256)
                baseline_raster = tifffile.imread(previous_obs.raster_artifact_path)
                baseline_vv_db = baseline_raster[0]
                baseline_vh_db = baseline_raster[1]

                # Convert dB back to linear for processing
                baseline_vv_lin = 10.0 ** (baseline_vv_db / 10.0)
                baseline_vh_lin = 10.0 ** (baseline_vh_db / 10.0)

                # Compute SAR differential change
                sar_change = self.sar_processor.compute_sar_change(
                    vv_t1_linear=baseline_vv_lin,
                    vh_t1_linear=baseline_vh_lin,
                    vv_t2_linear=vv_linear,
                    vh_t2_linear=vh_linear,
                    total_aoi_area_m2=aoi_area_m2,
                )

                # Save differential SAR mask
                mask_path = storage.save_sar_change_mask(
                    location_id=location.id,
                    baseline_id=previous_obs.id,
                    current_id=observation.id,
                    delta_vv_db=sar_change["delta_vv_db_array"],
                )

                # Persist to change_detections table
                change_record = ChangeDetection(
                    id=f"chg-sar-{observation.id[:18]}-{previous_obs.id[:18]}",
                    location_id=location.id,
                    current_observation_id=observation.id,
                    baseline_observation_id=previous_obs.id,
                    change_type=sar_change["change_type"],
                    baseline_water_area_m2=0.0,
                    current_water_area_m2=0.0,
                    water_change_area_m2=sar_change["significant_change_area_m2"],
                    water_change_percentage=sar_change["significant_change_percentage"],
                    mean_delta_ndwi=sar_change["mean_delta_vv_db"],  # Stored in delta metric column
                    max_delta_ndwi=sar_change["max_delta_vv_db"],
                    change_mask_path=mask_path,
                    summary_notes=(
                        f"Sentinel-1 SAR C-band IW Dual-Pol. "
                        f"Baseline VV: {sar_change['t1_vv_mean_db']} dB, Current VV: {sar_change['t2_vv_mean_db']} dB. "
                        f"Mean Delta: {sar_change['mean_delta_vv_db']} dB. "
                        f"Significant Area Shift: {sar_change['significant_change_area_m2']:,.0f} m² ({sar_change['significant_change_percentage']}%)."
                    ),
                )
                db.add(change_record)
                change_result = change_record.to_dict()

            job.status = "COMPLETED"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()

            return {
                "status": "SUCCESS",
                "observation_id": observation.id,
                "location_id": location.id,
                "sensor": "SAR-C",
                "vv_mean_db": round(float(np.mean(vv_db)), 2),
                "vh_mean_db": round(float(np.mean(vh_db)), 2),
                "sar_raster_path": sar_raster_path,
                "change_detection": change_result,
            }

        except Exception as e:
            logger.error(f"SAR processing failed for observation {observation.id}: {e}")
            job.status = "FAILED"
            job.error_message = str(e)
            job.completed_at = datetime.now(timezone.utc)
            observation.quality_status = "PROCESSING_FAILED"
            observation.rejection_reason = str(e)
            db.commit()
            raise e
