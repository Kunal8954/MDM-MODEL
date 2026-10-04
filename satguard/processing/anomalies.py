"""
satguard/processing/anomalies.py
Anomaly region extraction with separated, auditable confidence measures.

A single "score" is not a usable output for an operational alerting system, because
three different questions are being conflated:

  1. Is the *comparison* trustworthy? (Was either scene usable at all?)
  2. Did the detectors actually agree that *this pixel* changed?
  3. Does this change *matter* for the requested monitoring purpose?

These are answered by three separate quantities and are never collapsed:

  detection_confidence  How reliable the run as a whole was: usable data, season,
                         registration, sensor comparability.
  anomaly_confidence    How strongly the independent layers corroborate this specific
                         region, discounted where the underlying data was weak.
  severity              Operational significance, driven by physical extent and the
                         monitoring mode, independent of how confident we are.

Every anomaly carries the evidence that produced it and the caveats that limit it, so
a reviewer can see why something was flagged without trusting the score blindly.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from satguard.geospatial.raster import GeoTransform, polygons_from_mask
from satguard.processing.change_detection import (
    ChangeLayer,
    DetectionOutcome,
    Severity,
    classify_severity,
    get_domain_config,
)

logger = logging.getLogger("satguard.anomalies")


class AnomalyError(Exception):
    error_code = "ANOMALY_EXTRACTION_FAILED"


# Severity must be ordered by operational rank. Comparing the string values sorts
# alphabetically, which would rank "critical" below "low" and invert every ordering.
SEVERITY_RANK: Dict[str, int] = {
    "none": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4,
}

# Sentinel-2 geolocation error is of the order of one pixel, so a region spanning only a
# handful of pixels can move materially under that uncertainty. The threshold is
# expressed in pixels because it must hold regardless of the sensor's resolution.
GEOLOCATION_SENSITIVE_PIXELS = 100


def severity_rank(severity: Severity) -> int:
    return SEVERITY_RANK.get(severity.value, 0)


@dataclass
class Evidence:
    """
    One auditable reason a region was flagged.

    `value` is the measured quantity and `interpretation` states plainly what it means,
    so a reviewer never has to infer intent from a bare number.
    """
    source: str
    observation: str
    value: Optional[float] = None
    unit: Optional[str] = None
    interpretation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "observation": self.observation,
            "value": None if self.value is None or not np.isfinite(self.value)
                     else round(float(self.value), 6),
            "unit": self.unit,
            "interpretation": self.interpretation,
        }


@dataclass
class AnomalyRegion:
    """One georeferenced anomalous region with its own confidence and evidence."""
    region_id: str
    geometry: Dict[str, Any]
    centroid_lon: float
    centroid_lat: float
    bbox: Tuple[float, float, float, float]
    area_m2: float
    pixel_count: int
    monitoring_mode: str
    detection_confidence: float
    anomaly_confidence: float
    severity: Severity
    evidence: List[Evidence] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    layer_agreement: Dict[str, float] = field(default_factory=dict)
    detected_at: Optional[datetime] = None
    source: str = "LIVE"

    @property
    def area_km2(self) -> float:
        return self.area_m2 / 1e6

    @property
    def area_ha(self) -> float:
        return self.area_m2 / 1e4

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "geometry": self.geometry,
            "centroid": {"lon": self.centroid_lon, "lat": self.centroid_lat},
            "bbox": list(self.bbox),
            "area_m2": round(self.area_m2, 2),
            "area_km2": round(self.area_km2, 6),
            "area_ha": round(self.area_ha, 4),
            "pixel_count": self.pixel_count,
            "monitoring_mode": self.monitoring_mode,
            "detection_confidence": round(self.detection_confidence, 4),
            "anomaly_confidence": round(self.anomaly_confidence, 4),
            "severity": self.severity.value,
            "layer_agreement": {
                k: round(v, 4) for k, v in self.layer_agreement.items()
            },
            "evidence": [item.to_dict() for item in self.evidence],
            "caveats": self.caveats,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "source": self.source,
        }


@dataclass
class RunConfidence:
    """
    How much the run as a whole can be trusted, independent of any single region.

    This is the first of the three separated quantities. A run with perfect layer
    agreement over 5% usable data is not a confident run, and must not be reported as
    one just because its pixels agree.
    """
    detection_confidence: float
    components: Dict[str, float]
    caveats: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detection_confidence": round(self.detection_confidence, 4),
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "caveats": self.caveats,
        }


def compute_run_confidence(
    outcome: DetectionOutcome,
    scl_available: bool = True,
    radiometric_applied: bool = False,
    radiometric_rejected: bool = False,
    alignment_unverified: bool = False,
    persistence_available: bool = False,
) -> RunConfidence:
    """
    Derive overall run confidence from data quality and comparability.

    Layer agreement is deliberately not a component here: it belongs to the per-region
    anomaly confidence. Mixing them would let strong agreement on poor data inflate the
    headline number.
    """
    factors = outcome.factors
    components: Dict[str, float] = {}
    caveats: List[str] = []

    valid_fraction = float(factors.get("valid_fraction", 0.0))
    components["usable_data"] = float(np.clip(valid_fraction / 0.5, 0.0, 1.0))
    if valid_fraction < 0.5:
        caveats.append(
            f"Only {valid_fraction:.1%} of the AOI was usable in both dates; "
            f"absence of detection elsewhere is not evidence of stability."
        )

    if scl_available:
        components["cloud_screening"] = 1.0
    else:
        components["cloud_screening"] = 0.4
        caveats.append(
            "Scene Classification Layer was unavailable, so cloud and shadow could "
            "not be masked. Undetected cloud may be reported as change."
        )

    seasonal_gap = int(factors.get("seasonal_gap_days", 0))
    seasonal_tolerance = 45
    components["seasonal_match"] = float(
        np.clip(1.0 - seasonal_gap / max(seasonal_tolerance, 1), 0.0, 1.0)
    )

    shift = float(factors.get("registration_shift_px", 0.0))
    if factors.get("registration_corrected"):
        components["co_registration"] = 0.9
    elif alignment_unverified:
        components["co_registration"] = 0.5
        caveats.append(
            "Scene alignment could not be verified, so residual misregistration may "
            "inflate the apparent change."
        )
    else:
        components["co_registration"] = float(np.clip(1.0 - shift / 2.0, 0.0, 1.0))

    if radiometric_applied:
        components["radiometric_consistency"] = 0.9
    elif radiometric_rejected:
        components["radiometric_consistency"] = 0.6
        caveats.append(
            "The radiometric relationship between the scenes was implausible and was "
            "not corrected, so scene-wide brightness differences remain in the result."
        )
    else:
        components["radiometric_consistency"] = 1.0

    components["cross_sensor"] = 1.0 if factors.get("cross_sensor_available") else 0.7
    components["temporal_persistence"] = 1.0 if persistence_available else 0.6
    if not persistence_available:
        caveats.append(
            "Only two dates were compared, so a persistent event cannot be "
            "distinguished from a single-scene artefact."
        )

    weights = {
        "usable_data": 0.25,
        "cloud_screening": 0.2,
        "seasonal_match": 0.15,
        "co_registration": 0.15,
        "radiometric_consistency": 0.1,
        "cross_sensor": 0.075,
        "temporal_persistence": 0.075,
    }
    confidence = float(
        sum(components.get(key, 0.5) * weight for key, weight in weights.items())
    )
    return RunConfidence(
        detection_confidence=float(np.clip(confidence, 0.0, 1.0)),
        components=components,
        caveats=caveats,
    )


def _layer_masks_by_id(outcome: DetectionOutcome) -> Dict[str, np.ndarray]:
    """
    Layer masks keyed by layer name, for per-region support counting.

    These come from the detection run itself rather than being recomputed, so the
    support measured here is guaranteed to match the run that produced the mask.
    """
    return {
        name: np.asarray(mask, dtype=bool)
        for name, mask in (outcome.layer_masks or {}).items()
        if np.asarray(mask).size
    }


def _region_support(
    region_mask: np.ndarray,
    layer_masks: Dict[str, np.ndarray],
) -> Dict[str, float]:
    """Fraction of the region supported by each independent layer."""
    support: Dict[str, float] = {}
    region_pixels = int(region_mask.sum())
    if region_pixels == 0:
        return support
    for name, mask in layer_masks.items():
        if mask.shape != region_mask.shape:
            continue
        support[name] = float(np.count_nonzero(region_mask & mask) / region_pixels)
    return support


def compute_anomaly_confidence(
    layer_support: Dict[str, float],
    detection_confidence: float,
    min_support: int = 2,
) -> float:
    """
    Confidence for one region: how many independent layers corroborate it, discounted
    by how trustworthy the underlying comparison was.

    This is deliberately distinct from `detection_confidence`. A region can be strongly
    corroborated (high anomaly confidence) while the run as a whole is weak, and the
    reverse is also true.
    """
    if not layer_support:
        return 0.0
    corroborating = sum(1 for value in layer_support.values() if value > 0.5)
    max_possible = max(min_support, len(layer_support))
    agreement = float(np.clip(corroborating / max_possible, 0.0, 1.0))
    mean_support = float(np.mean(list(layer_support.values())))
    raw = float(np.clip(0.5 * agreement + 0.5 * mean_support, 0.0, 1.0))
    return float(np.clip(raw * (0.5 + 0.5 * detection_confidence), 0.0, 1.0))


def extract_anomalies(
    outcome: DetectionOutcome,
    transform: GeoTransform,
    crs: str = "EPSG:4326",
    monitoring_mode: Optional[str] = None,
    run_confidence: Optional[RunConfidence] = None,
    layer_masks: Optional[Dict[str, np.ndarray]] = None,
    index_evidence: Optional[Dict[str, Any]] = None,
    detected_at: Optional[datetime] = None,
    source: str = "LIVE",
    max_regions: int = 100,
) -> List[AnomalyRegion]:
    """
    Convert a detection outcome into individually reportable anomaly regions.

    Each region gets real coordinates, a real area, its own confidence, the evidence
    behind it and the caveats that limit it.
    """
    mask = np.asarray(outcome.anomaly_mask, dtype=bool)
    if mask.ndim != 2:
        raise AnomalyError(
            f"Change mask must be 2-D, received shape {mask.shape}"
        )
    grid_shape = mask.shape

    if run_confidence is None:
        run_confidence = compute_run_confidence(outcome)
    mode = monitoring_mode or outcome.monitoring_mode
    supported = layer_masks or _layer_masks_by_id(outcome)

    polygons = polygons_from_mask(
        mask, transform, crs=crs, min_pixels=1, max_regions=max_regions
    )
    if not polygons:
        return []

    total_pixels = int(mask.sum())
    aoi_pixels = int(mask.size)
    domain_config = get_domain_config(mode)
    anomalies: List[AnomalyRegion] = []

    for polygon in polygons:
        region_mask = _mask_for_polygon(polygon, transform, grid_shape)
        if region_mask is None:
            support = {}
        else:
            support = _region_support(region_mask, supported)

        anomaly_confidence = compute_anomaly_confidence(
            support, run_confidence.detection_confidence
        )
        # Severity is decided per region from that region's own extent. Reusing the
        # run-level severity here would label a handful of pixels as critical simply
        # because a large change elsewhere in the same scene was critical.
        severity = classify_severity(
            confidence=anomaly_confidence,
            changed_fraction=polygon["pixel_count"] / max(aoi_pixels, 1),
            area_m2=float(polygon["area_m2"]),
            config=domain_config,
        )
        evidence = _build_evidence(
            polygon, outcome, support, index_evidence, anomaly_confidence
        )
        caveats = list(run_confidence.caveats)
        share = polygon["pixel_count"] / max(total_pixels, 1)
        if polygon["pixel_count"] < GEOLOCATION_SENSITIVE_PIXELS:
            caveats.append(
                f"Region covers only {polygon['pixel_count']} pixels, so its extent and "
                f"boundary are sensitive to geolocation error of about one pixel."
            )
        if severity is Severity.NONE:
            caveats.append(
                "Severity is 'none': the change was detected but is not "
                "operationally significant for this monitoring mode, or the "
                "independent layers did not corroborate it strongly enough."
            )
        if share > 0.8:
            caveats.append(
                "This region accounts for most of the detected change; verify the "
                "baseline is not stale or seasonally unmatched."
            )

        region_id = _region_id(polygon, mode, detected_at)
        anomalies.append(AnomalyRegion(
            region_id=region_id,
            geometry=polygon["geometry"],
            centroid_lon=polygon["centroid_lon"],
            centroid_lat=polygon["centroid_lat"],
            bbox=tuple(polygon["bbox"]),
            area_m2=float(polygon["area_m2"]),
            pixel_count=int(polygon["pixel_count"]),
            monitoring_mode=mode,
            detection_confidence=run_confidence.detection_confidence,
            anomaly_confidence=anomaly_confidence,
            severity=severity,
            evidence=evidence,
            caveats=caveats,
            layer_agreement=support,
            detected_at=detected_at or datetime.now(),
            source=source,
        ))

    # Most operationally significant first.
    anomalies.sort(
        key=lambda a: (severity_rank(a.severity), a.area_m2, a.anomaly_confidence),
        reverse=True,
    )
    return anomalies


def _mask_for_polygon(
    polygon: Dict[str, Any], transform: GeoTransform, grid_shape: Tuple[int, int]
) -> Optional[np.ndarray]:
    """Rasterise a polygon's bounding box back onto the analysis grid."""
    try:
        from rasterio.features import rasterize

        west, south, east, north = polygon["bbox"]
        pad = abs(transform.a) + abs(transform.e)
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [west - pad, south - pad], [east + pad, south - pad],
                [east + pad, north + pad], [west - pad, north + pad],
                [west - pad, south - pad],
            ]],
        }
        burned = rasterize(
            [(geometry, 1)],
            out_shape=grid_shape,
            transform=transform.as_affine(),
            fill=0,
            dtype="uint8",
        )
        return burned.astype(bool)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not rasterise anomaly region for layer support: %s", e)
        return None


