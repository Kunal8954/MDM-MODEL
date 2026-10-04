"""
satguard/api/main.py
FastAPI Server for SATGUARD Critical Location Earth Observation Platform.
Structured RESTful endpoints providing surveillance state, observation feeds,
and differential change analytics.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, SatelliteObservation, ChangeDetection
from satguard.ingestion.detector import ObservationDetector
from satguard.processing.pipeline import MonitoringPipeline
from satguard.api.monitoring_router import router as monitoring_router

from contextlib import asynccontextmanager
import logging
import os

from satguard.config import settings
from satguard.observability.logging import configure_logging
from satguard.observability.health import check_liveness, check_readiness
from satguard.observability.metrics import metrics_collector
from satguard.security import (
    SecurityHeadersMiddleware,
    RequestCorrelationMiddleware,
    RateLimitingMiddleware,
    RoleEnum,
    UserLoginRequest,
    TokenResponse,
    UserProfileResponse,
    UserCreateRequest,
    AuditLogResponse,
    authenticate_user,
    create_access_token,
    get_current_user,
    require_role,
    record_audit_event,
    query_audit_logs,
)
from satguard.models.entities import User

logger = logging.getLogger("satguard.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(
        level=os.getenv("LOG_LEVEL", "INFO"),
        json_format=(settings.SATGUARD_ENV == "production"),
    )
    init_db()
    try:
        from satguard.monitoring.scheduler import scheduler
        scheduler.start()
    except Exception as e:
        logger.warning(f"Background monitoring scheduler startup deferred: {e}")
    yield
    try:
        from satguard.monitoring.scheduler import scheduler
        scheduler.stop()
    except Exception:
        pass


app = FastAPI(
    title="SATGUARD Critical Location Surveillance API",
    description="Government-grade Earth observation, temporal change detection, and operational intelligence platform",
    version="1.0.0",
    lifespan=lifespan,
)

# Arbitrary-AOI monitoring: areas, runs, anomalies and DEMO exploration.
app.include_router(monitoring_router)

# Phase 10 Security Middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(RateLimitingMiddleware, max_requests=settings.RATE_LIMIT_REQUESTS_PER_MINUTE)

from fastapi.middleware.cors import CORSMiddleware

cors_origins = list(settings.CORS_ALLOWED_ORIGINS) if settings.CORS_ALLOWED_ORIGINS else ["http://localhost:5173", "http://localhost:3000"]
if settings.SATGUARD_ENV != "production" and "*" not in cors_origins:
    cors_origins.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def get_db():
    session = get_db_session()
    try:
        yield session
    finally:
        session.close()


# ==============================================================================
# PHASE 10 — HEALTH, OBSERVABILITY & METRICS ENDPOINTS
# ==============================================================================

@app.get("/health", tags=["System"])
@app.get("/api/health", tags=["System"])
def health_endpoint():
    """Standard health endpoint compatible with Phase 1 expectations."""
    return check_liveness(legacy_compat=True)


@app.get("/live", tags=["System"])
@app.get("/api/health/live", tags=["System"])
def health_liveness_endpoint():
    """Liveness probe indicating application process is operational."""
    return check_liveness(legacy_compat=False)


@app.get("/ready", tags=["System"])
@app.get("/api/health/ready", tags=["System"])
def health_readiness_endpoint(db: Session = Depends(get_db)):
    """Readiness probe verifying operational health of database, scheduler, and dependencies."""
    res = check_readiness(db)
    if res["status"] == "UNHEALTHY":
        raise HTTPException(status_code=503, detail=res)
    return res


@app.get("/metrics", tags=["System"])
@app.get("/api/metrics", tags=["System"])
def operational_metrics_endpoint():
    """Exposes real-time operational performance, request latencies, and monitoring run statistics."""
    return metrics_collector.get_summary()


@app.get("/api/data-status", tags=["System"])
def data_status():
    return {
        "providers": {
            "copernicus_sentinel_2": "ONLINE",
            "copernicus_sentinel_1": "ONLINE",
            "copernicus_dem_glo30": "ONLINE",
            "usgs_earthquakes": "ONLINE",
            "openstreetmap": "ONLINE",
            "nasa_firms": "ONLINE",
            "groq_lpu": "ONLINE",
        },
        "mode": "REAL_DATA_ONLY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/overview", tags=["System"])
def get_system_overview(db: Session = Depends(get_db)):
    """
    Returns high-level operational statistics across all government critical locations.
    All metrics are computed live from the authoritative database.
    """
    from satguard.models.entities import Alert as DBAlert, MonitoringRun, RiskAssessment
    
    total_locations = db.query(CriticalLocation).count()
    active_monitoring_locations = (
        db.query(CriticalLocation)
        .filter(CriticalLocation.monitoring_status == "ACTIVE")
        .count()
    )
    
    # Compute high/critical risk location counts from latest RiskAssessments
    all_locs = db.query(CriticalLocation).all()
    high_risk_count = 0
    critical_risk_count = 0
    for loc in all_locs:
        latest_ra = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.location_id == loc.id)
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
        if latest_ra:
            if latest_ra.risk_level == "HIGH":
                high_risk_count += 1
            elif latest_ra.risk_level == "CRITICAL":
                critical_risk_count += 1

    active_alerts_count = db.query(DBAlert).filter(DBAlert.status == "ACTIVE").count()
    total_alerts_count = db.query(DBAlert).count()
    recent_runs_count = db.query(MonitoringRun).count()
    
    latest_run = db.query(MonitoringRun).order_by(MonitoringRun.created_at.desc()).first()
    data_freshness = (
        latest_run.created_at.isoformat()
        if latest_run and latest_run.created_at
        else datetime.now(timezone.utc).isoformat()
    )
    
    return {
        "total_locations": total_locations,
        "active_monitoring_locations": active_monitoring_locations,
        "high_risk_locations": high_risk_count,
        "critical_risk_locations": critical_risk_count,
        "active_alerts_count": active_alerts_count,
        "total_alerts_count": total_alerts_count,
        "recent_runs_count": recent_runs_count,
        "system_status": "OPERATIONAL",
        "mode": "REAL_DATA_ONLY",
        "data_freshness": data_freshness,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


import json
import re
from pydantic import BaseModel, Field


class LocationCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    location_type: str = Field(default="CRITICAL_INFRASTRUCTURE")
    radius_m: int = Field(default=5000, ge=100, le=100000)
    description: Optional[str] = None
    priority: str = Field(default="high")
    risk_category: str = Field(default="multi_hazard")


@app.get("/api/locations", tags=["Locations"])
def list_locations(db: Session = Depends(get_db)):
    from satguard.models.entities import RiskAssessment
    locs = db.query(CriticalLocation).all()
    result = []
    for loc in locs:
        data = loc.to_dict()
        latest_ra = (
            db.query(RiskAssessment)
            .filter(RiskAssessment.location_id == loc.id)
            .order_by(RiskAssessment.created_at.desc())
            .first()
        )
        if latest_ra:
            data["latest_risk"] = latest_ra.to_dict()
        result.append(data)
    return result


@app.post("/api/locations", tags=["Locations"])
def create_location(payload: LocationCreateRequest, db: Session = Depends(get_db)):
    """Registers a new critical location or custom point of interest for surveillance."""
    slug = re.sub(r"[^a-z0-9]+", "-", payload.name.lower()).strip("-")
    loc_id = f"loc-custom-{slug[:25]}-{int(datetime.now(timezone.utc).timestamp())}"
    
    geom = json.dumps({
        "type": "Point",
        "coordinates": [payload.longitude, payload.latitude]
    })
    
    new_loc = CriticalLocation(
        id=loc_id,
        name=payload.name,
        location_type=payload.location_type,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius_m=payload.radius_m,
        geometry=geom,
        priority=payload.priority,
        risk_category=payload.risk_category,
        monitoring_frequency="continuous_pass",
        monitoring_enabled=True,
        monitoring_interval_hours=24.0,
        monitoring_status="ACTIVE",
        description=payload.description or f"Custom surveillance zone for {payload.name}",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    db.add(new_loc)
    db.commit()
    db.refresh(new_loc)
    return new_loc.to_dict()


@app.get("/api/locations/{location_id}", tags=["Locations"])
def get_location(location_id: str, db: Session = Depends(get_db)):
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")
    return loc.to_dict()


@app.get("/api/locations/{location_id}/observations", tags=["Observations"])
def list_observations(location_id: str, db: Session = Depends(get_db)):
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")
    
    obs = (
        db.query(SatelliteObservation)
        .filter(SatelliteObservation.location_id == location_id)
        .order_by(SatelliteObservation.acquisition_time.desc())
        .all()
    )
    return [o.to_dict() for o in obs]


@app.post("/api/locations/{location_id}/check", tags=["Surveillance"])
def check_location_observations(location_id: str, db: Session = Depends(get_db)):
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    detector = ObservationDetector()
    result = detector.check_location(db=db, location=loc)
    return result


@app.post("/api/locations/{location_id}/process", tags=["Surveillance"])
def process_latest_observation(location_id: str, db: Session = Depends(get_db)):
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    # Find observation awaiting processing or latest available
    obs = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.location_id == location_id,
            SatelliteObservation.quality_status == "NEW_OBSERVATION_AVAILABLE",
        )
        .order_by(SatelliteObservation.acquisition_time.desc())
        .first()
    )

    if not obs:
        # Check if there is an unprocessed observation in catalog
        detector = ObservationDetector()
        check_res = detector.check_location(db=db, location=loc)
        if check_res.get("status") == "NEW_OBSERVATION_AVAILABLE":
            obs = db.query(SatelliteObservation).filter(SatelliteObservation.id == check_res["observation_id"]).first()
        else:
            return {
                "location_id": location_id,
                "status": check_res.get("status", "NO_NEW_OBSERVATION"),
                "message": "No observation currently queued for processing.",
            }

    pipeline = MonitoringPipeline()
    result = pipeline.process_observation(db=db, location=loc, observation=obs)
    return result


@app.get("/api/locations/{location_id}/changes", tags=["Analytics"])
def get_location_changes(location_id: str, db: Session = Depends(get_db)):
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    changes = (
        db.query(ChangeDetection)
        .filter(ChangeDetection.location_id == location_id)
        .order_by(ChangeDetection.created_at.desc())
        .all()
    )
    return [c.to_dict() for c in changes]


# ----------------------------------------------------------------------
# SENTINEL-1 SAR ENDPOINTS
# ----------------------------------------------------------------------
@app.get("/api/locations/{location_id}/sar/observations", tags=["SAR Analytics"])
def list_sar_observations(location_id: str, db: Session = Depends(get_db)):
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    obs = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.location_id == location_id,
            SatelliteObservation.sensor == "SAR-C",
        )
        .order_by(SatelliteObservation.acquisition_time.desc())
        .all()
    )
    return [o.to_dict() for o in obs]


@app.post("/api/locations/{location_id}/sar/process", tags=["SAR Analytics"])
def process_latest_sar_observation(location_id: str, db: Session = Depends(get_db)):
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    obs = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.location_id == location_id,
            SatelliteObservation.sensor == "SAR-C",
            SatelliteObservation.quality_status == "NEW_OBSERVATION_AVAILABLE",
        )
        .order_by(SatelliteObservation.acquisition_time.desc())
        .first()
    )

    if not obs:
        return {
            "location_id": location_id,
            "status": "NO_NEW_OBSERVATION",
            "message": "No unanalyzed Sentinel-1 SAR observation currently queued.",
        }

    pipeline = MonitoringPipeline()
    result = pipeline.process_sar_observation(db=db, location=loc, observation=obs)
    return result


@app.get("/api/locations/{location_id}/sar/changes", tags=["SAR Analytics"])
def get_sar_changes(location_id: str, db: Session = Depends(get_db)):
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    changes = (
        db.query(ChangeDetection)
        .filter(
            ChangeDetection.location_id == location_id,
            ChangeDetection.change_type.in_(["SAR_BACKSCATTER_CHANGE", "SURFACE_ROUGHNESS_CHANGE", "NO_CHANGE"]),
        )
        .order_by(ChangeDetection.created_at.desc())
        .all()
    )
    return [c.to_dict() for c in changes]


# ----------------------------------------------------------------------
# PHASE 2.1: SENTINEL-1 OBSERVATION DISCOVERY & FRESHNESS ENDPOINTS
# ----------------------------------------------------------------------
@app.get("/api/locations/{location_id}/sentinel-1/observations", tags=["Sentinel-1 Discovery"])
def get_sentinel1_observations(location_id: str, db: Session = Depends(get_db)):
    """
    Returns all registered Sentinel-1 SAR observations for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    obs = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.location_id == location_id,
            SatelliteObservation.sensor == "SAR-C",
        )
        .order_by(SatelliteObservation.acquisition_time.desc())
        .all()
    )
    return [o.to_dict() for o in obs]


