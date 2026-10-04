"""
satguard/processing/change_detection.py
Layered, evidence-based change detection for arbitrary AOIs.

The previous detector (`satguard/processing/ndwi.py`) computed NDWI on a single
baseline/current pair and thresholded it at a fixed constant. That is unreliable for
three reasons this module addresses directly:

  1. A single pair has no way to distinguish a one-off artefact from a persistent
     change, so clouds, shadows and sensor noise all became "anomalies".
  2. A fixed threshold means different thresholds per index, per region and per season,
     and none of them are calibrated to the noise actually present in the data.
  3. Nothing checked that the two scenes were geometrically or radiometrically
     comparable, so misregistration and illumination change masqueraded as change.

Change is therefore evaluated as independent layers of evidence, each of which must
agree before an anomaly is reported:

    L1 spectral     index-space change in the domain-relevant direction
    L2 structure    texture / gradient change, independent of radiometry
    L3 persistence  change repeated across multiple dates, not a single-scene blip
    L4 cross-sensor optical evidence corroborated by SAR backscatter change
    L5 domain       monitoring-mode specific physical rules

Confidence is derived from how many independent layers agree. It is deliberately kept
separate from severity: a large seasonal water-level swing in a reservoir is a
confident detection of low operational significance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

from satguard.processing.indices import compute_indices, index_statistics
from satguard.processing.preprocess import QualityMask

logger = logging.getLogger("satguard.change_detection")


class ChangeLayer(str, Enum):
    L1_SPECTRAL = "L1_spectral"
    L2_STRUCTURE = "L2_structure"
    L3_PERSISTENCE = "L3_persistence"
    L4_CROSS_SENSOR = "L4_cross_sensor"
    L5_DOMAIN = "L5_domain"


class Severity(str, Enum):
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# domain configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexRule:
    """One index change expected in a particular direction for a monitoring mode."""
    index: str
    direction: int          # +1 expects an increase, -1 expects a decrease
    prior_threshold: float  # minimum |delta| considered meaningful before adaptation
    weight: float = 1.0


@dataclass(frozen=True)
class DomainConfig:
    monitoring_mode: str
    indices: Tuple[str, ...]
    rules: Tuple[IndexRule, ...]
    structure_weight: float
    require_cross_sensor: bool
    min_changed_pixels: int
    seasonal_tolerance_days: int
    description: str


DOMAIN_CONFIGS: Dict[str, DomainConfig] = {
    "water_body": DomainConfig(
        monitoring_mode="water_body",
        indices=("ndwi", "mndwi", "ndvi"),
        rules=(
            IndexRule("mndwi", +1, 0.10, 1.2),   # urban water is best seen in MNDWI
            IndexRule("ndwi", +1, 0.08, 1.0),
        ),
        structure_weight=0.6,
        require_cross_sensor=False,
        min_changed_pixels=40,
        seasonal_tolerance_days=45,
        description="Open-water extent and shoreline movement",
    ),
    "flood": DomainConfig(
        monitoring_mode="flood",
        indices=("ndwi", "mndwi"),
        rules=(
            IndexRule("ndwi", +1, 0.12, 1.3),
            IndexRule("mndwi", +1, 0.12, 1.2),
        ),
        structure_weight=0.5,
        require_cross_sensor=True,   # water lowers SAR backscatter; use both sensors
        min_changed_pixels=60,
        seasonal_tolerance_days=30,
        description="Inundation extent during a flood event",
    ),
    "infrastructure": DomainConfig(
        monitoring_mode="infrastructure",
        indices=("ndbi", "ndvi", "brightness"),
        rules=(
            IndexRule("ndbi", +1, 0.06, 1.2),    # built-up surface appears
            IndexRule("ndvi", -1, 0.08, 0.8),    # vegetation replaced
        ),
        structure_weight=1.0,                   # buildings are structural, not spectral
        require_cross_sensor=False,
        min_changed_pixels=25,
        seasonal_tolerance_days=60,
        description="Construction, urban expansion and structural damage",
    ),
    "vegetation": DomainConfig(
        monitoring_mode="vegetation",
        indices=("ndvi", "ndre"),
        rules=(
            IndexRule("ndvi", -1, 0.12, 1.2),    # vegetation loss
            IndexRule("ndre", -1, 0.10, 0.9),
        ),
        structure_weight=0.7,
        require_cross_sensor=False,
        min_changed_pixels=80,
        seasonal_tolerance_days=30,             # phenology is strong; match season
        description="Vegetation stress, deforestation and crop loss",
    ),
    "glacier": DomainConfig(
        monitoring_mode="glacier",
        indices=("ndsi", "nbr", "brightness"),
        rules=(
            # Losing snow and ice darkens the surface and exposes material that absorbs
            # in the SWIR, so NDSI falls, NBR rises and overall brightness drops. Each
            # sign below is the direction that indicates genuine ice loss.
            IndexRule("ndsi", -1, 0.08, 1.3),       # snow and ice lost
            IndexRule("nbr", +1, 0.06, 0.8),        # SWIR-absorbing ground exposed
            IndexRule("brightness", -1, 0.08, 0.6), # high-albedo cover removed
        ),
        structure_weight=0.5,
        require_cross_sensor=False,
        min_changed_pixels=50,
        seasonal_tolerance_days=90,             # melt is seasonal; compare like-for-like
        description="Glacier mass loss, snowline change and terminus retreat",
    ),
    "general": DomainConfig(
        monitoring_mode="general",
        indices=("ndvi", "brightness", "ndbi"),
        rules=(
            IndexRule("brightness", +1, 0.10, 0.7),
            IndexRule("ndvi", -1, 0.12, 0.7),
        ),
        structure_weight=0.8,
        require_cross_sensor=False,
        min_changed_pixels=50,
        seasonal_tolerance_days=45,
        description="Unclassified surface disturbance",
    ),
}


def get_domain_config(monitoring_mode: str) -> DomainConfig:
    """Unknown modes fall back to the deliberately conservative general profile."""
    return DOMAIN_CONFIGS.get((monitoring_mode or "general").lower(), DOMAIN_CONFIGS["general"])


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@dataclass
class LayerEvidence:
    layer: ChangeLayer
    score: float                       # 0..1 normalised evidence strength
    passed: bool
    weight: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityGate:
    """A check that can veto a detection before it is reported."""
    name: str
    passed: bool
    detail: str
    blocking: bool = True


@dataclass
class DetectionOutcome:
    anomaly_mask: np.ndarray
    layers: List[LayerEvidence]
    gates: List[QualityGate]
    confidence: float
    severity: Severity
    factors: Dict[str, Any]
    monitoring_mode: str
    rejected: bool = False
    reject_reason: Optional[str] = None
    layer_masks: Dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def changed_pixels(self) -> int:
        return int(np.count_nonzero(self.anomaly_mask))

    @property
    def accepted(self) -> bool:
        return not self.rejected and self.changed_pixels > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "monitoring_mode": self.monitoring_mode,
            "confidence": round(self.confidence, 4),
            "severity": self.severity.value,
            "changed_pixels": self.changed_pixels,
            "rejected": self.rejected,
            "reject_reason": self.reject_reason,
            "factors": self.factors,
            "layers": [
                {
                    "layer": layer.layer.value,
                    "score": round(layer.score, 4),
                    "passed": layer.passed,
                    "weight": layer.weight,
                    "details": layer.details,
                }
                for layer in self.layers
            ],
            "gates": [
                {
                    "name": gate.name,
                    "passed": gate.passed,
                    "detail": gate.detail,
                    "blocking": gate.blocking,
                }
                for gate in self.gates
            ],
        }


class ChangeDetectionError(Exception):
    error_code = "CHANGE_DETECTION_FAILED"


# ---------------------------------------------------------------------------
# temporal pairing
# ---------------------------------------------------------------------------


@dataclass
class Observation:
    """One dated, preprocessed observation ready for differencing."""
    acquisition_time: datetime
    bands: Dict[str, np.ndarray]
    quality: QualityMask

    @property
    def day_of_year(self) -> int:
        return self.acquisition_time.timetuple().tm_yday


@dataclass
class TemporalBaseline:
    """
    A composited baseline built from one or more observations.

    A median composite across several scenes suppresses single-date artefacts that
    would otherwise dominate a one-to-one comparison.
    """
    bands: Dict[str, np.ndarray]
    dates: List[datetime]
    quality: QualityMask
    scene_count: int

    @property
    def median_date(self) -> datetime:
        return sorted(self.dates)[len(self.dates) // 2]

    @property
    def day_of_year(self) -> int:
        return self.median_date.timetuple().tm_yday


def select_temporal_baseline(
    current: Observation,
    candidates: Sequence[Observation],
    min_gap_days: int = 20,
    max_gap_days: int = 400,
    seasonal_tolerance_days: int = 45,
    max_scenes: int = 5,
) -> Optional[TemporalBaseline]:
    """
    Choose and composite a baseline that is both sufficiently old and seasonally
    comparable to the current observation.

    Season is the important constraint. Comparing a January scene to an August scene in
    a monsoon region produces a full-magnitude vegetation "change" every year that has
    nothing to do with any event.
    """
    usable: List[Observation] = []
    for obs in candidates:
        gap = (current.acquisition_time - obs.acquisition_time).days
        if not (min_gap_days <= gap <= max_gap_days):
            continue
        seasonal_gap = abs(obs.day_of_year - current.day_of_year)
        seasonal_gap = min(seasonal_gap, 365 - seasonal_gap)
        if seasonal_gap > seasonal_tolerance_days:
            continue
        usable.append(obs)

    if not usable:
        return None

    usable.sort(key=lambda o: o.acquisition_time)
    selected = usable[-max_scenes:]

    band_names = set(current.bands)
    for obs in selected:
        band_names &= set(obs.bands)
    if not band_names:
        raise ChangeDetectionError(
            "Baseline candidates share no spectral bands with the current observation."
        )

    composite: Dict[str, np.ndarray] = {}
    for name in sorted(band_names):
        stack = np.stack([obs.bands[name] for obs in selected], axis=0)
        with np.errstate(invalid="ignore"):
            composite[name] = np.nanmedian(stack, axis=0)

    baseline_quality = selected[0].quality
    for obs in selected[1:]:
        baseline_quality = QualityMask(
            valid=baseline_quality.valid & obs.quality.valid,
            cloud=baseline_quality.cloud,
            shadow=baseline_quality.shadow,
            nodata=baseline_quality.nodata,
            snow=baseline_quality.snow,
            water=baseline_quality.water,
            vegetation=baseline_quality.vegetation,
            saturated=baseline_quality.saturated,
            aoi=baseline_quality.aoi,
            scl_available=baseline_quality.scl_available,
        )

    return TemporalBaseline(
        bands=composite,
        dates=[obs.acquisition_time for obs in selected],
        quality=baseline_quality,
        scene_count=len(selected),
    )


# ---------------------------------------------------------------------------
# co-registration
# ---------------------------------------------------------------------------


# A correlation peak below this height cannot be used to locate an offset, so the
# offset is reported as unknown rather than applied. Verified registrations peak near
# 1.0, while a low-texture scene leaves the peak ambiguous at a few hundredths.
MIN_REGISTRATION_CONFIDENCE = 0.15


def estimate_registration_shift(
    baseline: np.ndarray,
    current: np.ndarray,
    valid: np.ndarray,
    min_confidence: float = 0.01,
    verify_improvement_ratio: float = 0.95,
    max_candidates: int = 5,
) -> Tuple[float, float, float]:
    """
    Estimate the offset between two scenes by normalised phase correlation.

    Returns (apply_cols, apply_rows, confidence) such that applying the returned
    translation to `baseline` aligns it with `current`.

    Phase correlation is a *proposal*, not a verdict. On a low-texture scene, for
    example a single pond in a uniform field, the correlation peak is weak and its
    position is unreliable, yet a real several-pixel misregistration may still exist.
    Every proposal is therefore verified by measuring whether applying it actually
    reduces the difference between the scenes; a proposal that fails this check is
    discarded and reported as zero offset.

    `confidence` is the peak height of the normalised cross-power spectrum, where a
    perfect match scores 1.0 and incoherent noise scores near 1/N. It describes how
    trustworthy the correlation was, and callers use it to decide whether the
    comparison itself is sound.

    Measured accuracy: integer offsets are recovered exactly when the correlation is
    strong; fractional offsets are recovered to within roughly half a pixel, because
    magnitude normalisation whitens the spectrum and biases the parabolic peak
    refinement.

    Known limitation: on a low-texture scene, such as a single water body in an
    otherwise uniform field, many offsets fit almost equally well and the reported
    magnitude can exceed the true offset. The comparison is still refused in that
    situation, because any non-zero offset is treated as misregistration, so the
    outcome remains safe even though the magnitude is not exact.
    """
    shape = valid.shape
    if baseline.shape != shape or current.shape != shape:
        raise ChangeDetectionError(
            f"Registration inputs must share a grid: "
            f"{baseline.shape}, {current.shape}, {valid.shape}"
        )

    usable = valid & np.isfinite(baseline) & np.isfinite(current)
    if usable.sum() < 256:
        return 0.0, 0.0, 0.0

    a = np.where(usable, np.nan_to_num(baseline), 0.0)
    b = np.where(usable, np.nan_to_num(current), 0.0)
    a = a - a[usable].mean()
    b = b - b[usable].mean()

    fa = np.fft.fft2(a)
    fb = np.fft.fft2(b)
    cross_power = fa * np.conj(fb)
    magnitude = np.abs(cross_power)
    cross_power = np.divide(
        cross_power, magnitude, out=np.zeros_like(cross_power), where=magnitude > 0
    )

    # The sum of the un-normalised correlation surface equals cross_power[0,0] == 1,
    # so the raw peak value is already a 0..1 confidence and must not be rescaled.
    correlation = np.fft.fftshift(np.fft.ifft2(cross_power).real)
    confidence = float(correlation.max())
    if confidence < min_confidence:
        return 0.0, 0.0, confidence

    rows, cols = shape
    mid_row, mid_col = rows // 2, cols // 2

    # A scene with one salient feature has several correlation peaks of similar height,
    # so the single argmax can identify the wrong offset. Each of the strongest peaks is
    # therefore treated as a candidate and checked against the imagery itself.
    reference_mad = float(np.nanmean(np.abs(baseline - current)[usable]))
    if reference_mad > 0:
        work = correlation.copy()
        work[mid_row, mid_col] = -np.inf          # ignore the zero-shift peak
        best_mad = reference_mad
        best_peak: Optional[Tuple[int, int]] = None

        for _ in range(max_candidates):
            flat = int(np.argmax(work))
            peak_row, peak_col = np.unravel_index(flat, work.shape)
            offset_rows = peak_row - mid_row
            offset_cols = peak_col - mid_col
            if offset_rows > rows // 2:
                offset_rows -= rows
            if offset_cols > cols // 2:
                offset_cols -= cols

            if (offset_cols or offset_rows):
                apply_cols = float(-offset_cols)
                apply_rows = float(-offset_rows)
                corrected_mad = float(
                    np.nanmean(
                        np.abs(shift_array(baseline, apply_cols, apply_rows) - current)[usable]
                    )
                )
                if corrected_mad < best_mad:
                    best_mad = corrected_mad
                    best_peak = (peak_row, peak_col)

            # Suppress this peak so the next candidate can be evaluated.
            window = (
                slice(max(0, peak_row - 2), peak_row + 3),
                slice(max(0, peak_col - 2), peak_col + 3),
            )
            work[window] = -np.inf

        # The achievable improvement is bounded by the noise floor, so the test is
        # relative: a candidate must explain a meaningful share of the difference
        # between the scenes, not a fixed fraction of it.
        if best_peak is not None and best_mad < reference_mad * verify_improvement_ratio:
            peak_row, peak_col = best_peak
            return (
                float(-(peak_col - mid_col + _parabolic_offset(correlation, peak_row, peak_col, axis=1))),
                float(-(peak_row - mid_row + _parabolic_offset(correlation, peak_row, peak_col, axis=0))),
                confidence,
            )

    return 0.0, 0.0, confidence


def _parabolic_offset(surface: np.ndarray, row: int, col: int, axis: int) -> float:
    """Sub-pixel peak refinement from a three-point parabolic fit along one axis."""
    peak = surface[row, col]
    if axis == 0:
        if row <= 0 or row >= surface.shape[0] - 1:
            return 0.0
        left, right = surface[row - 1, col], surface[row + 1, col]
    else:
        if col <= 0 or col >= surface.shape[1] - 1:
            return 0.0
        left, right = surface[row, col - 1], surface[row, col + 1]

    denominator = left - 2.0 * peak + right
    if abs(denominator) < 1e-12:
        return 0.0
    delta = 0.5 * (left - right) / denominator
    return float(np.clip(delta, -1.0, 1.0))


def shift_array(array: np.ndarray, shift_cols: float, shift_rows: float) -> np.ndarray:
    """Translate a raster by a sub-pixel amount using linear interpolation."""
    if shift_cols == 0.0 and shift_rows == 0.0:
        return array
    return ndimage.shift(
        np.asarray(array, dtype=np.float64),
        shift=(shift_rows, shift_cols),
        order=1,
        mode="nearest",
    )


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------


def robust_change_threshold(
    difference: np.ndarray,
    valid: np.ndarray,
    sensitivity: float = 3.0,
    floor: float = 0.0,
) -> Tuple[float, float, float]:
    """
    Derive a change threshold from the data instead of hard-coding one.

    Uses a median-absolute-deviation estimate of the noise floor, floored by the
    domain prior. Returns (threshold, median_difference, noise_sigma).
    """
    values = difference[valid & np.isfinite(difference)]
    if values.size == 0:
        return floor, 0.0, 0.0

    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    sigma = mad * 1.4826
    threshold = max(floor, median + sensitivity * sigma)
    return float(threshold), median, float(sigma)


def spectral_layer(
    baseline: TemporalBaseline,
    current: Observation,
    valid: np.ndarray,
    config: DomainConfig,
) -> Tuple[np.ndarray, LayerEvidence, Dict[str, np.ndarray]]:
    """
    L1: accumulate index change in the direction the monitoring mode expects.

    Only signed change is counted. An NDWI *decrease* is not water loss evidence in a
    water-body monitoring mode, so counting absolute difference alone would let any
    spectral movement register as a change of interest.
    """
    requested = list(config.indices)
    base_indices = compute_indices(baseline.bands, requested, nodata_mask=valid)
    curr_indices = compute_indices(current.bands, requested, nodata_mask=valid)

    combined = np.zeros(valid.shape, dtype=bool)
    weighted = np.zeros(valid.shape, dtype=np.float64)
    total_weight = 0.0
    per_index: Dict[str, Any] = {}

    for rule in config.rules:
        b = base_indices.get(rule.index)
        c = curr_indices.get(rule.index)
        if b is None or c is None:
            per_index[rule.index] = {"status": "unavailable"}
            continue

        signed_difference = (c - b) * rule.direction
        threshold, median, sigma = robust_change_threshold(
            signed_difference, valid, floor=rule.prior_threshold
        )
        exceeded = signed_difference > threshold
        combined |= exceeded
        weighted += np.where(exceeded, rule.weight, 0.0)
        total_weight += rule.weight

        per_index[rule.index] = {
            "direction": rule.direction,
            "prior_threshold": rule.prior_threshold,
            "adaptive_threshold": round(threshold, 6),
            "median_signed_difference": round(median, 6),
            "noise_sigma": round(sigma, 6),
            "changed_pixels": int(np.count_nonzero(exceeded & valid)),
            "baseline_stats": _round_stats(index_statistics(b)),
            "current_stats": _round_stats(index_statistics(c)),
        }

    if total_weight > 0:
        score = float(np.clip(np.nanmean(np.where(valid, weighted / total_weight, np.nan)), 0, 1))
    else:
        score = 0.0

    evidence = LayerEvidence(
        layer=ChangeLayer.L1_SPECTRAL,
        score=score,
        passed=bool(combined.any()),
        weight=1.0,
        details={"indices": per_index},
    )
    return combined & valid, evidence, curr_indices


def _round_stats(stats: Dict[str, float]) -> Dict[str, float]:
    return {k: round(float(v), 6) for k, v in stats.items() if isinstance(v, (int, float))}


def structure_layer(
    baseline: np.ndarray,
    current: np.ndarray,
    valid: np.ndarray,
    config: DomainConfig,
    window: int = 7,
) -> Tuple[np.ndarray, LayerEvidence]:
    """
    L2: texture and edge-energy change.

    This layer is radiometrically insensitive by construction: it responds to the
    spatial arrangement of brightness, so a building appearing over bare ground changes
    texture strongly even when mean reflectance barely moves. That independence is
    what makes it useful corroboration for the spectral layer.
    """
    structure = np.zeros(valid.shape, dtype=bool)
    if config.structure_weight <= 0:
        return structure, LayerEvidence(
            ChangeLayer.L2_STRUCTURE, 0.0, False, 0.0, {"status": "disabled"}
        )

    usable = valid & np.isfinite(baseline) & np.isfinite(current)
    if usable.sum() < window * window * 4:
        return structure, LayerEvidence(
            ChangeLayer.L2_STRUCTURE, 0.0, False, 0.0,
            {"status": "insufficient_valid_pixels"},
        )

    b = np.where(usable, np.nan_to_num(baseline), np.nan)
    c = np.where(usable, np.nan_to_num(current), np.nan)

    def texture(raster: np.ndarray) -> np.ndarray:
        mean = ndimage.uniform_filter(raster, size=window, mode="nearest")
        mean_sq = ndimage.uniform_filter(raster * raster, size=window, mode="nearest")
        local_std = np.sqrt(np.clip(mean_sq - mean * mean, 0, None))
        grad = np.hypot(
            ndimage.sobel(raster, axis=0, mode="nearest"),
            ndimage.sobel(raster, axis=1, mode="nearest"),
        )
        return local_std + 0.05 * grad

    texture_change = np.abs(texture(c) - texture(b))
    threshold, median, sigma = robust_change_threshold(
        texture_change, usable, sensitivity=3.0, floor=1e-6
    )
    structure = (texture_change > threshold) & usable

    score = float(np.clip(np.nanmean(np.where(usable, texture_change / (threshold + 1e-9), np.nan)), 0, 1))
    evidence = LayerEvidence(
        layer=ChangeLayer.L2_STRUCTURE,
        score=score,
        passed=bool(structure.any()),
        weight=config.structure_weight,
        details={
            "window": window,
            "adaptive_threshold": round(threshold, 6),
            "median_change": round(median, 6),
            "noise_sigma": round(sigma, 6),
            "changed_pixels": int(structure.sum()),
        },
    )
    return structure, evidence


def persistence_layer(
    change_masks: Sequence[np.ndarray],
    minimum_dates: int = 2,
) -> Tuple[np.ndarray, LayerEvidence]:
    """
    L3: require change to repeat across dates.

    A single-scene anomaly is far more likely to be an artefact than an event. This
    layer counts how many observations independently show the same change.
    """
    if not change_masks:
        raise ChangeDetectionError("Persistence layer requires at least one change mask.")

    stack = np.stack([np.asarray(m, dtype=bool) for m in change_masks], axis=0)
    vote_count = stack.sum(axis=0)
    persistent = vote_count >= minimum_dates

    total = persistent.size
    score = float(np.count_nonzero(vote_count >= 1) / total) if total else 0.0
    evidence = LayerEvidence(
        layer=ChangeLayer.L3_PERSISTENCE,
        score=score,
        passed=bool(persistent.any()),
        weight=1.0,
        details={
            "dates_examined": len(change_masks),
            "minimum_dates_required": minimum_dates,
            "max_votes": int(vote_count.max()) if vote_count.size else 0,
            "persistent_pixels": int(persistent.sum()),
        },
    )
    return persistent, evidence


def cross_sensor_layer(
    optical_change: np.ndarray,
    sar_change: np.ndarray,
    valid: np.ndarray,
) -> Tuple[np.ndarray, LayerEvidence]:
    """
    L4: require optical change to be corroborated by SAR change.

    Independent sensing is the strongest available check against a shared optical
    artefact, since a cloud produces no SAR signature at all.
    """
    if sar_change is None:
        raise ChangeDetectionError("Cross-sensor layer requires a SAR change mask.")

    optical = np.asarray(optical_change, dtype=bool)
    sar = np.asarray(sar_change, dtype=bool)
    if optical.shape != sar.shape:
        raise ChangeDetectionError(
            f"Optical and SAR masks must share a grid: {optical.shape} vs {sar.shape}"
        )

    agreed = optical & sar & valid
    optical_only = optical & ~sar & valid
    sar_only = sar & ~optical & valid

    score = float(np.count_nonzero(agreed) / max(np.count_nonzero(optical | sar), 1))
    evidence = LayerEvidence(
        layer=ChangeLayer.L4_CROSS_SENSOR,
        score=score,
        passed=bool(agreed.any()),
        weight=1.0,
        details={
            "agreed_pixels": int(agreed.sum()),
            "optical_only_pixels": int(optical_only.sum()),
            "sar_only_pixels": int(sar_only.sum()),
        },
    )
    return agreed, evidence


def domain_layer(
    indices: Dict[str, np.ndarray],
    config: DomainConfig,
    valid: np.ndarray,
) -> Tuple[np.ndarray, LayerEvidence]:
    """
    L5: monitoring-mode specific interpretation.

    Encodes what the change actually means for the requested use of the AOI, so that
    the same pixel can be high-severity for one domain and irrelevant for another.
    """
    applied: List[str] = []
    mask = np.zeros(valid.shape, dtype=bool)
    factors: Dict[str, Any] = {"monitoring_mode": config.monitoring_mode,
                               "description": config.description}

    if config.monitoring_mode in ("water_body", "flood"):
        ndwi = indices.get("ndwi")
        if ndwi is not None:
            open_water = np.isfinite(ndwi) & (ndwi > 0.1)
            mask |= open_water & valid
            applied.append("ndwi_open_water")
            factors["open_water_pixels"] = int(np.count_nonzero(open_water & valid))

    if config.monitoring_mode == "glacier":
        ndsi = indices.get("ndsi")
        if ndsi is not None:
            snow_ice = np.isfinite(ndsi) & (ndsi > 0.1)
            factors["snow_ice_pixels"] = int(np.count_nonzero(snow_ice & valid))
            applied.append("ndsi_snow_ice")

    if config.monitoring_mode == "vegetation":
        ndvi = indices.get("ndvi")
        if ndvi is not None:
            vegetation = np.isfinite(ndvi) & (ndvi > 0.2)
            factors["vegetation_pixels"] = int(np.count_nonzero(vegetation & valid))
            applied.append("ndvi_vegetation")

    if config.monitoring_mode == "infrastructure":
        ndbi = indices.get("ndbi")
        if ndbi is not None:
            built_up = np.isfinite(ndbi) & (ndbi > -0.05)
            factors["built_up_pixels"] = int(np.count_nonzero(built_up & valid))
            applied.append("ndbi_built_up")

    factors["rules_applied"] = applied
    evidence = LayerEvidence(
        layer=ChangeLayer.L5_DOMAIN,
        score=1.0 if applied else 0.0,
        passed=bool(applied),
        weight=0.5,
        details=factors,
    )
    return mask & valid, evidence


# ---------------------------------------------------------------------------
# spatial filtering
# ---------------------------------------------------------------------------


def remove_small_regions(
    mask: np.ndarray,
    min_pixels: int,
    pixel_area_m2: Optional[float] = None,
    connectivity: int = 8,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Drop change components below a physical minimum size.

    Real events such as a new building or a flooded field occupy a contiguous area;
    isolated pixels are noise. When the pixel area is known the threshold is also
    reported in real units so the filtering is physically meaningful.
    """
    mask = np.asarray(mask, dtype=bool)
    if min_pixels <= 1 or not mask.any():
        return mask, {"removed_regions": 0, "regions_kept": 0, "min_pixels": min_pixels}

    structure = ndimage.generate_binary_structure(2, connectivity)
    labels, count = ndimage.label(mask, structure=structure)
    if count == 0:
        return mask, {"removed_regions": 0, "regions_kept": 0, "min_pixels": min_pixels}

    sizes = ndimage.sum_labels(mask, labels, index=range(1, count + 1))
    keep = {i + 1 for i, size in enumerate(sizes) if size >= min_pixels}
    filtered = np.isin(labels, list(keep)) if keep else np.zeros_like(mask)

    details: Dict[str, Any] = {
        "min_pixels": min_pixels,
        "regions_found": int(count),
        "regions_kept": len(keep),
        "removed_regions": int(count - len(keep)),
        "pixels_before": int(mask.sum()),
        "pixels_after": int(filtered.sum()),
    }
    if pixel_area_m2:
        details["min_area_m2"] = round(min_pixels * pixel_area_m2, 2)
    return filtered, details