def _region_id(
    polygon: Dict[str, Any], mode: str, detected_at: Optional[datetime]
) -> str:
    """Stable, human-referenceable identifier derived from location and time."""
    west, south = polygon["bbox"][0], polygon["bbox"][1]
    stamp = (detected_at or datetime.now()).strftime("%Y%m%dT%H%M%S")
    digest = hashlib.sha1(
        f"{mode}:{west:.6f}:{south:.6f}:{stamp}".encode()
    ).hexdigest()[:8]
    return f"{mode[:4].upper()}-{stamp}-{digest}"


def _build_evidence(
    polygon: Dict[str, Any],
    outcome: DetectionOutcome,
    support: Dict[str, float],
    index_evidence: Optional[Dict[str, Any]],
    anomaly_confidence: float,
) -> List[Evidence]:
    """Assemble the audit trail for one region."""
    evidence: List[Evidence] = [
        Evidence(
            source="detector",
            observation="Spatial extent of the change mask",
            value=float(polygon["area_km2"]),
            unit="km2",
            interpretation=(
                f"{polygon['pixel_count']} pixels changed, covering "
                f"{polygon['area_km2']:.4f} km2 at "
                f"{polygon['centroid_lat']:.5f}N {polygon['centroid_lon']:.5f}E."
            ),
        ),
    ]

    for layer in outcome.layers:
        if layer.layer is ChangeLayer.L5_DOMAIN:
            for rule in layer.details.get("rules_applied") or []:
                name = rule.get("rule") if isinstance(rule, dict) else str(rule)
                evidence.append(Evidence(
                    source="domain_rule",
                    observation=f"{layer.layer.value}:{name}",
                    interpretation=(
                        f"Monitoring mode '{outcome.monitoring_mode}' evaluated this "
                        f"region against the '{name}' rule"
                        + (
                            f" ({rule.get('status')})."
                            if isinstance(rule, dict) and rule.get("status")
                            else "."
                        )
                    ),
                ))
            continue

        share = support.get(layer.layer.value)
        if share is None:
            continue
        evidence.append(Evidence(
            source="layer",
            observation=layer.layer.value,
            value=share,
            unit="fraction_of_region",
            interpretation=(
                f"{layer.layer.value} supported "
                f"{share:.0%} of this region's pixels."
            ),
        ))

    if index_evidence:
        for index_name, detail in index_evidence.items():
            if not isinstance(detail, dict):
                continue
            threshold = detail.get("adaptive_threshold")
            median = detail.get("median_signed_difference")
            if threshold is None or median is None:
                continue
            evidence.append(Evidence(
                source="spectral_index_run_level",
                observation=index_name,
                value=float(median),
                unit="median_signed_difference",
                interpretation=(
                    f"Across the whole comparison, {index_name} differed by a median "
                    f"of {median:+.4f} against an adaptive threshold of {threshold:.4f}"
                    + (f" in the expected {detail.get('direction', 1):+d} direction."
                       if detail.get("direction") else ".")
                    + " This is run-level context, not measured inside this region."
                ),
            ))

    evidence.append(Evidence(
        source="confidence",
        observation="anomaly_confidence",
        value=anomaly_confidence,
        interpretation=(
            f"{anomaly_confidence:.0%} confidence that this region represents real "
            f"surface change rather than an artefact."
        ),
    ))
    return evidence