@app.post("/api/locations/{location_id}/sentinel-1/check", tags=["Sentinel-1 Discovery"])
def check_sentinel1_freshness(
    location_id: str,
    lookback_days: int = Query(default=15, ge=1, le=60),
    polarization: Optional[str] = Query(default=None),
    orbit_direction: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Audits Copernicus catalog freshness for new Sentinel-1 observations.
    Returns NO_NEW_OBSERVATION if nothing newer exists, or NEW_OBSERVATION_AVAILABLE with structured metadata.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.ingestion.sentinel1_discovery import Sentinel1DiscoveryService

    service = Sentinel1DiscoveryService()
    try:
        result = service.check_freshness(
            db=db,
            location_id=location_id,
            lookback_days=lookback_days,
            polarization=polarization,
            orbit_direction=orbit_direction,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/locations/{location_id}/sentinel-1/observations/{observation_id}/retrieve",
    tags=["Sentinel-1 Retrieval"],
)
def retrieve_sentinel1_observation_endpoint(
    location_id: str,
    observation_id: str,
    db: Session = Depends(get_db),
):
    """
    Triggers idempotent retrieval of real Sentinel-1 SAR imagery from CDSE.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    obs = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.id == observation_id,
            SatelliteObservation.location_id == location_id,
        )
        .first()
    )
    if not obs:
        raise HTTPException(
            status_code=404,
            detail=f"Observation '{observation_id}' not found for location '{location_id}'",
        )

    from satguard.ingestion.sentinel1_retrieval import (
        retrieve_sentinel1_observation,
        CDSEAuthenticationError,
        CDSEProductNotFoundError,
        CDSEIntegrityError,
    )

    try:
        result = retrieve_sentinel1_observation(observation_id=observation_id, db=db)
        return result
    except (CDSEAuthenticationError, PermissionError) as e:
        raise HTTPException(status_code=401, detail=str(e))
    except (CDSEProductNotFoundError, FileNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (CDSEIntegrityError, ValueError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ----------------------------------------------------------------------
# PHASE 2 COMPLETE: SENTINEL-1 SAR PROCESSING & CHANGE DETECTION ENDPOINTS
# ----------------------------------------------------------------------
@app.post(
    "/api/locations/{location_id}/sentinel-1/observations/{observation_id}/process",
    tags=["Sentinel-1 SAR Processing"],
)
def process_sentinel1_observation_endpoint(
    location_id: str,
    observation_id: str,
    speckle_filter: Optional[str] = Query(default=None),
    force_reprocess: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """
    Executes SAR preprocessing, AOI masking, and dual-polarization (VV + VH) backscatter extraction in dB.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    obs = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.id == observation_id,
            SatelliteObservation.location_id == location_id,
        )
        .first()
    )
    if not obs:
        raise HTTPException(
            status_code=404,
            detail=f"Observation '{observation_id}' not found for location '{location_id}'",
        )

    from satguard.processing.sar import SARProcessor, SARValidationError

    processor = SARProcessor()
    try:
        result = processor.preprocess_observation(
            observation_id=observation_id,
            db=db,
            speckle_filter=speckle_filter,
            force_reprocess=force_reprocess,
        )
        return {
            "location_id": result["location_id"],
            "observation_id": result["observation_id"],
            "product_id": result["product_id"],
            "status": result["status"],
            "vv_raster": result["vv_raster"],
            "vh_raster": result["vh_raster"],
            "vv_mean_db": result["vv_mean_db"],
            "vh_mean_db": result["vh_mean_db"],
            "vv_statistics": result.get("vv_statistics"),
            "vh_statistics": result.get("vh_statistics"),
        }
    except SARValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/locations/{location_id}/sentinel-1/change",
    tags=["Sentinel-1 SAR Processing"],
)
def compute_sentinel1_change_endpoint(
    location_id: str,
    t1_observation_id: Optional[str] = Query(default=None),
    t2_observation_id: Optional[str] = Query(default=None),
    vv_threshold_db: float = Query(default=3.0, ge=0.5, le=15.0),
    vh_threshold_db: float = Query(default=3.0, ge=0.5, le=15.0),
    allow_cross_orbit: bool = Query(default=False),
    force_reprocess: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """
    Computes temporal SAR change detection between T1 and T2 observations.
    Validates acquisition geometry, calculates ΔVV and ΔVH, and generates a spatial change map.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.processing.sar import SARProcessor

    processor = SARProcessor(
        vv_change_threshold_db=vv_threshold_db,
        vh_change_threshold_db=vh_threshold_db,
    )
    try:
        result = processor.compare_observations(
            location_id=location_id,
            db=db,
            t1_observation_id=t1_observation_id,
            t2_observation_id=t2_observation_id,
            vv_threshold_db=vv_threshold_db,
            vh_threshold_db=vh_threshold_db,
            allow_cross_orbit=allow_cross_orbit,
            force_reprocess=force_reprocess,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/locations/{location_id}/sentinel-1/changes",
    tags=["Sentinel-1 SAR Processing"],
)
def get_sentinel1_changes_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns historical Sentinel-1 SAR change detection records for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import Sentinel1ChangeDetection

    changes = (
        db.query(Sentinel1ChangeDetection)
        .filter(Sentinel1ChangeDetection.location_id == location_id)
        .order_by(Sentinel1ChangeDetection.created_at.desc())
        .all()
    )
    return [c.to_dict() for c in changes]


# ----------------------------------------------------------------------
# PHASE 3: MULTI-SENSOR EVIDENCE FUSION ENDPOINTS
# ----------------------------------------------------------------------
@app.post(
    "/api/locations/{location_id}/evidence/fuse",
    tags=["Multi-Sensor Evidence Fusion"],
)
def fuse_evidence_endpoint(
    location_id: str,
    window_days: int = Query(default=40, ge=1, le=180),
    force_recompute: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """
    Executes unified multi-sensor evidence fusion across Sentinel-1, Sentinel-2,
    NASA GPM, NASA FIRMS, USGS Earthquake, and Copernicus DEM.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.fusion.engine import EvidenceFusionEngine

    engine = EvidenceFusionEngine()
    try:
        evidence = engine.fuse_location_evidence(
            db=db,
            location_id=location_id,
            window_days=window_days,
            force_recompute=force_recompute,
        )
        return evidence.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/locations/{location_id}/evidence/snapshots",
    tags=["Multi-Sensor Evidence Fusion"],
)
def list_evidence_snapshots_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Lists historical multi-sensor EvidenceSnapshots for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import EvidenceSnapshot

    snaps = (
        db.query(EvidenceSnapshot)
        .filter(EvidenceSnapshot.location_id == location_id)
        .order_by(EvidenceSnapshot.created_at.desc())
        .all()
    )
    return [s.to_dict() for s in snaps]