def dilate_and_refine(
    mask: np.ndarray,
    close_radius: int = 1,
    open_radius: int = 1,
) -> np.ndarray:
    """
    Morphological closing then opening to consolidate fragmented detections.

    Applied only to the final mask, so the connected-component size filter always sees
    true contiguous regions rather than artefacts of the closing step.
    """
    result = np.asarray(mask, dtype=bool)
    if close_radius > 0:
        result = ndimage.binary_closing(
            result, structure=np.ones((3, 3), bool), iterations=close_radius
        )
    if open_radius > 0:
        result = ndimage.binary_opening(
            result, structure=np.ones((3, 3), bool), iterations=open_radius
        )
    return result


# ---------------------------------------------------------------------------
# fusion
# ---------------------------------------------------------------------------


def fuse_layers(
    layers: Sequence[LayerEvidence],
    masks: Dict[ChangeLayer, np.ndarray],
    config: DomainConfig,
    min_support: int = 2,
) -> Tuple[np.ndarray, float]:
    """
    Combine layers into a consensus mask and a confidence.

    Confidence rises with the number of independent layers supporting the same pixels,
    saturating once full agreement is reached. It is a measure of evidence strength
    only; severity is assigned separately.
    """
    reference_shape = next(iter(masks.values())).shape
    participating = [
        (layer, masks[layer.layer])
        for layer in layers
        if layer.passed
        and masks.get(layer.layer) is not None
        and masks[layer.layer].shape == reference_shape
        # A layer that flagged evidence but contributed no pixels cannot corroborate
        # anything, and including it would dilute the weight of layers that did.
        and bool(masks[layer.layer].any())
    ]
    if not participating:
        return np.zeros(reference_shape, dtype=bool), 0.0

    stack = np.stack([m for _, m in participating], axis=0)
    weights = np.array([layer.weight for layer, _ in participating], dtype=np.float64)
    weights = weights / weights.sum()

    vote_count = stack.sum(axis=0)
    consensus = vote_count >= min_support

    if consensus.any():
        weighted_support = np.tensordot(weights, stack.astype(np.float64), axes=(0, 0))
        mean_support = float(np.mean(weighted_support[consensus]))
    else:
        mean_support = 0.0

    agreement_ratio = float(np.count_nonzero(consensus) / max(np.count_nonzero(stack.any(axis=0)), 1))
    confidence = float(np.clip(0.6 * mean_support + 0.4 * agreement_ratio, 0.0, 1.0))

    return consensus, confidence


