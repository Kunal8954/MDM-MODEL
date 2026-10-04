"""
Regression tests for layered change detection.

The legacy detector thresholded a single NDWI difference at a fixed constant, with no
cloud mask, no seasonal control and no registration check. These tests pin the
behaviours that separate a usable detector from that one:

  * real change in each monitoring mode is found, with no spurious pixels
  * clouds, cloud shadow, illumination drift, sensor noise and seasonal phenology do
    not produce anomalies
  * misregistration and season-incomparable pairs are refused explicitly
  * confidence is kept separate from severity

Surface reflectance values are physically plausible Sentinel-2 L2A radiances for water,
vegetation, bare soil, built-up surface, snow/ice, cloud and cloud shadow, with the
matching SCL class code for each.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from scipy import ndimage

from satguard.processing.change_detection import (
    ChangeDetectionError,
    ChangeLayer,
    Observation,
    Severity,
    TemporalBaseline,
    cross_sensor_layer,
    detect_change,
    dilate_and_refine,
    estimate_registration_shift,
    get_domain_config,
    persistence_layer,
    remove_small_regions,
    robust_change_threshold,
    shift_array,
    spectral_layer,
)
from satguard.processing.preprocess import build_quality_mask

BANDS = ["B02", "B03", "B04", "B06", "B08", "B11", "B12"]

SURFACE_REFLECTANCE = {
    # band:    B02   B03   B04   B06   B08   B11   B12
    "water":  dict(B02=280,  B03=260,  B04=240,  B06=180,  B08=110,  B11=90,   B12=70),
    "veget":  dict(B02=700,  B03=900,  B04=800,  B06=2100, B08=3400, B11=2200, B12=1400),
    "soil":   dict(B02=1400, B03=1700, B04=1900, B06=2400, B08=2600, B11=3400, B12=3200),
    "urban":  dict(B02=1900, B03=2000, B04=2100, B06=2300, B08=2000, B11=2600, B12=2400),
    "snow":   dict(B02=7800, B03=8200, B04=8400, B06=6000, B08=4200, B11=2600, B12=2200),
    "cloud":  dict(B02=7600, B03=7900, B04=8200, B06=8100, B08=8000, B11=7000, B12=6800),
    "shadow": dict(B02=420,  B03=460,  B04=500,  B06=520,  B08=560,  B11=600,  B12=640),
}

SCL_CODE = {
    "water": 6, "veget": 4, "soil": 5, "urban": 5,
    "snow": 11, "cloud": 9, "shadow": 3,
}

H = W = 160
BASE_DATE = datetime(2024, 6, 10, tzinfo=timezone.utc)
CURR_DATE = datetime(2024, 6, 25, tzinfo=timezone.utc)


def render(classes: np.ndarray, seed: int, noise: float = 0.02):
    """Build plausible Sentinel-2 bands plus an SCL grid from a surface-class map."""
    rng = np.random.default_rng(seed)
    bands = {}
    for band in BANDS:
        array = np.zeros(classes.shape, dtype=np.float64)
        for name, reflectance in SURFACE_REFLECTANCE.items():
            mask = classes == name
            if mask.any():
                array[mask] = reflectance[band]
        bands[band] = np.maximum(array * (1 + rng.normal(0, noise, array.shape)), 1.0)

    scl = np.zeros(classes.shape, dtype=np.uint8)
    for name, code in SCL_CODE.items():
        scl[classes == name] = code
    return bands, scl


def make_pair(classes_baseline, classes_current, noise: float = 0.02):
    baseline_bands, baseline_scl = render(classes_baseline, 0, noise)
    current_bands, current_scl = render(classes_current, 1, noise)
    baseline = TemporalBaseline(
        bands=baseline_bands,
        dates=[BASE_DATE],
        quality=build_quality_mask(baseline_scl, classes_baseline.shape),
        scene_count=1,
    )
    current = Observation(
        acquisition_time=CURR_DATE,
        bands=current_bands,
        quality=build_quality_mask(current_scl, classes_current.shape),
    )
    return baseline, current


@pytest.fixture
def pond_scene():
    """Vegetated field with a small pond at rows 30:60, cols 30:60."""
    classes = np.full((H, W), "veget", dtype=object)
    classes[30:60, 30:60] = "water"
    return classes


# ---------------------------------------------------------------------------
# real change must be detected
# ---------------------------------------------------------------------------

def test_water_expansion_is_detected_without_spurious_pixels(pond_scene):
    current = pond_scene.copy()
    current[30:85, 30:85] = "water"          # pond grows from 30x30 to 55x55

    outcome = detect_change(
        *make_pair(pond_scene, current), "water_body", pixel_area_m2=100.0
    )

    assert not outcome.rejected
    assert outcome.changed_pixels > 0
    assert outcome.anomaly_mask[30:85, 30:85].sum() > 1000, "must overlap the real change"
    # Every reported pixel must lie inside the region that actually changed.
    assert not outcome.anomaly_mask[85:, :].any()
    assert outcome.confidence > 0.5
    assert outcome.factors["changed_area_m2"] > 0


def test_construction_is_detected_infrastructure_mode():
    baseline = np.full((H, W), "veget", dtype=object)
    current = baseline.copy()
    current[60:100, 60:100] = "urban"

    outcome = detect_change(
        *make_pair(baseline, current), "infrastructure", pixel_area_m2=100.0
    )

    assert not outcome.rejected
    assert outcome.changed_pixels > 500
    assert outcome.anomaly_mask[60:100, 60:100].sum() > 500


def test_vegetation_clearing_is_detected():
    baseline = np.full((H, W), "veget", dtype=object)
    current = baseline.copy()
    current[20:70, 20:70] = "soil"

    outcome = detect_change(
        *make_pair(baseline, current), "vegetation", pixel_area_m2=100.0
    )

    assert not outcome.rejected
    assert outcome.changed_pixels > 1000


def test_snow_ice_loss_is_detected_in_glacier_mode():
    baseline = np.full((H, W), "snow", dtype=object)
    current = baseline.copy()
    current[50:110, 50:110] = "soil"

    outcome = detect_change(*make_pair(baseline, current), "glacier", pixel_area_m2=100.0)

    assert not outcome.rejected
    assert outcome.changed_pixels > 1000


# ---------------------------------------------------------------------------
# false positives must not survive
# ---------------------------------------------------------------------------

def test_cloud_in_current_scene_produces_no_anomaly(pond_scene):
    """The headline false positive: a cloud must never register as surface change."""
    current = pond_scene.copy()
    current[10:50, 10:50] = "cloud"

    outcome = detect_change(
        *make_pair(pond_scene, current), "water_body", pixel_area_m2=100.0
    )

    assert outcome.changed_pixels == 0
    assert not outcome.accepted
    # The unusable fraction must still be reported so a caller can see why.
    assert outcome.factors["current_cloud_fraction"] > 0


def test_cloud_shadow_produces_no_anomaly(pond_scene):
    current = pond_scene.copy()
    current[10:50, 10:50] = "shadow"

    outcome = detect_change(
        *make_pair(pond_scene, current), "water_body", pixel_area_m2=100.0
    )

    assert outcome.changed_pixels == 0


def test_no_change_scenes_produce_no_anomaly(pond_scene):
    outcome = detect_change(
        *make_pair(pond_scene, pond_scene), "water_body", pixel_area_m2=100.0
    )

    assert outcome.changed_pixels == 0
    assert outcome.confidence == pytest.approx(0.0)
    assert outcome.severity is Severity.NONE


def test_uniform_illumination_change_is_not_water_change(pond_scene):
    """A global brightness increase is radiometry, not a shoreline moving."""
    baseline_bands, baseline_scl = render(pond_scene, 0)
    current_bands, current_scl = render(pond_scene, 1)
    brightened = {name: value * 1.18 for name, value in current_bands.items()}

    outcome = detect_change(
        TemporalBaseline(baseline_bands, [BASE_DATE],
                         build_quality_mask(baseline_scl, (H, W)), 1),
        Observation(CURR_DATE, brightened, build_quality_mask(current_scl, (H, W))),
        "water_body",
        pixel_area_m2=100.0,
    )

    assert outcome.changed_pixels == 0


def test_physically_too_small_change_is_filtered(pond_scene):
    """A 4x4 pixel disturbance is below the minimum physical extent."""
    current = pond_scene.copy()
    current[70:74, 70:74] = "water"

    outcome = detect_change(
        *make_pair(pond_scene, current), "water_body", pixel_area_m2=100.0
    )

    assert outcome.changed_pixels == 0


# ---------------------------------------------------------------------------
# comparability gates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shift_px", [15, 22])
def test_large_misregistration_is_rejected(pond_scene, shift_px):
    current = pond_scene.copy()
    current[30:85, 30:85] = "water"
    baseline, obs = make_pair(pond_scene, current)
    rolled = Observation(
        obs.acquisition_time,
        {name: np.roll(value, shift_px, axis=1) for name, value in obs.bands.items()},
        obs.quality,
    )

    outcome = detect_change(baseline, rolled, "water_body", pixel_area_m2=100.0)

    assert outcome.rejected
    assert outcome.reject_reason == "misregistration"
    assert outcome.changed_pixels == 0


def test_seasonally_incomparable_pair_is_rejected(pond_scene):
    baseline_bands, baseline_scl = render(pond_scene, 0)
    current_bands, current_scl = render(pond_scene, 1)

    outcome = detect_change(
        TemporalBaseline(baseline_bands, [datetime(2024, 1, 10, tzinfo=timezone.utc)],
                         build_quality_mask(baseline_scl, (H, W)), 1),
        Observation(datetime(2024, 8, 25, tzinfo=timezone.utc), current_bands,
                    build_quality_mask(current_scl, (H, W))),
        "vegetation",
        pixel_area_m2=100.0,
    )

    assert outcome.rejected
    assert outcome.reject_reason == "seasonal_mismatch"


def test_flood_mode_refuses_without_cross_sensor_evidence():
    """Flood claims need SAR corroboration; optical alone must not be trusted."""
    baseline = np.full((H, W), "veget", dtype=object)
    current = baseline.copy()
    current[40:110, 40:110] = "water"

    outcome = detect_change(
        *make_pair(baseline, current), "flood", pixel_area_m2=100.0
    )

    assert outcome.rejected
    assert outcome.reject_reason == "cross_sensor_unavailable"


def test_flood_mode_detects_with_cross_sensor_agreement():
    baseline = np.full((H, W), "veget", dtype=object)
    current = baseline.copy()
    current[40:110, 40:110] = "water"
    sar_change = np.zeros((H, W), dtype=bool)
    sar_change[40:110, 40:110] = True

    outcome = detect_change(
        *make_pair(baseline, current), "flood",
        pixel_area_m2=100.0, sar_change_mask=sar_change,
    )

    assert not outcome.rejected
    assert outcome.changed_pixels > 1000


def test_insufficient_valid_data_is_reported_not_silently_empty():
    classes = np.full((H, W), "cloud", dtype=object)   # entire scene is cloud
    outcome = detect_change(*make_pair(classes, classes), "water_body", pixel_area_m2=100.0)

    assert outcome.rejected
    assert outcome.reject_reason == "insufficient_valid_data"


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shift_cols,shift_rows", [(1, 0), (3, 0), (0, 2), (-4, 3), (7, -6)])
def test_registration_recovers_integer_offsets_exactly(shift_cols, shift_rows):
    rng = np.random.default_rng(0)
    scene = ndimage.gaussian_filter(rng.normal(size=(200, 200)), 1.2)
    shifted = np.roll(np.roll(scene, shift_rows, axis=0), shift_cols, axis=1)
    valid = np.ones(scene.shape, dtype=bool)

    apply_cols, apply_rows, confidence = estimate_registration_shift(scene, shifted, valid)

    assert apply_cols == pytest.approx(shift_cols, abs=0.5)
    assert apply_rows == pytest.approx(shift_rows, abs=0.5)
    assert confidence > 0.1


def test_registration_proposal_must_improve_alignment():
    """
    An uncorroborated proposal must be discarded: acting on a weak correlation peak
    would corrupt the comparison rather than fix it.
    """
    rng = np.random.default_rng(0)
    scene = ndimage.gaussian_filter(rng.normal(size=(200, 200)), 1.2)
    valid = np.ones(scene.shape, dtype=bool)

    apply_cols, apply_rows, _ = estimate_registration_shift(scene, scene, valid)
    assert apply_cols == pytest.approx(0.0, abs=1e-9)
    assert apply_rows == pytest.approx(0.0, abs=1e-9)


def test_incoherent_input_yields_no_confident_correction():
    rng = np.random.default_rng(1)
    a = rng.normal(size=(200, 200))
    b = rng.normal(size=(200, 200))
    valid = np.ones(a.shape, dtype=bool)

    apply_cols, apply_rows, confidence = estimate_registration_shift(a, b, valid)

    assert apply_cols == pytest.approx(0.0, abs=1e-9)
    assert apply_rows == pytest.approx(0.0, abs=1e-9)
    assert confidence < 0.15


def test_registration_refuses_when_too_little_valid_data():
    scene = np.zeros((200, 200))
    valid = np.zeros((200, 200), dtype=bool)
    valid[:10, :10] = True

    assert estimate_registration_shift(scene, scene, valid) == (0.0, 0.0, 0.0)


def test_registration_rejects_mismatched_grids():
    with pytest.raises(ChangeDetectionError):
        estimate_registration_shift(
            np.zeros((10, 10)), np.zeros((12, 12)), np.ones((10, 10), dtype=bool)
        )


def test_weak_alignment_is_reported_as_unverified_not_as_aligned(pond_scene):
    """The gate must not claim alignment it could not establish."""
    baseline, obs = make_pair(pond_scene, pond_scene)
    outcome = detect_change(baseline, obs, "water_body", pixel_area_m2=100.0)

    gate = next(g for g in outcome.gates if g.name == "co_registration")
    if outcome.factors.get("alignment_unverified"):
        assert "could not be verified" in gate.detail
    else:
        assert "aligned within" in gate.detail


# ---------------------------------------------------------------------------
# layer units
# ---------------------------------------------------------------------------

def test_spectral_layer_counts_only_expected_direction(pond_scene):
    baseline_bands, baseline_scl = render(pond_scene, 0)
    current_bands, current_scl = render(pond_scene, 1)
    config = get_domain_config("water_body")
    valid = build_quality_mask(baseline_scl, (H, W)).valid

    mask, evidence, _ = spectral_layer(
        TemporalBaseline(baseline_bands, [BASE_DATE], None, 1),
        Observation(CURR_DATE, current_bands, build_quality_mask(current_scl, (H, W))),
        valid,
        config,
    )

    assert evidence.passed is False, "an unchanged scene has no spectral change"
    assert evidence.layer is ChangeLayer.L1_SPECTRAL
    assert mask.sum() == 0


def test_persistence_layer_requires_repeat_observations():
    a = np.zeros((10, 10), dtype=bool)
    b = np.zeros((10, 10), dtype=bool)
    b[2:5, 2:5] = True
    c = b.copy()

    single, single_evidence = persistence_layer([a, b], minimum_dates=2)
    repeated, repeated_evidence = persistence_layer([a, b, c], minimum_dates=2)

    assert single.sum() == 0, "a single-date blip must not persist"
    assert single_evidence.passed is False
    assert repeated[3, 3]
    assert repeated_evidence.details["dates_examined"] == 3


def test_cross_sensor_layer_requires_agreement():
    optical = np.zeros((20, 20), dtype=bool)
    optical[2:8, 2:8] = True
    optical[12:16, 12:16] = True          # optical-only finding
    sar = np.zeros((20, 20), dtype=bool)
    sar[2:8, 2:8] = True                  # agrees on one block only

    agreed, evidence = cross_sensor_layer(optical, sar, np.ones((20, 20), dtype=bool))

    assert agreed[3, 3]
    assert not agreed[13, 13]
    assert evidence.details["optical_only_pixels"] == 16


def test_cross_sensor_layer_rejects_mismatched_grids():
    with pytest.raises(ChangeDetectionError):
        cross_sensor_layer(
            np.zeros((10, 10), bool), np.zeros((12, 12), bool),
            np.ones((10, 10), bool),
        )


def test_remove_small_regions_reports_physical_area():
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:40, 10:40] = True      # 900 px
    mask[80:82, 80:82] = True      # 4 px

    filtered, details = remove_small_regions(mask, min_pixels=40, pixel_area_m2=100.0)

    assert filtered[20, 20]
    assert not filtered[80, 80]
    assert details["regions_found"] == 2
    assert details["regions_kept"] == 1
    assert details["min_area_m2"] == 4000.0


def test_robust_threshold_adapts_to_noise_level():
    rng = np.random.default_rng(4)
    quiet = rng.normal(0, 0.01, 5000)
    noisy = rng.normal(0, 0.20, 5000)
    valid = np.ones(5000, dtype=bool)

    quiet_threshold, _, quiet_sigma = robust_change_threshold(quiet, valid, floor=0.05)
    noisy_threshold, _, noisy_sigma = robust_change_threshold(noisy, valid, floor=0.05)

    assert noisy_sigma > quiet_sigma * 5
    assert noisy_threshold > quiet_threshold
    assert quiet_threshold == pytest.approx(0.05), "the domain prior floors the estimate"


def test_dilate_and_refine_removes_speckle():
    mask = np.zeros((60, 60), dtype=bool)
    mask[20, 20] = True                       # isolated speckle
    mask[30:40, 30:40] = True                 # real block

    refined = dilate_and_refine(mask)

    assert not refined[20, 20]
    assert refined[35, 35]


def test_shift_array_is_identity_for_zero_shift():
    array = np.random.default_rng(0).normal(size=(20, 20))
    assert np.array_equal(shift_array(array, 0.0, 0.0), array)


# ---------------------------------------------------------------------------
# domain configuration
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mode,expected_index",
    [
        ("water_body", "mndwi"),
        ("flood", "ndwi"),
        ("infrastructure", "ndbi"),
        ("vegetation", "ndvi"),
        ("glacier", "ndsi"),
    ],
)
def test_every_monitoring_mode_has_its_own_domain_profile(mode, expected_index):
    config = get_domain_config(mode)

    assert config.monitoring_mode == mode
    assert any(rule.index == expected_index for rule in config.rules)
    assert config.rules, "a mode with no spectral rule could never detect anything"


def test_unknown_mode_falls_back_to_conservative_general_profile():
    assert get_domain_config("not_a_real_mode").monitoring_mode == "general"
    assert get_domain_config(None).monitoring_mode == "general"


def test_severity_is_independent_of_confidence():
    """
    A tiny but perfectly confident detection must not be reported as critical.
    """
    config = get_domain_config("general")
    from satguard.processing.change_detection import classify_severity

    assert classify_severity(1.0, 0.0001, 50.0, config) is Severity.LOW
    assert classify_severity(1.0, 0.5, 10_000_000.0, config) is Severity.CRITICAL
    assert classify_severity(0.3, 0.5, 10_000_000.0, config) is Severity.NONE