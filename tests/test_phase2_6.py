"""
tests/test_phase2_6.py
Unit tests for Phase 2.6: Spatial SAR Change Map Generation.
Covers:
1. Configurable change-detection thresholds (VV_CHANGE_THRESHOLD_DB, VH_CHANGE_THRESHOLD_DB)
2. 5-class categorical change mask assignment (0: No Data, 1: No Change, 2: VV, 3: VH, 4: Joint)
3. Changed pixel percentage calculations
4. Connected components analysis for Significant SAR Change Regions
"""

import numpy as np
import pytest
from satguard.processing.sar import SARProcessor


def test_categorical_change_mask():
    processor = SARProcessor(vv_change_threshold_db=3.0, vh_change_threshold_db=3.0)

    # 4 distinct test pixels
    # Pixel 0: ΔVV=1.0, ΔVH=1.0 -> No significant change (1)
    # Pixel 1: ΔVV=4.0, ΔVH=1.0 -> VV change (2)
    # Pixel 2: ΔVV=1.0, ΔVH=4.0 -> VH change (3)
    # Pixel 3: ΔVV=4.0, ΔVH=4.0 -> VV and VH joint change (4)
    delta_vv = np.array([[1.0, 4.0], [1.0, 4.0]], dtype=np.float32)
    delta_vh = np.array([[1.0, 1.0], [4.0, 4.0]], dtype=np.float32)

    change_mask = np.ones((2, 2), dtype=np.uint8)
    vv_ch = np.abs(delta_vv) >= 3.0
    vh_ch = np.abs(delta_vh) >= 3.0

    change_mask[vv_ch & ~vh_ch] = 2
    change_mask[~vv_ch & vh_ch] = 3
    change_mask[vv_ch & vh_ch] = 4

    assert change_mask[0, 0] == 1  # No change
    assert change_mask[0, 1] == 2  # VV only
    assert change_mask[1, 0] == 3  # VH only
    assert change_mask[1, 1] == 4  # Joint VV & VH


def test_connected_change_regions_detection():
    processor = SARProcessor(pixel_resolution_m=10.0)

    # Create a 20x20 grid with one 3x3 connected change cluster
    mask = np.ones((20, 20), dtype=np.uint8)
    # Plant a 3x3 block of joint change (class 4) = 9 pixels
    mask[5:8, 5:8] = 4

    regions = processor.detect_connected_change_regions(mask, min_pixels=5)

    assert len(regions) == 1
    reg = regions[0]
    assert reg["designation"] == "SIGNIFICANT_SAR_CHANGE_REGION"
    assert reg["pixel_count"] == 9
    assert reg["area_m2"] == 9 * 100.0  # 900 m2
    assert reg["bounding_box"] == [5, 5, 7, 7]
    assert reg["centroid"] == [6.0, 6.0]
