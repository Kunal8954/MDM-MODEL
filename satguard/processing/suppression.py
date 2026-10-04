"""
satguard/processing/suppression.py
Residual false-positive suppression for multi-temporal comparison.

Change detection still produces false positives after clouds, shadows, season and
registration have been handled. What remains are systematic differences between two
scenes that are not surface change at all:

  * Radiometric drift. The same surface recorded months apart differs in brightness
    because of sun angle, atmospheric path radiance and sensor calibration. An absolute
    reflectance difference of 300 counts means nothing on its own.
  * Sensor inconsistency. Comparing ascending and descending SAR passes, or two
    different processing baselines, compares viewing geometry and calibration rather
    than the ground.
  * Detector noise. A small number of pixels will always exceed any threshold purely by
    chance, so the noise floor has to be measured rather than assumed.

Each mechanism here is applied before differencing, and each reports what it did so
that the resulting confidence can reflect the correction that was applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

logger = logging.getLogger("satguard.suppression")


class SuppressionError(Exception):
    error_code = "SUPPRESSION_FAILED"


@dataclass
class RadiometricNormalization:
    """Result of aligning one scene's radiometry to another's."""
    gain: float = 1.0
    offset: float = 0.0
    method: str = "none"
    stable_pixel_count: int = 0
    residual_before: float = float("nan")
    residual_after: float = float("nan")
    fit_quality: float = float("nan")

    @property
    def applied(self) -> bool:
        return self.method != "none"

    def summary(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "gain": round(self.gain, 6),
            "offset": round(self.offset, 4),
            "stable_pixels": self.stable_pixel_count,
            "residual_before": _round(self.residual_before),
            "residual_after": _round(self.residual_after),
            "improvement_pct": _round(
                100.0 * (1.0 - self.residual_after / self.residual_before)
                if np.isfinite(self.residual_before) and self.residual_before > 0 else np.nan
            ),
            "fit_quality": _round(self.fit_quality),
        }


def _round(value: float, digits: int = 4) -> Optional[float]:
    return round(float(value), digits) if np.isfinite(value) else None


# ---------------------------------------------------------------------------
# stability and radiometric normalisation
# ---------------------------------------------------------------------------


def estimate_stability_mask(
    arrays: Sequence[np.ndarray],
    valid: np.ndarray,
    sensitivity: float = 3.0,
) -> np.ndarray:
    """
    Identify pixels that are radiometrically stable across the whole series.

    Pixels that barely move between dates are, by construction, not changing. They form
    the reference set used to estimate how much of a difference is scene-wide radiometry
    rather than local surface change.
    """
    stack = np.stack([np.asarray(a, dtype=np.float64) for a in arrays], axis=0)
    finite = np.isfinite(stack)
    usable = valid[None, ...] & finite
    counts = usable.sum(axis=0)
    comparable = counts >= max(2, stack.shape[0] - 1)

    if not comparable.any():
        return np.zeros(valid.shape, dtype=bool)

    filled = np.where(usable, stack, np.nan)
    with np.errstate(invalid="ignore"):
        spread = np.nanstd(filled, axis=0)

    values = spread[comparable]
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    sigma = mad * 1.4826
    threshold = max(median + sensitivity * sigma, np.finfo(np.float64).eps)

    return comparable & (spread <= threshold)


def _residual(baseline_flat: np.ndarray, current_flat: np.ndarray) -> float:
    """Mean absolute residual between two stable-pixel samples."""
    if baseline_flat.size == 0:
        return float("nan")
    return float(np.mean(np.abs(baseline_flat - current_flat)))


def _finalize_gain_offset(
    gain: float,
    offset: float,
    forward_gain: float,
    forward_offset: float,
    base_ref: np.ndarray,
    stable_pixel_count: int,
    residual_before: float,
    max_gain: float = 3.0,
    max_offset_fraction: float = 0.5,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Apply the plausibility guard and return the correction, or (None, None) to refuse.

    The guard tests the fitted relationship between the scenes rather than the inverted
    correction, so a 40x brightening and a 40x darkening are both rejected instead of one
    being silently divided down and the other accepted.
    """
    scale = float(np.mean(np.abs(base_ref))) or 1.0
    relation_gain = forward_gain if np.isfinite(forward_gain) else 1.0
    relation_offset = forward_offset if np.isfinite(forward_offset) else 0.0
    if (
        not np.isfinite(gain)
        or not np.isfinite(offset)
        or gain <= 0
        or not (1.0 / max_gain <= relation_gain <= max_gain)
        or abs(relation_offset) > max_offset_fraction * scale
    ):
        logger.info(
            "Radiometric correction rejected as implausible (gain=%.3f offset=%.1f)",
            relation_gain, relation_offset,
        )
        return None, None
    return gain, offset


