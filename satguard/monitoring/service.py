"""
satguard/monitoring/service.py
Core Monitoring Service for SATGUARD.
Iterates over enabled critical locations, audits catalog freshness,
enforces zero wasted bandwidth, and triggers processing pipelines only on new valid observations.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from satguard.db.session import get_db_session
from satguard.models.entities import CriticalLocation, SatelliteObservation
from satguard.ingestion.detector import ObservationDetector
from satguard.processing.pipeline import MonitoringPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("satguard.monitoring")


class MonitoringService:
    def __init__(
        self,
        detector: Optional[ObservationDetector] = None,
        pipeline: Optional[MonitoringPipeline] = None,
    ):
        self.detector = detector or ObservationDetector()
        self.pipeline = pipeline or MonitoringPipeline()

    def run_check_cycle(
        self,
        db: Session,
        location_id: Optional[str] = None,
        auto_process: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Executes an observation monitoring cycle across all active critical locations.
        """
        query = db.query(CriticalLocation).filter(CriticalLocation.monitoring_enabled == True)
        if location_id:
            query = query.filter(CriticalLocation.id == location_id)

        locations = query.all()
        logger.info(f"Initiating surveillance check across {len(locations)} critical locations...")

        results: List[Dict[str, Any]] = []

        for loc in locations:
            logger.info(f"--- Checking Location: {loc.name} ({loc.id}) ---")
            check_res = self.detector.check_location(db=db, location=loc)

            cycle_entry = {
                "location_id": loc.id,
                "location_name": loc.name,
                "check_result": check_res,
                "processed": False,
                "change_detected": None,
            }

            if check_res.get("status") == "NEW_OBSERVATION_AVAILABLE" and auto_process:
                obs_id = check_res.get("observation_id")
                obs = db.query(SatelliteObservation).filter(SatelliteObservation.id == obs_id).first()
                if obs:
                    logger.info(f"Processing newly discovered observation {obs.product_id}...")
                    proc_res = self.pipeline.process_observation(db=db, location=loc, observation=obs)
                    cycle_entry["processed"] = True
                    cycle_entry["processing_result"] = proc_res
                    cycle_entry["change_detected"] = proc_res.get("change_detection")

            results.append(cycle_entry)

        return results


def run_monitoring_cli(location_id: Optional[str] = None):
    session = get_db_session()
    service = MonitoringService()
    try:
        results = service.run_check_cycle(session, location_id=location_id)
        print("\n" + "=" * 70)
        print("SATGUARD MONITORING CYCLE REPORT")
        print("=" * 70)
        for r in results:
            name = r["location_name"]
            status = r["check_result"].get("status")
            print(f"Location: {name:<35s} | Status: {status}")
            if r.get("processed"):
                cd = r.get("change_detected")
                if cd:
                    print(f"  --> CHANGE DETECTED: {cd['change_type']} (Delta NDWI: {cd['mean_delta_ndwi']}, Area Delta: {cd['water_change_area_m2']} m²)")
                else:
                    print("  --> Baseline observation registered. Awaiting next revisit for differential comparison.")
        print("=" * 70 + "\n")
    finally:
        session.close()


if __name__ == "__main__":
    run_monitoring_cli()