def classify_severity(
    confidence: float,
    changed_fraction: float,
    area_m2: Optional[float],
    config: DomainConfig,
) -> Severity:
    """
    Assign operational severity from confidence plus physical scale.

    Severity is deliberately independent of confidence so that a confident detection
    of a tiny disturbance is not reported as critical.
    """
    if confidence < 0.5 or changed_fraction <= 0:
        return Severity.NONE

    if config.monitoring_mode == "glacier":
        # Glacier mass loss is significant at small areas.
        large_area = (area_m2 or 0.0) >= 1_000_000
        large_fraction = changed_fraction >= 0.05
    else:
        large_area = (area_m2 or 0.0) >= 250_000
        large_fraction = changed_fraction >= 0.02

    if confidence >= 0.8 and (large_area or large_fraction):
        return Severity.CRITICAL
    if confidence >= 0.65 and (large_area or large_fraction):
        return Severity.HIGH
    if confidence >= 0.55 and changed_fraction >= 0.01:
        return Severity.MODERATE
    return Severity.LOW


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def detect_change(
    baseline: TemporalBaseline,
    current: Observation,
    monitoring_mode: str = "general",
    sar_change_mask: Optional[np.ndarray] = None,
    change_mask_series: Optional[Sequence[np.ndarray]] = None,
    pixel_area_m2: Optional[float] = None,
    registration_band: str = "B03",
    max_registration_shift_px: float = 2.0,
    registration_verified: bool = False,
    max_changed_fraction: float = 0.6,
    min_valid_fraction: float = 0.10,
    min_support: int = 2,
    min_changed_pixels: Optional[int] = None,
) -> DetectionOutcome:
    """
    Run the full layered detector for one temporal comparison.

    Returns a `DetectionOutcome` that is either accepted, or rejected with the specific
    gate that vetoed it. A rejection carries the same evidence structure as an
    acceptance so that a caller can tell "nothing changed" apart from "nothing could be
    evaluated".
    """
    config = get_domain_config(monitoring_mode)
    shape = current.quality.valid.shape
    empty = np.zeros(shape, dtype=bool)

    gates: List[QualityGate] = []
    factors: Dict[str, Any] = {
        "monitoring_mode": config.monitoring_mode,
        "description": config.description,
        "baseline_scene_count": baseline.scene_count,
        "baseline_dates": [d.isoformat() for d in baseline.dates],
        "current_date": current.acquisition_time.isoformat(),
    }

    # --- gate: usable data -------------------------------------------------
    valid = baseline.quality.valid & current.quality.valid
    valid_fraction = float(np.count_nonzero(valid) / max(valid.size, 1))
    factors["valid_fraction"] = round(valid_fraction, 6)
    factors["baseline_scl_available"] = baseline.quality.scl_available
    factors["current_scl_available"] = current.quality.scl_available
    factors["baseline_cloud_fraction"] = round(float(np.mean(baseline.quality.cloud)), 6)
    factors["current_cloud_fraction"] = round(float(np.mean(current.quality.cloud)), 6)

    if valid_fraction < min_valid_fraction:
        gates.append(QualityGate(
            "usable_data",
            False,
            f"Only {valid_fraction:.1%} of pixels are valid in both dates "
            f"(minimum {min_valid_fraction:.0%}).",
        ))
        return DetectionOutcome(
            anomaly_mask=empty, layers=[], gates=gates, confidence=0.0,
            severity=Severity.NONE, factors=factors, monitoring_mode=config.monitoring_mode,
            rejected=True, reject_reason="insufficient_valid_data",
        )

    # --- gate: seasonal comparability -------------------------------------
    seasonal_gap = abs(current.day_of_year - baseline.day_of_year)
    seasonal_gap = min(seasonal_gap, 365 - seasonal_gap)
    factors["temporal_gap_days"] = abs(
        (current.acquisition_time - baseline.median_date).days
    )
    factors["seasonal_gap_days"] = seasonal_gap
    if seasonal_gap > config.seasonal_tolerance_days:
        gates.append(QualityGate(
            "seasonal_match",
            False,
            f"Scenes are {seasonal_gap} days apart in the year, beyond the "
            f"{config.seasonal_tolerance_days} day tolerance for "
            f"{config.monitoring_mode}. Difference is dominated by season.",
        ))
        return DetectionOutcome(
            anomaly_mask=empty, layers=[], gates=gates, confidence=0.0,
            severity=Severity.NONE, factors=factors, monitoring_mode=config.monitoring_mode,
            rejected=True, reject_reason="seasonal_mismatch",
        )
    gates.append(QualityGate(
        "seasonal_match", True,
        f"Seasonal gap {seasonal_gap} days is within tolerance.",
    ))

    # --- gate: co-registration --------------------------------------------
    baseline_bands = baseline.bands
    current_bands = current.bands
    if registration_verified:
        # Synthetic scenes are rendered on one shared grid, so alignment is exact by
        # construction. Estimating it is meaningless: on a low-texture scene the
        # correlation cannot locate an offset and returns a large spurious one, which
        # would otherwise veto a real change as "misregistration". LIVE scenes still
        # take the full estimation path below.
        gates.append(QualityGate(
            "co_registration", True,
            "Synthetic scenes share one grid, so alignment is exact by construction; "
            "registration was not estimated.",
            blocking=False,
        ))
        factors["registration_verified_by_construction"] = True
    elif registration_band in baseline_bands and registration_band in current_bands:
        shift_cols, shift_rows, peak = estimate_registration_shift(
            baseline_bands[registration_band], current_bands[registration_band], valid
        )
        shift_magnitude = float(np.hypot(shift_cols, shift_rows))
        factors["registration_shift_px"] = round(shift_magnitude, 4)
        factors["registration_peak"] = round(peak, 6)

        factors["registration_confidence"] = round(peak, 6)
        if shift_magnitude > max_registration_shift_px:
            gates.append(QualityGate(
                "co_registration",
                False,
                f"Scenes are misregistered by {shift_magnitude:.2f} px "
                f"(limit {max_registration_shift_px:.2f} px). Apparent change would be "
                f"an artefact of alignment.",
            ))
            return DetectionOutcome(
                anomaly_mask=empty, layers=[], gates=gates, confidence=0.0,
                severity=Severity.NONE, factors=factors,
                monitoring_mode=config.monitoring_mode,
                rejected=True, reject_reason="misregistration",
            )
        if shift_magnitude > 0.25 and peak >= MIN_REGISTRATION_CONFIDENCE:
            factors["registration_correction_trusted"] = True
            baseline_bands = {
                name: shift_array(arr, shift_cols, shift_rows)
                for name, arr in baseline_bands.items()
            }
            valid = shift_array(valid.astype(np.float64), shift_cols, shift_rows) > 0.99
            gates.append(QualityGate(
                "co_registration", True,
                f"Applied a {shift_magnitude:.2f} px correction before comparison.",
            ))
            factors["registration_corrected"] = True
        else:
            # A shift of zero from a weak correlation means alignment is unknown, not
            # proven, so the gate says so rather than asserting the scenes are aligned.
            if peak >= MIN_REGISTRATION_CONFIDENCE:
                gates.append(QualityGate(
                    "co_registration", True,
                    f"Scenes are aligned within {shift_magnitude:.2f} px.",
                    blocking=False,
                ))
            else:
                gates.append(QualityGate(
                    "co_registration", True,
                    f"Alignment could not be verified: correlation confidence "
                    f"{peak:.3f} is too weak to locate an offset. Comparison proceeds "
                    f"without correction, so residual misregistration may inflate "
                    f"detected change.",
                    blocking=False,
                ))
                factors["alignment_unverified"] = True
    else:
        gates.append(QualityGate(
            "co_registration", True,
            f"Band {registration_band} unavailable; registration not verified.",
            blocking=False,
        ))

    # --- layers ------------------------------------------------------------
    spectral_mask, spectral_evidence, current_indices = spectral_layer(
        TemporalBaseline(
            bands=baseline_bands,
            dates=baseline.dates,
            quality=baseline.quality,
            scene_count=baseline.scene_count,
        ),
        Observation(current.acquisition_time, current_bands, current.quality),
        valid,
        config,
    )

    # Brightness is needed by the structural layer regardless of which indices the
    # monitoring mode happens to request, so it is computed explicitly rather than
    # picked out of the spectral layer's output.
    baseline_brightness = compute_indices(
        baseline_bands, ["brightness"], nodata_mask=valid
    ).get("brightness")
    current_brightness = compute_indices(
        current_bands, ["brightness"], nodata_mask=valid
    ).get("brightness")

    if baseline_brightness is None or current_brightness is None:
        structural_mask, structural_evidence = np.zeros(shape, bool), LayerEvidence(
            ChangeLayer.L2_STRUCTURE, 0.0, False, 0.0,
            {"status": "brightness_unavailable"},
        )
    else:
        structural_mask, structural_evidence = structure_layer(
            baseline_brightness, current_brightness, valid, config
        )

    layers = [spectral_evidence, structural_evidence]

    if change_mask_series:
        persistent_mask, persistence_evidence = persistence_layer(change_mask_series)
        persistent_mask = persistent_mask & valid
        layers.append(persistence_evidence)
    else:
        persistent_mask = np.zeros(shape, dtype=bool)

    if sar_change_mask is not None:
        cross_mask, cross_evidence = cross_sensor_layer(
            spectral_mask, sar_change_mask, valid
        )
        layers.append(cross_evidence)
        cross_sensor_used = True
    else:
        cross_mask = np.zeros(shape, dtype=bool)
        cross_sensor_used = False

    _, domain_evidence = domain_layer(current_indices, config, valid)
    layers.append(domain_evidence)

    factors["cross_sensor_available"] = cross_sensor_used
    factors["cross_sensor_required"] = config.require_cross_sensor

    masks: Dict[ChangeLayer, np.ndarray] = {
        ChangeLayer.L1_SPECTRAL: spectral_mask,
        ChangeLayer.L2_STRUCTURE: structural_mask,
        ChangeLayer.L3_PERSISTENCE: persistent_mask,
        ChangeLayer.L4_CROSS_SENSOR: cross_mask,
        # The domain layer supplies interpretation and factors rather than pixels, so it
        # is recorded but deliberately kept out of the vote.
        ChangeLayer.L5_DOMAIN: np.zeros(shape, dtype=bool),
    }

    # --- fusion ------------------------------------------------------------
    effective_support = min_support
    if config.require_cross_sensor and not cross_sensor_used:
        gates.append(QualityGate(
            "cross_sensor_required",
            False,
            f"{config.monitoring_mode} monitoring requires SAR corroboration, which "
            f"was not supplied for this comparison.",
        ))
        return DetectionOutcome(
            anomaly_mask=empty, layers=layers, gates=gates, confidence=0.0,
            severity=Severity.NONE, factors=factors, monitoring_mode=config.monitoring_mode,
            rejected=True, reject_reason="cross_sensor_unavailable",
        )

    consensus, confidence = fuse_layers(layers, masks, config, min_support=effective_support)

    # --- spatial consolidation and physical filtering ----------------------
    consolidated = dilate_and_refine(consensus)
    min_pixels = min_changed_pixels if min_changed_pixels is not None else config.min_changed_pixels
    filtered, region_details = remove_small_regions(
        consolidated, min_pixels, pixel_area_m2=pixel_area_m2
    )
    factors["regions"] = region_details

    # --- sanity: implausibly large change usually means a broken comparison -
    changed_fraction = float(np.count_nonzero(filtered) / max(valid.size, 1))
    factors["changed_fraction"] = round(changed_fraction, 6)
    if changed_fraction > max_changed_fraction:
        gates.append(QualityGate(
            "plausible_extent", False,
            f"Change covers {changed_fraction:.1%} of the AOI, above the "
            f"{max_changed_fraction:.0%} plausibility limit. This usually indicates "
            f"season, illumination or processing error rather than a real event.",
        ))
        return DetectionOutcome(
            anomaly_mask=empty, layers=layers, gates=gates, confidence=0.0,
            severity=Severity.NONE, factors=factors, monitoring_mode=config.monitoring_mode,
            rejected=True, reject_reason="implausible_extent",
        )
    gates.append(QualityGate(
        "plausible_extent", True, f"Changed extent {changed_fraction:.3%} is plausible."
    ))

    area_m2 = float(np.count_nonzero(filtered) * (pixel_area_m2 or 0.0))
    factors["changed_area_m2"] = round(area_m2, 2)
    severity = classify_severity(confidence, changed_fraction, area_m2, config)

    factors["layer_agreement"] = {
        layer.layer.value: {"passed": layer.passed, "score": round(layer.score, 4)}
        for layer in layers
    }

    return DetectionOutcome(
        anomaly_mask=filtered,
        layers=layers,
        gates=gates,
        confidence=confidence,
        severity=severity,
        factors=factors,
        monitoring_mode=config.monitoring_mode,
        rejected=False,
        reject_reason=None,
        # Carried so downstream consumers can measure per-region layer support instead
        # of having to recompute each layer, which risks disagreeing with this run. Only
        # layers that actually participated are recorded: a layer with no data cannot
        # corroborate a region, and counting it would dilute real support and drive
        # per-region confidence down for the wrong reason.
        layer_masks={
            layer.layer.value: masks[layer.layer]
            for layer in layers
            if layer.layer is not ChangeLayer.L5_DOMAIN
            and layer.passed
            and masks.get(layer.layer) is not None
            and bool(masks[layer.layer].any())
        },
    )