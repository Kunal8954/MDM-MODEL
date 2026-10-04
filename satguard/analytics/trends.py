"""
satguard/analytics/trends.py
Descriptive Historical Trend Analysis for SAR, Optical, Risk, and Alerts.
Strictly adheres to deterministic statistical analysis and conservative government-grade terminology.
"""

from typing import List, Optional
import math
from satguard.analytics.schemas import (
    SARHistoricalPoint,
    SARTrendSummary,
    OpticalHistoricalPoint,
    OpticalTrendSummary,
    RiskHistoricalPoint,
    RiskTrendSummary,
    RiskTrendClassificationEnum,
    AlertHistoricalPoint,
    AlertTrendSummary,
)
from satguard.analytics.baseline import calculate_descriptive_stats


def analyze_sar_trends(points: List[SARHistoricalPoint]) -> SARTrendSummary:
    """
    Computes descriptive metrics for SAR historical series.
    Uses 'SAR change signal trend' semantics, never 'disaster/damage trend'.
    """
    total = len(points)
    if total == 0:
        return SARTrendSummary(observation_count=0, valid_change_count=0, signal_trend="INSUFFICIENT_DATA")

    valid_changes = [p for p in points if p.changed_percentage is not None]
    valid_count = len(valid_changes)

    vv_vals = [p.delta_vv_mean for p in points if p.delta_vv_mean is not None]
    vh_vals = [p.delta_vh_mean for p in points if p.delta_vh_mean is not None]
    pct_vals = [p.changed_percentage for p in points if p.changed_percentage is not None]

    vv_stats = calculate_descriptive_stats(vv_vals, "delta_vv")
    vh_stats = calculate_descriptive_stats(vh_vals, "delta_vh")
    pct_stats = calculate_descriptive_stats(pct_vals, "changed_percentage")

    # Determine signal trend
    signal_trend = "INSUFFICIENT_DATA"
    if valid_count >= 3:
        # Check trajectory of changed_percentage
        first_half = pct_vals[: valid_count // 2]
        second_half = pct_vals[valid_count // 2 :]
        avg1 = sum(first_half) / len(first_half) if first_half else 0.0
        avg2 = sum(second_half) / len(second_half) if second_half else 0.0

        if pct_stats.std and pct_stats.std > 10.0:
            signal_trend = "VOLATILE"
        elif avg2 - avg1 > 5.0:
            signal_trend = "INCREASING"
        elif avg1 - avg2 > 5.0:
            signal_trend = "DECREASING"
        else:
            signal_trend = "STABLE"
    elif valid_count > 0:
        signal_trend = "STABLE"

    return SARTrendSummary(
        observation_count=total,
        valid_change_count=valid_count,
        mean_delta_vv=vv_stats.mean,
        median_delta_vv=vv_stats.median,
        mean_delta_vh=vh_stats.mean,
        median_delta_vh=vh_stats.median,
        mean_changed_percentage=pct_stats.mean,
        max_changed_percentage=pct_stats.max_val,
        signal_trend=signal_trend,
        points=points,
    )


def analyze_optical_trends(points: List[OpticalHistoricalPoint]) -> OpticalTrendSummary:
    """
    Computes cloud-adjusted optical series metrics.
    Cloud-obscured scenes are distinguished from valid clear-sky observations.
    """
    total = len(points)
    if total == 0:
        return OpticalTrendSummary(
            total_scenes=0,
            usable_scenes=0,
            cloud_obscured_scenes=0,
            optical_stability="INSUFFICIENT_DATA",
        )

    cloud_obscured = [p for p in points if p.is_cloud_obscured or (p.cloud_cover is not None and p.cloud_cover > 50.0)]
    usable = [p for p in points if p not in cloud_obscured]
    cloud_vals = [p.cloud_cover for p in points if p.cloud_cover is not None]

    mean_cloud = round(sum(cloud_vals) / len(cloud_vals), 2) if cloud_vals else None

    # Optical observation stability
    if len(usable) == 0 and total > 0:
        stability = "FREQUENT_CLOUD_OBSCURATION"
    elif len(usable) < 2:
        stability = "INSUFFICIENT_DATA"
    elif len(cloud_obscured) / total > 0.5:
        stability = "FREQUENT_CLOUD_OBSCURATION"
    else:
        stability = "STABLE"

    return OpticalTrendSummary(
        total_scenes=total,
        usable_scenes=len(usable),
        cloud_obscured_scenes=len(cloud_obscured),
        mean_cloud_cover=mean_cloud,
        optical_stability=stability,
        points=points,
    )


def analyze_risk_trends(points: List[RiskHistoricalPoint]) -> RiskTrendSummary:
    """
    Analyzes historical risk score trajectory and transitions.
    Uses 'risk assessment trend', never 'probability trend'.
    Historical assessments are immutable.
    """
    total = len(points)
    if total == 0:
        return RiskTrendSummary(
            assessment_count=0,
            classification=RiskTrendClassificationEnum.INSUFFICIENT_DATA,
        )

    # Chronological sort
    sorted_pts = sorted(points, key=lambda p: p.timestamp)
    scores = [p.score for p in sorted_pts]
    score_stats = calculate_descriptive_stats(scores, "risk_score")

    latest_score = scores[-1]
    earliest_score = scores[0]
    score_delta = round(latest_score - earliest_score, 2)

    # Transitions count and level counts
    transitions = 0
    high_count = sum(1 for p in sorted_pts if p.risk_level in ("HIGH", "URGENT"))
    critical_count = sum(1 for p in sorted_pts if p.risk_level in ("CRITICAL", "URGENT"))

    for i in range(1, total):
        if sorted_pts[i].risk_level != sorted_pts[i - 1].risk_level:
            transitions += 1

    # Trend classification
    if total < 2:
        classification = RiskTrendClassificationEnum.INSUFFICIENT_DATA
    elif score_stats.std and score_stats.std > 15.0 and transitions >= 3:
        classification = RiskTrendClassificationEnum.VOLATILE
    elif score_delta > 7.0:
        classification = RiskTrendClassificationEnum.INCREASING
    elif score_delta < -7.0:
        classification = RiskTrendClassificationEnum.DECREASING
    else:
        classification = RiskTrendClassificationEnum.STABLE

    return RiskTrendSummary(
        assessment_count=total,
        latest_score=round(latest_score, 2),
        average_score=score_stats.mean,
        min_score=score_stats.min_val,
        max_score=score_stats.max_val,
        score_delta=score_delta,
        level_transitions_count=transitions,
        high_level_count=high_count,
        critical_level_count=critical_count,
        classification=classification,
        points=sorted_pts,
    )


def analyze_alert_trends(points: List[AlertHistoricalPoint]) -> AlertTrendSummary:
    """
    Analyzes alert history, lifecycle distribution, and recurrence patterns.
    """
    total = len(points)
    if total == 0:
        return AlertTrendSummary(total_alerts=0)

    active = sum(1 for p in points if p.status == "ACTIVE")
    acknowledged = sum(1 for p in points if p.status == "ACKNOWLEDGED")
    in_review = sum(1 for p in points if p.status == "IN_REVIEW")
    resolved = sum(1 for p in points if p.status in ("RESOLVED", "EXPIRED", "SUPERSEDED"))

    # Recurrence detection:
    # Deterministic criteria: Multiple (>=2) high/urgent alerts or multiple resolved episodes
    high_priority_alerts = [p for p in points if p.priority in ("HIGH", "URGENT")]
    recurrence_detected = False
    recurrence_pattern = None

    if len(high_priority_alerts) >= 2:
        # Check if at least one was resolved while another followed
        resolved_high = [p for p in high_priority_alerts if p.status in ("RESOLVED", "EXPIRED", "SUPERSEDED")]
        if len(resolved_high) >= 1:
            recurrence_detected = True
            recurrence_pattern = f"RECURRING_ALERT_PATTERN: {len(high_priority_alerts)} high/urgent alerts detected with prior resolution."

    return AlertTrendSummary(
        total_alerts=total,
        active_alerts=active,
        acknowledged_alerts=acknowledged,
        in_review_alerts=in_review,
        resolved_alerts=resolved,
        recurrence_detected=recurrence_detected,
        recurrence_pattern=recurrence_pattern,
        points=sorted(points, key=lambda p: p.created_at),
    )
