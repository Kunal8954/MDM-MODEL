"""
Tests for false-positive suppression (increment F).

The properties verified here are the ones that decide whether suppression is safe: it
must remove scene-wide radiometric drift while leaving genuine change intact, refuse
implausible corrections rather than applying them, and never invent a threshold from a
signal-free image.
"""

import numpy as np
import pytest

from satguard.processing.suppression import (
    SensorMetadata,
    check_sensor_consistency,
    estimate_noise_floor,
    estimate_stability_mask,
    relative_radiometric_normalization,
    suppress_speckle,
)


@pytest.fixture
def scene():
    """A synthetic scene pair with a known change block and known radiometric drift."""
    rng = np.random.default_rng(7)
    height = width = 120
    baseline = rng.uniform(800.0, 3000.0, (height, width))
    change = np.zeros((height, width), dtype=bool)
    change[40:80, 40:80] = True
    current = baseline.copy()
    current[change] += 900.0
    stable_mask = estimate_stability_mask(
        [baseline, current], np.ones((height, width), dtype=bool)
    )
    return baseline, current, change, stable_mask


def test_stability_mask_excludes_the_changed_block(scene):
    baseline, current, change, stable_mask = scene
    assert stable_mask[change].sum() == 0, "changed pixels must not calibrate the fit"
    assert stable_mask[~change].mean() > 0.5


def test_linear_normalization_removes_drift_and_keeps_change_intact(scene):
    baseline, current, change, stable_mask = scene
    drifted = current * 1.12 + 40.0
    normalized, info = relative_radiometric_normalization(
        baseline, drifted, stable_mask=stable_mask
    )

    background = ~change
    # The drift that the correction must erase, measured only where nothing changed.
    assert np.abs(baseline - drifted)[background].mean() > 100.0, "fixture must contain drift"
    assert np.abs(baseline - normalized)[background].mean() < 1.0

    # The genuine change must survive with its true amplitude, not be suppressed away.
    assert np.abs(np.abs(normalized - baseline)[change].mean() - 900.0) < 1.0
    assert info.method == "linear"
    assert info.fit_quality > 0.99


def test_fit_is_inverted_so_the_correction_maps_current_onto_baseline(scene):
    baseline, current, _, stable_mask = scene
    _, info = relative_radiometric_normalization(
        baseline, current * 1.12 + 40.0, stable_mask=stable_mask
    )
    # gain and offset are reported for the correction (current -> baseline), so they
    # must be 1/1.12 and -40/1.12 rather than the forward fit of 1.12 and 40.
    assert info.gain == pytest.approx(1.0 / 1.12, abs=1e-6)
    assert info.offset == pytest.approx(-40.0 / 1.12, abs=1e-6)


def test_darkened_and_brightened_scenes_are_both_rejected(scene):
    baseline, current, _, stable_mask = scene
    for label, mangled in (
        ("brighter", current * 40.0),
        ("darker", current / 40.0),
        ("offset", current + 5000.0),
    ):
        _, info = relative_radiometric_normalization(
            baseline, mangled, stable_mask=stable_mask
        )
        assert info.method == "rejected", f"{label} scene should be refused"


def test_plausible_drift_is_accepted(scene):
    baseline, current, _, stable_mask = scene
    _, info = relative_radiometric_normalization(
        baseline, current * 1.05 + 5.0, stable_mask=stable_mask
    )
    assert info.method == "linear"


def test_median_and_cdf_methods_are_usable(scene):
    baseline, current, change, stable_mask = scene
    drifted = current + 40.0
    for method in ("median", "cdf"):
        normalized, info = relative_radiometric_normalization(
            baseline, drifted, stable_mask=stable_mask, method=method
        )
        assert info.method == method
        background = ~change
        assert np.abs(normalized - baseline)[background].mean() < 1.0


def test_unknown_method_is_rejected(scene):
    baseline, current, _, stable_mask = scene
    with pytest.raises(ValueError):
        relative_radiometric_normalization(
            baseline, current, stable_mask=stable_mask, method="bogus"
        )


def test_noise_floor_recovers_injected_noise():
    rng = np.random.default_rng(3)
    difference = rng.normal(0.0, 40.0, (80, 80))
    floor = estimate_noise_floor(difference, np.ones((80, 80), dtype=bool))
    assert 30.0 < floor["noise_sigma"] < 52.0
    assert abs(floor["median_difference"]) < 5.0
    assert floor["noise_p999"] > floor["noise_sigma"]


def test_noise_floor_on_a_constant_difference_is_zero():
    difference = np.full((60, 60), 7.0)
    floor = estimate_noise_floor(difference, np.ones((60, 60), dtype=bool))
    assert floor["noise_sigma"] < 1e-6
    assert floor["median_difference"] == pytest.approx(7.0)


def test_sensor_consistency_allows_family_change_but_flags_processing_drift():
    current = SensorMetadata(
        platform="SENTINEL-2A", instrument="MSI", collection="sentinel-2-l2a",
        processing_baseline="05.00", resolution_m=10.0,
        orbit_direction="ASCENDING", polarizations=("VV", "VH"),
    )
    reference = SensorMetadata(
        platform="SENTINEL-2B", instrument="MSI", collection="sentinel-2-l2a",
        processing_baseline="04.00", resolution_m=10.0,
        orbit_direction="DESCENDING", polarizations=("VV",),
    )
    checks = {c.name: c for c in check_sensor_consistency(reference, current)}

    # A different platform within the same family is normal and must not be an error.
    assert checks["platform"].passed
    # These three genuinely affect comparability.
    assert not checks["processing_baseline"].passed
    assert not checks["orbit_direction"].passed
    assert not checks["polarization"].passed
    assert all(c.detail for c in checks.values()), "each check must explain itself"


def test_sensor_consistency_flags_unrelated_sensors():
    optical = SensorMetadata(platform="SENTINEL-2A", instrument="MSI")
    radar = SensorMetadata(platform="SENTINEL-1A", instrument="SAR")
    checks = {c.name: c for c in check_sensor_consistency(optical, radar)}
    assert not checks["instrument"].passed


def test_identical_sensor_metadata_is_fully_consistent():
    metadata = SensorMetadata(
        platform="SENTINEL-1A", instrument="SAR", collection="sentinel-1-grd",
        processing_baseline="05.00", resolution_m=10.0,
        orbit_direction="ASCENDING", polarizations=("VV", "VH"),
    )
    assert all(c.passed for c in check_sensor_consistency(metadata, metadata))


def test_speckle_filters_reduce_variance_without_shifting_the_mean():
    rng = np.random.default_rng(11)
    speckled = rng.gamma(2.0, 1.0, (100, 100)) * 100.0
    original_mean = speckled.mean()
    for method in ("median", "mean", "lee"):
        filtered = suppress_speckle(speckled, method)
        assert filtered.std() < speckled.std(), f"{method} did not reduce speckle"
        assert filtered.mean() == pytest.approx(original_mean, rel=0.05)


def test_speckle_passes_through_when_method_is_none():
    speckled = np.arange(100, dtype=float).reshape(10, 10)
    assert np.array_equal(suppress_speckle(speckled, "none"), speckled)


def test_speckle_handles_nan_as_missing():
    speckled = np.full((20, 20), 50.0)
    speckled[5, 5] = np.nan
    filtered = suppress_speckle(speckled, "median")
    assert np.isfinite(filtered).all()
    assert filtered[5, 5] == pytest.approx(50.0)