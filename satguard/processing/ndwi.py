"""
satguard/processing/ndwi.py
Scientific Normalized Difference Water Index (NDWI) and Differential Change Calculator.

Formula:
  NDWI = (Green - NIR) / (Green + NIR)
  Sentinel-2 Bands: Green = B03, NIR = B08

Differential Change:
  Delta_NDWI = NDWI_T2 - NDWI_T1

Important Scientific Rule:
  Do NOT categorize changes as "disasters" or "predictions".
  Outputs are strictly: 'WATER_EXTENT_CHANGE', 'NO_CHANGE', or 'QUALITY_REJECTED'.
"""

from typing import Dict, Any, Tuple
import numpy as np


class NDWIProcessor:
    """
    Computes calibrated NDWI and differential surface water statistics.
    """

    def __init__(self, water_threshold: float = 0.1, pixel_resolution_m: float = 10.0):
        self.water_threshold = water_threshold
        self.pixel_area_m2 = pixel_resolution_m * pixel_resolution_m  # 10m x 10m = 100 m²

    def compute_ndwi(self, green_band: np.ndarray, nir_band: np.ndarray) -> np.ndarray:
        """
        Computes 2D float32 NDWI array with division-by-zero protection.
        """
        if green_band.shape != nir_band.shape:
            raise ValueError(f"Band dimension mismatch: Green {green_band.shape} vs NIR {nir_band.shape}")

        numerator = green_band.astype(np.float32) - nir_band.astype(np.float32)
        denominator = green_band.astype(np.float32) + nir_band.astype(np.float32)

        # Division by zero protection
        epsilon = 1e-6
        valid_mask = np.abs(denominator) > epsilon
        ndwi = np.zeros_like(numerator, dtype=np.float32)
        ndwi[valid_mask] = numerator[valid_mask] / denominator[valid_mask]

        # Clip to mathematical range [-1.0, 1.0]
        return np.clip(ndwi, -1.0, 1.0)

    def extract_water_mask(self, ndwi: np.ndarray) -> np.ndarray:
        """
        Returns boolean mask where True indicates open water surface (NDWI > threshold).
        """
        return ndwi > self.water_threshold

    def calculate_water_extent(self, ndwi: np.ndarray, total_aoi_area_m2: float) -> Dict[str, Any]:
        """
        Calculates total water pixels and surface water area in square meters.
        """
        water_mask = self.extract_water_mask(ndwi)
        water_pixel_count = int(np.sum(water_mask))
        total_pixels = ndwi.size

        water_area_m2 = (water_pixel_count / total_pixels) * total_aoi_area_m2

        return {
            "water_pixel_count": water_pixel_count,
            "total_pixels": total_pixels,
            "water_area_m2": round(water_area_m2, 2),
            "water_coverage_ratio": round(water_pixel_count / total_pixels, 4),
            "mean_ndwi": float(np.mean(ndwi)),
            "min_ndwi": float(np.min(ndwi)),
            "max_ndwi": float(np.max(ndwi)),
        }

    def compute_differential_change(
        self,
        ndwi_t1: np.ndarray,
        ndwi_t2: np.ndarray,
        total_aoi_area_m2: float,
    ) -> Dict[str, Any]:
        """
        Compares Baseline T1 with Current T2 to compute physical water change metrics.
        """
        if ndwi_t1.shape != ndwi_t2.shape:
            raise ValueError(f"Observation grid dimension mismatch: T1 {ndwi_t1.shape} vs T2 {ndwi_t2.shape}")

        delta_ndwi = ndwi_t2 - ndwi_t1

        t1_metrics = self.calculate_water_extent(ndwi_t1, total_aoi_area_m2)
        t2_metrics = self.calculate_water_extent(ndwi_t2, total_aoi_area_m2)

        baseline_area = t1_metrics["water_area_m2"]
        current_area = t2_metrics["water_area_m2"]
        water_change_area = current_area - baseline_area

        if baseline_area > 0:
            percentage_change = (water_change_area / baseline_area) * 100.0
        else:
            percentage_change = 0.0

        mean_delta = float(np.mean(delta_ndwi))
        max_delta = float(np.max(delta_ndwi))

        # Scientific classification
        if abs(percentage_change) > 5.0 or abs(mean_delta) > 0.05:
            change_type = "WATER_EXTENT_CHANGE"
        else:
            change_type = "NO_CHANGE"

        return {
            "change_type": change_type,
            "baseline_water_area_m2": baseline_area,
            "current_water_area_m2": current_area,
            "water_change_area_m2": round(water_change_area, 2),
            "water_change_percentage": round(percentage_change, 2),
            "mean_delta_ndwi": round(mean_delta, 4),
            "max_delta_ndwi": round(max_delta, 4),
            "delta_ndwi_array": delta_ndwi,
        }