@app.get(
    "/api/locations/{location_id}/evidence/snapshots/{snapshot_id}",
    tags=["Multi-Sensor Evidence Fusion"],
)
def get_evidence_snapshot_endpoint(
    location_id: str,
    snapshot_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves a specific EvidenceSnapshot by ID.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import EvidenceSnapshot

    snap = (
        db.query(EvidenceSnapshot)
        .filter(
            EvidenceSnapshot.id == snapshot_id,
            EvidenceSnapshot.location_id == location_id,
        )
        .first()
    )
    if not snap:
        raise HTTPException(status_code=404, detail=f"Evidence snapshot '{snapshot_id}' not found")
    return snap.to_dict()


# ----------------------------------------------------------------------
# PHASE 4: RISK ASSESSMENT ENGINE ENDPOINTS
# ----------------------------------------------------------------------

@app.get(
    "/api/locations/{location_id}/risk",
    tags=["Risk Assessment"],
)
def list_risk_assessments_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Lists historical deterministic risk assessments for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import RiskAssessment

    assessments = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.location_id == location_id)
        .order_by(RiskAssessment.created_at.desc())
        .all()
    )
    return [a.to_dict() for a in assessments]


@app.get(
    "/api/locations/{location_id}/risk/latest",
    tags=["Risk Assessment"],
)
def get_latest_risk_assessment_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves the most recent deterministic risk assessment for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import RiskAssessment

    latest = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.location_id == location_id)
        .order_by(RiskAssessment.created_at.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail=f"No risk assessment found for location '{location_id}'")
    return latest.to_dict()


@app.post(
    "/api/locations/{location_id}/risk/assess",
    tags=["Risk Assessment"],
)
def trigger_risk_assessment_endpoint(
    location_id: str,
    snapshot_id: Optional[str] = Query(None, description="Optional specific EvidenceSnapshot ID to assess"),
    db: Session = Depends(get_db),
):
    """
    Executes deterministic risk assessment on latest or specified EvidenceSnapshot.
    Calculates normalized score, assigns risk level and monitoring priority, evaluates evidence strength,
    records uncertainty factors, and persists the auditable RiskAssessment record.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import EvidenceSnapshot
    from satguard.risk.engine import RiskAssessmentEngine
    from satguard.fusion.engine import EvidenceFusionEngine

    # 1. Load target evidence snapshot
    if snapshot_id:
        snap = (
            db.query(EvidenceSnapshot)
            .filter(
                EvidenceSnapshot.id == snapshot_id,
                EvidenceSnapshot.location_id == location_id,
            )
            .first()
        )
        if not snap:
            raise HTTPException(status_code=404, detail=f"Evidence snapshot '{snapshot_id}' not found")
    else:
        snap = (
            db.query(EvidenceSnapshot)
            .filter(EvidenceSnapshot.location_id == location_id)
            .order_by(EvidenceSnapshot.created_at.desc())
            .first()
        )
        if not snap:
            # Fuse evidence on-the-fly if not already fused
            logger.info(f"No existing EvidenceSnapshot for {location_id}; initiating evidence fusion...")
            fusion_engine = EvidenceFusionEngine()
            snap_obj = fusion_engine.fuse_location_evidence(db=db, location_id=location_id)
            snap = db.query(EvidenceSnapshot).filter(EvidenceSnapshot.id == snap_obj.id).first()

    if not snap:
        raise HTTPException(status_code=404, detail="Failed to load or generate multi-sensor evidence for risk assessment")

    # 2. Run deterministic risk assessment engine
    risk_engine = RiskAssessmentEngine()
    result = risk_engine.assess_and_persist(db=db, evidence=snap, location_name=loc.name)
    return result.model_dump()


# ----------------------------------------------------------------------
# PHASE 5: GROQ EVIDENCE ANALYST ENDPOINTS
# ----------------------------------------------------------------------

@app.post(
    "/api/locations/{location_id}/analysis",
    tags=["Evidence Analyst"],
)
def trigger_evidence_analysis_endpoint(
    location_id: str,
    snapshot_id: Optional[str] = Query(None, description="Optional specific EvidenceSnapshot ID"),
    assessment_id: Optional[str] = Query(None, description="Optional specific RiskAssessment ID"),
    db: Session = Depends(get_db),
):
    """
    Executes Groq Evidence Analyst report generation.
    Collates latest MultiSensorEvidence and authoritative RiskAssessment, invokes Groq LPU inference,
    validates risk immutability and schema structure, and persists the AnalystReport.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.analyst.engine import (
        EvidenceAnalystEngine,
        GroqConfigurationError,
        GroqInferenceError,
        ReportValidationError,
    )

    analyst_engine = EvidenceAnalystEngine()
    if not analyst_engine.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Groq Evidence Analyst is not configured. Please supply a valid GROQ_API_KEY.",
        )

    try:
        report = analyst_engine.generate_and_persist(
            db=db,
            location_id=location_id,
            snapshot_id=snapshot_id,
            assessment_id=assessment_id,
        )
        return report.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (GroqInferenceError, ReportValidationError) as e:
        raise HTTPException(status_code=502, detail=f"Evidence Analyst execution error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during evidence analysis: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during evidence analysis.")


