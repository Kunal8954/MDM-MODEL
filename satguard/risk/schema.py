"""
satguard/risk/schema.py
Pydantic Schemas and Explicit Enums for Risk Assessment Engine (Phase 4).
Strictly separates monitoring risk classification from disaster predictions.
"""

from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """
    Monitoring risk level classification.
    Represents normalized monitoring urgency based on multi-sensor evidence.
    Does NOT indicate a confirmed disaster or disaster probability.
    """
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MonitoringPriority(str, Enum):
    """
    Operational monitoring priority for sovereign surveillance resources.
    """
    ROUTINE = "ROUTINE"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    URGENT = "URGENT"


class EvidenceStrength(str, Enum):
    """
    Measures the robustness, sensor independence, and alignment of the supporting evidence.
    Independent of the actual risk score.
    """
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


class RecencyStatus(str, Enum):
    """
    Temporal recency classification of an observation relative to the reference time.
    """
    RECENT = "RECENT"
    RECENT_ENOUGH = "RECENT_ENOUGH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class FactorType(str, Enum):
    """
    Taxonomy of deterministic evidence contribution factors.
    """
    SAR_CHANGE = "SAR_CHANGE"
    OPTICAL_CHANGE = "OPTICAL_CHANGE"
    MULTI_SENSOR_CORRELATION = "MULTI_SENSOR_CORRELATION"
    RAINFALL = "RAINFALL"
    FIRE = "FIRE"
    EARTHQUAKE = "EARTHQUAKE"
    TERRAIN_SLOPE = "TERRAIN_SLOPE"
    RECENCY = "RECENCY"
    DATA_QUALITY = "DATA_QUALITY"


class ContributingFactor(BaseModel):
    """
    An auditable factor contributing to the overall monitoring risk score.
    """
    factor: str = Field(..., description="Factor identifier from FactorType taxonomy")
    contribution: float = Field(..., description="Deterministic point contribution (>= 0)")
    evidence_id: Optional[str] = Field(None, description="Identifier of the supporting observation or product")
    reason: str = Field(..., description="Explainable rationale for point assignment")


class RiskAssessmentResult(BaseModel):
    """
    Auditable result produced by the Risk Assessment Engine for a critical location.
    """
    id: str = Field(..., description="Unique assessment identifier")
    location_id: str = Field(..., description="Monitored critical location ID")
    location_name: Optional[str] = Field(None, description="Monitored location name")
    evidence_snapshot_id: str = Field(..., description="Associated EvidenceSnapshot ID")
    score: float = Field(..., ge=0.0, le=100.0, description="Normalized deterministic risk score (0-100)")
    risk_level: RiskLevel = Field(..., description="Monitoring risk classification")
    monitoring_priority: MonitoringPriority = Field(..., description="Operational surveillance priority")
    evidence_strength: EvidenceStrength = Field(..., description="Evidence robustness and multi-sensor corroboration")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Quality/confidence score of underlying evidence")
    contributing_factors: List[ContributingFactor] = Field(default_factory=list, description="Detailed point breakdown")
    uncertainty_factors: List[str] = Field(default_factory=list, description="Explicit uncertainty declarations")
    explanation: str = Field(..., description="Deterministic, human-readable assessment explanation")
    recommended_action: str = Field(..., description="Operational recommendation for sovereign analysts")
    engine_version: str = Field("risk_engine_v1", description="Version of the risk assessment engine")
    provenance: Dict[str, Any] = Field(default_factory=dict, description="Execution and system provenance metadata")
    score_interpretation: str = Field(
        default="Monitoring risk score (0-100 scale). This is NOT a probability of disaster or confirmation of damage.",
        description="Scientific interpretation boundary"
    )
    created_at: datetime = Field(..., description="Timestamp when assessment was generated")
