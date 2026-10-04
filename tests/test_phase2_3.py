"""
tests/test_phase2_3.py
Unit tests for Phase 2.3: Sentinel-1 SAR Preprocessing.
Covers:
1. Raster file existence, non-zero size, and dimension validation
2. Missing file / 0-byte file / 1-band file error handling
3. Circular AOI mask creation
4. Radiometric dB conversion (linear power vs already in dB)
5. Optional speckle filtering (box_3x3, median_3x3, none)
6. Preprocessing workflow and manifest generation
"""

import json
from pathlib import Path
import numpy as np
import pytest
import tifffile

from satguard.processing.sar import (
    SARProcessor,
    SARValidationError,
)


def test_raster_validation_success(tmp_path):
    processor = SARProcessor(base_storage_dir=tmp_path)
    raster_file = tmp_path / "valid_sar.tif"

    # Create 2-band float32 SAR test array (height=64, width=64, bands=2)
    test_array = np.random.uniform(0.01, 2.0, (64, 64, 2)).astype(np.float32)
    tifffile.imwrite(str(raster_file), test_array)

    res = processor.validate_sar_raster(raster_file)
    assert res["valid"] is True
    assert res["dimensions"]["height"] == 64
    assert res["dimensions"]["width"] == 64
    assert res["dimensions"]["bands"] == 2
    assert res["file_size_bytes"] > 0
    assert res["nan_count"] == 0


def test_raster_validation_errors(tmp_path):
    processor = SARProcessor(base_storage_dir=tmp_path)

    # 1. Non-existent file
    with pytest.raises(SARValidationError) as exc:
        processor.validate_sar_raster(tmp_path / "does_not_exist.tif")
    assert "does not exist" in str(exc.value)

    # 2. Empty file
    empty_file = tmp_path / "empty.tif"
    empty_file.write_bytes(b"")
    with pytest.raises(SARValidationError) as exc:
        processor.validate_sar_raster(empty_file)
    assert "is empty (0 bytes)" in str(exc.value)

    # 3. Single-band raster (expected at least 2: VV, VH)
    single_band = tmp_path / "single_band.tif"
    tifffile.imwrite(str(single_band), np.ones((64, 64), dtype=np.float32))
    with pytest.raises(SARValidationError) as exc:
        processor.validate_sar_raster(single_band)
    assert "Expected at least 2 bands" in str(exc.value)


def test_aoi_masking():
    processor = SARProcessor()
    mask = processor.create_aoi_mask(height=100, width=100)

    assert mask.shape == (100, 100)
    assert mask.dtype == bool
    # Center pixel should be within circular AOI
    assert mask[50, 50] is np.True_
    # Four corners should be outside circular AOI
    assert mask[0, 0] is np.False_
    assert mask[0, 99] is np.False_
    assert mask[99, 0] is np.False_
    assert mask[99, 99] is np.False_
    # Area of circle within square is ~ pi/4 = ~78.5%
    ratio = np.mean(mask)
    assert 0.75 < ratio < 0.82


def test_radiometric_db_conversion():
    processor = SARProcessor()

    # Linear power -> dB: 1.0 -> 0.0 dB, 0.1 -> -10.0 dB, 10.0 -> +10.0 dB
    linear = np.array([1.0, 0.1, 10.0], dtype=np.float32)
    db_out, unit = processor.calibrate_to_db(linear)
    assert unit == "dB"
    assert np.isclose(db_out[0], 0.0, atol=1e-3)
    assert np.isclose(db_out[1], -10.0, atol=1e-3)
    assert np.isclose(db_out[2], 10.0, atol=1e-3)

    # Already in dB: negative SAR dB values should be preserved without re-conversion
    already_db = np.array([-15.0, -12.5, -20.0, -8.0], dtype=np.float32)
    preserved_out, unit = processor.calibrate_to_db(already_db)
    assert unit == "dB"
    np.testing.assert_allclose(preserved_out, already_db)


def test_speckle_filtering():
    processor = SARProcessor()
    arr = np.array([
        [1.0, 1.0, 10.0],
        [1.0, 1.0, 1.0],
        [1.0, 1.0, 1.0],
    ], dtype=np.float32)

    # Filter 'none' -> unchanged
    out_none = processor.apply_speckle_filter(arr, None)
    np.testing.assert_array_equal(out_none, arr)

    # Filter 'box_3x3' -> uniform mean
    out_box = processor.apply_speckle_filter(arr, "box_3x3")
    assert out_box[1, 1] < 10.0
    assert out_box[0, 2] < 10.0

    # Filter 'median_3x3' -> eliminates outlier impulse
    out_med = processor.apply_speckle_filter(arr, "median_3x3")
    assert out_med[1, 1] == 1.0