@app.get(
    "/api/locations/{location_id}/analysis/latest",
    tags=["Evidence Analyst"],
)
def get_latest_analyst_report_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves the most recent Groq Evidence Analyst report for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import AnalystReport as DBAnalystReport

    latest = (
        db.query(DBAnalystReport)
        .filter(DBAnalystReport.location_id == location_id)
        .order_by(DBAnalystReport.created_at.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail=f"No analyst report found for location '{location_id}'")
    return latest.to_dict()


@app.get(
    "/api/locations/{location_id}/analysis",
    tags=["Evidence Analyst"],
)
def list_analyst_reports_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Lists historical Groq Evidence Analyst reports for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import AnalystReport as DBAnalystReport

    reports = (
        db.query(DBAnalystReport)
        .filter(DBAnalystReport.location_id == location_id)
        .order_by(DBAnalystReport.created_at.desc())
        .all()
    )
    return [r.to_dict() for r in reports]


# ----------------------------------------------------------------------
# PHASE 6: GOVERNMENT ALERT & DECISION SUPPORT ENDPOINTS
# ----------------------------------------------------------------------

@app.post(
    "/api/locations/{location_id}/alerts/generate",
    tags=["Government Alerts & Decision Support"],
)
def generate_location_alert_endpoint(
    location_id: str,
    risk_assessment_id: Optional[str] = Query(None, description="Optional specific RiskAssessment ID"),
    analyst_report_id: Optional[str] = Query(None, description="Optional specific AnalystReport ID"),
    db: Session = Depends(get_db),
):
    """
    Generates a deterministic government surveillance alert from authoritative Phase 4 RiskAssessment
    and validated Phase 5 AnalystReport. Enforces duplicate suppression and escalation history.
    """
    from satguard.alert.engine import AlertDecisionEngine

    engine = AlertDecisionEngine()
    try:
        alert_result = engine.generate_and_persist(
            db=db,
            location_id=location_id,
            risk_assessment_id=risk_assessment_id,
            analyst_report_id=analyst_report_id,
        )
        return alert_result.model_dump(mode="json")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating alert for {location_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during alert generation.")


@app.get(
    "/api/locations/{location_id}/alerts",
    tags=["Government Alerts & Decision Support"],
)
def list_location_alerts_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns historical government surveillance alerts for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import Alert as DBAlert

    alerts = (
        db.query(DBAlert)
        .filter(DBAlert.location_id == location_id)
        .order_by(DBAlert.created_at.desc())
        .all()
    )
    return [a.to_dict() for a in alerts]


@app.get(
    "/api/locations/{location_id}/alerts/active",
    tags=["Government Alerts & Decision Support"],
)
def list_active_location_alerts_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns currently ACTIVE government surveillance alerts for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import Alert as DBAlert

    alerts = (
        db.query(DBAlert)
        .filter(
            DBAlert.location_id == location_id,
            DBAlert.status == "ACTIVE",
        )
        .order_by(DBAlert.created_at.desc())
        .all()
    )
    return [a.to_dict() for a in alerts]


@app.get(
    "/api/locations/{location_id}/alerts/latest",
    tags=["Government Alerts & Decision Support"],
)
def get_latest_location_alert_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns the latest government surveillance alert for a critical location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import Alert as DBAlert

    latest = (
        db.query(DBAlert)
        .filter(DBAlert.location_id == location_id)
        .order_by(DBAlert.created_at.desc())
        .first()
    )
    if not latest:
        raise HTTPException(status_code=404, detail=f"No alerts found for location '{location_id}'")
    return latest.to_dict()


@app.post(
    "/api/alerts/{alert_id}/acknowledge",
    tags=["Government Alerts & Decision Support"],
)
def acknowledge_alert_endpoint(
    alert_id: str,
    payload: Optional[dict] = None,
    current_user: User = Depends(require_role(RoleEnum.OPERATOR)),
    db: Session = Depends(get_db),
):
    """
    Transition alert status: ACTIVE -> ACKNOWLEDGED.
    Protected by RBAC: Requires minimum OPERATOR role.
    """
    from satguard.alert.engine import AlertDecisionEngine

    engine = AlertDecisionEngine()
    actor = (payload or {}).get("actor") or (current_user.username if current_user else "operator")
    note = (payload or {}).get("note")

    try:
        res = engine.acknowledge_alert(db=db, alert_id=alert_id, actor=actor, note=note)
        record_audit_event(
            db=db,
            actor=actor,
            role=current_user.role if current_user else "OPERATOR",
            action="ALERT_ACKNOWLEDGE",
            resource="alert",
            resource_id=alert_id,
            result="SUCCESS",
            metadata={"note": note},
        )
        return res.model_dump(mode="json")
    except ValueError as e:
        record_audit_event(
            db=db,
            actor=actor,
            role=current_user.role if current_user else "OPERATOR",
            action="ALERT_ACKNOWLEDGE",
            resource="alert",
            resource_id=alert_id,
            result="FAILURE",
            metadata={"error": str(e)},
        )
        raise HTTPException(status_code=404, detail=str(e))


@app.post(
    "/api/alerts/{alert_id}/review",
    tags=["Government Alerts & Decision Support"],
)
def review_alert_endpoint(
    alert_id: str,
    payload: Optional[dict] = None,
    current_user: User = Depends(require_role(RoleEnum.OPERATOR)),
    db: Session = Depends(get_db),
):
    """
    Transition alert status: ACKNOWLEDGED / ACTIVE -> IN_REVIEW.
    Protected by RBAC: Requires minimum OPERATOR role.
    """
    from satguard.alert.engine import AlertDecisionEngine

    engine = AlertDecisionEngine()
    actor = (payload or {}).get("actor") or (current_user.username if current_user else "operator")
    note = (payload or {}).get("note")

    try:
        res = engine.start_review(db=db, alert_id=alert_id, actor=actor, note=note)
        record_audit_event(
            db=db,
            actor=actor,
            role=current_user.role if current_user else "OPERATOR",
            action="ALERT_REVIEW",
            resource="alert",
            resource_id=alert_id,
            result="SUCCESS",
            metadata={"note": note},
        )
        return res.model_dump(mode="json")
    except ValueError as e:
        record_audit_event(
            db=db,
            actor=actor,
            role=current_user.role if current_user else "OPERATOR",
            action="ALERT_REVIEW",
            resource="alert",
            resource_id=alert_id,
            result="FAILURE",
            metadata={"error": str(e)},
        )
        raise HTTPException(status_code=404, detail=str(e))


@app.post(
    "/api/alerts/{alert_id}/resolve",
    tags=["Government Alerts & Decision Support"],
)
def resolve_alert_endpoint(
    alert_id: str,
    payload: Optional[dict] = None,
    current_user: User = Depends(require_role(RoleEnum.SUPERVISOR)),
    db: Session = Depends(get_db),
):
    """
    Transition alert status to RESOLVED.
    Protected by RBAC: Requires minimum SUPERVISOR role.
    """
    from satguard.alert.engine import AlertDecisionEngine

    engine = AlertDecisionEngine()
    actor = (payload or {}).get("actor") or (current_user.username if current_user else "supervisor")
    note = (payload or {}).get("note")

    try:
        res = engine.resolve_alert(db=db, alert_id=alert_id, actor=actor, note=note)
        record_audit_event(
            db=db,
            actor=actor,
            role=current_user.role if current_user else "SUPERVISOR",
            action="ALERT_RESOLVE",
            resource="alert",
            resource_id=alert_id,
            result="SUCCESS",
            metadata={"note": note},
        )
        return res.model_dump(mode="json")
    except ValueError as e:
        record_audit_event(
            db=db,
            actor=actor,
            role=current_user.role if current_user else "SUPERVISOR",
            action="ALERT_RESOLVE",
            resource="alert",
            resource_id=alert_id,
            result="FAILURE",
            metadata={"error": str(e)},
        )
        raise HTTPException(status_code=404, detail=str(e))


@app.get(
    "/api/alerts",
    tags=["Government Alerts & Decision Support"],
)
def list_all_alerts_endpoint(
    location_id: Optional[str] = Query(None, description="Filter by location ID"),
    status: Optional[str] = Query(None, description="Filter by alert status"),
    priority: Optional[str] = Query(None, description="Filter by alert priority"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Returns unified list of government surveillance alerts across all locations,
    enriched with location metadata.
    """
    from satguard.models.entities import Alert as DBAlert
    query = db.query(DBAlert)
    if location_id:
        query = query.filter(DBAlert.location_id == location_id)
    if status:
        query = query.filter(DBAlert.status == status.upper())
    if priority:
        query = query.filter(DBAlert.priority == priority.upper())

    alerts = query.order_by(DBAlert.created_at.desc()).offset(offset).limit(limit).all()
    loc_names = {loc.id: loc.name for loc in db.query(CriticalLocation).all()}
    res = []
    for a in alerts:
        d = a.to_dict()
        d["location_name"] = loc_names.get(a.location_id, a.location_id)
        res.append(d)
    return res


@app.get(
    "/api/alerts/{alert_id}",
    tags=["Government Alerts & Decision Support"],
)
def get_alert_detail_endpoint(
    alert_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns single government surveillance alert details, including audit trail history.
    """
    from satguard.models.entities import Alert as DBAlert
    alert = db.query(DBAlert).filter(DBAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' not found")
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == alert.location_id).first()
    d = alert.to_dict()
    d["location_name"] = loc.name if loc else alert.location_id
    d["events"] = [e.to_dict() for e in alert.events] if hasattr(alert, "events") and alert.events else []
    return d


@app.get(
    "/api/locations/{location_id}/timeline",
    tags=["Analytics"],
)
def get_location_timeline_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Provides a chronological event timeline for a critical location combining:
    Sentinel-2 optical observations, Sentinel-1 SAR observations & changes,
    Multi-sensor evidence fusions, Risk assessments, Analyst reports, Alerts, and Monitoring runs.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Critical location not found")

    from satguard.models.entities import (
        SatelliteObservation,
        Sentinel1Retrieval,
        Sentinel1ChangeDetection,
        EvidenceSnapshot,
        RiskAssessment,
        AnalystReport,
        Alert as DBAlert,
        MonitoringRun,
    )

    events = []
    # 1. S2 Optical Observations
    s2_obs = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.location_id == location_id,
            SatelliteObservation.sensor != "SAR-C",
        )
        .all()
    )
    for o in s2_obs:
        t = o.acquisition_time.isoformat() if o.acquisition_time else None
        if t:
            cloud_val = getattr(o, "cloud_cover", None)
            events.append({
                "id": o.id,
                "event_type": "SENTINEL_2_OBSERVATION",
                "timestamp": t,
                "title": "Sentinel-2 Optical Observation",
                "summary": f"Cloud coverage: {cloud_val:.1f}%" if cloud_val is not None else "Optical observation recorded",
                "details": {
                    "product_id": o.product_id,
                    "cloud_cover": cloud_val,
                    "quality_status": getattr(o, "quality_status", None),
                },
            })

    # 2. S1 SAR Observations
    s1_obs = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.location_id == location_id,
            SatelliteObservation.sensor == "SAR-C",
        )
        .all()
    )
    for o in s1_obs:
        t = o.acquisition_time.isoformat() if o.acquisition_time else None
        if t:
            events.append({
                "id": o.id,
                "event_type": "SENTINEL_1_OBSERVATION",
                "timestamp": t,
                "title": "Sentinel-1 SAR Observation",
                "summary": "C-band SAR radar observation",
                "details": {
                    "product_id": o.product_id,
                    "quality_status": getattr(o, "quality_status", None),
                },
            })

    # 3. SAR Change Detections
    s1_changes = db.query(Sentinel1ChangeDetection).filter(Sentinel1ChangeDetection.location_id == location_id).all()
    for c in s1_changes:
        t = c.t2_acquisition_time.isoformat() if c.t2_acquisition_time else (c.created_at.isoformat() if c.created_at else None)
        if t:
            events.append({
                "id": c.id,
                "event_type": "SAR_CHANGE_DETECTION",
                "timestamp": t,
                "title": "Sentinel-1 SAR Change Detection",
                "summary": f"Significant SAR change detected ({c.changed_percentage:.1f}% pixels)",
                "details": {
                    "t1_product_id": c.t1_product_id,
                    "t2_product_id": c.t2_product_id,
                    "changed_percentage": c.changed_percentage,
                    "delta_vv_statistics": c.delta_vv_statistics,
                    "delta_vh_statistics": c.delta_vh_statistics,
                },
            })

    # 4. Evidence Fusion Snapshots
    snapshots = db.query(EvidenceSnapshot).filter(EvidenceSnapshot.location_id == location_id).all()
    for s in snapshots:
        t = s.created_at.isoformat() if s.created_at else None
        if t:
            events.append({
                "id": s.id,
                "event_type": "EVIDENCE_FUSION",
                "timestamp": t,
                "title": "Multi-Sensor Evidence Fusion",
                "summary": "Multi-sensor evidence alignment and spatial-temporal fusion snapshot",
                "details": {
                    "has_s1": s.sentinel1_evidence is not None,
                    "has_s2": s.sentinel2_evidence is not None,
                    "has_terrain": s.terrain_evidence is not None,
                },
            })

    # 5. Risk Assessments
    risks = db.query(RiskAssessment).filter(RiskAssessment.location_id == location_id).all()
    for r in risks:
        t = r.created_at.isoformat() if r.created_at else None
        if t:
            events.append({
                "id": r.id,
                "event_type": "RISK_ASSESSMENT",
                "timestamp": t,
                "title": f"Risk Assessment: {r.risk_level}",
                "summary": f"Authoritative Score: {r.score:.2f} / 100 | Priority: {r.monitoring_priority}",
                "details": {
                    "score": r.score,
                    "risk_level": r.risk_level,
                    "monitoring_priority": r.monitoring_priority,
                    "evidence_strength": r.evidence_strength,
                    "recommended_action": r.recommended_action,
                },
            })

    # 6. Analyst Reports
    reports = db.query(AnalystReport).filter(AnalystReport.location_id == location_id).all()
    for rep in reports:
        t = rep.created_at.isoformat() if rep.created_at else None
        if t:
            events.append({
                "id": rep.id,
                "event_type": "ANALYST_REPORT",
                "timestamp": t,
                "title": f"Groq Evidence Analyst Report ({rep.model})",
                "summary": (rep.executive_summary[:160] + "...") if rep.executive_summary and len(rep.executive_summary) > 160 else (rep.executive_summary or "Report generated"),
                "details": {
                    "model": rep.model,
                    "prompt_version": rep.prompt_version,
                    "validation_status": rep.validation_status,
                },
            })

    # 7. Alerts
    alerts = db.query(DBAlert).filter(DBAlert.location_id == location_id).all()
    for a in alerts:
        t = a.created_at.isoformat() if a.created_at else None
        if t:
            events.append({
                "id": a.id,
                "event_type": "GOVERNMENT_ALERT",
                "timestamp": t,
                "title": f"Government Alert: {a.priority} ({a.status})",
                "summary": a.title or a.summary or "Government surveillance alert",
                "details": {
                    "priority": a.priority,
                    "status": a.status,
                    "alert_level": a.alert_level,
                    "recommended_action": a.recommended_action,
                },
            })

    # 8. Monitoring Runs
    runs = db.query(MonitoringRun).filter(MonitoringRun.location_id == location_id).all()
    for run in runs:
        t = run.created_at.isoformat() if run.created_at else None
        if t:
            events.append({
                "id": run.id,
                "event_type": "MONITORING_RUN",
                "timestamp": t,
                "title": f"Monitoring Run ({run.trigger_type}) - {run.status}",
                "summary": f"Current stage: {run.current_stage}, Outcome: {run.outcome_code or 'N/A'}",
                "details": {
                    "trigger_type": run.trigger_type,
                    "status": run.status,
                    "current_stage": run.current_stage,
                    "outcome_code": run.outcome_code,
                    "observations_checked": run.observations_checked,
                    "observations_processed": run.observations_processed,
                },
            })

    events.sort(key=lambda x: x["timestamp"], reverse=True)
    return events