def _cdf_match(current: np.ndarray, base_ref: np.ndarray, curr_ref: np.ndarray) -> np.ndarray:
    """
    Match the histogram of `current` to the baseline distribution.

    Quantiles of the two stable-pixel samples are paired and used as an interpolation
    curve, so the corrected scene follows the baseline's radiometric response across its
    whole range rather than being shifted by a single constant.
    """
    finite = np.isfinite(current)
    if not finite.any():
        return current.copy()
    knots = np.linspace(0.0, 1.0, 257)
    source = np.quantile(curr_ref, knots)
    target = np.quantile(base_ref, knots)
    # np.interp needs an ascending x; ties in the source quantiles are collapsed.
    keep = np.concatenate([[True], np.diff(source) > 0])
    source, target = source[keep], target[keep]
    if source.size < 2:
        return current - float(np.median(curr_ref)) + float(np.median(base_ref))

    matched = np.interp(
        np.where(finite, current, source[0]), source, target
    )
    return np.where(finite, matched, current)


def relative_radiometric_normalization(
    baseline: np.ndarray,
    current: np.ndarray,
    stable_mask: Optional[np.ndarray] = None,
    valid: Optional[np.ndarray] = None,
    method: str = "linear",
    max_gain: float = 3.0,
    max_offset_fraction: float = 0.5,
) -> Tuple[np.ndarray, RadiometricNormalization]:
    """
    Align `current` to `baseline` using only the stable pixels.

    Fitting on stable pixels is what makes this safe. Fitting on the whole scene would
    partly absorb the real change into the correction and hide it.

    Returns the normalized array and a record of what was applied.
    """
    base = np.asarray(baseline, dtype=np.float64)
    curr = np.asarray(current, dtype=np.float64)
    if base.shape != curr.shape:
        raise SuppressionError(f"Shape mismatch: {base.shape} vs {curr.shape}")

    if valid is None:
        valid = np.ones(base.shape, dtype=bool)
    usable = valid & np.isfinite(base) & np.isfinite(curr)

    if stable_mask is None:
        stable_mask = usable
    reference = usable & stable_mask

    if reference.sum() < 100:
        return curr, RadiometricNormalization(
            method="none", stable_pixel_count=int(reference.sum())
        )

    base_ref = base[reference]
    curr_ref = curr[reference]
    residual_before = float(np.mean(np.abs(base_ref - curr_ref)))

    forward_gain = forward_offset = float("nan")
    forward_gain, forward_offset = float("nan"), float("nan")
    if method == "linear":
        forward_gain, forward_offset = _fit_linear(base_ref, curr_ref)
        # The fit expresses baseline as a function of current, but the correction must
        # map current onto baseline, so the relationship is inverted before use.
        if abs(forward_gain) < 1e-12:
            gain, offset = 1.0, float(np.mean(base_ref) - np.mean(curr_ref))
        else:
            gain = 1.0 / forward_gain
            offset = -forward_offset / forward_gain
    elif method == "median":
        gain, offset = 1.0, float(np.median(base_ref) - np.median(curr_ref))
    elif method == "cdf":
        # True histogram matching, not a median shift: this corrects the whole
        # radiometric response curve, including the gain change a median offset hides.
        normalized = _cdf_match(curr, base_ref, curr_ref)
        forward_gain, forward_offset = _fit_linear(base_ref, normalized[reference])
        if abs(forward_gain) < 1e-12:
            gain, offset = 1.0, float(np.mean(base_ref) - np.mean(normalized[reference]))
        else:
            gain, offset = 1.0 / forward_gain, -forward_offset / forward_gain
        gain, offset = _finalize_gain_offset(
            gain, offset, forward_gain, forward_offset, base_ref,
            int(reference.sum()), residual_before,
        )
        if gain is None:
            return curr, RadiometricNormalization(
                method="rejected", gain=forward_gain, offset=forward_offset,
                stable_pixel_count=int(reference.sum()),
                residual_before=residual_before,
            )
        return normalized, RadiometricNormalization(
            method="cdf", gain=gain, offset=offset,
            stable_pixel_count=int(reference.sum()),
            residual_before=residual_before,
            fit_quality=_fit_quality(
                base_ref, forward_gain, forward_offset, normalized[reference]
            ),
            residual_after=_residual(base_ref, normalized[reference]),
        )
    elif method == "none":
        return curr, RadiometricNormalization(method="none")
    else:
        raise ValueError(f"Unknown normalization method '{method}'")

    gain, offset = _finalize_gain_offset(
        gain, offset, forward_gain, forward_offset, base_ref,
        int(reference.sum()), residual_before,
    )
    if gain is None:
        return curr, RadiometricNormalization(
            method="rejected", gain=forward_gain, offset=forward_offset,
            stable_pixel_count=int(reference.sum()),
            residual_before=residual_before,
        )

    normalized = curr * gain + offset
    residual_after = float(np.mean(np.abs(base_ref - (curr_ref * gain + offset))))
    # Quality describes how well the two scenes agree as a radiometric pair, so it is
    # measured with the forward (current = gain * baseline + offset) relationship.
    fit_quality = _fit_quality(base_ref, forward_gain, forward_offset, curr_ref)

    return normalized, RadiometricNormalization(
        gain=gain,
        offset=offset,
        method=method,
        stable_pixel_count=int(reference.sum()),
        residual_before=residual_before,
        residual_after=residual_after,
        fit_quality=fit_quality,
    )


