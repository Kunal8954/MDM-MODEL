"""
satguard/analyst/schema.py
Pydantic Schemas for Phase 5 Groq Evidence Analyst.
Enforces strict boundaries between LLM narrative synthesis and authoritative risk assessment.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from satguard.fusion.schema import MultiSensorEvidence
from satguard.risk.schema import RiskAssessmentResult


class AnalystInput(BaseModel):
    """
    Structured, fully grounded input supplied to the Groq Evidence Analyst.
    Combines location parameters, multi-sensor evidence (Phase 3), and authoritative risk assessment (Phase 4).
    """
    location: Dict[str, Any] = Field(..., description="Target location identity and AOI bounds")
    evidence: MultiSensorEvidence = Field(..., description="Normalized multi-sensor evidence snapshot")
    risk_assessment: Dict[str, Any] = Field(..., description="Authoritative Phase 4 deterministic assessment")


class ObservedChangeItem(BaseModel):
    """
    An individual observation directly traceable to sensor telemetry.
    """
    category: str = Field(..., description="SAR, OPTICAL, RAINFALL, SEISMIC, THERMAL, or TERRAIN")
    finding: str = Field(..., description="Factual description of the sensor change or measurement")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of source observations or granules")
    traceability_metric: Optional[str] = Field(None, description="Key numerical indicator supporting the finding")


class CrossSensorFindingItem(BaseModel):
    """
    A cross-sensor correlation grounded in Phase 3 multi-sensor analysis.
    """
    correlation_type: str = Field(..., description="Identified correlation relationship")
    finding: str = Field(..., description="Explanation of the cross-sensor association")
    source_evidence_ids: List[str] = Field(default_factory=list, description="IDs of correlated evidence sources")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Correlation confidence score")
    scientific_interpretation: str = Field(..., description="Conservative interpretation of the relationship")


class AnalystReport(BaseModel):
    """
    Auditable intelligence report produced by the Groq Evidence Analyst.
    Enforces risk immutability: authoritative risk scores/levels cannot be modified by the LLM.
    """
    report_id: str = Field(..., description="Unique report identifier")
    location_id: str = Field(..., description="Critical location ID")
    risk_assessment_id: str = Field(..., description="Associated authoritative Phase 4 RiskAssessment ID")
    authoritative_risk_score: float = Field(..., description="Authoritative Phase 4 monitoring score (0-100)")
    authoritative_risk_level: str = Field(..., description="Authoritative Phase 4 risk level (LOW/MODERATE/HIGH/CRITICAL)")
    authoritative_monitoring_priority: str = Field(..., description="Authoritative Phase 4 monitoring priority")
    authoritative_evidence_strength: str = Field(..., description="Authoritative Phase 4 evidence strength")
    executive_summary: str = Field(..., description="Concise summary answering What changed? Supporting evidence? Priority? Uncertainties?")
    observed_changes: List[ObservedChangeItem] = Field(default_factory=list, description="Categorized observed changes")
    supporting_evidence: Dict[str, Any] = Field(default_factory=dict, description="Summary mapping of active sensors and channels")
    cross_sensor_findings: List[CrossSensorFindingItem] = Field(default_factory=list, description="Interpreted cross-sensor correlations")
    uncertainty: List[str] = Field(default_factory=list, description="Explicit uncertainty statements")
    monitoring_assessment: str = Field(..., description="Narrative contextualizing the deterministic score and priority")
    recommended_verification: List[str] = Field(default_factory=list, description="Proportional operational verification recommendations")
    data_gaps: List[str] = Field(default_factory=list, description="Missing or stale sensor streams")
    validation_status: str = Field("VALIDATED", description="VALIDATED or VALIDATION_FAILED")
    validation_errors: List[str] = Field(default_factory=list, description="Validation issues detected during post-processing")
    model: str = Field(..., description="Name of the inference model used")
    prompt_version: str = Field("evidence_analyst_v1", description="Version of the prompt template")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp of generation")
