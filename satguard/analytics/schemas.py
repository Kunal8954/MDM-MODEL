"""
satguard/analytics/schemas.py
Pydantic Schemas and Enumerations for Historical Intelligence & Trend Analytics.
Adheres strictly to deterministic, explainable, and conservative scientific semantics.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class DataSufficiencyEnum(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"


class PersistenceStatusEnum(str, Enum):
    NO_SIGNAL = "NO_SIGNAL"
    ISOLATED_SIGNAL = "ISOLATED_SIGNAL"
    INTERMITTENT_SIGNAL = "INTERMITTENT_SIGNAL"
    PERSISTENT_SIGNAL = "PERSISTENT_SIGNAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RiskTrendClassificationEnum(str, Enum):
    STABLE = "STABLE"
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    VOLATILE = "VOLATILE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class BaselineComparisonStatusEnum(str, Enum):
    ABOVE_BASELINE = "ABOVE_BASELINE"
    WITHIN_BASELINE = "WITHIN_BASELINE"
    BELOW_BASELINE = "BELOW_BASELINE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DeviationStatusEnum(str, Enum):
    NORMAL = "NORMAL"
    HISTORICAL_DEVIATION = "HISTORICAL_DEVIATION"
    UNUSUAL_RELATIVE_TO_BASELINE = "UNUSUAL_RELATIVE_TO_BASELINE"
    ABOVE_HISTORICAL_RANGE = "ABOVE_HISTORICAL_RANGE"


class HistoricalWindow(BaseModel):
    days: int
    start_time: datetime
    end_time: datetime


class SARHistoricalPoint(BaseModel):
    change_id: Optional[str] = None
    observation_id: str
    t1_acquisition_time: Optional[datetime] = None
    t2_acquisition_time: Optional[datetime] = None
    relative_orbit: Optional[int] = None
    orbit_direction: Optional[str] = None
    delta_vv_mean: Optional[float] = None
    delta_vh_mean: Optional[float] = None
    changed_percentage: Optional[float] = None
    valid_pixel_count: Optional[int] = None
    is_significant_change: bool = False


class SARTrendSummary(BaseModel):
    observation_count: int = 0
    valid_change_count: int = 0
    mean_delta_vv: Optional[float] = None
    median_delta_vv: Optional[float] = None
    mean_delta_vh: Optional[float] = None
    median_delta_vh: Optional[float] = None
    mean_changed_percentage: Optional[float] = None
    max_changed_percentage: Optional[float] = None
    signal_trend: str = "INSUFFICIENT_DATA"
    points: List[SARHistoricalPoint] = Field(default_factory=list)


class OpticalHistoricalPoint(BaseModel):
    observation_id: str
    acquisition_time: datetime
    cloud_cover: Optional[float] = None
    is_cloud_obscured: bool = False
    quality_status: Optional[str] = None


class OpticalTrendSummary(BaseModel):
    total_scenes: int = 0
    usable_scenes: int = 0
    cloud_obscured_scenes: int = 0
    mean_cloud_cover: Optional[float] = None
    optical_stability: str = "INSUFFICIENT_DATA"
    points: List[OpticalHistoricalPoint] = Field(default_factory=list)


class EnvironmentalHistorySummary(BaseModel):
    rainfall_status: str = "UNAVAILABLE"
    rainfall_observation_count: int = 0
    rainfall_mean_mm: Optional[float] = None
    fire_status: str = "VALID_ZERO_OBSERVATION"
    fire_detection_count: int = 0
    seismic_status: str = "NO_EVENTS_DETECTED"
    seismic_event_count: int = 0
    nearest_earthquake_distance_km: Optional[float] = None


class RiskHistoricalPoint(BaseModel):
    risk_assessment_id: str
    timestamp: datetime
    score: float
    risk_level: str
    monitoring_priority: str
    evidence_strength: str
    confidence_score: float
    engine_version: str


class RiskTrendSummary(BaseModel):
    assessment_count: int = 0
    latest_score: Optional[float] = None
    average_score: Optional[float] = None
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    score_delta: Optional[float] = None
    level_transitions_count: int = 0
    high_level_count: int = 0
    critical_level_count: int = 0
    classification: RiskTrendClassificationEnum = RiskTrendClassificationEnum.INSUFFICIENT_DATA
    points: List[RiskHistoricalPoint] = Field(default_factory=list)


class AlertHistoricalPoint(BaseModel):
    alert_id: str
    created_at: datetime
    priority: str
    status: str
    title: str
    resolved_at: Optional[datetime] = None


class AlertTrendSummary(BaseModel):
    total_alerts: int = 0
    active_alerts: int = 0
    acknowledged_alerts: int = 0
    in_review_alerts: int = 0
    resolved_alerts: int = 0
    recurrence_detected: bool = False
    recurrence_pattern: Optional[str] = None
    points: List[AlertHistoricalPoint] = Field(default_factory=list)


class PersistenceResult(BaseModel):
    persistence_status: PersistenceStatusEnum
    significant_observations_count: int = 0
    total_evaluated_observations: int = 0
    signal_ratio: float = 0.0
    consecutive_significant_count: int = 0
    explanation: str


class BaselineStatistics(BaseModel):
    metric_name: str
    sample_count: int = 0
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    iqr: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None


class BaselineComparisonResult(BaseModel):
    comparison_status: BaselineComparisonStatusEnum
    current_value: Optional[float] = None
    baseline_mean: Optional[float] = None
    baseline_median: Optional[float] = None
    deviation_value: Optional[float] = None
    deviation_status: DeviationStatusEnum
    explanation: str


class HistoricalAnalyticsReport(BaseModel):
    id: str
    location_id: str
    location_name: Optional[str] = None
    window: HistoricalWindow
    data_sufficiency: DataSufficiencyEnum
    persistence: PersistenceResult
    sar_trends: SARTrendSummary
    optical_trends: OpticalTrendSummary
    environmental_history: EnvironmentalHistorySummary
    risk_trends: RiskTrendSummary
    alert_trends: AlertTrendSummary
    baseline_comparison: BaselineComparisonResult
    engine_version: str = "analytics_v1"
    disclaimer: str = (
        "Historical trend analysis is an operational monitoring and prioritization tool. "
        "It does NOT claim exact disaster prediction. All observations reflect conservative, "
        "deterministic multi-sensor evaluation."
    )
    generated_at: datetime