def _fit_linear(x: np.ndarray, y: np.ndarray) -> Tuple[float, float]:
    """Least-squares fit of y = gain * x + offset."""
    var = float(np.var(x))
    if var < 1e-12:
        return 1.0, float(np.mean(y) - np.mean(x))
    gain = float(np.mean((x - x.mean()) * (y - y.mean())) / var)
    offset = float(y.mean() - gain * x.mean())
    return gain, offset


def _fit_quality(x: np.ndarray, gain: float, offset: float, y: np.ndarray) -> float:
    """Coefficient of determination of the fitted correction."""
    predicted = x * gain + offset
    total = float(np.sum((y - y.mean()) ** 2))
    if total < 1e-12:
        return 1.0
    residual = float(np.sum((y - predicted) ** 2))
    return float(1.0 - residual / total)


# ---------------------------------------------------------------------------
# sensor consistency
# ---------------------------------------------------------------------------


@dataclass
class SensorCheck:
    name: str
    passed: bool
    detail: str
    blocking: bool = True


@dataclass
class SensorMetadata:
    """The acquisition attributes that must match for a comparison to be valid."""
    platform: Optional[str] = None
    instrument: Optional[str] = None
    collection: Optional[str] = None
    product_type: Optional[str] = None
    orbit_direction: Optional[str] = None
    polarizations: Optional[Tuple[str, ...]] = None
    processing_baseline: Optional[str] = None
    resolution_m: Optional[float] = None
    mean_solar_zenith_deg: Optional[float] = None
    sun_azimuth_difference_deg: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def check_sensor_consistency(
    baseline: SensorMetadata,
    current: SensorMetadata,
    max_resolution_ratio: float = 2.0,
    max_solar_zenith_difference: float = 30.0,
    max_sun_azimuth_difference: float = 45.0,
) -> List[SensorCheck]:
    """
    Verify that two observations are actually comparable.

    Each check corresponds to a real way that a comparison can be invalid while still
    producing confident-looking output.
    """
    checks: List[SensorCheck] = []

    if baseline.platform and current.platform:
        same_family = _same_platform_family(baseline.platform, current.platform)
        checks.append(SensorCheck(
            "platform",
            same_family,
            f"{baseline.platform} vs {current.platform}"
            + ("" if same_family else " are different platforms; response differs."),
            blocking=True,
        ))

    if baseline.instrument and current.instrument:
        same = baseline.instrument == current.instrument
        checks.append(SensorCheck(
            "instrument", same,
            f"{baseline.instrument} vs {current.instrument}"
            + ("" if same else " use different sensors."),
        ))

    if baseline.collection and current.collection:
        same = baseline.collection == current.collection
        checks.append(SensorCheck(
            "collection", same,
            f"{baseline.collection} vs {current.collection}"
            + ("" if same else " are different product collections."),
        ))

    if baseline.processing_baseline and current.processing_baseline:
        same = baseline.processing_baseline == current.processing_baseline
        checks.append(SensorCheck(
            "processing_baseline", same,
            f"{baseline.processing_baseline} vs {current.processing_baseline}"
            + ("" if same else " use different processing baselines; radiometry is not "
                                 "directly comparable."),
        ))

    if baseline.orbit_direction and current.orbit_direction:
        same = baseline.orbit_direction.upper() == current.orbit_direction.upper()
        checks.append(SensorCheck(
            "orbit_direction", same,
            f"{baseline.orbit_direction} vs {current.orbit_direction}"
            + ("" if same else " viewing geometries differ; SAR backscatter cannot be "
                               "differenced across passes."),
        ))

    if baseline.polarizations and current.polarizations:
        same = set(baseline.polarizations) == set(current.polarizations)
        checks.append(SensorCheck(
            "polarization", same,
            f"{sorted(baseline.polarizations)} vs {sorted(current.polarizations)}"
            + ("" if same else " polarization sets differ."),
        ))

    if baseline.resolution_m and current.resolution_m:
        ratio = max(
            baseline.resolution_m / current.resolution_m,
            current.resolution_m / baseline.resolution_m,
        )
        same = ratio <= max_resolution_ratio
        checks.append(SensorCheck(
            "resolution", same,
            f"{baseline.resolution_m} m vs {current.resolution_m} m"
            + ("" if same else " differ by more than the resampling tolerance."),
        ))

    zenith_delta = _delta(baseline.mean_solar_zenith_deg, current.mean_solar_zenith_deg)
    if zenith_delta is not None:
        same = zenith_delta <= max_solar_zenith_difference
        checks.append(SensorCheck(
            "illumination", same,
            f"Mean solar zenith differs by {zenith_delta:.1f} degrees"
            + ("" if same else ", which changes shadow length and radiometry."),
            blocking=False,
        ))

    azimuth_delta = _delta(
        baseline.sun_azimuth_difference_deg, current.sun_azimuth_difference_deg
    )
    if azimuth_delta is not None:
        same = azimuth_delta <= max_sun_azimuth_difference
        checks.append(SensorCheck(
            "sun_azimuth", same,
            f"Sun azimuth differs by {azimuth_delta:.1f} degrees"
            + ("" if same else ", so shadows fall in different directions."),
            blocking=False,
        ))

    return checks


