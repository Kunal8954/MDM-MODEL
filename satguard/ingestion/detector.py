"""
satguard/ingestion/detector.py
Zero-Wasted-Bandwidth Observation Detection & Ingestion Engine.
Determines whether fresh satellite observations exist for a monitored Critical Location.
Never downloads imagery if no new observation exists.
Never fabricates observations.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.models.entities import CriticalLocation, SatelliteObservation
from satguard.providers.copernicus import CopernicusSatelliteProvider
from satguard.geospatial.aoi import create_circular_aoi, create_bbox_from_point

logger = logging.getLogger("satguard.ingestion")


class ObservationDetector:
    """
    Evaluates catalog freshness and enforces the observation state machine:
    - NO_NEW_OBSERVATION
    - NEW_OBSERVATION_AVAILABLE
    - QUALITY_REJECTED
    - DATA_UNAVAILABLE
    - ERROR
    """

    def __init__(self, provider: Optional[CopernicusSatelliteProvider] = None):
        self.provider = provider or CopernicusSatelliteProvider(
            client_id=settings.CDSE_CLIENT_ID,
            client_secret=settings.CDSE_CLIENT_SECRET,
            s3_access_key=settings.CDSE_S3_ACCESS_KEY,
            s3_secret_key=settings.CDSE_S3_SECRET_KEY,
        )

    def check_location(
        self,
        db: Session,
        location: CriticalLocation,
        lookback_days: int = 15,
        max_cloud_cover: float = 25.0,
    ) -> Dict[str, Any]:
        """
        Queries spaceborne catalog for observations after the latest successfully processed acquisition.
        """
        logger.info(f"Checking catalog freshness for location: {location.name} ({location.id})")

        # 1. Fetch latest processed observation
        latest_obs = (
            db.query(SatelliteObservation)
            .filter(
                SatelliteObservation.location_id == location.id,
                SatelliteObservation.quality_status.in_(["ANALYSIS_COMPLETE", "NEW_OBSERVATION_AVAILABLE"]),
            )
            .order_by(SatelliteObservation.acquisition_time.desc())
            .first()
        )

        now = datetime.now(timezone.utc)
        if latest_obs and latest_obs.acquisition_time:
            # Query strictly after the last known observation
            start_time = latest_obs.acquisition_time + timedelta(seconds=1)
            last_obs_time_str = latest_obs.acquisition_time.isoformat()
        else:
            start_time = now - timedelta(days=lookback_days)
            last_obs_time_str = None

        # 2. Build AOI geometry and bounding box
        poly_aoi = create_circular_aoi(
            latitude=location.latitude,
            longitude=location.longitude,
            radius_m=location.radius_m,
        )

        try:
            # 3. Query space agency STAC catalog
            candidates = self.provider.search_observations(
                geometry=poly_aoi,
                start_time=start_time,
                end_time=now,
                collection="sentinel-2-l2a",
                max_cloud_cover=100.0,  # Query all to perform strict quality evaluation
                limit=10,
            )
        except Exception as e:
            logger.error(f"Catalog query failed for {location.name}: {e}")
            return {
                "location_id": location.id,
                "status": "DATA_UNAVAILABLE",
                "message": f"Copernicus catalog error: {str(e)}",
                "last_observation": last_obs_time_str,
                "checked_at": now.isoformat(),
                "source": "COPERNICUS_SENTINEL_2",
            }

        # Filter out already existing products in database
        existing_product_ids = set(
            p[0]
            for p in db.query(SatelliteObservation.product_id)
            .filter(SatelliteObservation.location_id == location.id)
            .all()
        )

        new_candidates = [c for c in candidates if c.product_id not in existing_product_ids]

        if not new_candidates:
            logger.info(f"No new observations for {location.name}. Bandwidth saved.")
            return {
                "location_id": location.id,
                "status": "NO_NEW_OBSERVATION",
                "last_observation": last_obs_time_str,
                "checked_at": now.isoformat(),
                "source": "COPERNICUS_SENTINEL_2",
            }

        # 4. Sort new candidates by acquisition time descending (latest first)
        new_candidates.sort(key=lambda x: x.acquisition_time, reverse=True)
        selected = new_candidates[0]

        # 5. Quality Control evaluation
        cloud_cover = selected.cloud_cover or 0.0
        if cloud_cover > max_cloud_cover:
            rejection_reason = f"Cloud cover {cloud_cover:.1f}% exceeds maximum threshold {max_cloud_cover:.1f}%"
            logger.warning(f"Observation {selected.product_id} rejected: {rejection_reason}")

            # Persist rejected observation record to audit log
            rejected_obs = SatelliteObservation(
                id=f"obs-{selected.product_id[:40]}-{int(now.timestamp())}",
                location_id=location.id,
                product_id=selected.product_id,
                collection=selected.collection,
                sensor=selected.sensor,
                acquisition_time=selected.acquisition_time,
                cloud_cover=cloud_cover,
                quality_status="QUALITY_REJECTED",
                rejection_reason=rejection_reason,
            )
            db.add(rejected_obs)
            db.commit()

            return {
                "location_id": location.id,
                "status": "QUALITY_REJECTED",
                "product_id": selected.product_id,
                "acquisition_time": selected.acquisition_time.isoformat(),
                "cloud_cover": cloud_cover,
                "rejection_reason": rejection_reason,
                "last_observation": last_obs_time_str,
                "checked_at": now.isoformat(),
                "source": "COPERNICUS_SENTINEL_2",
            }

        # Valid new observation available
        new_obs = SatelliteObservation(
            id=f"obs-{selected.product_id[:40]}-{int(now.timestamp())}",
            location_id=location.id,
            product_id=selected.product_id,
            collection=selected.collection,
            sensor=selected.sensor,
            acquisition_time=selected.acquisition_time,
            cloud_cover=cloud_cover,
            quality_status="NEW_OBSERVATION_AVAILABLE",
        )
        db.add(new_obs)
        db.commit()

        logger.info(f"New valid observation discovered: {selected.product_id} (Cloud: {cloud_cover}%)")
        return {
            "location_id": location.id,
            "status": "NEW_OBSERVATION_AVAILABLE",
            "observation_id": new_obs.id,
            "product_id": selected.product_id,
            "acquisition_time": selected.acquisition_time.isoformat(),
            "cloud_cover": cloud_cover,
            "last_observation": last_obs_time_str,
            "checked_at": now.isoformat(),
            "source": "COPERNICUS_SENTINEL_2",
        }