# ==============================================================================
# PHASE 7 — CONTINUOUS MONITORING & AUTOMATED REASSESSMENT ENDPOINTS
# ==============================================================================

from satguard.monitoring.schema import (
    MonitoringTriggerRequest,
    MonitoringConfigureRequest,
    MonitoringRunSummary,
    MonitoringRunDetail,
    LocationMonitoringStatusResponse,
    MonitoringTriggerTypeEnum,
)
from satguard.monitoring.orchestrator import ContinuousMonitoringOrchestrator
from satguard.models.entities import (
    MonitoringRun,
    EvidenceSnapshot,
    RiskAssessment,
    AnalystReport as DBAnalystReport,
    Alert as DBAlert,
)


@app.post(
    "/api/locations/{location_id}/monitoring/run",
    tags=["Continuous Monitoring"],
    response_model=MonitoringRunDetail,
)
def trigger_location_monitoring_endpoint(
    location_id: str,
    payload: Optional[MonitoringTriggerRequest] = None,
    current_user: User = Depends(require_role(RoleEnum.OPERATOR)),
    db: Session = Depends(get_db),
):
    """
    Manually triggers an immediate continuous monitoring run for a specific sovereign critical location.
    Enforces concurrency protection, RBAC authorization, and records complete stage audit history.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    orchestrator = ContinuousMonitoringOrchestrator()
    triggered_by = (payload.triggered_by if payload else None) or (current_user.username if current_user else "manual_api_operator")
    force = payload.force if payload else True

    run = orchestrator.execute_monitoring_run(
        location_id=location_id,
        trigger_type=MonitoringTriggerTypeEnum.MANUAL,
        triggered_by=triggered_by,
        force=force,
    )

    record_audit_event(
        db=db,
        actor=triggered_by,
        role=current_user.role if current_user else "OPERATOR",
        action="MONITORING_TRIGGER",
        resource="critical_location",
        resource_id=location_id,
        result="SUCCESS" if run.status != "FAILED" else "FAILURE",
        metadata={"run_id": run.id, "status": run.status},
    )

    res_dict = run.to_dict()
    if not res_dict.get("location_name") and loc:
        res_dict["location_name"] = loc.name
    return res_dict


@app.post(
    "/api/monitoring/run",
    tags=["Continuous Monitoring"],
)
def trigger_monitoring_pipeline_endpoint(
    payload: Optional[MonitoringTriggerRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Triggers monitoring execution across specified location or all due locations.
    """
    orchestrator = ContinuousMonitoringOrchestrator()
    triggered_by = payload.triggered_by if payload else "api_operator"
    force = payload.force if payload else False

    if payload and payload.location_id:
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == payload.location_id).first()
        if not loc:
            raise HTTPException(status_code=404, detail=f"Critical location '{payload.location_id}' not found.")
        run = orchestrator.execute_monitoring_run(
            location_id=payload.location_id,
            trigger_type=MonitoringTriggerTypeEnum.MANUAL,
            triggered_by=triggered_by,
            force=force,
        )
        return {"dispatched": 1, "runs": [run.to_dict()]}

    # Run for all due locations
    from satguard.monitoring.scheduler import scheduler
    due_runs = scheduler.poll_and_execute_due_locations()
    return {"dispatched": len(due_runs), "runs": due_runs}


