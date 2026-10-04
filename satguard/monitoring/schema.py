"""
satguard/monitoring/schema.py
Pydantic schemas and enums for Phase 7 Continuous Monitoring and Automated Reassessment.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class MonitoringStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    DISABLED = "DISABLED"


class MonitoringRunStatusEnum(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class MonitoringTriggerTypeEnum(str, Enum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"
    RETRY = "RETRY"


class MonitoringStageEnum(str, Enum):
    PENDING = "PENDING"
    DISCOVERY = "DISCOVERY"
    OBSERVATION_PROCESSING = "OBSERVATION_PROCESSING"
    EVIDENCE_FUSION = "EVIDENCE_FUSION"
    RISK_ASSESSMENT = "RISK_ASSESSMENT"
    ANALYST = "ANALYST"
    ALERT_EVALUATION = "ALERT_EVALUATION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MonitoringOutcomeCodeEnum(str, Enum):
    NO_NEW_DATA = "NO_NEW_DATA"
    NO_NEW_EVIDENCE = "NO_NEW_EVIDENCE"
    NO_SIGNIFICANT_CHANGE = "NO_SIGNIFICANT_CHANGE"
    RISK_UNCHANGED = "RISK_UNCHANGED"
    ALERT_UNCHANGED = "ALERT_UNCHANGED"
    ALERT_GENERATED = "ALERT_GENERATED"
    CONCURRENT_RUN_SKIPPED = "CONCURRENT_RUN_SKIPPED"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


class MonitoringTriggerRequest(BaseModel):
    location_id: Optional[str] = Field(None, description="Optional specific location ID. If omitted, all due or enabled locations can be evaluated.")
    force: bool = Field(False, description="If True, bypasses interval check and forces run immediately.")
    triggered_by: str = Field("system", description="Identifier of the operator or service triggering the run.")


class MonitoringConfigureRequest(BaseModel):
    monitoring_enabled: Optional[bool] = None
    monitoring_interval_hours: Optional[float] = Field(None, ge=0.5, le=720.0)
    monitoring_status: Optional[MonitoringStatusEnum] = None


class MonitoringRunSummary(BaseModel):
    id: str
    location_id: str
    status: str
    trigger_type: str
    triggered_by: str
    current_stage: str
    observations_checked: int
    observations_processed: int
    new_observations_found: int
    outcome_code: Optional[str] = None
    evidence_snapshot_id: Optional[str] = None
    risk_assessment_id: Optional[str] = None
    analyst_report_id: Optional[str] = None
    alert_id: Optional[str] = None
    alert_action: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MonitoringRunDetail(MonitoringRunSummary):
    stage_history: List[Dict[str, Any]] = Field(default_factory=list)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)


class LocationMonitoringStatusResponse(BaseModel):
    location_id: str
    location_name: str
    monitoring_enabled: bool
    monitoring_status: str
    monitoring_interval_hours: float
    last_run: Optional[datetime] = None
    last_successful_run: Optional[datetime] = None
    last_failed_run: Optional[datetime] = None
    next_scheduled_run: Optional[datetime] = None
    active_run: Optional[MonitoringRunSummary] = None
    last_observation_check: Optional[datetime] = None
    last_processed_observation: Optional[str] = None
    observations_processed_count: int = 0
    latest_evidence_snapshot_id: Optional[str] = None
    latest_risk_assessment: Optional[Dict[str, Any]] = None
    latest_alert: Optional[Dict[str, Any]] = None
