"""
tests/test_phase2_4.py
Unit tests for Phase 2.4: VV and VH Backscatter Processing.
Covers:
1. VV and VH separate extraction and validation
2. Calibrated decibel (dB) scaling
3. Robust handling of NaN, Inf, and non-finite pixels
4. Descriptive statistics calculation for VV and VH
5. Preservation of individual polarization channels
"""

import numpy as np
import pytest
from satguard.processing.sar import SARProcessor


def test_vv_vh_separation_and_stats():
    processor = SARProcessor()

    # Synthetic backscatter values in linear scale
    vv_linear = np.array([
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
        [0.7, 0.8, 0.9],
    ], dtype=np.float32)

    vh_linear = np.array([
        [0.01, 0.02, 0.03],
        [0.04, 0.05, 0.06],
        [0.07, 0.08, 0.09],
    ], dtype=np.float32)

    vv_db, _ = processor.calibrate_to_db(vv_linear)
    vh_db, _ = processor.calibrate_to_db(vh_linear)

    # VV and VH must remain distinct arrays
    assert not np.array_equal(vv_db, vh_db)

    # Compute stats
    vv_stats = processor.calculate_band_statistics(vv_db)
    vh_stats = processor.calculate_band_statistics(vh_db)

    assert vv_stats["valid_pixel_count"] == 9
    assert vh_stats["valid_pixel_count"] == 9
    assert vv_stats["mean"] > vh_stats["mean"]  # VV generally higher than cross-pol VH
    assert vv_stats["min"] == round(float(np.min(vv_db)), 4)
    assert vv_stats["max"] == round(float(np.max(vv_db)), 4)
    assert "median" in vv_stats
    assert "std" in vv_stats


def test_nan_and_inf_handling():
    processor = SARProcessor()

    # Array with NaN and Inf values
    dirty_db = np.array([
        [-10.0, np.nan, -12.0],
        [np.inf, -15.0, -11.0],
        [-14.0, -13.0, -np.inf],
    ], dtype=np.float32)

    stats = processor.calculate_band_statistics(dirty_db)

    # Exactly 6 valid finite pixels out of 9
    assert stats["valid_pixel_count"] == 6
    assert stats["min"] == -15.0
    assert stats["max"] == -10.0
    assert not np.isnan(stats["mean"])
    assert not np.isinf(stats["mean"])


def test_masked_statistics():
    processor = SARProcessor()
    data_db = np.array([
        [1.0, 2.0],
        [3.0, 4.0],
    ], dtype=np.float32)

    # Mask only top row
    mask = np.array([
        [True, True],
        [False, False],
    ], dtype=bool)

    stats = processor.calculate_band_statistics(data_db, mask=mask)
    assert stats["valid_pixel_count"] == 2
    assert stats["min"] == 1.0
    assert stats["max"] == 2.0
    assert stats["mean"] == 1.5