@app.get(
    "/api/locations/{location_id}/monitoring/status",
    tags=["Continuous Monitoring"],
    response_model=LocationMonitoringStatusResponse,
)
def get_location_monitoring_status_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns real-time operational continuous monitoring status, latest observation timestamps,
    next scheduled cycle, and authoritative latest risk/alert references.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    # Latest runs
    last_run_rec = (
        db.query(MonitoringRun)
        .filter(MonitoringRun.location_id == location_id)
        .order_by(MonitoringRun.started_at.desc())
        .first()
    )
    last_failed_rec = (
        db.query(MonitoringRun)
        .filter(
            MonitoringRun.location_id == location_id,
            MonitoringRun.status == "FAILED",
        )
        .order_by(MonitoringRun.started_at.desc())
        .first()
    )
    active_run_rec = (
        db.query(MonitoringRun)
        .filter(
            MonitoringRun.location_id == location_id,
            MonitoringRun.status == "RUNNING",
        )
        .order_by(MonitoringRun.started_at.desc())
        .first()
    )

    # Latest observation
    latest_obs = (
        db.query(SatelliteObservation)
        .filter(SatelliteObservation.location_id == location_id)
        .order_by(SatelliteObservation.acquisition_time.desc())
        .first()
    )
    obs_count = (
        db.query(SatelliteObservation)
        .filter(
            SatelliteObservation.location_id == location_id,
            SatelliteObservation.quality_status == "ANALYSIS_COMPLETE",
        )
        .count()
    )

    # Latest evidence snapshot
    latest_snap = (
        db.query(EvidenceSnapshot)
        .filter(EvidenceSnapshot.location_id == location_id)
        .order_by(EvidenceSnapshot.created_at.desc())
        .first()
    )

    # Latest authoritative risk assessment
    latest_risk = (
        db.query(RiskAssessment)
        .filter(RiskAssessment.location_id == location_id)
        .order_by(RiskAssessment.created_at.desc())
        .first()
    )

    # Latest alert
    latest_alert = (
        db.query(DBAlert)
        .filter(DBAlert.location_id == location_id)
        .order_by(DBAlert.created_at.desc())
        .first()
    )

    return LocationMonitoringStatusResponse(
        location_id=loc.id,
        location_name=loc.name,
        monitoring_enabled=bool(loc.monitoring_enabled),
        monitoring_status=loc.monitoring_status or "ACTIVE",
        monitoring_interval_hours=float(loc.monitoring_interval_hours or 24.0),
        last_run=last_run_rec.started_at if last_run_rec else None,
        last_successful_run=loc.last_successful_run,
        last_failed_run=last_failed_rec.started_at if last_failed_rec else None,
        next_scheduled_run=loc.next_scheduled_run,
        active_run=active_run_rec.to_dict() if active_run_rec else None,
        last_observation_check=loc.last_observation_check,
        last_processed_observation=latest_obs.product_id if latest_obs else None,
        observations_processed_count=obs_count,
        latest_evidence_snapshot_id=latest_snap.id if latest_snap else None,
        latest_risk_assessment=latest_risk.to_dict() if latest_risk else None,
        latest_alert=latest_alert.to_dict() if latest_alert else None,
    )


