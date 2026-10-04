"""
satguard/monitoring/orchestrator.py
Phase 7: Continuous Monitoring & Automated Reassessment Orchestrator.
Orchestrates the authoritative pipeline:
Critical Location -> Observation Discovery -> Incremental Processing ->
Evidence Fusion (P3) -> Risk Reassessment (P4) -> Groq Analyst (P5) ->
Alert Decision (P6) -> Audit Trail.

Guarantees:
- Phase 4 remains the ONLY authoritative risk engine.
- Phase 5 remains the authoritative evidence analyst.
- Phase 6 remains the authoritative alert engine.
- Safe idempotency: satellite observations and alert conditions are never duplicated.
- Concurrency control: database-backed locking per location.
- Failure isolation: failure in one location never disrupts other locations.
- Controlled bounded retries with backoff.
"""

import time
import json
import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.db.session import get_db_session
from satguard.models.entities import (
    CriticalLocation,
    SatelliteObservation,
    MonitoringRun,
    EvidenceSnapshot,
    RiskAssessment,
    AnalystReport as DBAnalystReport,
    Alert as DBAlert,
)
from satguard.monitoring.schema import (
    MonitoringRunStatusEnum,
    MonitoringTriggerTypeEnum,
    MonitoringStageEnum,
    MonitoringOutcomeCodeEnum,
)
from satguard.ingestion.sentinel1_discovery import Sentinel1DiscoveryService
from satguard.ingestion.detector import ObservationDetector
from satguard.processing.sar import SARProcessor
from satguard.processing.pipeline import MonitoringPipeline
from satguard.fusion.engine import EvidenceFusionEngine
from satguard.risk.engine import RiskAssessmentEngine
from satguard.analyst.engine import EvidenceAnalystEngine
from satguard.alert.engine import AlertDecisionEngine

logger = logging.getLogger("satguard.monitoring.orchestrator")


