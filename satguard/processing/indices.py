"""
satguard/processing/indices.py
Spectral indices for multi-domain change and anomaly detection.

Each index is computed from Sentinel-2 L2A surface reflectance bands. Every function
operates on plain float arrays with division-by-zero protection and returns NaN where
the result is undefined, so that invalid pixels can be masked rather than silently
becoming zero (an undefined index forced to 0 is a false change signal).

Sentinel-2 band mapping used throughout:
    B02 Blue   490 nm      B03 Green  560 nm     B04 Red    665 nm
    B05 RedEdge1 705 nm    B06 RedEdge2 740 nm   B07 RedEdge3 783 nm
    B08 NIR    842 nm      B11 SWIR1  1610 nm    B12 SWIR2  2190 nm
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# Reflectance values are scaled by 10000 in Sentinel-2 L2A products.
REFLECTANCE_SCALE = 10000.0

# Canonical index -> required bands, used to validate that a scene carries what a
# monitoring mode needs before any index is attempted.
INDEX_BANDS: Dict[str, Tuple[str, ...]] = {
    "ndwi":   ("B03", "B08"),
    "mndwi":  ("B03", "B11"),
    "ndvi":   ("B08", "B04"),
    "ndbi":   ("B11", "B08"),
    "ndsi":   ("B03", "B11"),   # green vs SWIR1, matching compute_ndsi
    "ndre":   ("B06", "B04"),
    "nbr":    ("B12", "B11"),
    "brightness": ("B02", "B03", "B04"),
}

INDEX_DESCRIPTIONS: Dict[str, str] = {
    "ndwi": "McFeeters Normalized Difference Water Index (green vs NIR)",
    "mndwi": "Modified NDWI using shortwave infrared (water vs land)",
    "ndvi": "Normalized Difference Vegetation Index (NIR vs red)",
    "ndbi": "Normalized Difference Built-up Index (SWIR1 vs NIR)",
    "ndsi": "Normalized Difference Snow Index (green vs SWIR1)",
    "ndre": "Normalized Difference Red Edge index (red-edge vs red)",
    "nbr": "Normalized Burn Ratio (SWIR2 vs SWIR1)",
    "brightness": "Visible-band mean brightness",
}

_EPS = 1e-6


def safe_ratio(
    a: np.ndarray,
    b: np.ndarray,
    scale: float = 1.0,
) -> np.ndarray:
    """
    Element-wise (a - b) / (a + b) * scale with undefined results masked as NaN.

    A near-zero denominator means the index is not physically meaningful at that pixel
    (for example over water for a vegetation index), so NaN is returned rather than 0.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        raise ValueError(f"Band shape mismatch: {a.shape} vs {b.shape}")

    numerator = a - b
    denominator = a + b
    valid = np.isfinite(numerator) & np.isfinite(denominator) & (np.abs(denominator) > _EPS)

    out = np.full(a.shape, np.nan, dtype=np.float64)
    out[valid] = (numerator[valid] / denominator[valid]) * scale
    return np.clip(out, -1.0, 1.0)


def compute_ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDWI = (Green - NIR) / (Green + NIR). High values indicate open water."""
    return safe_ratio(green, nir)


def compute_mndwi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """
    MNDWI = (Green - SWIR1) / (Green + SWIR1).

    Suppresses built-up and soil responses better than NDWI, which makes it the
    preferred water index in urban and reservoir contexts.
    """
    return safe_ratio(green, swir1)


def compute_ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - Red) / (NIR + Red). High values indicate healthy vegetation."""
    return safe_ratio(nir, red)