def _same_platform_family(a: str, b: str) -> bool:
    """
    Sentinel-2A and 2B are interchangeable for surface monitoring; a different mission
    is not.
    """
    def family(platform: str) -> str:
        token = platform.strip().upper().replace("SENTINEL-", "S")
        return token[:2]

    return family(a) == family(b)


def _delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return abs(float(a) - float(b))


# ---------------------------------------------------------------------------
# noise
# ---------------------------------------------------------------------------


def estimate_noise_floor(
    difference: np.ndarray,
    valid: np.ndarray,
) -> Dict[str, float]:
    """
    Measure the detector noise present in a difference image.

    Using the median absolute deviation rather than the standard deviation keeps the
    estimate from being inflated by the very change being measured.
    """
    values = np.asarray(difference, dtype=np.float64)
    usable = valid & np.isfinite(values)
    if usable.sum() < 32:
        return {
            "noise_sigma": float("nan"), "noise_mad": float("nan"),
            "median_difference": float("nan"), "valid_pixels": int(usable.sum()),
            "noise_p999": float("nan"),
        }

    sample = values[usable]
    median = float(np.median(sample))
    mad = float(np.median(np.abs(sample - median)))
    return {
        "noise_sigma": mad * 1.4826,
        "noise_mad": mad,
        "median_difference": median,
        "valid_pixels": int(usable.sum()),
        # The 99.9th percentile is the value a purely noisy image would exceed by
        # chance for roughly one pixel in a thousand; anything beyond it is a candidate.
        "noise_p999": float(np.percentile(np.abs(sample - median), 99.9)),
    }


