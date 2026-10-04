"""
satguard/monitoring/scheduler.py
Phase 7: Continuous Monitoring Scheduler.
Provides background scheduled orchestration for government-defined critical locations.
Identifies due locations, prevents overlapping runs, isolates failures, and respects
monitoring intervals without adding heavy distributed infrastructure.
"""

import time
import logging
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.db.session import get_db_session
from satguard.models.entities import CriticalLocation
from satguard.monitoring.schema import MonitoringTriggerTypeEnum
from satguard.monitoring.orchestrator import ContinuousMonitoringOrchestrator

logger = logging.getLogger("satguard.monitoring.scheduler")


class MonitoringScheduler:
    """
    Lightweight, reliable background scheduler for SATGUARD continuous monitoring.
    Periodically checks critical locations and triggers automated reassessment.
    """

    def __init__(
        self,
        orchestrator: Optional[ContinuousMonitoringOrchestrator] = None,
        db_session_factory=get_db_session,
        check_interval_seconds: float = 10.0,
    ):
        self.orchestrator = orchestrator or ContinuousMonitoringOrchestrator(db_session_factory=db_session_factory)
        self.db_session_factory = db_session_factory
        self.check_interval_seconds = check_interval_seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Starts the scheduler background thread."""
        with self._lock:
            if self.is_running:
                logger.info("MonitoringScheduler is already running.")
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._scheduler_loop,
                name="SATGUARD-MonitoringScheduler",
                daemon=True,
            )
            self._thread.start()
            logger.info("MonitoringScheduler background worker started.")

    def stop(self, timeout: float = 5.0) -> None:
        """Stops the scheduler background thread cleanly."""
        with self._lock:
            if not self.is_running:
                return

            logger.info("Stopping MonitoringScheduler background worker...")
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=timeout)
                self._thread = None
            logger.info("MonitoringScheduler background worker stopped.")

    def _scheduler_loop(self) -> None:
        """Main loop executed by the background thread."""
        logger.info(f"MonitoringScheduler loop initialized (check interval: {self.check_interval_seconds}s).")
        while not self._stop_event.is_set():
            try:
                self.poll_and_execute_due_locations()
            except Exception as e:
                logger.error(f"Unexpected error in scheduler loop: {e}", exc_info=True)

            # Sleep in small increments for responsive shutdown
            elapsed = 0.0
            step = 0.5
            while elapsed < self.check_interval_seconds and not self._stop_event.is_set():
                time.sleep(step)
                elapsed += step

    def get_due_locations(self, db: Session) -> List[CriticalLocation]:
        """
        Queries all critical locations that are due for a monitoring run:
        - monitoring_enabled is True
        - monitoring_status is 'ACTIVE'
        - next_scheduled_run is NULL or <= now_utc
        """
        now_utc = datetime.now(timezone.utc)
        all_enabled = (
            db.query(CriticalLocation)
            .filter(
                CriticalLocation.monitoring_enabled == True,
                CriticalLocation.monitoring_status == "ACTIVE",
            )
            .all()
        )

        due: List[CriticalLocation] = []
        for loc in all_enabled:
            if loc.next_scheduled_run is None:
                due.append(loc)
            else:
                next_run = loc.next_scheduled_run
                if next_run.tzinfo is None:
                    next_run = next_run.replace(tzinfo=timezone.utc)
                if next_run <= now_utc:
                    due.append(loc)

        return due

    def poll_and_execute_due_locations(self) -> List[Dict[str, Any]]:
        """
        Identifies and executes monitoring runs for all due locations.
        Enforces strict per-location failure isolation.
        """
        db = self.db_session_factory()
        results: List[Dict[str, Any]] = []
        try:
            due_locations = self.get_due_locations(db)
            if not due_locations:
                return results

            logger.info(f"MonitoringScheduler identified {len(due_locations)} due locations.")

            for location in due_locations:
                loc_id = location.id
                loc_name = location.name
                try:
                    logger.info(f"Triggering scheduled monitoring for location '{loc_name}' ({loc_id})...")
                    run = self.orchestrator.execute_monitoring_run(
                        location_id=loc_id,
                        trigger_type=MonitoringTriggerTypeEnum.SCHEDULED,
                        triggered_by="scheduler",
                        force=False,
                    )
                    results.append({
                        "location_id": loc_id,
                        "run_id": run.id,
                        "status": run.status,
                        "outcome": run.outcome_code,
                    })
                except Exception as loc_err:
                    # Strict failure isolation: one location failure must NOT stop other locations
                    logger.error(
                        f"Scheduler error processing location '{loc_name}' ({loc_id}): {loc_err}",
                        exc_info=True,
                    )
                    results.append({
                        "location_id": loc_id,
                        "error": str(loc_err),
                        "status": "FAILED",
                    })

            return results
        finally:
            db.close()

    def trigger_location_now(
        self,
        location_id: str,
        triggered_by: str = "manual_operator",
        force: bool = True,
    ) -> Any:
        """
        Direct manual trigger entrypoint for API and operator workflows.
        """
        return self.orchestrator.execute_monitoring_run(
            location_id=location_id,
            trigger_type=MonitoringTriggerTypeEnum.MANUAL,
            triggered_by=triggered_by,
            force=force,
        )


# Global scheduler singleton
scheduler = MonitoringScheduler()
