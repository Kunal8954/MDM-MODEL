"""
Tests for anomaly region extraction and separated confidence (increments G and H).

The failure modes these guard against are operational rather than numerical: a handful
of pixels reported as critical, a confident-looking headline number built on unusable
data, and an anomaly that cannot explain itself.
"""

from datetime import datetime, timezone

import numpy as np
import pytest

from satguard.geospatial.raster import GeoTransform
from satguard.processing.anomalies import (
    AnomalyError,
    compute_anomaly_confidence,
    compute_run_confidence,
    extract_anomalies,
    severity_rank,
    summarize_by_severity,
)
from satguard.processing.change_detection import (
    Observation,
    Severity,
    TemporalBaseline,
    detect_change,
)
from satguard.processing.preprocess import build_quality_mask

BANDS = ["B02", "B03", "B04", "B06", "B08", "B11", "B12"]
SURFACE = {
    "water": dict(B02=280, B03=260, B04=240, B06=180, B08=110, B11=90, B12=70),
    "vegetation": dict(B02=700, B03=900, B04=800, B06=2100, B08=3400, B11=2200, B12=1400),
    "urban": dict(B02=1900, B03=2000, B04=2100, B06=2300, B08=2000, B11=2600, B12=2400),
}
SCL_CLASS = {"water": 6, "vegetation": 4, "urban": 5}

# A geographic transform needs an explicit centre latitude for square metres.
_CENTER_LAT = 28.60


def _render(classes, seed, shape=(200, 200)):
    """Render physically plausible surface reflectance and a matching SCL grid."""
    rng = np.random.default_rng(seed)
    bands = {}
    for band in BANDS:
        plane = np.zeros(shape)
        for name, values in SURFACE.items():
            selected = classes == name
            if selected.any():
                plane[selected] = values[band]
        bands[band] = np.maximum(plane * (1 + rng.normal(0, 0.02, shape)), 1.0)
    scl = np.zeros(shape, np.uint8)
    for name, code in SCL_CLASS.items():
        scl[classes == name] = code
    return bands, scl


@pytest.fixture
def construction_scene():
    """Vegetation replaced by three built-up sites of markedly different sizes."""
    baseline_classes = np.full((200, 200), "vegetation", object)
    current_classes = baseline_classes.copy()
    current_classes[30:80, 30:80] = "urban"      # ~6.8 km2
    current_classes[120:132, 140:155] = "urban"  # ~0.5 km2
    current_classes[170:176, 20:26] = "urban"    # ~0.1 km2

    baseline, baseline_scl = _render(baseline_classes, 0)
    current, current_scl = _render(current_classes, 1)
    transform = GeoTransform.from_bounds((77.20, 28.55, 77.30, 28.65), 200, 200)
    return baseline, current, baseline_scl, current_scl, transform


def _detect(baseline, current, baseline_scl, current_scl, transform, mode="infrastructure"):
    return detect_change(
        TemporalBaseline(
            baseline,
            [datetime(2024, 6, 10, tzinfo=timezone.utc)],
            build_quality_mask(baseline_scl, baseline["B02"].shape),
            1,
        ),
        Observation(
            datetime(2024, 6, 25, tzinfo=timezone.utc),
            current,
            build_quality_mask(current_scl, baseline["B02"].shape),
        ),
        mode,
        pixel_area_m2=transform.pixel_area_m2(_CENTER_LAT),
    )