def _fill_missing(filled: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Replace invalid pixels with an inpaint so no NaN escapes the filter."""
    if valid.all():
        return filled
    result = np.asarray(filled, dtype=np.float64).copy()
    if not valid.any():
        return np.zeros_like(result)
    nearest = ndimage.distance_transform_edt(
        ~valid, return_distances=False, return_indices=True
    )
    return np.where(valid, result, result[tuple(nearest)])


def suppress_speckle(
    array: np.ndarray,
    method: str = "median",
    window: int = 3,
) -> np.ndarray:
    """Spatial speckle filter for SAR or other multiplicative-noise rasters."""
    data = np.asarray(array, dtype=np.float64)
    if method == "none":
        return data
    if method not in ("median", "mean", "lee"):
        raise ValueError(f"Unknown speckle filter '{method}'")

    valid = np.isfinite(data)
    if not valid.any():
        return data

    # Missing pixels are treated as absent rather than propagated, otherwise a single
    # no-data pixel spreads NaN across the whole filtered window.
    multiplicative = float(np.nanmin(data)) >= 0.0
    filled = np.where(valid, data, 0.0)

    if method == "median" and multiplicative:
        # A median filter applied to right-skewed multiplicative noise biases the mean
        # downwards by more than ten percent, which differencing would report as a
        # scene-wide brightness change. Filtering the log intensities keeps the
        # radiometric level of a multiplicative signal.
        filtered = np.exp(
            ndimage.median_filter(
                np.where(valid, np.log(np.where(filled > 0, filled, 1.0)), 0.0),
                size=window, mode="nearest",
            )
        )
        filtered = np.where(filled > 0, filtered, filled)
    elif method == "median":
        filtered = ndimage.median_filter(filled, size=window, mode="nearest")
    elif method == "mean":
        counts = ndimage.uniform_filter(
            valid.astype(np.float64), size=window, mode="nearest"
        )
        total = ndimage.uniform_filter(filled, size=window, mode="nearest")
        filtered = total / np.clip(counts, 1.0, None)
    else:
        filtered = _lee_filter(filled, window)

    return _preserve_mean(_fill_missing(filtered, valid), filled, valid)


def _preserve_mean(
    filtered: np.ndarray, original: np.ndarray, valid: np.ndarray
) -> np.ndarray:
    """
    Rescale a filtered raster so filtering cannot change its radiometric level.

    Any filter that systematically shifts the mean would appear as scene-wide change to
    the differencing stage, so the filtered mean is returned to the original mean.
    """
    reference = float(np.mean(original[valid])) if valid.any() else 0.0
    result = float(np.mean(filtered[valid])) if valid.any() else 0.0
    if not np.isfinite(result) or result == 0.0 or reference == 0.0:
        return filtered
    return filtered * (reference / result)


def _lee_filter(array: np.ndarray, window: int) -> np.ndarray:
    """
    Local (Lee) speckle filter: an edge-preserving weighted average that reduces
    speckle inside homogeneous areas while leaving real structure intact.
    """
    mean = ndimage.uniform_filter(array, size=window, mode="nearest")
    mean_sq = ndimage.uniform_filter(array * array, size=window, mode="nearest")
    variance = np.clip(mean_sq - mean * mean, 0, None)

    overall_variance = float(np.nanvar(array))
    noise = max(overall_variance - float(np.nanmean(variance)), 1e-12)

    weight = np.clip((variance - noise) / np.clip(variance, 1e-12, None), 0.0, 1.0)
    return mean + weight * (array - mean)