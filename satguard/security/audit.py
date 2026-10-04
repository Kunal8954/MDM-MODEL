"""
satguard/security/audit.py
Immutable Audit Logging Service for Government Accountability and Forensics.
"""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timezone
import uuid
import logging
from sqlalchemy.orm import Session

from satguard.models.entities import AuditLog
from satguard.config import settings

logger = logging.getLogger("satguard.audit")


def record_audit_event(
    db: Session,
    actor: str,
    role: str,
    action: str,
    resource: str,
    resource_id: Optional[str] = None,
    result: str = "SUCCESS",
    ip_address: Optional[str] = None,
    request_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[AuditLog]:
    """
    Creates an immutable audit log entry.
    Ensures security and operational tracking without storing sensitive credentials or tokens.
    """
    if not settings.AUDIT_LOGGING_ENABLED:
        return None

    # Sanitize metadata (remove passwords, tokens, keys)
    safe_metadata = {}
    if metadata:
        for k, v in metadata.items():
            if any(secret_term in k.lower() for secret_term in ["password", "token", "secret", "key"]):
                safe_metadata[k] = "[REDACTED]"
            else:
                safe_metadata[k] = v

    event_id = f"aud-{uuid.uuid4().hex[:12]}"
    audit_entry = AuditLog(
        id=f"log-{uuid.uuid4().hex[:10]}",
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        actor=actor,
        role=role,
        action=action,
        resource=resource,
        resource_id=resource_id,
        result=result,
        ip_address=ip_address,
        request_id=request_id,
        event_metadata=safe_metadata,
    )

    try:
        db.add(audit_entry)
        db.commit()
        db.refresh(audit_entry)
        logger.info(f"AUDIT [{event_id}] actor={actor} role={role} action={action} resource={resource} result={result}")
        return audit_entry
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to record audit event: {e}")
        return None


def query_audit_logs(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    actor: Optional[str] = None,
    action: Optional[str] = None,
    resource: Optional[str] = None,
    resource_id: Optional[str] = None,
) -> Tuple[List[AuditLog], int]:
    """
    Returns filtered, paginated audit records with total count.
    """
    query = db.query(AuditLog)
    if actor:
        query = query.filter(AuditLog.actor == actor)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource:
        query = query.filter(AuditLog.resource == resource)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)

    total = query.count()
    logs = query.order_by(AuditLog.timestamp.desc()).offset(offset).limit(limit).all()
    return logs, total

