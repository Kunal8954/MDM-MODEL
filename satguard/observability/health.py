"""
satguard/observability/health.py
System Health, Liveness, Readiness, and Dependency Diagnostics.
Adheres to strict government security boundaries (no leaked secrets).
"""

from typing import Dict, Any
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session

from satguard.config import settings


def check_liveness(legacy_compat: bool = False) -> Dict[str, Any]:
    """
    Evaluates process liveness for Kubernetes / container orchestration.
    When legacy_compat=True (e.g. /api/health), returns status 'HEALTHY'.
    When called for /live or /health/live, returns status 'LIVE'.
    """
    return {
        "status": "HEALTHY" if legacy_compat else "LIVE",
        "service": "SATGUARD",
        "version": "1.0.0",
        "environment": settings.SATGUARD_ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }



def check_readiness(db: Session) -> Dict[str, Any]:
    """
    Evaluates system readiness across core dependencies (database, storage, scheduler).
    Never exposes provider keys or credentials in response.
    """
    dependencies: Dict[str, Any] = {}
    is_ready = True

    # 1. Database Check
    try:
        db.execute(text("SELECT 1"))
        dependencies["database"] = {
            "status": "AVAILABLE",
            "type": "sqlite" if (not settings.DATABASE_URL or "sqlite" in settings.DATABASE_URL) else "postgresql",
        }
    except Exception as e:
        is_ready = False
        dependencies["database"] = {
            "status": "UNAVAILABLE",
            "error": "Connection test failed",
        }

    # 2. Continuous Monitoring Scheduler
    try:
        from satguard.monitoring.scheduler import scheduler
        sched_status = "ACTIVE" if scheduler.is_running else "STANDBY"

        # MonitoringScheduler is thread-based and exposes no job registry, so the
        # meaningful health signal is the count of locations under monitoring.
        monitored_locations = None
        try:
            from satguard.models.entities import CriticalLocation
            from satguard.db.session import get_db_session
            _sess = get_db_session()
            try:
                monitored_locations = _sess.query(CriticalLocation).filter(
                    CriticalLocation.monitoring_enabled.is_(True)
                ).count()
            finally:
                _sess.close()
        except Exception:
            monitored_locations = None

        dependencies["scheduler"] = {
            "status": "AVAILABLE",
            "scheduler_state": sched_status,
            "monitored_locations": monitored_locations,
            "check_interval_seconds": scheduler.check_interval_seconds,
        }
    except Exception:
        dependencies["scheduler"] = {"status": "DEGRADED", "scheduler_state": "UNAVAILABLE"}

    # 3. Provider Configuration Status (checks presence of credentials without exposing values)
    providers_status = {
        "cdse_copernicus": "AVAILABLE" if (settings.CDSE_CLIENT_ID and settings.CDSE_CLIENT_SECRET) else "DEGRADED",
        "groq_lpu": "AVAILABLE" if settings.GROQ_API_KEY else "DEGRADED",
        "nasa_firms": "AVAILABLE" if settings.FIRMS_MAP_KEY else "DEGRADED",
        "nasa_earthdata": "AVAILABLE" if (settings.EARTHDATA_USERNAME and settings.EARTHDATA_PASSWORD) else "DEGRADED",
    }
    dependencies["providers"] = providers_status

    overall_status = "READY" if is_ready else "UNHEALTHY"

    return {
        "status": overall_status,
        "service": "SATGUARD",
        "environment": settings.SATGUARD_ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dependencies": dependencies,
    }
