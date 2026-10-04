"""
satguard/api/monitoring_router.py
Arbitrary-AOI monitoring endpoints.

Everything here accepts any AOI geometry the user supplies: a point, a bounding box, a
polygon, GeoJSON, or a place name. Nothing is limited to a seeded list of sites.

Provenance is explicit on every response. A DEMO run is labelled DEMO and carries a
`source` field; a LIVE run either returns real observations or fails. There is no code
path that returns synthetic data under a LIVE label.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from satguard.db.session import get_db_session
from satguard.geospatial.area_of_interest import (
    AOIError,
    MonitoringMode,
    build_aoi,
)
from satguard.models.entities import AnomalyRecord, MonitoringArea, MonitoringJob
from satguard.monitoring.jobs import (
    MonitoringJobRunner,
    create_job,
    job_to_dict,
    launch,
    session_factory_for,
)
from satguard.processing.demo import (
    DEMO_SOURCE,
    available_demo_sites,
    scenarios_for_mode,
)
from satguard.processing.monitoring import (
    DEMO_SOURCE as RUN_DEMO_SOURCE,
    LIVE_SOURCE,
    LiveDataUnavailable,
    MonitoringError,
    MonitoringRequest,
    MonitoringResult,
    run_monitoring,
)

logger = logging.getLogger("satguard.api.monitoring")

router = APIRouter(prefix="/api", tags=["monitoring"])


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------


class CreateAreaRequest(BaseModel):
    """Any geometry the user can express, or a place name to geocode."""
    geometry: Optional[Dict[str, Any]] = None
    point: Optional[Dict[str, float]] = None
    bbox: Optional[List[float]] = None
    polygon: Optional[List[List[float]]] = None
    geojson: Optional[Any] = None
    place_name: Optional[str] = None
    monitoring_mode: str = Field(default="general")
    user_label: str = ""
    source: str = Field(default=LIVE_SOURCE, description="LIVE or DEMO")


class RunRequest(BaseModel):
    area_id: str
    source: str = Field(default=DEMO_SOURCE, description="LIVE or DEMO")
    monitoring_mode: Optional[str] = None
    demo_scenario: Optional[str] = None
    demo_interval_days: int = 15
    grid_size: int = Field(default=200, ge=32, le=1024)
    max_cloud_cover: Optional[float] = 20.0
    require_sar: bool = False
    normalization: str = "linear"
    speckle_filter: Optional[str] = "median"


# ----------------------------------------------------------------------
# Area helpers
# ----------------------------------------------------------------------


def _persist_area(db: Session, aoi, source: str) -> MonitoringArea:
    """
    Insert the AOI, or update it if the same geometry already exists.

    Area ids are derived from the geometry, mode and label precisely so that re-submitting
    the same selection is idempotent. Re-using that id here keeps the promise and avoids a
    duplicate-insert failure when a client redraws an area it already created.
    """
    payload = aoi.to_dict()
    west, south, east, north = aoi.geometry.bounds
    metadata_json = json.dumps({
        "sensor_strategy": payload.get("sensor_strategy"),
        "required_indices": payload.get("required_indices"),
    })

    record = db.get(MonitoringArea, aoi.id)
    if record is None:
        record = MonitoringArea(id=aoi.id, created_at=datetime.now(timezone.utc))
        db.add(record)

    record.user_label = aoi.user_label or payload.get("user_label", "")
    record.monitoring_mode = aoi.monitoring_mode.value
    record.geometry = json.dumps(payload["geometry"])
    record.geometry_type = payload["geometry"]["type"]
    record.bbox = json.dumps([west, south, east, north])
    record.center_lon = payload["center_lon"]
    record.center_lat = payload["center_lat"]
    record.area_m2 = payload["area_m2"]
    record.crs = aoi.crs
    record.source = source
    record.metadata_json = metadata_json

    db.commit()
    db.refresh(record)
    return record


def _area_to_dict(record: MonitoringArea) -> Dict[str, Any]:
    return {
        "id": record.id,
        "user_label": record.user_label,
        "monitoring_mode": record.monitoring_mode,
        "geometry": json.loads(record.geometry),
        "bbox": json.loads(record.bbox),
        "center": {"lon": record.center_lon, "lat": record.center_lat},
        "area_km2": round(record.area_m2 / 1e6, 6),
        "crs": record.crs,
        "source": record.source,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "metadata": json.loads(record.metadata_json or "{}"),
    }


def _rebuild_aoi(record: MonitoringArea):
    return build_aoi(
        geojson={"type": "Feature", "geometry": json.loads(record.geometry),
                 "properties": {}},
        monitoring_mode=record.monitoring_mode,
        user_label=record.user_label,
        validate=False,
    )


def _persist_anomalies(db: Session, area_id: str, result: MonitoringResult,
                       run_id: str) -> List[AnomalyRecord]:
    records: List[AnomalyRecord] = []
    for anomaly in result.anomalies:
        payload = anomaly.to_dict()
        record = AnomalyRecord(
            id=f"anom-{uuid.uuid4().hex[:16]}",
            area_id=area_id,
            run_id=run_id,
            region_id=anomaly.region_id,
            monitoring_mode=anomaly.monitoring_mode,
            geometry=json.dumps(payload["geometry"]),
            centroid_lon=anomaly.centroid_lon,
            centroid_lat=anomaly.centroid_lat,
            bbox=json.dumps(list(anomaly.bbox)),
            area_m2=anomaly.area_m2,
            pixel_count=anomaly.pixel_count,
            detection_confidence=anomaly.detection_confidence,
            anomaly_confidence=anomaly.anomaly_confidence,
            severity=anomaly.severity.value,
            evidence=json.dumps(payload["evidence"]),
            caveats=json.dumps(payload["caveats"]),
            layer_agreement=json.dumps(payload["layer_agreement"]),
            source=result.source,
            detected_at=anomaly.detected_at or datetime.now(timezone.utc),
        )
        db.add(record)
        records.append(record)
    db.commit()
    return records


def _anomaly_to_dict(record: AnomalyRecord) -> Dict[str, Any]:
    return {
        "id": record.id,
        "area_id": record.area_id,
        "run_id": record.run_id,
        "region_id": record.region_id,
        "monitoring_mode": record.monitoring_mode,
        "geometry": json.loads(record.geometry),
        "centroid": {"lon": record.centroid_lon, "lat": record.centroid_lat},
        "bbox": json.loads(record.bbox),
        "area_km2": round(record.area_m2 / 1e6, 6),
        "area_ha": round(record.area_m2 / 1e4, 4),
        "pixel_count": record.pixel_count,
        "detection_confidence": round(record.detection_confidence, 4),
        "anomaly_confidence": round(record.anomaly_confidence, 4),
        "severity": record.severity,
        "layer_agreement": json.loads(record.layer_agreement or "{}"),
        "evidence": json.loads(record.evidence or "[]"),
        "caveats": json.loads(record.caveats or "[]"),
        "source": record.source,
        "detected_at": record.detected_at.isoformat() if record.detected_at else None,
    }


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


@router.get("/demo/sites")
def list_demo_sites() -> Dict[str, Any]:
    """Sample areas available for exploration, clearly separated from real monitoring."""
    return {
        "source": DEMO_SOURCE,
        "disclaimer": (
            "DEMO sites render synthetic data so the product can be explored without "
            "Sentinel credentials. Results from them are not satellite observations."
        ),
        "sites": available_demo_sites(),
    }


@router.get("/demo/scenarios")
def list_demo_scenarios(monitoring_mode: str = Query(default="general")) -> Dict[str, Any]:
    return {"monitoring_mode": monitoring_mode,
            "scenarios": scenarios_for_mode(monitoring_mode)}


@router.post("/aoi", status_code=status.HTTP_201_CREATED)
def create_area(payload: CreateAreaRequest,
                db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    """Register any AOI: point, bounding box, polygon, GeoJSON or place name."""
    try:
        mode = MonitoringMode(payload.monitoring_mode)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown monitoring mode '{payload.monitoring_mode}'. "
                   f"Valid modes: {[m.value for m in MonitoringMode]}",
        )

    if not any([payload.geometry, payload.point, payload.bbox, payload.polygon,
                payload.geojson, payload.place_name]):
        raise HTTPException(
            status_code=422,
            detail="Provide one of geometry, point, bbox, polygon, geojson or place_name.",
        )

    try:
        aoi = build_aoi(
            geometry=payload.geometry, point=payload.point, bbox=payload.bbox,
            polygon=payload.polygon, geojson=payload.geojson,
            place_name=payload.place_name, monitoring_mode=mode,
            user_label=payload.user_label,
        )
    except AOIError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("AOI construction failed")
        raise HTTPException(status_code=422, detail=f"Invalid AOI: {exc}")

    source = payload.source.upper() if payload.source else LIVE_SOURCE
    return _area_to_dict(_persist_area(db, aoi, source))


@router.get("/aoi")
def list_areas(monitoring_mode: Optional[str] = Query(default=None),
               source: Optional[str] = Query(default=None),
               db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    query = db.query(MonitoringArea)
    if monitoring_mode:
        query = query.filter(MonitoringArea.monitoring_mode == monitoring_mode)
    if source:
        query = query.filter(MonitoringArea.source == source.upper())
    areas = query.order_by(MonitoringArea.created_at.desc()).all()
    return {"count": len(areas), "areas": [_area_to_dict(a) for a in areas]}


@router.get("/aoi/{area_id}")
def get_area(area_id: str, db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    record = db.get(MonitoringArea, area_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No AOI '{area_id}'")
    return _area_to_dict(record)


@router.delete("/aoi/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_area(area_id: str, db: Session = Depends(get_db_session)) -> None:
    record = db.get(MonitoringArea, area_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No AOI '{area_id}'")
    # Children are removed explicitly rather than relying on `ondelete="CASCADE"`, which
    # SQLite ignores unless foreign keys are enabled per connection.
    db.query(AnomalyRecord).filter(AnomalyRecord.area_id == area_id).delete(
        synchronize_session=False)
    db.delete(record)
    db.commit()


def _execute_run(db: Session, record: MonitoringArea, payload: "RunRequest",
                 stage: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """
    Run one monitoring comparison and persist its anomalies.

    Shared by the synchronous endpoint and the background job runner so both produce
    identical payloads. `stage` is called with each pipeline stage name as it starts.
    """
    source = payload.source.upper()
    if source not in (LIVE_SOURCE, RUN_DEMO_SOURCE):
        raise MonitoringError(f"Unknown source '{payload.source}'. Use LIVE or DEMO.")

    mode = payload.monitoring_mode or record.monitoring_mode
    aoi = _rebuild_aoi(record)
    request = MonitoringRequest(
        aoi=aoi,
        monitoring_mode=mode,
        source=source,
        demo_scenario=payload.demo_scenario,
        demo_interval_days=payload.demo_interval_days,
        max_cloud_cover=payload.max_cloud_cover,
        require_sar=payload.require_sar,
        normalization=payload.normalization,
        speckle_filter=payload.speckle_filter,
        grid_shape=(payload.grid_size, payload.grid_size),
    )

    def report(name: str) -> None:
        if stage is not None:
            stage(name)

    run_id = f"run-{uuid.uuid4().hex[:16]}"
    started = datetime.now(timezone.utc)

    result = run_monitoring(request, progress=report)

    report("PERSISTING")
    persisted = _persist_anomalies(db, record.id, result, run_id)

    body = result.to_dict()
    body["run_id"] = run_id
    body["started_at"] = started.isoformat()
    body["completed_at"] = datetime.now(timezone.utc).isoformat()
    body["persisted_anomaly_ids"] = [a.id for a in persisted]
    return body


@router.post("/monitor")
def run_monitoring_endpoint(payload: RunRequest,
                            db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    """
    Run one monitoring comparison for an AOI and persist the anomalies.

    LIVE runs require Sentinel Hub credentials. Without them the request fails with
    `LIVE_DATA_UNAVAILABLE` rather than returning DEMO data under a LIVE label. Use
    `POST /api/monitor/jobs` for a non-blocking run with progress.
    """
    record = db.get(MonitoringArea, payload.area_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No AOI '{payload.area_id}'")

    try:
        return _execute_run(db, record, payload)
    except LiveDataUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "error_code": exc.error_code, "message": str(exc),
        })
    except MonitoringError as exc:
        raise HTTPException(status_code=422, detail={
            "error_code": exc.error_code, "message": str(exc),
        })


@router.post("/monitor/jobs", status_code=status.HTTP_202_ACCEPTED)
def queue_monitoring_job(payload: RunRequest,
                         db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    """
    Queue a monitoring run and return immediately.

    The run happens on a background thread. Poll `GET /api/jobs/{job_id}` for stage and
    progress. A failure is reported on the job with its error code; it is never replaced by
    synthetic data.
    """
    record = db.get(MonitoringArea, payload.area_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No AOI '{payload.area_id}'")
    if payload.source.upper() not in (LIVE_SOURCE, RUN_DEMO_SOURCE):
        raise HTTPException(status_code=422,
                            detail=f"Unknown source '{payload.source}'. Use LIVE or DEMO.")

    job = create_job(db, record, payload.model_dump())

    def _run(runner: "MonitoringJobRunner") -> None:
        runner.execute(lambda stage: _execute_run(runner.db, record, payload, stage))

    # The worker binds to this request's engine, not the global factory.
    launch(session_factory_for(db), job.id, _run)
    return {"job_id": job.id, "status": job.status, "stage": job.stage,
            "progress_percent": job.progress_percent, "area_id": record.id,
            "source": job.source}


@router.get("/jobs")
def list_jobs(area_id: Optional[str] = Query(default=None),
              status_filter: Optional[str] = Query(default=None, alias="status"),
              limit: int = Query(default=50, ge=1, le=500),
              db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    query = db.query(MonitoringJob)
    if area_id:
        query = query.filter(MonitoringJob.area_id == area_id)
    if status_filter:
        query = query.filter(MonitoringJob.status == status_filter.upper())
    jobs = query.order_by(MonitoringJob.created_at.desc()).limit(limit).all()
    return {"count": len(jobs), "jobs": [job_to_dict(j, include_result=False) for j in jobs]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, include_result: bool = Query(default=True),
            db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    """Poll a job's stage, progress and, once finished, its result."""
    job = db.get(MonitoringJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"No job '{job_id}'")
    return job_to_dict(job, include_result=include_result)