class ContinuousMonitoringOrchestrator:
    """
    Coordinates automated continuous monitoring and reassessment cycles.
    """

    def __init__(
        self,
        db_session_factory=get_db_session,
        s1_discovery: Optional[Sentinel1DiscoveryService] = None,
        s2_detector: Optional[ObservationDetector] = None,
        sar_processor: Optional[SARProcessor] = None,
        pipeline: Optional[MonitoringPipeline] = None,
        fusion_engine: Optional[EvidenceFusionEngine] = None,
        risk_engine: Optional[RiskAssessmentEngine] = None,
        analyst_engine: Optional[EvidenceAnalystEngine] = None,
        alert_engine: Optional[AlertDecisionEngine] = None,
    ):
        self.db_session_factory = db_session_factory
        self.s1_discovery = s1_discovery or Sentinel1DiscoveryService()
        self.s2_detector = s2_detector or ObservationDetector()
        self.sar_processor = sar_processor or SARProcessor()
        self.pipeline = pipeline or MonitoringPipeline()
        self.fusion_engine = fusion_engine or EvidenceFusionEngine()
        self.risk_engine = risk_engine or RiskAssessmentEngine()
        self.analyst_engine = analyst_engine or EvidenceAnalystEngine()
        self.alert_engine = alert_engine or AlertDecisionEngine()

    def _acquire_location_lock(
        self,
        db: Session,
        location_id: str,
        timeout_minutes: float = 30.0,
    ) -> Optional[MonitoringRun]:
        """
        Database-backed concurrency control.
        Verifies if an active RUNNING run exists for the location.
        Handles stale locks (> timeout_minutes) by failing the stale run.
        Returns active run if locked, or None if lock is successfully acquired.
        """
        active_run = (
            db.query(MonitoringRun)
            .filter(
                MonitoringRun.location_id == location_id,
                MonitoringRun.status == MonitoringRunStatusEnum.RUNNING.value,
            )
            .order_by(MonitoringRun.started_at.desc())
            .first()
        )

        if not active_run:
            return None

        # Check for stale lock
        now_utc = datetime.now(timezone.utc)
        start_time = active_run.started_at
        if start_time and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        duration_sec = (now_utc - start_time).total_seconds() if start_time else 0
        if duration_sec > timeout_minutes * 60.0:
            logger.warning(
                f"Stale monitoring run lock detected for {location_id} (Run {active_run.id}, "
                f"duration {duration_sec:.1f}s > {timeout_minutes*60}s). Forcing status to FAILED."
            )
            active_run.status = MonitoringRunStatusEnum.FAILED.value
            active_run.current_stage = MonitoringStageEnum.FAILED.value
            active_run.outcome_code = MonitoringOutcomeCodeEnum.ERROR.value
            active_run.error_message = f"Monitoring run aborted: lock timed out after {duration_sec:.1f} seconds."
            active_run.completed_at = now_utc
            db.commit()
            return None

        logger.info(f"Location {location_id} is currently locked by active run {active_run.id}.")
        return active_run

    def _advance_stage(
        self,
        db: Session,
        run: MonitoringRun,
        new_stage: MonitoringStageEnum,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Atomically updates the current stage and records stage entry in stage_history.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        run.current_stage = new_stage.value
        history = json.loads(run.stage_history) if isinstance(run.stage_history, str) else list(run.stage_history or [])
        history.append({
            "stage": new_stage.value,
            "timestamp": now_iso,
            "metadata": metadata or {},
        })
        run.stage_history = json.dumps(history)
        db.commit()
        logger.info(f"MonitoringRun {run.id} advanced to stage: {new_stage.value}")

    def execute_monitoring_run(
        self,
        location_id: str,
        trigger_type: MonitoringTriggerTypeEnum = MonitoringTriggerTypeEnum.SCHEDULED,
        triggered_by: str = "scheduler",
        force: bool = False,
        max_retries: Optional[int] = None,
        retry_backoff: Optional[float] = None,
    ) -> MonitoringRun:
        """
        Executes an end-to-end monitoring run for a single critical location with
        strict failure isolation, database-backed concurrency lock, and controlled retries.
        """
        retries = max_retries if max_retries is not None else settings.MAX_RETRIES
        backoff = retry_backoff if retry_backoff is not None else settings.RETRY_BACKOFF_SECONDS

        db = self.db_session_factory()
        db.expire_on_commit = False
        try:
            location = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
            if not location:
                raise ValueError(f"Critical location with ID '{location_id}' not found.")

            now_utc = datetime.now(timezone.utc)

            # Verification of monitoring status & enabled flag
            if not force:
                if not location.monitoring_enabled:
                    logger.info(f"Location {location_id} monitoring is disabled. Skipping run.")
                    skipped_run = MonitoringRun(
                        id=f"mrun-skip-{location_id}-{uuid.uuid4().hex[:12]}",
                        location_id=location_id,
                        status=MonitoringRunStatusEnum.SKIPPED.value,
                        trigger_type=trigger_type.value,
                        triggered_by=triggered_by,
                        current_stage=MonitoringStageEnum.PENDING.value,
                        outcome_code="LOCATION_DISABLED",
                        error_message="Location monitoring is disabled.",
                        stage_history=json.dumps([{"stage": "SKIPPED", "timestamp": now_utc.isoformat(), "reason": "LOCATION_DISABLED"}]),
                        started_at=now_utc,
                        completed_at=now_utc,
                        created_at=now_utc,
                    )
                    db.add(skipped_run)
                    db.commit()
                    return skipped_run

                if location.monitoring_status in ["DISABLED", "PAUSED"]:
                    logger.info(f"Location {location_id} monitoring status is {location.monitoring_status}. Skipping run.")
                    skipped_run = MonitoringRun(
                        id=f"mrun-skip-{location_id}-{uuid.uuid4().hex[:12]}",
                        location_id=location_id,
                        status=MonitoringRunStatusEnum.SKIPPED.value,
                        trigger_type=trigger_type.value,
                        triggered_by=triggered_by,
                        current_stage=MonitoringStageEnum.PENDING.value,
                        outcome_code=f"LOCATION_{location.monitoring_status}",
                        error_message=f"Location monitoring status is {location.monitoring_status}.",
                        stage_history=json.dumps([{"stage": "SKIPPED", "timestamp": now_utc.isoformat(), "reason": location.monitoring_status}]),
                        started_at=now_utc,
                        completed_at=now_utc,
                        created_at=now_utc,
                    )
                    db.add(skipped_run)
                    db.commit()
                    return skipped_run

            # Concurrency Control Check
            active_run = self._acquire_location_lock(
                db=db,
                location_id=location_id,
                timeout_minutes=settings.LOCK_TIMEOUT_MINUTES,
            )
            if active_run:
                logger.warning(
                    f"Concurrent run skipped for {location_id}: active run {active_run.id} is already in progress."
                )
                skipped_run = MonitoringRun(
                    id=f"mrun-skip-{location_id}-{uuid.uuid4().hex[:12]}",
                    location_id=location_id,
                    status=MonitoringRunStatusEnum.SKIPPED.value,
                    trigger_type=trigger_type.value,
                    triggered_by=triggered_by,
                    current_stage=MonitoringStageEnum.PENDING.value,
                    outcome_code=MonitoringOutcomeCodeEnum.CONCURRENT_RUN_SKIPPED.value,
                    error_message=f"Concurrent run in progress (active run: {active_run.id}).",
                    stage_history=json.dumps([{"stage": "SKIPPED", "timestamp": now_utc.isoformat(), "reason": "CONCURRENT_RUN_SKIPPED"}]),
                    started_at=now_utc,
                    completed_at=now_utc,
                    created_at=now_utc,
                )
                db.add(skipped_run)
                db.commit()
                return skipped_run

            # Create persistent active MonitoringRun record
            run_id = f"mrun-{location_id}-{uuid.uuid4().hex[:12]}"
            monitoring_run = MonitoringRun(
                id=run_id,
                location_id=location_id,
                status=MonitoringRunStatusEnum.RUNNING.value,
                trigger_type=trigger_type.value,
                triggered_by=triggered_by,
                current_stage=MonitoringStageEnum.PENDING.value,
                stage_history=json.dumps([]),
                observations_checked=0,
                observations_processed=0,
                new_observations_found=0,
                retry_count=0,
                started_at=now_utc,
                created_at=now_utc,
            )
            db.add(monitoring_run)
            location.last_attempted_run = now_utc
            db.commit()
        finally:
            db.close()

        attempt = 0
        while attempt <= retries:
            db = self.db_session_factory()
            db.expire_on_commit = False
            try:
                location = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
                monitoring_run = db.query(MonitoringRun).filter(MonitoringRun.id == run_id).first()
                monitoring_run.retry_count = attempt
                db.commit()

                # Execute pipeline stages within safe isolation
                return self._run_pipeline_stages(db=db, location=location, run=monitoring_run)

            except Exception as e:
                attempt += 1
                logger.error(
                    f"Monitoring run error on location {location_id} (Attempt {attempt}/{retries + 1}): {e}",
                    exc_info=True,
                )
                if attempt <= retries:
                    time.sleep(backoff * attempt)
                    continue

                # Max retries exhausted: mark as FAILED
                try:
                    monitoring_run = db.query(MonitoringRun).filter(MonitoringRun.id == run_id).first()
                    location = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
                    if monitoring_run:
                        monitoring_run.status = MonitoringRunStatusEnum.FAILED.value
                        monitoring_run.current_stage = MonitoringStageEnum.FAILED.value
                        monitoring_run.outcome_code = MonitoringOutcomeCodeEnum.ERROR.value
                        monitoring_run.error_message = str(e)
                        monitoring_run.completed_at = datetime.now(timezone.utc)
                        monitoring_run.retry_count = attempt - 1
                    if location:
                        location.monitoring_status = "ERROR"
                    db.commit()
                    return monitoring_run
                except Exception as commit_err:
                    logger.error(f"Failed to record run failure in DB: {commit_err}")
                    raise
            finally:
                db.close()

    def _run_pipeline_stages(
        self,
        db: Session,
        location: CriticalLocation,
        run: MonitoringRun,
    ) -> MonitoringRun:
        """
        Executes the internal pipeline stages sequentially.
        Stage failure safely isolates and marks the run as FAILED without impacting other locations.
        """
        location_id = location.id
        now_utc = datetime.now(timezone.utc)

        # ----------------------------------------------------------------------
        # STAGE 1: DISCOVERY (Phase 7.4)
        # ----------------------------------------------------------------------
        self._advance_stage(db, run, MonitoringStageEnum.DISCOVERY)

        new_s1_obs_count = 0
        new_s2_obs_count = 0
        total_checked = 0

        # Sentinel-1 Discovery
        try:
            s1_freshness = self.s1_discovery.check_freshness(
                db=db,
                location_id=location_id,
                lookback_days=settings.OBSERVATION_LOOKBACK_DAYS,
                auto_persist=True,
            )
            new_s1_obs_count = s1_freshness.get("new_observations_count", 0)
            total_checked += s1_freshness.get("total_found", len(s1_freshness.get("new_observations", [])))
        except Exception as e:
            logger.warning(f"Sentinel-1 catalog discovery encountered an issue: {e}")

        # Sentinel-2 Discovery
        try:
            s2_result = self.s2_detector.check_location(
                db=db,
                location=location,
                lookback_days=settings.OBSERVATION_LOOKBACK_DAYS,
            )
            total_checked += 1
            if s2_result.get("status") == "NEW_OBSERVATION_AVAILABLE":
                new_s2_obs_count += 1
        except Exception as e:
            logger.warning(f"Sentinel-2 catalog discovery encountered an issue: {e}")

        new_total_found = new_s1_obs_count + new_s2_obs_count
        run.observations_checked = total_checked
        run.new_observations_found = new_total_found
        location.last_observation_check = now_utc
        db.commit()

        # Check for un-processed observations in database
        unprocessed_obs = (
            db.query(SatelliteObservation)
            .filter(
                SatelliteObservation.location_id == location_id,
                SatelliteObservation.quality_status == "NEW_OBSERVATION_AVAILABLE",
            )
            .all()
        )

        has_work_to_process = bool(new_total_found > 0 or len(unprocessed_obs) > 0)

        # ----------------------------------------------------------------------
        # STAGE 2: OBSERVATION PROCESSING (Phase 7.5, 7.6, 7.7)
        # ----------------------------------------------------------------------
        self._advance_stage(
            db,
            run,
            MonitoringStageEnum.OBSERVATION_PROCESSING,
            metadata={"new_s1": new_s1_obs_count, "new_s2": new_s2_obs_count, "pending_count": len(unprocessed_obs)},
        )

        processed_count = 0
        for obs in unprocessed_obs:
            try:
                if obs.sensor == "SAR-C":
                    # Sentinel-1 Preprocessing
                    self.sar_processor.preprocess_observation(obs.id, db)
                    # Attempt differential comparison if compatible pair exists
                    try:
                        self.sar_processor.compare_observations(location_id, db)
                    except Exception as comp_err:
                        logger.info(f"SAR comparison not yet possible for {obs.id}: {comp_err}")
                    obs.quality_status = "ANALYSIS_COMPLETE"
                    processed_count += 1
                elif obs.collection == "sentinel-2-l2a":
                    # Sentinel-2 Optical Preprocessing & baseline comparison
                    self.pipeline.process_observation(db, location, obs)
                    processed_count += 1
            except Exception as proc_err:
                logger.error(f"Error processing observation {obs.id}: {proc_err}")
                obs.quality_status = "PROCESSING_FAILED"
                obs.rejection_reason = str(proc_err)

        db.commit()
        run.observations_processed = processed_count

        # ----------------------------------------------------------------------
        # STAGE 3: MULTI-SENSOR EVIDENCE FUSION (Phase 7.8)
        # ----------------------------------------------------------------------
        self._advance_stage(db, run, MonitoringStageEnum.EVIDENCE_FUSION)

        # Invoke Phase 3 fusion engine
        evidence_snapshot = self.fusion_engine.fuse_location_evidence(
            db=db,
            location_id=location_id,
            window_days=settings.CATALOG_QUERY_WINDOW_DAYS,
            force_recompute=has_work_to_process,
        )

        db_snapshot = db.query(EvidenceSnapshot).filter(EvidenceSnapshot.id == evidence_snapshot.id).first()
        if db_snapshot:
            run.evidence_snapshot_id = db_snapshot.id
        db.commit()

        # ----------------------------------------------------------------------
        # STAGE 4: RISK REASSESSMENT (Phase 7.9)
        # ----------------------------------------------------------------------
        self._advance_stage(db, run, MonitoringStageEnum.RISK_ASSESSMENT)

        # Authoritative Phase 4 Risk Engine
        risk_result = self.risk_engine.assess_and_persist(
            db=db,
            evidence=evidence_snapshot,
            location_name=location.name,
        )
        run.risk_assessment_id = risk_result.id
        db.commit()

        # ----------------------------------------------------------------------
        # STAGE 5: GROQ EVIDENCE ANALYST (Phase 7.10)
        # ----------------------------------------------------------------------
        self._advance_stage(db, run, MonitoringStageEnum.ANALYST)

        analyst_report_id = None
        try:
            analyst_res = self.analyst_engine.generate_and_persist(
                db=db,
                location_id=location_id,
                snapshot_id=evidence_snapshot.id,
                assessment_id=risk_result.id,
            )
            analyst_report_id = analyst_res.report_id
            run.analyst_report_id = analyst_report_id
            db.commit()
        except Exception as analyst_err:
            logger.warning(
                f"Groq analyst stage warning for {location_id}: {analyst_err}. "
                "Authoritative risk score remains authoritative and unaffected."
            )

        # ----------------------------------------------------------------------
        # STAGE 6: ALERT EVALUATION (Phase 7.11, 7.12, 7.13)
        # ----------------------------------------------------------------------
        self._advance_stage(db, run, MonitoringStageEnum.ALERT_EVALUATION)

        alert_res = self.alert_engine.generate_and_persist(
            db=db,
            location_id=location_id,
            risk_assessment_id=risk_result.id,
            analyst_report_id=analyst_report_id,
        )

        run.alert_id = alert_res.alert_id

        # Determine outcome code and alert action
        if alert_res.is_duplicate:
            run.alert_action = "UNCHANGED"
            if not has_work_to_process:
                run.outcome_code = MonitoringOutcomeCodeEnum.NO_NEW_DATA.value
            else:
                run.outcome_code = MonitoringOutcomeCodeEnum.ALERT_UNCHANGED.value
        else:
            if alert_res.escalation_history:
                esc_type = alert_res.escalation_history[0].get("type", "ESCALATION")
                run.alert_action = esc_type
                run.outcome_code = f"ALERT_{esc_type}"
            else:
                run.alert_action = "CREATED"
                run.outcome_code = MonitoringOutcomeCodeEnum.ALERT_GENERATED.value

        # ----------------------------------------------------------------------
        # STAGE 7: COMPLETED (Phase 7.20)
        # ----------------------------------------------------------------------
        run.status = MonitoringRunStatusEnum.COMPLETED.value
        run.completed_at = datetime.now(timezone.utc)
        self._advance_stage(
            db,
            run,
            MonitoringStageEnum.COMPLETED,
            metadata={"outcome": run.outcome_code, "alert_action": run.alert_action},
        )

        # Update critical location tracking fields
        interval_hours = location.monitoring_interval_hours or settings.DEFAULT_MONITORING_INTERVAL_HOURS
        location.last_successful_run = run.completed_at
        location.next_scheduled_run = run.completed_at + timedelta(hours=interval_hours)
        location.monitoring_status = "ACTIVE"
        db.commit()

        logger.info(
            f"MonitoringRun {run.id} for {location.name} successfully COMPLETED: "
            f"outcome={run.outcome_code}, alert_action={run.alert_action}, risk={risk_result.score}/100."
        )
        return run
