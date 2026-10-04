"""
satguard/risk/config.py
Configurable, Transparent, Versioned Thresholds and Weights for Risk Assessment Engine.
All parameters are auditable and strictly separated from machine learning or heuristic black boxes.
"""

from typing import Dict, Any
from pydantic import BaseModel, Field


class RiskEngineConfig(BaseModel):
    """
    Transparent configuration model for Risk Assessment Engine.
    Enforces deterministic scoring rules and thresholds.
    """
    engine_version: str = "risk_engine_v1"

    # Score Classification Thresholds (0.0 to 100.0)
    low_max_score: float = 24.99
    moderate_max_score: float = 49.99
    high_max_score: float = 74.99
    # Anything >= 75.0 is CRITICAL

    # Maximum Point Allocations per Dimension
    max_sar_points: float = 30.0
    max_optical_points: float = 25.0
    max_correlation_points: float = 25.0
    max_rainfall_points: float = 10.0
    max_earthquake_points: float = 10.0
    max_fire_points: float = 10.0
    max_terrain_points: float = 5.0

    # SAR Signal Scoring Rules
    sar_joint_change_thresholds: Dict[str, float] = Field(
        default_factory=lambda: {
            "tier1": 20.0,  # >= 20% -> 18 pts
            "tier2": 10.0,  # >= 10% -> 12 pts
            "tier3": 5.0,   # >= 5%  -> 8 pts
            "tier4": 2.0,   # >= 2%  -> 4 pts
        }
    )
    sar_region_count_thresholds: Dict[str, int] = Field(
        default_factory=lambda: {
            "tier1": 10,  # >= 10 regions -> 8 pts
            "tier2": 3,   # >= 3 regions  -> 5 pts
            "tier3": 1,   # >= 1 region   -> 3 pts
        }
    )
    sar_backscatter_shift_db: float = 0.5  # Mean delta shift to trigger backscatter shift points

    # Optical Signal Scoring Rules
    optical_change_pct_thresholds: Dict[str, float] = Field(
        default_factory=lambda: {
            "tier1": 25.0,  # >= 25% change -> 18 pts
            "tier2": 10.0,  # >= 10% change -> 10 pts
            "tier3": 5.0,   # >= 5% change  -> 5 pts
        }
    )
    cloud_rejection_threshold: float = 50.0  # Above this, optical evidence is damped to 0 pts

    # Correlation Bonus Points
    correlation_points: Dict[str, float] = Field(
        default_factory=lambda: {
            "MULTI-SENSOR_CHANGE_SIGNAL": 15.0,
            "SAR_RAINFALL_ASSOCIATION": 8.0,
            "EARTHQUAKE_SAR_ASSOCIATION": 8.0,
            "FIRE_OPTICAL_ASSOCIATION": 8.0,
            "TERRAIN_SLOPE_ASSOCIATION": 5.0,
        }
    )

    # Contextual Signals
    rainfall_threshold_mm: float = 25.0
    earthquake_distance_threshold_km: float = 150.0
    earthquake_mag_threshold: float = 4.0
    terrain_slope_threshold_deg: float = 20.0

    # Temporal Recency Windows (hours)
    recent_window_hours: float = 48.0
    recent_enough_window_hours: float = 336.0  # 14 days
    stale_damping_factor: float = 0.5


default_risk_config = RiskEngineConfig()