@app.patch(
    "/api/locations/{location_id}/monitoring/config",
    tags=["Continuous Monitoring"],
)
def configure_location_monitoring_endpoint(
    location_id: str,
    payload: MonitoringConfigureRequest,
    db: Session = Depends(get_db),
):
    """
    Configures continuous monitoring settings for a critical sovereign location.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    if payload.monitoring_enabled is not None:
        loc.monitoring_enabled = payload.monitoring_enabled
    if payload.monitoring_interval_hours is not None:
        loc.monitoring_interval_hours = payload.monitoring_interval_hours
    if payload.monitoring_status is not None:
        loc.monitoring_status = payload.monitoring_status.value

    db.commit()
    db.refresh(loc)
    return {
        "location_id": loc.id,
        "monitoring_enabled": loc.monitoring_enabled,
        "monitoring_interval_hours": loc.monitoring_interval_hours,
        "monitoring_status": loc.monitoring_status,
    }


@app.get(
    "/api/monitoring/runs",
    tags=["Continuous Monitoring"],
    response_model=List[MonitoringRunSummary],
)
def list_monitoring_runs_endpoint(
    location_id: Optional[str] = Query(None, description="Filter by location ID"),
    status: Optional[str] = Query(None, description="Filter by run status"),
    trigger_type: Optional[str] = Query(None, description="Filter by trigger type"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Returns paginated history of continuous monitoring runs.
    """
    query = db.query(MonitoringRun)
    if location_id:
        query = query.filter(MonitoringRun.location_id == location_id)
    if status:
        query = query.filter(MonitoringRun.status == status.upper())
    if trigger_type:
        query = query.filter(MonitoringRun.trigger_type == trigger_type.upper())

    runs = query.order_by(MonitoringRun.created_at.desc()).offset(offset).limit(limit).all()
    return [r.to_dict() for r in runs]


