"""
satguard/ingestion/sentinel1_discovery.py
Phase 2.1: Sentinel-1 Observation Discovery & Registry Engine.
Performs catalog search, AOI intersection, metadata normalization, quality filtering,
freshness verification, and duplicate-safe database registration for Sentinel-1 GRD.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from shapely.geometry import shape, Polygon

from satguard.config import settings
from satguard.models.entities import CriticalLocation, SatelliteObservation
from satguard.providers.copernicus import CopernicusSatelliteProvider
from satguard.geospatial.aoi import create_circular_aoi

logger = logging.getLogger("satguard.sentinel1.discovery")


class Sentinel1ObservationMetadata(BaseModel):
    """
    Standardized, authoritative metadata model for Sentinel-1 SAR products.
    """
    product_id: str
    mission: str = "Sentinel-1"
    acquisition_time: datetime
    processing_level: str = "GRD"
    instrument_mode: str = "IW"
    polarizations: List[str] = Field(default_factory=lambda: ["VV", "VH"])
    orbit_direction: Optional[str] = None  # ASCENDING / DESCENDING
    relative_orbit: Optional[int] = None
    geometry: Dict[str, Any]
    provider: str = "Copernicus"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "mission": self.mission,
            "acquisition_time": self.acquisition_time.isoformat(),
            "processing_level": self.processing_level,
            "instrument_mode": self.instrument_mode,
            "polarizations": self.polarizations,
            "orbit_direction": self.orbit_direction,
            "relative_orbit": self.relative_orbit,
            "geometry": self.geometry,
            "provider": self.provider,
        }


class Sentinel1DiscoveryService:
    """
    Orchestrates discovery and validation of Sentinel-1 observations for critical locations.
    """

    def __init__(self, provider: Optional[CopernicusSatelliteProvider] = None):
        self.provider = provider or CopernicusSatelliteProvider(
            client_id=settings.CDSE_CLIENT_ID,
            client_secret=settings.CDSE_CLIENT_SECRET,
            s3_access_key=settings.CDSE_S3_ACCESS_KEY,
            s3_secret_key=settings.CDSE_S3_SECRET_KEY,
        )

    def get_latest_sentinel1_observation(
        self,
        db: Session,
        location_id: str,
    ) -> Optional[SatelliteObservation]:
        """
        Retrieves the most recent Sentinel-1 SAR observation recorded in the database for a location.
        """
        return (
            db.query(SatelliteObservation)
            .filter(
                SatelliteObservation.location_id == location_id,
                SatelliteObservation.sensor == "SAR-C",
            )
            .order_by(SatelliteObservation.acquisition_time.desc())
            .first()
        )

    def search_sentinel1_observations(
        self,
        db: Session,
        location_id: str,
        start_time: datetime,
        end_time: datetime,
        polarization: Optional[str] = None,  # e.g. "VV" or "VH"
        orbit_direction: Optional[str] = None,  # "ASCENDING" or "DESCENDING"
        acquisition_mode: Optional[str] = "IW",
    ) -> Dict[str, Any]:
        """
        Queries Copernicus Data Space catalog for Sentinel-1 GRD covering the location's AOI.
        Applies quality filtering and returns structured observation metadata.
        """
        location = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
        if not location:
            raise ValueError(f"Critical location with ID '{location_id}' not found.")

        # 1. Generate AOI using existing Phase 1 generator
        aoi_poly = create_circular_aoi(
            latitude=location.latitude,
            longitude=location.longitude,
            radius_m=location.radius_m,
        )

        logger.info(
            f"Querying Sentinel-1 STAC catalog for {location.name} "
            f"from {start_time.isoformat()} to {end_time.isoformat()}"
        )

        try:
            raw_features = self.provider.search_sentinel1_raw(
                geometry=aoi_poly,
                start_time=start_time,
                end_time=end_time,
                acquisition_mode=acquisition_mode,
                orbit_direction=orbit_direction,
                limit=30,
            )
        except Exception as e:
            logger.error(f"Sentinel-1 search failed: {e}")
            raise ConnectionError(f"Copernicus Sentinel-1 catalog error: {e}")

        accepted: List[Sentinel1ObservationMetadata] = []
        rejected: List[Dict[str, Any]] = []

        for feat in raw_features:
            product_id = feat.get("id")
            props = feat.get("properties", {})
            geom_data = feat.get("geometry")

            # ------------------------------------------------------------------
            # QUALITY FILTER 1: Metadata Validity
            # ------------------------------------------------------------------
            if not product_id or not geom_data or "datetime" not in props:
                rejected.append({
                    "product_id": product_id or "UNKNOWN",
                    "reason": "Invalid product metadata: missing product_id, geometry, or datetime",
                })
                continue

            try:
                acq_time = datetime.fromisoformat(props["datetime"].replace("Z", "+00:00"))
            except Exception:
                rejected.append({
                    "product_id": product_id,
                    "reason": "Unparseable acquisition datetime timestamp",
                })
                continue

            # ------------------------------------------------------------------
            # QUALITY FILTER 2: AOI Intersection Verification
            # ------------------------------------------------------------------
            try:
                footprint_shape = shape(geom_data)
                if not footprint_shape.intersects(aoi_poly):
                    rejected.append({
                        "product_id": product_id,
                        "reason": "Product footprint does not intersect monitored AOI",
                    })
                    continue
            except Exception as e:
                rejected.append({
                    "product_id": product_id,
                    "reason": f"Corrupt geometric footprint: {e}",
                })
                continue

            # ------------------------------------------------------------------
            # QUALITY FILTER 3: Instrument Mode & Processing Level Check
            # ------------------------------------------------------------------
            mode = props.get("sar:instrument_mode", "IW")
            if acquisition_mode and mode.upper() != acquisition_mode.upper():
                rejected.append({
                    "product_id": product_id,
                    "reason": f"Instrument mode '{mode}' does not match requested mode '{acquisition_mode}'",
                })
                continue

            # ------------------------------------------------------------------
            # QUALITY FILTER 4: Polarization Requirements
            # ------------------------------------------------------------------
            polars = props.get("sar:polarizations", ["VV", "VH"])
            if polarization and polarization.upper() not in [p.upper() for p in polars]:
                rejected.append({
                    "product_id": product_id,
                    "reason": f"Required polarization '{polarization}' not available in product polarizations {polars}",
                })
                continue

            # ------------------------------------------------------------------
            # QUALITY FILTER 5: Orbit Direction (Optional filter)
            # ------------------------------------------------------------------
            feat_orbit = props.get("sat:orbit_state", "").upper()
            if orbit_direction and feat_orbit and orbit_direction.upper() != feat_orbit:
                rejected.append({
                    "product_id": product_id,
                    "reason": f"Orbit direction '{feat_orbit}' does not match requested '{orbit_direction.upper()}'",
                })
                continue

            # Normalize relative orbit number
            rel_orbit = props.get("sat:relative_orbit")
            if rel_orbit is not None:
                try:
                    rel_orbit = int(rel_orbit)
                except ValueError:
                    rel_orbit = None

            obs_meta = Sentinel1ObservationMetadata(
                product_id=product_id,
                mission="Sentinel-1",
                acquisition_time=acq_time,
                processing_level="GRD",
                instrument_mode=mode,
                polarizations=polars,
                orbit_direction=feat_orbit or None,
                relative_orbit=rel_orbit,
                geometry=geom_data,
                provider="Copernicus",
            )
            accepted.append(obs_meta)

        # Sort by acquisition time descending (newest first)
        accepted.sort(key=lambda x: x.acquisition_time, reverse=True)

        return {
            "location_id": location_id,
            "total_found": len(raw_features),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted_observations": accepted,
            "rejected_observations": rejected,
        }

    def check_freshness(
        self,
        db: Session,
        location_id: str,
        lookback_days: int = 15,
        polarization: Optional[str] = None,
        orbit_direction: Optional[str] = None,
        acquisition_mode: Optional[str] = "IW",
        auto_persist: bool = True,
    ) -> Dict[str, Any]:
        """
        Implements Step 8 Freshness Check:
        1. Reads latest successfully recorded Sentinel-1 observation.
        2. Queries Copernicus catalog after that timestamp.
        3. Returns NO_NEW_OBSERVATION or NEW_OBSERVATION_AVAILABLE.
        4. Persists new products without duplicates.
        """
        location = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
        if not location:
            raise ValueError(f"Critical location with ID '{location_id}' not found.")

        latest_obs = self.get_latest_sentinel1_observation(db, location_id)
        now = datetime.now(timezone.utc)

        if latest_obs and latest_obs.acquisition_time:
            # Query strictly after latest observation
            start_time = latest_obs.acquisition_time + timedelta(seconds=1)
            latest_time_str = latest_obs.acquisition_time.isoformat()
        else:
            start_time = now - timedelta(days=lookback_days)
            latest_time_str = None

        search_result = self.search_sentinel1_observations(
            db=db,
            location_id=location_id,
            start_time=start_time,
            end_time=now,
            polarization=polarization,
            orbit_direction=orbit_direction,
            acquisition_mode=acquisition_mode,
        )

        accepted_list = search_result["accepted_observations"]

        # Filter out observations that already exist in database (Uniqueness Check)
        existing_ids = set(
            p[0]
            for p in db.query(SatelliteObservation.product_id)
            .filter(
                SatelliteObservation.location_id == location_id,
                SatelliteObservation.sensor == "SAR-C",
            )
            .all()
        )

        truly_new = [obs for obs in accepted_list if obs.product_id not in existing_ids]

        if not truly_new:
            return {
                "location_id": location_id,
                "sensor": "SENTINEL-1",
                "status": "NO_NEW_OBSERVATION",
                "latest_processed": latest_time_str,
                "checked_at": now.isoformat(),
                "new_observations": [],
            }

        # Persist new observations to database if auto_persist is True
        persisted_records: List[Dict[str, Any]] = []
        if auto_persist:
            for obs_meta in truly_new:
                record_id = f"obs-s1-{obs_meta.product_id[:40]}-{int(now.timestamp())}"
                new_record = SatelliteObservation(
                    id=record_id,
                    location_id=location_id,
                    product_id=obs_meta.product_id,
                    collection="sentinel-1-grd",
                    sensor="SAR-C",
                    acquisition_time=obs_meta.acquisition_time,
                    cloud_cover=0.0,
                    quality_status="NEW_OBSERVATION_AVAILABLE",
                    raw_metadata=obs_meta.model_dump_json(),
                )
                db.add(new_record)
                persisted_records.append(obs_meta.to_dict())
            db.commit()
        else:
            persisted_records = [obs.to_dict() for obs in truly_new]

        return {
            "location_id": location_id,
            "sensor": "SENTINEL-1",
            "status": "NEW_OBSERVATION_AVAILABLE",
            "latest_processed": latest_time_str,
            "checked_at": now.isoformat(),
            "new_observations_count": len(truly_new),
            "new_observations": persisted_records,
        }
