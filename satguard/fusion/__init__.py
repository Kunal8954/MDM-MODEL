"""
satguard/fusion package
Multi-Sensor Evidence Fusion Layer for SATGUARD.
"""

from satguard.fusion.schema import (
    TemporalAlignment,
    SpatialAlignment,
    Sentinel1Evidence,
    Sentinel2Evidence,
    RainfallEvidence,
    FireEvidence,
    EarthquakeEvidence,
    TerrainEvidence,
    EvidenceCorrelation,
    MultiSensorEvidence,
)

__all__ = [
    "TemporalAlignment",
    "SpatialAlignment",
    "Sentinel1Evidence",
    "Sentinel2Evidence",
    "RainfallEvidence",
    "FireEvidence",
    "EarthquakeEvidence",
    "TerrainEvidence",
    "EvidenceCorrelation",
    "MultiSensorEvidence",
]
