"""
satguard/processing/preprocess.py
Preprocessing for multi-temporal optical (Sentinel-2) and SAR (Sentinel-1) analysis.

This is the layer that removes the dominant source of false positives in optical change
detection. The previous pipeline thresholded raw B03/B08 with no cloud or shadow mask at
all, so any cloud present between the baseline and current observation registered as
surface change.

Sentinel-2 Scene Classification Layer (SCL) classes, as produced by Level-2A products
and requested here from the Sentinel Hub Process API::

    0  no data                     1  saturated / defective
    2  cast shadow (dark)          3  cloud shadow
    4  vegetation                  5  non-vegetated
    6  water                       7  unclassified / low probability cloud
    8  cloud medium probability    9  cloud high probability
    10 thin cirrus                11 snow / ice
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np
from scipy import ndimage

from satguard.geospatial.raster import RasterProfile

# SCL class -> human readable name
SCL_CLASSES: Dict[int, str] = {
    0: "no_data",
    1: "saturated_or_defective",
    2: "cast_shadow",
    3: "cloud_shadow",
    4: "vegetation",
    5: "non_vegetated",
    6: "water",
    7: "unclassified",
    8: "cloud_medium_probability",
    9: "cloud_high_probability",
    10: "thin_cirrus",
    11: "snow_ice",
}

# Classes that must never participate in change detection: they describe atmosphere
# or sensor artefacts rather than the surface.
SCL_REJECT_CLASSES: Tuple[int, ...] = (0, 1, 2, 3, 7, 8, 9, 10)

# Classes treated as cloud-like for the purpose of scene usability reporting.
SCL_CLOUD_CLASSES: Tuple[int, ...] = (2, 3, 7, 8, 9, 10)

# Sentinel-2 L2A reflectance at or above this is radiometrically saturated.
REFLECTANCE_SATURATION = 10000.0

# Classes that legitimately contain snow/ice, and so must be retained for glacier and
# water monitoring but excluded from vegetation monitoring.
SCL_SNOW_CLASSES: Tuple[int, ...] = (11,)


class PreprocessingError(Exception):
    error_code = "PREPROCESSING_FAILED"


@dataclass
class QualityMask:
    """
    Per-pixel usability flags for one observation.

    `valid` is the conjunction of every rejection reason, so downstream differencing
    only ever compares pixels that were actually observed in both dates.
    """
    valid: np.ndarray
    cloud: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    shadow: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    nodata: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    snow: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    water: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    vegetation: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    saturated: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    aoi: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=bool))
    scl_available: bool = False

    @property
    def valid_fraction(self) -> float:
        total = self.valid.size
        return float(np.count_nonzero(self.valid) / total) if total else 0.0

    def reject_for_mode(self, monitoring_mode: str = "general") -> "QualityMask":
        """
        Return a copy whose `valid` mask additionally respects the monitoring mode.

        Snow and ice are real surface cover for glacier and water monitoring but are a
        seasonal artefact for vegetation monitoring, so their treatment is mode-aware
        rather than globally excluded.
        """
        if self.snow.size == 0 or not self.snow.any():
            return self

        # For modes where snow and ice are the subject rather than an artefact, the snow
        # pixels are restored to valid. Without this, glacier monitoring can never
        # observe the ice it exists to monitor, because class 3 is excluded globally.
        if monitoring_mode in ("glacier", "water_body"):
            combined_valid = self.valid | self.snow
        elif monitoring_mode in ("general", "flood"):
            return self
        else:
            combined_valid = self.valid & ~self.snow

        return QualityMask(
            valid=combined_valid,
            cloud=self.cloud, shadow=self.shadow, nodata=self.nodata,
            snow=self.snow, water=self.water, vegetation=self.vegetation,
            saturated=self.saturated, aoi=self.aoi, scl_available=self.scl_available,
        )

    def summary(self) -> Dict[str, Any]:
        total = int(self.valid.size)

        def frac(mask: np.ndarray) -> Optional[float]:
            if mask.size != total or total == 0:
                return None
            return round(float(np.count_nonzero(mask) / total), 6)

        return {
            "scl_available": self.scl_available,
            "total_pixels": total,
            "valid_fraction": round(self.valid_fraction, 6),
            "cloud_fraction": frac(self.cloud),
            "shadow_fraction": frac(self.shadow),
            "nodata_fraction": frac(self.nodata),
            "saturated_fraction": frac(self.saturated),
            "snow_fraction": frac(self.snow),
            "water_fraction": frac(self.water),
            "vegetation_fraction": frac(self.vegetation),
            "aoi_fraction": frac(self.aoi),
        }


def build_quality_mask(
    scl: Optional[np.ndarray],
    shape_hw: Tuple[int, int],
    aoi_mask: Optional[np.ndarray] = None,
    nodata_value: Optional[float] = None,
    bands: Optional[Dict[str, np.ndarray]] = None,
    nodata_band_threshold: float = 0.0,
) -> QualityMask:
    """
    Derive a per-pixel quality mask from the SCL band plus optional auxiliary inputs.

    When the SCL band is unavailable, the mask falls back to nodata and spectral
    screening only. That fallback is reported explicitly via `scl_available=False` so
    that a caller can treat the result as lower confidence rather than assuming cloud
    screening was performed.
    """
    height, width = shape_hw

    if aoi_mask is not None:
        aoi = np.asarray(aoi_mask, dtype=bool)
        if aoi.shape != (height, width):
            raise PreprocessingError(
                f"AOI mask shape {aoi.shape} does not match grid {(height, width)}"
            )
    else:
        aoi = np.ones((height, width), dtype=bool)

    nodata = np.zeros((height, width), dtype=bool)
    saturated = np.zeros((height, width), dtype=bool)

    if bands:
        for name, array in bands.items():
            arr = np.asarray(array, dtype=np.float64)
            if arr.shape != (height, width):
                continue
            nodata |= ~np.isfinite(arr)
            # Sentinel-2 L2A reflectance of 0 means no signal reached the sensor.
            nodata |= arr <= nodata_band_threshold
            # Values at or above the saturation ceiling are radiometrically invalid.
            saturated |= arr >= REFLECTANCE_SATURATION

    if scl is not None:
        scl_arr = np.rint(np.asarray(scl, dtype=np.float64)).astype(np.int16)
        if scl_arr.shape != (height, width):
            raise PreprocessingError(
                f"SCL shape {scl_arr.shape} does not match grid {(height, width)}"
            )
        in_range = np.isin(scl_arr, list(SCL_CLASSES.keys()))
        cloud = np.isin(scl_arr, [7, 8, 9, 10])
        shadow = np.isin(scl_arr, [2, 3])
        scl_nodata = np.isin(scl_arr, [0, 1])
        snow = np.isin(scl_arr, SCL_SNOW_CLASSES)
        water = scl_arr == 6
        vegetation = scl_arr == 4
        nodata = nodata | scl_nodata | ~in_range
        scl_available = True
    else:
        cloud = np.zeros((height, width), dtype=bool)
        shadow = np.zeros((height, width), dtype=bool)
        snow = np.zeros((height, width), dtype=bool)
        water = np.zeros((height, width), dtype=bool)
        vegetation = np.zeros((height, width), dtype=bool)
        scl_available = False

    valid = aoi & ~nodata & ~saturated
    if scl_available:
        valid = valid & ~cloud & ~shadow

    return QualityMask(
        valid=valid,
        cloud=cloud,
        shadow=shadow,
        nodata=nodata,
        snow=snow,
        water=water,
        vegetation=vegetation,
        saturated=saturated,
        aoi=aoi,
        scl_available=scl_available,
    )


def fill_masked(array: np.ndarray, mask: np.ndarray, method: str = "nearest") -> np.ndarray:
    """
    Replace invalid pixels using nearest-valid-neighbour interpolation.

    Called before filters so that convolution across nodata and cloud edges does not
    produce ringing artefacts that would themselves look like change. Filled pixels
    become finite so filters behave, but they remain excluded from analysis because
    the caller intersects results with `QualityMask.valid`.

    Pixels with no valid neighbour anywhere (a fully masked grid) stay NaN.
    """
    arr = np.asarray(array, dtype=np.float64).copy()
    invalid = ~np.asarray(mask, dtype=bool) | ~np.isfinite(arr)
    if invalid.all():
        return arr
    if not invalid.any():
        return arr

    if method == "nearest":
        indices = ndimage.distance_transform_edt(
            invalid, return_distances=False, return_indices=True
        )
        return arr[tuple(indices)]

    if method == "mean":
        valid_values = arr[~invalid]
        if valid_values.size == 0:
            return arr
        arr[invalid] = float(np.mean(valid_values))
        return arr

    raise ValueError(f"Unknown fill method '{method}'")


def preprocess_optical(
    profile: RasterProfile,
    scl_band: Optional[np.ndarray] = None,
    aoi_mask: Optional[np.ndarray] = None,
    monitoring_mode: str = "general",
    fill_nodata: bool = True,
) -> Tuple[RasterProfile, QualityMask]:
    """
    Prepare a Sentinel-2 observation for change detection.

    Steps:
      1. Build a quality mask from SCL (cloud, shadow, nodata, saturation) and the AOI.
      2. Mask bands to the AOI.
      3. Optionally fill masked pixels with nearest valid neighbour so that subsequent
         filters do not manufacture edge artefacts.
      4. Return the masked profile together with the quality mask, which the caller
         must intersect across dates before differencing.
    """
    height, width = profile.height, profile.width
    mask = build_quality_mask(
        scl=scl_band,
        shape_hw=(height, width),
        aoi_mask=aoi_mask,
        bands={
            "b0": profile.band(0),
        } if profile.band_count >= 1 else None,
    )
    mask = mask.reject_for_mode(monitoring_mode)

    array = profile.array.astype(np.float64)
    if fill_nodata and mask.valid.any():
        if array.ndim == 2:
            array = fill_masked(array, mask.valid, method="nearest")
        else:
            for i in range(array.shape[2]):
                array[:, :, i] = fill_masked(array[:, :, i], mask.valid, method="nearest")
    else:
        array = np.where(np.broadcast_to(mask.valid[..., None] if array.ndim == 3 else mask.valid, array.shape), array, np.nan)

    processed = RasterProfile(
        array=array,
        transform=profile.transform,
        crs=profile.crs,
        nodata=np.nan,
        band_names=profile.band_names,
        meta={**profile.meta, "preprocessed": True, "monitoring_mode": monitoring_mode},
    )
    return processed, mask


def preprocess_sar(
    profile: RasterProfile,
    aoi_mask: Optional[np.ndarray] = None,
    speckle_filter: Optional[str] = "median",
    min_valid_fraction: float = 0.15,
) -> Tuple[RasterProfile, QualityMask]:
    """
    Prepare a Sentinel-1 observation for change detection.

    Steps:
      1. Convert linear backscatter to decibels (idempotent: already-dB input is kept).
      2. Optionally apply a speckle filter.
      3. Mask to the AOI and drop no-data pixels.

    Speckle is multiplicative noise; leaving it in place is the main cause of isolated
    single-pixel change in SAR differencing.
    """
    from satguard.processing.sar import SARProcessor

    height, width = profile.height, profile.width
    processor = SARProcessor()

    array = profile.array.astype(np.float64)
    if array.ndim == 2:
        array = array[:, :, np.newaxis]

    processed_bands = []
    for i in range(array.shape[2]):
        band = np.asarray(processor.calibrate_to_db(array[:, :, i]), dtype=np.float64)
        if speckle_filter:
            band = processor.apply_speckle_filter(band, speckle_filter)
        processed_bands.append(band)
    stacked = np.stack(processed_bands, axis=-1)

    mask = build_quality_mask(
        scl=None,
        shape_hw=(height, width),
        aoi_mask=aoi_mask,
        bands={f"b{i}": stacked[:, :, i] for i in range(stacked.shape[2])},
        nodata_band_threshold=-50.0,  # below -50 dB is effectively no return
    )
    mask.nodata = ~np.isfinite(stacked).all(axis=2)
    mask.valid = mask.aoi & ~mask.nodata & ~mask.saturated

    valid_fraction = mask.valid_fraction
    if valid_fraction < min_valid_fraction:
        raise PreprocessingError(
            f"Only {valid_fraction:.1%} of the SAR grid is usable after masking "
            f"(minimum {min_valid_fraction:.0%}). The acquisition likely does not "
            f"cover the AOI."
        )

    masked = np.where(
        np.broadcast_to(mask.valid[..., None], stacked.shape), stacked, np.nan
    )
    out = RasterProfile(
        array=masked[:, :, 0] if masked.shape[2] == 1 else masked,
        transform=profile.transform,
        crs=profile.crs,
        nodata=np.nan,
        band_names=profile.band_names,
        meta={**profile.meta, "preprocessed": True, "sensor": "SENTINEL-1"},
    )
    return out, mask


def observation_pair_mask(
    mask_baseline: QualityMask,
    mask_current: QualityMask,
    monitoring_mode: str = "general",
) -> np.ndarray:
    """
    Intersection of two quality masks.

    Only pixels observed cleanly in BOTH dates may be differenced. Comparing a
    cloud-free baseline against a clouded current scene is the single largest source
    of spurious change, and this intersection prevents it structurally.
    """
    baseline = mask_baseline.reject_for_mode(monitoring_mode).valid
    current = mask_current.reject_for_mode(monitoring_mode).valid
    if baseline.shape != current.shape:
        raise PreprocessingError(
            f"Quality mask shape mismatch: {baseline.shape} vs {current.shape}"
        )
    return baseline & current


def sun_angle_difference(
    baseline_mean: Optional[Dict[str, Any]],
    current_mean: Optional[Dict[str, Any]],
) -> Optional[float]:
    """
    Difference in mean solar zenith angle between two observations, if recorded.

    A large difference drives radiometric and shadow-length differences between scenes
    and must be treated as a false-positive risk during validation.
    """
    if not baseline_mean or not current_mean:
        return None
    a = baseline_mean.get("mean_solar_zenith_deg")
    b = current_mean.get("mean_solar_zenith_deg")
    if a is None or b is None:
        return None
    return abs(float(a) - float(b))


def day_of_year_difference(date_baseline: Any, date_current: Any) -> Optional[int]:
    """Day-of-year separation between two acquisitions, used for seasonality checks."""
    if date_baseline is None or date_current is None:
        return None
    try:
        a = date_baseline.timetuple().tm_yday
        b = date_current.timetuple().tm_yday
    except AttributeError:
        return None
    diff = abs(a - b)
    return min(diff, 365 - diff)