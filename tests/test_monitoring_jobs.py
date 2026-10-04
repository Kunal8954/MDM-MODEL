"""
Tests for asynchronous AOI monitoring jobs.

The point of the job wrapper is that a client can reconnect mid-run and see real progress,
and that a failure is recorded as a failure rather than being papered over with DEMO data.
"""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import satguard.api.main as api_main
from satguard.config import settings
from satguard.api.main import app
from satguard.db.session import create_sqlite_engine, get_db_session
from satguard.models.entities import Base, MonitoringJob
from satguard.monitoring.jobs import (
    COMPLETED,
    FAILED,
    STAGE_PERCENT,
    MonitoringJobRunner,
    create_job,
)

TEHRI_BBOX = [78.58, 30.28, 78.72, 30.40]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated DB plus an app whose job threads are observable rather than racing."""
    engine = create_sqlite_engine(f"sqlite:///{tmp_path/'jobs.db'}")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def _get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(api_main, "init_db", lambda *a, **k: None, raising=False)
    monkeypatch.setattr("satguard.monitoring.scheduler.scheduler.start",
                        lambda *a, **k: None, raising=False)
    # Polling a job is many small requests, and the shared in-memory limiter is global to
    # the app, so a busy poll here would trip the same 120/min budget real clients rely on.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    app.dependency_overrides[get_db_session] = _get_session
    try:
        with TestClient(app) as client:
            yield client, TestingSession
    finally:
        app.dependency_overrides.clear()


def _create_area(client, **overrides):
    body = {"bbox": TEHRI_BBOX, "monitoring_mode": "infrastructure", "source": "DEMO"}
    body.update(overrides)
    response = client.post("/api/aoi", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _wait_for_job(client, job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["is_terminal"]:
            return body
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def test_stage_percentages_are_monotonic():
    values = [percent for _, percent in sorted(STAGE_PERCENT.items(),
                                               key=lambda kv: kv[1])]
    assert values == sorted(values)
    assert values[0] == 0 and values[-1] == 100


def test_job_is_queued_and_returns_immediately(env):
    client, _ = env
    area = _create_area(client)

    response = client.post("/api/monitor/jobs", json={"area_id": area["id"], "source": "DEMO"})
    assert response.status_code == 202, response.text
    body = response.json()

    assert body["status"] in ("QUEUED", "RUNNING")
    assert body["area_id"] == area["id"]
    assert body["source"] == "DEMO"
    assert 0 <= body["progress_percent"] <= 100


def test_job_reaches_completion_and_persists_anomalies(env):
    client, _ = env
    area = _create_area(client)
    job_id = client.post("/api/monitor/jobs", json={
        "area_id": area["id"], "source": "DEMO",
        "demo_scenario": "new_construction", "grid_size": 120,
    }).json()["job_id"]

    body = _wait_for_job(client, job_id)
    assert body["status"] == COMPLETED, body.get("error_message")
    assert body["progress_percent"] == 100
    assert body["stage"] == "COMPLETED"
    assert body["anomaly_count"] >= 1
    assert body["error_code"] is None
    assert body["is_terminal"] is True

    result = body["result"]
    assert result["source"] == "DEMO"
    assert len(result["persisted_anomaly_ids"]) == result["anomaly_count"]

    # The anomalies are queryable, not just embedded in the job payload.
    listed = client.get("/api/anomalies", params={"area_id": area["id"]}).json()
    assert listed["count"] == result["anomaly_count"]


def test_progress_history_covers_every_stage_it_passed(env):
    client, _ = env
    area = _create_area(client)
    job_id = client.post("/api/monitor/jobs", json={
        "area_id": area["id"], "source": "DEMO", "grid_size": 96,
    }).json()["job_id"]

    body = _wait_for_job(client, job_id)
    stages = [entry["stage"] for entry in body["stage_history"]]
    for expected in ("ACQUIRING", "PREPROCESSING", "SUPPRESSING", "DETECTING",
                     "EXTRACTING", "PERSISTING", "COMPLETED"):
        assert expected in stages, f"{expected} missing from {stages}"

    percents = [entry["percent"] for entry in body["stage_history"]]
    assert percents == sorted(percents), "progress must never move backwards"
    # Each stage is recorded exactly once: the runner and the run callback both emit them,
    # and a duplicate would make the history a misleading progress log.
    assert len(stages) == len(set(stages)), f"duplicate stages in {stages}"


def test_live_job_without_credentials_fails_with_an_error_code(env):
    client, _ = env
    area = _create_area(client, source="LIVE")
    job_id = client.post("/api/monitor/jobs", json={
        "area_id": area["id"], "source": "LIVE"}).json()["job_id"]

    body = _wait_for_job(client, job_id)
    assert body["status"] == FAILED
    assert body["error_code"] == "LIVE_DATA_UNAVAILABLE"
    assert "DEMO data is never substituted" in body["error_message"]
    assert body["anomaly_count"] == 0
    # Critically: no synthetic result was stored for a LIVE job.
    assert client.get("/api/anomalies", params={"area_id": area["id"]}).json()["count"] == 0


def test_unknown_area_and_source_are_rejected_before_queueing(env):
    client, _ = env
    assert client.post("/api/monitor/jobs",
                       json={"area_id": "nope", "source": "DEMO"}).status_code == 404
    area = _create_area(client)
    assert client.post("/api/monitor/jobs",
                       json={"area_id": area["id"], "source": "MADEUP"}).status_code == 422


def test_jobs_can_be_listed_and_filtered(env):
    client, _ = env
    area = _create_area(client)
    job_id = client.post("/api/monitor/jobs", json={
        "area_id": area["id"], "source": "DEMO", "grid_size": 96}).json()["job_id"]
    _wait_for_job(client, job_id)

    listing = client.get("/api/jobs", params={"area_id": area["id"]}).json()
    assert listing["count"] == 1
    assert listing["jobs"][0]["job_id"] == job_id
    # Listing stays light: the heavy result is opt-in.
    assert "result" not in listing["jobs"][0]

    assert client.get("/api/jobs", params={"status": "COMPLETED"}).json()["count"] == 1
    assert client.get("/api/jobs", params={"status": "FAILED"}).json()["count"] == 0


def test_missing_job_is_404(env):
    client, _ = env
    assert client.get("/api/jobs/mjob-missing").status_code == 404


def test_result_can_be_omitted_from_poll_response(env):
    client, _ = env
    area = _create_area(client)
    job_id = client.post("/api/monitor/jobs", json={
        "area_id": area["id"], "source": "DEMO", "grid_size": 96}).json()["job_id"]
    _wait_for_job(client, job_id)

    light = client.get(f"/api/jobs/{job_id}",
                       params={"include_result": False}).json()
    assert "result" not in light
    assert light["anomaly_count"] >= 1


def test_runner_records_a_failure_without_raising(env):
    """A crashing run must leave a FAILED job, not an exception on the worker thread."""
    _, TestingSession = env
    db = TestingSession()
    area_client = _create_area(Client_for(TestingSession))
    job = create_job(db, _area_record(db, area_client["id"]),
                     {"source": "DEMO", "monitoring_mode": "infrastructure"})

    def exploding_run(stage):
        stage("ACQUIRING")
        stage("SUPPRESSING")
        raise RuntimeError("sensor offline")

    MonitoringJobRunner(db, job.id).execute(exploding_run)

    db.expire_all()
    stored = db.get(MonitoringJob, job.id)
    assert stored.status == FAILED
    assert stored.error_code is None
    assert "sensor offline" in stored.error_message
    # Progress stops at the last stage that started rather than claiming completion.
    assert stored.progress_percent < 100
    assert stored.stage == "SUPPRESSING"
    stages = [e["stage"] for e in json.loads(stored.stage_history)]
    assert "DETECTING" not in stages
    db.close()


def test_runner_forwards_the_error_code_of_a_typed_error(env):
    from satguard.processing.monitoring import LiveDataUnavailable

    _, TestingSession = env
    db = TestingSession()
    area_client = _create_area(Client_for(TestingSession))
    job = create_job(db, _area_record(db, area_client["id"]), {"source": "LIVE"})

    def unavailable(stage):
        stage("ACQUIRING")
        raise LiveDataUnavailable("no credentials")

    MonitoringJobRunner(db, job.id).execute(unavailable)

    db.expire_all()
    assert db.get(MonitoringJob, job.id).error_code == "LIVE_DATA_UNAVAILABLE"
    db.close()


def test_concurrent_runners_do_not_interleave_stage_history(env):
    """Two jobs updating progress at once must not corrupt each other's history."""
    _, TestingSession = env
    area_client = _create_area(Client_for(TestingSession))
    db = TestingSession()
    area = _area_record(db, area_client["id"])

    jobs = [create_job(db, area, {"source": "DEMO"}) for _ in range(2)]
    ids = [job.id for job in jobs]
    barrier = threading.Barrier(len(ids))

    def make_runner(job_id):
        session = TestingSession()
        runner = MonitoringJobRunner(session, job_id)

        def run(stage):
            barrier.wait(timeout=10)  # force the two runners to overlap
            stage("DETECTING")
            session.close()

        return runner, run

    threads = []
    for job_id in ids:
        runner, run = make_runner(job_id)
        thread = threading.Thread(target=runner.execute, args=(run,))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    for job_id in ids:
        session = TestingSession()
        stored = session.get(MonitoringJob, job_id)
        stages = [e["stage"] for e in json.loads(stored.stage_history)]
        assert stages == ["ACQUIRING", "DETECTING"], stages
        session.close()
    db.close()


# -- small helpers -----------------------------------------------------


class Client_for:
    """A bare client used only for creating areas against an isolated session factory."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def post(self, path, json=None):
        session = self._session_factory()
        try:
            from satguard.api.monitoring_router import _persist_area
            from satguard.geospatial.area_of_interest import MonitoringMode, build_aoi

            aoi = build_aoi(bbox=json["bbox"], monitoring_mode=MonitoringMode("infrastructure"))
            record = _persist_area(session, aoi, json.get("source", "DEMO"))
            payload = {
                "id": record.id,
                "monitoring_mode": record.monitoring_mode,
                "source": record.source,
            }
            return _Response(201, payload)
        finally:
            session.close()


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _area_record(db, area_id):
    from satguard.models.entities import MonitoringArea

    record = db.get(MonitoringArea, area_id)
    assert record is not None
    return record