def test_each_construction_site_becomes_its_own_region(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(outcome, transform, run_confidence=compute_run_confidence(outcome))

    assert len(anomalies) == 3
    sizes = sorted(a.pixel_count for a in anomalies)
    assert sizes == [36, 180, 2500], "each site must be separated, not merged"


def test_anomalies_carry_true_geography_and_area(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(outcome, transform, run_confidence=compute_run_confidence(outcome))

    largest = max(anomalies, key=lambda a: a.area_m2)
    assert largest.geometry["type"] in ("Polygon", "MultiPolygon")

    west, south, east, north = largest.bbox
    assert 77.20 <= west < east <= 77.30
    assert 28.55 <= south < north <= 28.65
    assert west <= largest.centroid_lon <= east
    assert south <= largest.centroid_lat <= north

    # Area must be consistent with the reported pixel count at the pixel size.
    expected = largest.pixel_count * transform.pixel_area_m2(_CENTER_LAT)
    assert largest.area_m2 == pytest.approx(expected, rel=0.02)
    assert largest.area_km2 == pytest.approx(largest.area_m2 / 1e6, rel=1e-6)
    assert largest.area_ha == pytest.approx(largest.area_m2 / 1e4, rel=1e-6)


def test_severity_is_decided_per_region_not_from_the_run_total(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(outcome, transform, run_confidence=compute_run_confidence(outcome))

    by_size = sorted(anomalies, key=lambda a: a.pixel_count)
    # The run-level severity is critical because of the large site, but a 36-pixel
    # region must not inherit that.
    assert outcome.severity is Severity.CRITICAL
    assert by_size[-1].severity is Severity.CRITICAL
    assert by_size[0].severity is Severity.LOW
    assert by_size[0].severity is not outcome.severity


def test_anomalies_are_ordered_most_severe_first(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(outcome, transform, run_confidence=compute_run_confidence(outcome))

    ranks = [severity_rank(a.severity) for a in anomalies]
    assert ranks == sorted(ranks, reverse=True), "severity ordering must use operational rank"


def test_severity_rank_is_not_alphabetical():
    assert severity_rank(Severity.CRITICAL) > severity_rank(Severity.LOW)
    assert severity_rank(Severity.NONE) < severity_rank(Severity.HIGH)
    assert severity_rank(Severity.MODERATE) < severity_rank(Severity.CRITICAL)


def test_run_confidence_drops_when_inputs_are_poor_but_anomaly_confidence_does_not(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)

    good = compute_run_confidence(outcome)
    poor = compute_run_confidence(
        outcome, scl_available=False, alignment_unverified=True, persistence_available=False
    )
    assert poor.detection_confidence < good.detection_confidence

    # The two quantities are independent: identical pixel evidence, different run quality.
    support = {"L1_spectral": 1.0, "L2_structure": 1.0}
    assert compute_anomaly_confidence(support, good.detection_confidence) > (
        compute_anomaly_confidence(support, poor.detection_confidence)
    )
    assert 0.0 <= poor.detection_confidence < 1.0


def test_poor_inputs_produce_explicit_caveats(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    poor = compute_run_confidence(outcome, scl_available=False, alignment_unverified=True)
    text = " ".join(poor.caveats).lower()
    assert "classification layer" in text
    assert "alignment" in text


def test_anomaly_confidence_requires_actual_layer_support():
    assert compute_anomaly_confidence({}, 1.0) == 0.0
    # A single layer cannot corroborate itself, so confidence must stay below full.
    assert compute_anomaly_confidence({"L1_spectral": 1.0}, 1.0) < 1.0
    full = compute_anomaly_confidence(
        {"L1_spectral": 1.0, "L2_structure": 1.0, "L3_persistence": 1.0}, 1.0
    )
    assert full > compute_anomaly_confidence({"L1_spectral": 0.2, "L2_structure": 0.1}, 1.0)


def test_every_anomaly_explains_itself(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(outcome, transform, run_confidence=compute_run_confidence(outcome))

    for anomaly in anomalies:
        assert anomaly.evidence, "an anomaly must carry evidence"
        sources = {item.source for item in anomaly.evidence}
        assert "detector" in sources
        assert "confidence" in sources
        for item in anomaly.evidence:
            assert item.interpretation.strip(), "every evidence item must be explained"
            if item.value is not None:
                assert np.isfinite(item.value)


def test_small_regions_are_flagged_as_geolocation_sensitive(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(outcome, transform, run_confidence=compute_run_confidence(outcome))
    smallest = min(anomalies, key=lambda a: a.pixel_count)
    assert any("geolocation" in caveat for caveat in smallest.caveats)


def test_identifiers_are_unique_and_referenceable(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(
        outcome, transform, run_confidence=compute_run_confidence(outcome),
        detected_at=datetime(2024, 6, 25, tzinfo=timezone.utc),
    )
    ids = [a.region_id for a in anomalies]
    assert len(set(ids)) == len(ids)
    for anomaly in anomalies:
        assert anomaly.region_id.startswith("INFR-20240625T")


def test_clean_scene_produces_no_anomalies():
    classes = np.full((80, 80), "vegetation", object)
    baseline, baseline_scl = _render(classes, 2, (80, 80))
    current, current_scl = _render(classes, 3, (80, 80))
    transform = GeoTransform.from_bounds((77.0, 28.0, 77.1, 28.1), 80, 80)

    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(outcome, transform)
    assert anomalies == []


def test_summary_counts_regions_and_area_by_severity(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    anomalies = extract_anomalies(outcome, transform, run_confidence=compute_run_confidence(outcome))

    summary = summarize_by_severity(anomalies)
    assert set(summary) == {s.value for s in Severity}
    assert sum(v["count"] for v in summary.values()) == len(anomalies)
    assert summary[Severity.LOW.value]["count"] == 1


def test_mask_must_be_two_dimensional(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    outcome = _detect(baseline, current, baseline_scl, current_scl, transform)
    outcome.anomaly_mask = np.asarray([True, False])
    with pytest.raises(AnomalyError):
        extract_anomalies(outcome, transform)


def test_large_seasonal_gap_reduces_run_confidence(construction_scene):
    baseline, current, baseline_scl, current_scl, transform = construction_scene
    near = _detect(baseline, current, baseline_scl, current_scl, transform)

    outcome = detect_change(
        TemporalBaseline(
            baseline,
            [datetime(2023, 6, 10, tzinfo=timezone.utc)],
            build_quality_mask(baseline_scl, baseline["B02"].shape),
            1,
        ),
        Observation(
            datetime(2024, 6, 25, tzinfo=timezone.utc),
            current,
            build_quality_mask(current_scl, baseline["B02"].shape),
        ),
        "infrastructure",
        pixel_area_m2=transform.pixel_area_m2(_CENTER_LAT),
    )
    assert compute_run_confidence(outcome).detection_confidence < (
        compute_run_confidence(near).detection_confidence
    )