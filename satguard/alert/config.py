"""
satguard/alert/config.py
Configurable Thresholds, Mapping Rules, and Lifecycle Settings for Alert Decision Engine.
"""

from typing import Dict
from pydantic import BaseModel, Field


class AlertEngineConfig(BaseModel):
    """
    Transparent configuration for the Alert Decision Engine.
    Maps authoritative RiskAssessment classifications into operational government alerts.
    """
    alert_version: str = "alert_engine_v1"

    # Risk Level to Alert Level Mapping
    risk_to_alert_level_mapping: Dict[str, str] = Field(
        default_factory=lambda: {
            "LOW": "INFO",
            "MODERATE": "MONITOR",
            "HIGH": "HIGH",
            "CRITICAL": "URGENT",
        }
    )

    # Alert Level to Operational Priority Mapping
    alert_to_priority_mapping: Dict[str, str] = Field(
        default_factory=lambda: {
            "INFO": "ROUTINE",
            "MONITOR": "ROUTINE",
            "ELEVATED": "ELEVATED",
            "HIGH": "HIGH",
            "URGENT": "URGENT",
        }
    )

    # Time-to-Live / Review Intervals (in hours)
    alert_ttl_hours: Dict[str, float] = Field(
        default_factory=lambda: {
            "INFO": 168.0,      # 7 days
            "MONITOR": 96.0,    # 4 days
            "ELEVATED": 72.0,   # 3 days
            "HIGH": 48.0,       # 2 days
            "URGENT": 24.0,     # 1 day
        }
    )

    # Numeric Hierarchy for Escalation / De-escalation
    alert_level_severity_rank: Dict[str, int] = Field(
        default_factory=lambda: {
            "INFO": 1,
            "MONITOR": 2,
            "ELEVATED": 3,
            "HIGH": 4,
            "URGENT": 5,
        }
    )


default_alert_config = AlertEngineConfig()
