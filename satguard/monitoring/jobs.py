"""
satguard/monitoring/jobs.py
Asynchronous job runner for AOI monitoring.

`run_monitoring()` is synchronous and takes a few seconds for a DEMO run, more for LIVE.
This wrapper runs it in a worker thread while recording the stage it reached, so a client
can poll one endpoint and render progress instead of holding an open request.

The stages are reported rather than inferred: a job that fails during SAR acquisition says
so, and a job that succeeds reports the anomaly count it produced.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import sessionmaker

from satguard.models.entities import MonitoringArea, MonitoringJob

logger = logging.getLogger("satguard.jobs")

QUEUED = "QUEUED"
RUNNING = "RUNNING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

# Ordered so progress is monotonic: the UI can show a bar that only ever moves forward.
STAGES: List[tuple] = [
    ("QUEUED", 0),
    ("ACQUIRING", 15),
    ("PREPROCESSING", 35),
    ("SUPPRESSING", 55),
    ("DETECTING", 75),
    ("EXTRACTING", 90),
    ("PERSISTING", 97),
    ("COMPLETED", 100),
]
STAGE_PERCENT = dict(STAGES)
TERMINAL_STATUSES = (COMPLETED, FAILED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MonitoringJobRunner:
    """
    Runs one monitoring job on a background thread and persists its progress.

    `progress_hook` is invoked before the heavy work of each stage, so the stored progress
    reflects the stage that is about to run. A stage that never starts stays absent from
    `stage_history`, which is how a failure location is identified.
    """

    def __init__(self, db, job_id: str,
                 progress_hook: Optional[Callable[[str, int], None]] = None) -> None:
        self.db = db
        self.job_id = job_id
        self.progress_hook = progress_hook
        self._lock = threading.Lock()

    # -- persistence ---------------------------------------------------

    def _record_stage(self, job: MonitoringJob, stage: str, percent: int) -> None:
        job.stage = stage
        job.progress_percent = max(0, min(100, int(percent)))
        history = json.loads(job.stage_history or "[]")
        history.append({
            "stage": stage,
            "percent": job.progress_percent,
            "at": _now().isoformat(),
        })
        job.stage_history = json.dumps(history)
        if self.progress_hook is not None:
            self.progress_hook(stage, job.progress_percent)

    def _fail(self, job: MonitoringJob, code: Optional[str], message: str) -> None:
        logger.warning("Monitoring job %s failed at stage %s: %s",
                       job.id, job.stage, message)
        job.status = FAILED
        job.progress_percent = min(job.progress_percent, 99)
        job.error_code = code
        job.error_message = message[:2000]
        job.completed_at = _now()
        self.db.commit()

    # -- execution -----------------------------------------------------

    def execute(self, run: Callable[[Callable[[str], None]], Dict[str, Any]]) -> None:
        """
        Execute `run` with a stage callback, then persist success.

        `run` receives a `stage` callable and must return a JSON-serialisable result dict.
        All database failures are contained here so one bad job cannot kill the thread.
        """
        job = self.db.get(MonitoringJob, self.job_id)
        if job is None:
            logger.error("Monitoring job %s vanished before execution", self.job_id)
            return

        def stage(name: str) -> None:
            with self._lock:
                self._record_stage(job, name, STAGE_PERCENT.get(name, job.progress_percent))
                self.db.commit()

        try:
            job.status = RUNNING
            job.started_at = _now()
            # Only the opening stage is emitted here. Every later stage comes from the run
            # callback itself, so recording them in both places would double each entry.
            stage("ACQUIRING")

            result = run(stage)

            job.anomaly_count = int(result.get("anomaly_count", 0))
            job.result_json = json.dumps(result, default=str)
            job.status = COMPLETED
            self._record_stage(job, "COMPLETED", STAGE_PERCENT["COMPLETED"])
            job.completed_at = _now()
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 - a job failure must not kill the thread
            self.db.rollback()
            job = self.db.get(MonitoringJob, self.job_id)
            if job is not None:
                self._fail(job, getattr(exc, "error_code", None), f"{type(exc).__name__}: {exc}")
            else:
                logger.error("Monitoring job %s failed and could not be updated", self.job_id)


def create_job(db, area: MonitoringArea, request_payload: Dict[str, Any]) -> MonitoringJob:
    """Queue a monitoring job for an area. Returns the unscheduled job record."""
    job = MonitoringJob(
        id=f"mjob-{uuid.uuid4().hex[:16]}",
        area_id=area.id,
        source=request_payload.get("source", "LIVE"),
        monitoring_mode=request_payload.get("monitoring_mode", area.monitoring_mode),
        status=QUEUED,
        stage=QUEUED,
        progress_percent=STAGE_PERCENT["QUEUED"],
        request_json=json.dumps(request_payload, default=str),
        created_at=_now(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def job_to_dict(job: MonitoringJob, include_result: bool = True) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "job_id": job.id,
        "area_id": job.area_id,
        "source": job.source,
        "monitoring_mode": job.monitoring_mode,
        "status": job.status,
        "stage": job.stage,
        "progress_percent": job.progress_percent,
        "stage_history": json.loads(job.stage_history or "[]"),
        "anomaly_count": job.anomaly_count,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "is_terminal": job.status in TERMINAL_STATUSES,
    }
    if include_result and job.result_json:
        payload["result"] = json.loads(job.result_json)
    return payload


def session_factory_for(db):
    """
    Build a session factory bound to the same engine as an existing session.

    The worker thread must not use the module-level `SessionLocal`: the request's session
    may be bound to a different engine, and the job would then be written somewhere the
    caller never looks.
    """
    bind = db.get_bind()
    return sessionmaker(bind=bind, autocommit=False, autoflush=False)


def launch(db_factory, job_id: str, runner_fn: Callable[[MonitoringJobRunner], None]) -> threading.Thread:
    """
    Run `runner_fn` on a daemon thread with its own session.

    A dedicated session is required because SQLAlchemy sessions are not thread-safe and the
    request's session will be closed as soon as the HTTP response is sent.
    """
    def _worker() -> None:
        session = db_factory()
        try:
            runner_fn(MonitoringJobRunner(session, job_id))
        finally:
            session.close()

    thread = threading.Thread(target=_worker, name=f"monitoring-job-{job_id}", daemon=True)
    thread.start()
    return thread