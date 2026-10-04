"""
satguard/alert/schema.py
Pydantic Schemas and Explicit Enums for Phase 6 Government Alert & Decision Support.
Enforces conservative government-grade operational monitoring language.
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class AlertLevel(str, Enum):
    """
    Operational government monitoring alert level.
    Represents surveillance urgency; does NOT declare or confirm a disaster.
    """
    INFO = "INFO"
    MONITOR = "MONITOR"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    URGENT = "URGENT"


class AlertStatus(str, Enum):
    """
    Formal lifecycle state of a government surveillance alert.
    """
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class AlertPriority(str, Enum):
    """
    Operational priority tier for surveillance and analyst dispatch.
    """
    ROUTINE = "ROUTINE"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    URGENT = "URGENT"


class AlertAuditEventType(str, Enum):
    """
    Audit log events tracking complete lifecycle history.
    """
    ALERT_CREATED = "ALERT_CREATED"
    ALERT_ACKNOWLEDGED = "ALERT_ACKNOWLEDGED"
    ALERT_REVIEW_STARTED = "ALERT_REVIEW_STARTED"
    ALERT_ESCALATED = "ALERT_ESCALATED"
    ALERT_DE_ESCALATED = "ALERT_DE_ESCALATED"
    ALERT_RESOLVED = "ALERT_RESOLVED"
    ALERT_EXPIRED = "ALERT_EXPIRED"
    ALERT_SUPERSEDED = "ALERT_SUPERSEDED"


class AlertLifecycleRequest(BaseModel):
    """
    Payload for human operator actions on an alert (acknowledgement, review, resolution).
    """
    actor: Optional[str] = Field("operator", description="Identifier of the operator or sovereign agency")
    note: Optional[str] = Field(None, description="Operational notes or log explanation")


class AlertAuditEvent(BaseModel):
    """
    Structured representation of an audit event in the alert lifecycle.
    """
    id: str
    alert_id: str
    event_type: AlertAuditEventType
    previous_status: Optional[str] = None
    new_status: str
    previous_level: Optional[str] = None
    new_level: Optional[str] = None
    actor: Optional[str] = "system"
    reason: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AlertResult(BaseModel):
    """
    Full structured representation of a government monitoring alert.
    """
    alert_id: str = Field(..., description="Unique alert identifier")
    location_id: str = Field(..., description="Monitored sovereign critical location ID")
    location_name: Optional[str] = Field(None, description="Human-readable location title")
    risk_assessment_id: str = Field(..., description="Authoritative Phase 4 RiskAssessment ID")
    analyst_report_id: Optional[str] = Field(None, description="Phase 5 AnalystReport ID (if validated)")
    alert_level: AlertLevel = Field(..., description="Operational monitoring alert tier")
    priority: AlertPriority = Field(..., description="Surveillance verification priority")
    status: AlertStatus = Field(..., description="Current lifecycle state")
    title: str = Field(..., description="Standardized operational title")
    summary: str = Field(..., description="Core findings: What changed? Supporting evidence? Uncertainties?")
    reason: str = Field(..., description="Explicit analytical rationale triggering this alert")
    evidence_references: Dict[str, Any] = Field(default_factory=dict, description="Full lineage to raw observations")
    contributing_factors: List[Dict[str, Any]] = Field(default_factory=list, description="Breakdown of physical factors")
    uncertainty: List[str] = Field(default_factory=list, description="Declared sensor and environmental gaps")
    recommended_action: str = Field(..., description="Proportional operational verification directive")
    fingerprint: str = Field(..., description="Deterministic deduplication signature")
    escalation_history: List[Dict[str, Any]] = Field(default_factory=list, description="Audit of state transitions")
    acknowledgement_details: Optional[Dict[str, Any]] = None
    resolution_details: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    expires_at: datetime
    alert_version: str = "alert_engine_v1"
    source_engine_versions: Dict[str, str] = Field(default_factory=dict)
    is_duplicate: bool = False
    disclaimer: str = Field(
        default="Operational decision-support alert. Does not constitute a disaster declaration, structural damage confirmation, or evacuation order.",
        description="Strict sovereign interpretation boundary"
    )