@router.get("/anomalies")
def list_anomalies(area_id: Optional[str] = Query(default=None),
                   severity: Optional[str] = Query(default=None),
                   min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
                   source: Optional[str] = Query(default=None),
                   limit: int = Query(default=100, ge=1, le=1000),
                   db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    """List anomaly regions, filterable by area, severity and confidence."""
    query = db.query(AnomalyRecord)
    if area_id:
        query = query.filter(AnomalyRecord.area_id == area_id)
    if severity:
        query = query.filter(AnomalyRecord.severity == severity)
    if source:
        query = query.filter(AnomalyRecord.source == source.upper())
    query = query.filter(AnomalyRecord.anomaly_confidence >= min_confidence)
    records = query.order_by(
        AnomalyRecord.detected_at.desc(), AnomalyRecord.area_m2.desc()
    ).limit(limit).all()

    summary: Dict[str, Dict[str, Any]] = {}
    for severity_value in ("none", "low", "moderate", "high", "critical"):
        matching = [r for r in records if r.severity == severity_value]
        summary[severity_value] = {
            "count": len(matching),
            "area_km2": round(sum(r.area_m2 for r in matching) / 1e6, 6),
        }

    return {
        "count": len(records),
        "summary_by_severity": summary,
        "anomalies": [_anomaly_to_dict(r) for r in records],
    }


@router.get("/anomalies/{anomaly_id}")
def get_anomaly(anomaly_id: str,
                db: Session = Depends(get_db_session)) -> Dict[str, Any]:
    record = db.get(AnomalyRecord, anomaly_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No anomaly '{anomaly_id}'")
    return _anomaly_to_dict(record)