def compute_ndbi(swir1: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """
    NDBI = (SWIR1 - NIR) / (SWIR1 + NIR). High values indicate built-up surfaces.

    This is the primary signal for structural change: a new structure raises SWIR1
    reflectance while leaving NIR comparatively unchanged.
    """
    return safe_ratio(swir1, nir)


def compute_ndsi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """
    NDSI = (Green - SWIR1) / (Green + SWIR1). High values indicate snow and ice.

    Ice and liquid water both score high, so NDSI is paired with MNDWI to separate
    frozen from open water when classifying glacier change.
    """
    return safe_ratio(green, swir1)


def compute_ndre(red_edge2: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDRE = (RedEdge2 - Red) / (RedEdge2 + Red). Sensitive to canopy vigour."""
    return safe_ratio(red_edge2, red)


def compute_nbr(swir2: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """NBR = (SWIR2 - SWIR1) / (SWIR2 + SWIR1). Burned areas score low."""
    return safe_ratio(swir2, swir1)


def compute_brightness(blue: np.ndarray, green: np.ndarray, red: np.ndarray) -> np.ndarray:
    """Mean visible reflectance, a proxy for overall surface brightness."""
    stack = np.stack([np.asarray(blue, dtype=np.float64),
                      np.asarray(green, dtype=np.float64),
                      np.asarray(red, dtype=np.float64)], axis=0)
    with np.errstate(invalid="ignore"):
        out = np.nanmean(stack, axis=0)
    return np.where(np.isfinite(out), out, np.nan)


_INDEX_FUNCTIONS = {
    "ndwi": lambda b: compute_ndwi(b["B03"], b["B08"]),
    "mndwi": lambda b: compute_mndwi(b["B03"], b["B11"]),
    "ndvi": lambda b: compute_ndvi(b["B08"], b["B04"]),
    "ndbi": lambda b: compute_ndbi(b["B11"], b["B08"]),
    "ndsi": lambda b: compute_ndsi(b["B03"], b["B11"]),
    "ndre": lambda b: compute_ndre(b["B06"], b["B04"]),
    "nbr": lambda b: compute_nbr(b["B12"], b["B11"]),
    "brightness": lambda b: compute_brightness(b["B02"], b["B03"], b["B04"]),
}


def missing_bands(
    bands: Dict[str, np.ndarray],
    indices: Iterable[str],
) -> List[str]:
    """Bands required by `indices` that are absent from the supplied band set."""
    available = set(bands.keys())
    missing: List[str] = []
    for index in indices:
        for band in INDEX_BANDS.get(index, ()):  # type: ignore[arg-type]
            if band not in available:
                missing.append(band)
    return sorted(set(missing))


def compute_indices(
    bands: Dict[str, np.ndarray],
    indices: Sequence[str],
    nodata_mask: Optional[np.ndarray] = None,
) -> Dict[str, np.ndarray]:
    """
    Compute the requested indices from a band dictionary.

    `nodata_mask` marks pixels that must be excluded regardless of index value
    (cloud, shadow, outside the AOI). Pixels where an index is undefined come back as
    NaN and are unioned into the invalid mask by the caller.

    Raises:
        KeyError: if a band required by a requested index is missing, so that a
            monitoring run fails loudly rather than silently skipping an index.
    """
    results: Dict[str, np.ndarray] = {}

    for index in indices:
        required = INDEX_BANDS.get(index)
        if required is None:
            raise KeyError(f"Unknown spectral index '{index}'")
        absent = [b for b in required if b not in bands]
        if absent:
            raise KeyError(
                f"Index '{index}' requires band(s) {list(required)}; missing {absent}"
            )
        array = _INDEX_FUNCTIONS[index](bands)
        if nodata_mask is not None:
            # `nodata_mask` marks pixels to EXCLUDE, so NaN goes where it is False.
            array = np.where(nodata_mask, array, np.nan)
        results[index] = array

    return results


def index_statistics(array: np.ndarray) -> Dict[str, float]:
    """Descriptive statistics over the valid pixels of an index array."""
    valid = np.asarray(array, dtype=np.float64)
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        return {
            "valid_pixels": 0, "mean": None, "std": None, "min": None,
            "max": None, "median": None, "p10": None, "p90": None,
        }
    return {
        "valid_pixels": int(valid.size),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "median": float(np.median(valid)),
        "p10": float(np.percentile(valid, 10)),
        "p90": float(np.percentile(valid, 90)),
    }


def classify_thresholded(
    index_array: np.ndarray,
    threshold: float,
    above: bool = True,
) -> np.ndarray:
    """
    Boolean mask where an index exceeds (or falls below) a threshold.

    NaN pixels are False, so undefined index values can never register as a hit.
    """
    arr = np.asarray(index_array, dtype=np.float64)
    mask = arr >= threshold if above else arr <= threshold
    return np.where(np.isfinite(arr), mask, False)