@app.get(
    "/api/monitoring/runs/{run_id}",
    tags=["Continuous Monitoring"],
    response_model=MonitoringRunDetail,
)
def get_monitoring_run_detail_endpoint(
    run_id: str,
    db: Session = Depends(get_db),
):
    """
    Returns complete detailed audit trace for a specific monitoring run,
    including chronological stage transitions, error records, and referenced evidence/risk/alert IDs.
    """
    run = db.query(MonitoringRun).filter(MonitoringRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Monitoring run '{run_id}' not found.")
    return run.to_dict()


# ==============================================================================
# PHASE 9 — HISTORICAL INTELLIGENCE & TREND ANALYTICS ENDPOINTS
# ==============================================================================

from satguard.analytics.historical import HistoricalAnalyticsService
from satguard.analytics.schemas import HistoricalAnalyticsReport


@app.get(
    "/api/locations/{location_id}/analytics/history",
    tags=["Historical Intelligence"],
    response_model=HistoricalAnalyticsReport,
)
def get_location_historical_analytics_endpoint(
    location_id: str,
    days: int = Query(30, ge=1, le=1825, description="Time window in days (e.g. 7, 30, 90, 180, 365)"),
    start_time: Optional[datetime] = Query(None, description="Custom start timestamp (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="Custom end timestamp (ISO-8601)"),
    db: Session = Depends(get_db),
):
    """
    Returns comprehensive historical analytics across SAR, optical, environmental context,
    deterministic risk trends, alert recurrence, and baseline statistical comparison.
    Adheres to conservative, non-predictive government decision-support semantics.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    service = HistoricalAnalyticsService(db)
    report = service.generate_report(
        location_id=location_id,
        days=days,
        start_time=start_time,
        end_time=end_time,
        persist_snapshot=True,
    )
    return report


@app.get(
    "/api/locations/{location_id}/analytics/trends",
    tags=["Historical Intelligence"],
)
def get_location_trends_endpoint(
    location_id: str,
    days: int = Query(30, ge=1, le=1825),
    db: Session = Depends(get_db),
):
    """
    Returns descriptive trend metrics for SAR, optical scenes, risk assessments, and alert history.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    service = HistoricalAnalyticsService(db)
    report = service.generate_report(location_id=location_id, days=days, persist_snapshot=False)
    return {
        "location_id": location_id,
        "window": report.window.model_dump(),
        "sar_trends": report.sar_trends.model_dump(),
        "optical_trends": report.optical_trends.model_dump(),
        "risk_trends": report.risk_trends.model_dump(),
        "alert_trends": report.alert_trends.model_dump(),
        "disclaimer": report.disclaimer,
    }


@app.get(
    "/api/locations/{location_id}/analytics/baseline",
    tags=["Historical Intelligence"],
)
def get_location_baseline_endpoint(
    location_id: str,
    days: int = Query(90, ge=1, le=1825),
    db: Session = Depends(get_db),
):
    """
    Returns location-specific historical baseline and current statistical deviation status.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    service = HistoricalAnalyticsService(db)
    report = service.generate_report(location_id=location_id, days=days, persist_snapshot=False)
    return {
        "location_id": location_id,
        "window": report.window.model_dump(),
        "baseline_comparison": report.baseline_comparison.model_dump(),
        "data_sufficiency": report.data_sufficiency.value,
        "disclaimer": report.disclaimer,
    }


@app.get(
    "/api/locations/{location_id}/analytics/persistence",
    tags=["Historical Intelligence"],
)
def get_location_persistence_endpoint(
    location_id: str,
    days: int = Query(30, ge=1, le=1825),
    db: Session = Depends(get_db),
):
    """
    Returns deterministic persistence detection distinguishing isolated, intermittent, and persistent change signals.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    service = HistoricalAnalyticsService(db)
    report = service.generate_report(location_id=location_id, days=days, persist_snapshot=False)
    return {
        "location_id": location_id,
        "window": report.window.model_dump(),
        "persistence": report.persistence.model_dump(),
        "disclaimer": report.disclaimer,
    }


@app.get(
    "/api/locations/{location_id}/analytics/risk-history",
    tags=["Historical Intelligence"],
)
def get_location_risk_history_endpoint(
    location_id: str,
    days: int = Query(90, ge=1, le=1825),
    db: Session = Depends(get_db),
):
    """
    Returns immutable historical risk assessment trajectory and trend classification.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    service = HistoricalAnalyticsService(db)
    report = service.generate_report(location_id=location_id, days=days, persist_snapshot=False)
    return {
        "location_id": location_id,
        "window": report.window.model_dump(),
        "risk_trends": report.risk_trends.model_dump(),
        "disclaimer": report.disclaimer,
    }


@app.get(
    "/api/locations/{location_id}/analytics/alerts-history",
    tags=["Historical Intelligence"],
)
def get_location_alerts_history_endpoint(
    location_id: str,
    days: int = Query(90, ge=1, le=1825),
    db: Session = Depends(get_db),
):
    """
    Returns historical alert counts, lifecycle states, and recurrence pattern detection.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    service = HistoricalAnalyticsService(db)
    report = service.generate_report(location_id=location_id, days=days, persist_snapshot=False)
    return {
        "location_id": location_id,
        "window": report.window.model_dump(),
        "alert_trends": report.alert_trends.model_dump(),
        "disclaimer": report.disclaimer,
    }


@app.get(
    "/api/locations/{location_id}/analytics/latest",
    tags=["Historical Intelligence"],
)
def get_latest_analytics_snapshot_endpoint(
    location_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves the most recent persisted HistoricalAnalyticsSnapshot for fast dashboard load.
    Falls back to generating a fresh snapshot if none exists.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    service = HistoricalAnalyticsService(db)
    snapshot = service.get_latest_snapshot(location_id)
    if snapshot:
        return snapshot.to_dict()

    # Generate fresh snapshot
    report = service.generate_report(location_id=location_id, days=30, persist_snapshot=True)
    snapshot = service.get_latest_snapshot(location_id)
    return snapshot.to_dict() if snapshot else report.model_dump()


@app.get(
    "/api/analytics/compare",
    tags=["Historical Intelligence"],
)
def compare_locations_endpoint(
    location_ids: str = Query(..., description="Comma-separated critical location IDs"),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Comparative deterministic analytics across multiple government critical locations.
    Does not use arbitrary ranking formulas.
    """
    ids = [lid.strip() for lid in location_ids.split(",") if lid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="At least one location ID must be provided.")

    service = HistoricalAnalyticsService(db)
    results = []
    for lid in ids:
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == lid).first()
        if not loc:
            continue
        report = service.generate_report(location_id=lid, days=days, persist_snapshot=False)
        results.append({
            "location_id": lid,
            "location_name": loc.name,
            "type": loc.location_type,
            "data_sufficiency": report.data_sufficiency.value,
            "persistence_status": report.persistence.persistence_status.value,
            "risk_trend": report.risk_trends.classification.value,
            "latest_risk_score": report.risk_trends.latest_score,
            "average_risk_score": report.risk_trends.average_score,
            "sar_observation_count": report.sar_trends.observation_count,
            "sar_mean_changed_pct": report.sar_trends.mean_changed_percentage,
            "alert_count": report.alert_trends.total_alerts,
            "alert_recurrence": report.alert_trends.recurrence_detected,
        })

    return {
        "comparison_count": len(results),
        "days": days,
        "locations": results,
        "disclaimer": "Comparative metrics reflect deterministic monitoring signals. No ranking formula is implied.",
    }


@app.get(
    "/api/locations/{location_id}/analytics/report",
    tags=["Historical Intelligence"],
)
def export_historical_report_endpoint(
    location_id: str,
    days: int = Query(30, ge=1, le=1825),
    db: Session = Depends(get_db),
):
    """
    Returns an exportable, government-grade structured historical intelligence report
    with full scientific disclaimers and deterministic uncertainty indicators.
    """
    loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail=f"Critical location '{location_id}' not found.")

    service = HistoricalAnalyticsService(db)
    report = service.generate_report(location_id=location_id, days=days, persist_snapshot=False)
    return {
        "report_type": "SATGUARD_HISTORICAL_INTELLIGENCE_REPORT",
        "confidentiality": "GOVERNMENT_RESTRICTED",
        "location": {
            "id": loc.id,
            "name": loc.name,
            "type": loc.location_type,
            "coordinates": [loc.latitude, loc.longitude],
        },
        "time_window": report.window.model_dump(),
        "data_sufficiency": report.data_sufficiency.value,
        "persistence_assessment": report.persistence.model_dump(),
        "sar_surface_change_trend": report.sar_trends.model_dump(),
        "optical_observation_trend": report.optical_trends.model_dump(),
        "environmental_history": report.environmental_history.model_dump(),
        "risk_assessment_trend": report.risk_trends.model_dump(),
        "alert_recurrence_analysis": report.alert_trends.model_dump(),
        "historical_baseline_comparison": report.baseline_comparison.model_dump(),
        "recommended_monitoring_action": (
            "Elevate priority ground verification"
            if report.persistence.persistence_status == "PERSISTENT_SIGNAL"
            else "Maintain regular continuous observation cadence"
        ),
        "scientific_disclaimer": report.disclaimer,
        "generated_at": report.generated_at.isoformat(),
    }


# ==============================================================================
# PHASE 10 — AUTHENTICATION, OPERATOR MANAGEMENT & AUDIT LOG ENDPOINTS
# ==============================================================================

from fastapi import status


@app.post(
    "/api/auth/login",
    tags=["Authentication"],
    response_model=TokenResponse,
)
def login_endpoint(
    payload: UserLoginRequest,
    db: Session = Depends(get_db),
):
    """
    Authenticates government operator credentials and issues signed JWT bearer token.
    Tracks authentication attempts in the immutable audit log.
    """
    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        record_audit_event(
            db=db,
            actor=payload.username,
            role="UNKNOWN",
            action="LOGIN",
            resource="auth",
            result="FAILURE",
            metadata={"reason": "Invalid credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token({
        "sub": user.username,
        "user_id": user.id,
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
        "department": user.department,
    })

    record_audit_event(
        db=db,
        actor=user.username,
        role=user.role,
        action="LOGIN",
        resource="auth",
        resource_id=user.id,
        result="SUCCESS",
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_id=user.id,
        username=user.username,
        role=RoleEnum(user.role),
        full_name=user.full_name,
    )


@app.get(
    "/api/auth/me",
    tags=["Authentication"],
    response_model=UserProfileResponse,
)
def get_current_user_profile_endpoint(
    current_user: User = Depends(get_current_user),
):
    """
    Returns current authenticated operator identity, department, and RBAC role.
    """
    return UserProfileResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        department=current_user.department,
        role=RoleEnum(current_user.role),
        is_active=current_user.is_active,
        last_login=current_user.last_login.isoformat() if current_user.last_login else None,
        created_at=current_user.created_at.isoformat() if current_user.created_at else None,
    )


@app.get(
    "/api/auth/users",
    tags=["Authentication"],
    response_model=List[UserProfileResponse],
)
def list_users_endpoint(
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Lists government operator user accounts. Protected by ADMIN role.
    """
    users = db.query(User).order_by(User.username.asc()).all()
    return [
        UserProfileResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            department=u.department,
            role=RoleEnum(u.role),
            is_active=u.is_active,
            last_login=u.last_login.isoformat() if u.last_login else None,
            created_at=u.created_at.isoformat() if u.created_at else None,
        )
        for u in users
    ]


@app.post(
    "/api/auth/users",
    tags=["Authentication"],
    response_model=UserProfileResponse,
)
def create_user_endpoint(
    payload: UserCreateRequest,
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
    db: Session = Depends(get_db),
):
    """
    Creates a new government operator account with role-based privileges. Protected by ADMIN role.
    """
    from satguard.security.auth import hash_password
    import uuid

    existing = db.query(User).filter((User.username == payload.username) | (User.email == payload.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already registered.")

    new_user = User(
        id=f"usr-{uuid.uuid4().hex[:8]}",
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        department=payload.department,
        role=payload.role.value,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    record_audit_event(
        db=db,
        actor=current_user.username,
        role=current_user.role,
        action="USER_CREATE",
        resource="user",
        resource_id=new_user.id,
        result="SUCCESS",
        metadata={"created_username": payload.username, "assigned_role": payload.role.value},
    )

    return UserProfileResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        full_name=new_user.full_name,
        department=new_user.department,
        role=RoleEnum(new_user.role),
        is_active=new_user.is_active,
        created_at=new_user.created_at.isoformat() if new_user.created_at else None,
    )


@app.get(
    "/api/audit/logs",
    tags=["Audit & Forensics"],
)
def get_audit_logs_endpoint(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    actor: Optional[str] = Query(None, description="Filter by actor username"),
    action: Optional[str] = Query(None, description="Filter by action name"),
    resource: Optional[str] = Query(None, description="Filter by resource type"),
    current_user: User = Depends(require_role(RoleEnum.ANALYST)),
    db: Session = Depends(get_db),
):
    """
    Returns queryable, paginated audit records for government surveillance operations.
    Protected by minimum ANALYST role.
    """
    logs, total = query_audit_logs(
        db=db,
        limit=limit,
        offset=offset,
        actor=actor,
        action=action,
        resource=resource,
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [log.to_dict() for log in logs],
    }






