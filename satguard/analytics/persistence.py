"""
satguard/analytics/persistence.py
Deterministic Persistent Change Detection Engine.
Distinguishes isolated, intermittent, and persistent change signals.
Adheres strictly to deterministic, explainable, and non-predictive scientific semantics.
"""

from typing import List, Optional
from satguard.analytics.schemas import (
    SARHistoricalPoint,
    PersistenceResult,
    PersistenceStatusEnum,
)

# Configurable Default Thresholds
PERSISTENCE_MIN_OBSERVATIONS_DEFAULT = 2
PERSISTENCE_MIN_SIGNAL_RATIO_DEFAULT = 0.60
PERSISTENCE_CONSECUTIVE_MIN_DEFAULT = 2


def evaluate_persistence(
    points: List[SARHistoricalPoint],
    min_observations: int = PERSISTENCE_MIN_OBSERVATIONS_DEFAULT,
    min_signal_ratio: float = PERSISTENCE_MIN_SIGNAL_RATIO_DEFAULT,
    min_consecutive: int = PERSISTENCE_CONSECUTIVE_MIN_DEFAULT,
) -> PersistenceResult:
    """
    Evaluates temporal persistence of SAR change observations.

    Criteria:
    1. If points count < min_observations: INSUFFICIENT_DATA.
    2. If 0 significant change observations: NO_SIGNAL.
    3. If exactly 1 significant change observation: ISOLATED_SIGNAL.
    4. If >= 2 significant change observations:
       - If consecutive significant count >= min_consecutive AND signal_ratio >= min_signal_ratio:
         PERSISTENT_SIGNAL.
       - Otherwise (e.g. alternating/interspersed or low ratio):
         INTERMITTENT_SIGNAL.
    """
    # Sort points chronologically by t2_acquisition_time or t1_acquisition_time
    sorted_points = sorted(
        points,
        key=lambda p: p.t2_acquisition_time or p.t1_acquisition_time or ""
    )

    total_obs = len(sorted_points)
    if total_obs < min_observations:
        return PersistenceResult(
            persistence_status=PersistenceStatusEnum.INSUFFICIENT_DATA,
            significant_observations_count=0,
            total_evaluated_observations=total_obs,
            signal_ratio=0.0,
            consecutive_significant_count=0,
            explanation=(
                f"Insufficient historical observations (evaluated {total_obs}, "
                f"minimum required {min_observations}) to determine temporal persistence."
            ),
        )

    # Count significant change detections
    significant_count = sum(1 for p in sorted_points if p.is_significant_change)
    signal_ratio = round(significant_count / total_obs, 4) if total_obs > 0 else 0.0

    # Calculate max consecutive significant detections
    max_consecutive = 0
    current_consecutive = 0
    for p in sorted_points:
        if p.is_significant_change:
            current_consecutive += 1
            if current_consecutive > max_consecutive:
                max_consecutive = current_consecutive
        else:
            current_consecutive = 0

    if significant_count == 0:
        return PersistenceResult(
            persistence_status=PersistenceStatusEnum.NO_SIGNAL,
            significant_observations_count=0,
            total_evaluated_observations=total_obs,
            signal_ratio=0.0,
            consecutive_significant_count=0,
            explanation=f"No significant change detected across {total_obs} temporal observations.",
        )

    if significant_count == 1:
        return PersistenceResult(
            persistence_status=PersistenceStatusEnum.ISOLATED_SIGNAL,
            significant_observations_count=1,
            total_evaluated_observations=total_obs,
            signal_ratio=signal_ratio,
            consecutive_significant_count=1,
            explanation=(
                f"Single isolated change observation detected out of {total_obs} observations. "
                "No temporal persistence established."
            ),
        )

    # >= 2 significant observations
    if max_consecutive >= min_consecutive and signal_ratio >= min_signal_ratio:
        status = PersistenceStatusEnum.PERSISTENT_SIGNAL
        explanation = (
            f"Persistent change signal detected: {significant_count}/{total_obs} observations "
            f"({round(signal_ratio * 100, 1)}%) showed significant change with at least "
            f"{max_consecutive} consecutive significant detections. Elevated field verification priority."
        )
    else:
        status = PersistenceStatusEnum.INTERMITTENT_SIGNAL
        explanation = (
            f"Intermittent change signal detected: {significant_count}/{total_obs} observations "
            f"({round(signal_ratio * 100, 1)}%) showed significant change, but observations are "
            f"interspersed (max consecutive={max_consecutive}) or below persistence ratio threshold ({min_signal_ratio})."
        )

    return PersistenceResult(
        persistence_status=status,
        significant_observations_count=significant_count,
        total_evaluated_observations=total_obs,
        signal_ratio=signal_ratio,
        consecutive_significant_count=max_consecutive,
        explanation=explanation,
    )