@dataclass
class DetectionReport:
    """The complete, self-describing output of one monitoring comparison."""
    aoi_id: str
    monitoring_mode: str
    run_confidence: RunConfidence
    anomalies: List[AnomalyRegion]
    outcome: DetectionOutcome
    source: str = "LIVE"
    generated_at: Optional[datetime] = None

    @property
    def anomaly_count(self) -> int:
        return len(self.anomalies)

    @property
    def total_area_km2(self) -> float:
        return float(sum(a.area_km2 for a in self.anomalies))

    @property
    def max_severity(self) -> Severity:
        """Highest severity present, which is not necessarily every region's."""
        return max(
            (a.severity for a in self.anomalies), key=severity_rank, default=Severity.NONE
        )

    def to_dict(self, include_outcome: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "aoi_id": self.aoi_id,
            "monitoring_mode": self.monitoring_mode,
            "source": self.source,
            "generated_at": (self.generated_at or datetime.now()).isoformat(),
            "run_confidence": self.run_confidence.to_dict(),
            "anomaly_count": self.anomaly_count,
            "run_severity": self.outcome.severity.value,
            "max_anomaly_severity": self.max_severity.value,
            "total_area_km2": round(self.total_area_km2, 6),
            "anomalies": [a.to_dict() for a in self.anomalies],
        }
        if include_outcome:
            payload["detection"] = self.outcome.to_dict()
        return payload


def summarize_by_severity(anomalies: Sequence[AnomalyRegion]) -> Dict[str, Any]:
    """Counts and areas per severity, for dashboards."""
    summary: Dict[str, Any] = {}
    for severity in Severity:
        matching = [a for a in anomalies if a.severity is severity]
        summary[severity.value] = {
            "count": len(matching),
            "area_km2": round(sum(a.area_km2 for a in matching), 6),
        }
    return summary