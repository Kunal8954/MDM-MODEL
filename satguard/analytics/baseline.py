"""
satguard/analytics/baseline.py
Historical Baseline Construction & Deterministic Statistical Deviation Detection.
Adheres to conservative government-grade scientific semantics:
- Baseline is location-specific, time-bounded, transparent, and reproducible.
- Never claims "disaster predicted" or "failure predicted".
- Employs deterministic descriptive statistics (IQR, standard deviation, percentiles).
"""

from typing import List, Optional, Tuple
import math
from satguard.analytics.schemas import (
    BaselineStatistics,
    BaselineComparisonResult,
    BaselineComparisonStatusEnum,
    DeviationStatusEnum,
)


def calculate_descriptive_stats(values: List[float], metric_name: str) -> BaselineStatistics:
    """
    Computes deterministic baseline distribution statistics.
    Returns empty/insufficient stats if values list is empty.
    """
    valid_vals = [v for v in values if v is not None and not math.isnan(v)]
    n = len(valid_vals)
    if n == 0:
        return BaselineStatistics(metric_name=metric_name, sample_count=0)

    sorted_vals = sorted(valid_vals)
    mean_val = sum(sorted_vals) / n
    min_val = sorted_vals[0]
    max_val = sorted_vals[-1]

    # Median
    if n % 2 == 1:
        median_val = sorted_vals[n // 2]
    else:
        median_val = (sorted_vals[(n // 2) - 1] + sorted_vals[n // 2]) / 2.0

    # Variance & Standard Deviation
    if n > 1:
        variance = sum((x - mean_val) ** 2 for x in sorted_vals) / (n - 1)
        std_val = math.sqrt(variance)
    else:
        std_val = 0.0

    # Percentiles (p25, p75, IQR) using linear interpolation
    def _percentile(data: List[float], p: float) -> float:
        if len(data) == 1:
            return data[0]
        k = (len(data) - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return data[int(k)]
        d0 = data[int(f)] * (c - k)
        d1 = data[int(c)] * (k - f)
        return d0 + d1

    p25 = _percentile(sorted_vals, 0.25)
    p75 = _percentile(sorted_vals, 0.75)
    iqr = p75 - p25

    return BaselineStatistics(
        metric_name=metric_name,
        sample_count=n,
        mean=round(mean_val, 4),
        median=round(median_val, 4),
        std=round(std_val, 4),
        min_val=round(min_val, 4),
        max_val=round(max_val, 4),
        iqr=round(iqr, 4),
        p25=round(p25, 4),
        p75=round(p75, 4),
    )


def compare_value_to_baseline(
    current_value: Optional[float],
    baseline: BaselineStatistics,
    min_samples: int = 3,
) -> BaselineComparisonResult:
    """
    Compares the current observed metric against the historical baseline distribution.
    Uses deterministic statistical deviation rules (IQR & Z-score).
    """
    if current_value is None or baseline.sample_count < min_samples:
        return BaselineComparisonResult(
            comparison_status=BaselineComparisonStatusEnum.INSUFFICIENT_DATA,
            current_value=current_value,
            baseline_mean=baseline.mean,
            baseline_median=baseline.median,
            deviation_value=None,
            deviation_status=DeviationStatusEnum.NORMAL,
            explanation=f"Insufficient baseline samples (n={baseline.sample_count}, min_required={min_samples}) for statistical deviation testing.",
        )

    mean_val = baseline.mean or 0.0
    median_val = baseline.median or 0.0
    std_val = baseline.std or 0.0
    iqr = baseline.iqr or 0.0
    p75 = baseline.p75 or median_val
    p25 = baseline.p25 or median_val

    # Comparison to central tendency
    if abs(current_value - median_val) < 1e-4:
        comp_status = BaselineComparisonStatusEnum.WITHIN_BASELINE
    elif current_value > median_val:
        comp_status = BaselineComparisonStatusEnum.ABOVE_BASELINE
    else:
        comp_status = BaselineComparisonStatusEnum.BELOW_BASELINE

    # Statistical deviation classification
    # Rule 1: IQR Tukey fences
    upper_fence = p75 + (1.5 * iqr) if iqr > 0 else (p75 + 2 * std_val)
    extreme_fence = p75 + (3.0 * iqr) if iqr > 0 else (p75 + 3 * std_val)

    # Z-score if std is non-zero
    z_score = (current_value - mean_val) / std_val if std_val > 1e-6 else 0.0

    deviation_status = DeviationStatusEnum.NORMAL
    explanation_parts = []

    if current_value > extreme_fence or z_score >= 3.0:
        deviation_status = DeviationStatusEnum.ABOVE_HISTORICAL_RANGE
        explanation_parts.append(
            f"Current value ({current_value}) exceeds upper statistical historical range (upper fence {round(upper_fence, 3)}, z-score {round(z_score, 2)})."
        )
    elif current_value > upper_fence or z_score >= 2.0:
        deviation_status = DeviationStatusEnum.UNUSUAL_RELATIVE_TO_BASELINE
        explanation_parts.append(
            f"Current value ({current_value}) is unusual relative to historical baseline (z-score {round(z_score, 2)})."
        )
    elif abs(z_score) >= 1.5:
        deviation_status = DeviationStatusEnum.HISTORICAL_DEVIATION
        explanation_parts.append(
            f"Current value ({current_value}) exhibits historical deviation from mean ({round(mean_val, 3)})."
        )
    else:
        deviation_status = DeviationStatusEnum.NORMAL
        explanation_parts.append(
            f"Current value ({current_value}) falls within standard historical baseline distribution (n={baseline.sample_count})."
        )

    return BaselineComparisonResult(
        comparison_status=comp_status,
        current_value=round(current_value, 4),
        baseline_mean=baseline.mean,
        baseline_median=baseline.median,
        deviation_value=round(z_score, 3) if std_val > 1e-6 else None,
        deviation_status=deviation_status,
        explanation=" ".join(explanation_parts),
    )
