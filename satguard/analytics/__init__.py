"""
satguard/analytics package
Historical Intelligence & Trend Analytics for SATGUARD.
"""

from satguard.analytics.schemas import (
    HistoricalWindow,
    DataSufficiencyEnum,
    PersistenceStatusEnum,
    RiskTrendClassificationEnum,
    BaselineComparisonStatusEnum,
    DeviationStatusEnum,
    SARHistoricalPoint,
    SARTrendSummary,
    OpticalHistoricalPoint,
    OpticalTrendSummary,
    EnvironmentalHistorySummary,
    RiskHistoricalPoint,
    RiskTrendSummary,
    AlertHistoricalPoint,
    AlertTrendSummary,
    PersistenceResult,
    BaselineStatistics,
    BaselineComparisonResult,
    HistoricalAnalyticsReport,
)
from satguard.analytics.historical import HistoricalAnalyticsService
from satguard.analytics.baseline import calculate_descriptive_stats, compare_value_to_baseline
from satguard.analytics.persistence import evaluate_persistence
from satguard.analytics.trends import (
    analyze_sar_trends,
    analyze_optical_trends,
    analyze_risk_trends,
    analyze_alert_trends,
)

__all__ = [
    "HistoricalAnalyticsService",
    "HistoricalWindow",
    "DataSufficiencyEnum",
    "PersistenceStatusEnum",
    "RiskTrendClassificationEnum",
    "BaselineComparisonStatusEnum",
    "DeviationStatusEnum",
    "SARHistoricalPoint",
    "SARTrendSummary",
    "OpticalHistoricalPoint",
    "OpticalTrendSummary",
    "EnvironmentalHistorySummary",
    "RiskHistoricalPoint",
    "RiskTrendSummary",
    "AlertHistoricalPoint",
    "AlertTrendSummary",
    "PersistenceResult",
    "BaselineStatistics",
    "BaselineComparisonResult",
    "HistoricalAnalyticsReport",
    "calculate_descriptive_stats",
    "compare_value_to_baseline",
    "evaluate_persistence",
    "analyze_sar_trends",
    "analyze_optical_trends",
    "analyze_risk_trends",
    "analyze_alert_trends",
]
