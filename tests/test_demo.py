"""
Tests for labelled DEMO data and the end-to-end detection regression (J and L).

DEMO exists so the product can be demonstrated without Sentinel credentials. The two
properties that make it trustworthy are tested here: it is always labelled synthetic and
never substitutes for LIVE, and the detector scores well against the ground truth the
generator records.
"""

import numpy as np
import pytest

from satguard.geospatial.area_of_interest import aoi_from_bbox, aoi_from_polygon
from satguard.processing.change_detection import (
    Observation,
    TemporalBaseline,
    detect_change,
)
from satguard.processing.demo import (
    DEMO_SITES,
    DEMO_SOURCE,
    DemoError,
    available_demo_sites,
    build_demo_dataset,
    demo_site,
    scenarios_for_mode,
)

# Sites that do not require SAR corroboration, so they run on optical data alone.
OPTICAL_SITES = ("south_lhonak_glacier", "siachen_glacier",
                 "tehri_dam_construction", "sardar_sarovar_reservoir")


def _detect(dataset, monitoring_mode):
    quality_b = dataset.baseline.quality_mask(monitoring_mode)
    quality_c = dataset.current.quality_mask(monitoring_mode)
    return detect_change(
        TemporalBaseline(dataset.baseline.bands, [dataset.baseline.captured], quality_b, 1),
        Observation(dataset.current.captured, dataset.current.bands, quality_c),
        monitoring_mode,
        pixel_area_m2=dataset.transform.pixel_area_m2(
            dataset.transform.f + dataset.transform.e / 2.0
        ),
    )


def _iou(detected, truth):
    intersection = int((detected & truth).sum())
    union = int((detected | truth).sum())
    return intersection / union if union else 0.0


def test_everything_produced_by_demo_is_labelled_synthetic():
    dataset = build_demo_dataset(
        bounds=(78.58, 30.28, 78.72, 30.40),
        monitoring_mode="infrastructure",
        scenario="new_construction",
    )
    assert dataset.source == DEMO_SOURCE
    assert dataset.synthetic is True
    assert dataset.baseline.source == DEMO_SOURCE
    assert dataset.current.synthetic is True

    manifest = dataset.to_dict()
    assert manifest["source"] == DEMO_SOURCE
    assert manifest["synthetic"] is True
    assert "not satellite observations" in manifest["disclaimer"].lower()
    assert "synthetic" in manifest["baseline"]["description"].lower()


def test_demo_data_is_deterministic():
    first = build_demo_dataset(bounds=(78.58, 30.28, 78.72, 30.40),
                               monitoring_mode="infrastructure", scenario="new_construction")
    second = build_demo_dataset(bounds=(78.58, 30.28, 78.72, 30.40),
                                monitoring_mode="infrastructure", scenario="new_construction")
    assert np.array_equal(first.current.bands["B08"], second.current.bands["B08"])
    assert np.array_equal(first.truth_mask, second.truth_mask)


def test_scenes_are_georeferenced_and_the_aoi_is_honoured():
    dataset = build_demo_dataset(
        bounds=(78.58, 30.28, 78.72, 30.40), monitoring_mode="infrastructure",
        scenario="new_construction",
    )
    assert dataset.crs == "EPSG:4326"
    shape = dataset.baseline.scl.shape
    assert all(band.shape == shape for band in dataset.baseline.bands.values())
    # Everything is georeferenced back onto the requested extent.
    assert dataset.transform.pixel_to_lonlat(0, 0)[0] == pytest.approx(78.58, abs=1e-6)

    # A non-rectangular AOI leaves part of its own bounding grid outside the geometry.
    # Those pixels must be identical in both scenes: no change may be invented beyond
    # what the user actually asked to monitor.
    elbow = [[78.58, 30.28], [78.72, 30.28], [78.72, 30.33], [78.64, 30.33],
             [78.64, 30.40], [78.58, 30.40], [78.58, 30.28]]
    partial = build_demo_dataset(
        aoi=aoi_from_polygon(elbow, monitoring_mode="infrastructure"),
        scenario="new_construction",
    )
    inside = partial.aoi.mask_for(partial.transform, partial.baseline.scl.shape)
    assert not inside.all(), "test AOI must not cover its whole bounding grid"
    outside = ~inside
    for band, values in partial.current.bands.items():
        assert np.array_equal(values[outside], partial.baseline.bands[band][outside]), band
    assert not (partial.truth_mask & outside).any()


def test_snow_and_ice_is_not_labelled_as_cloud_shadow():
    """
    SCL class 3 is cloud shadow and class 11 is snow and ice. Getting this backwards
    would discard an entire glacier as unusable and hide every real change on it.
    """
    dataset = build_demo_dataset(
        bounds=demo_site("south_lhonak_glacier").bounds,
        monitoring_mode="glacier",
        scenario="glacier_retreat",
    )
    scl = dataset.baseline.scl
    assert 11 in np.unique(scl), "ice must be labelled SCL snow/ice"
    assert 3 not in np.unique(scl), "ice must never be labelled cloud shadow"
    assert dataset.baseline.quality_mask("glacier").valid.mean() > 0.9


def test_truth_mask_marks_only_pixels_that_actually_changed():
    dataset = build_demo_dataset(
        bounds=(78.58, 30.28, 78.72, 30.40), monitoring_mode="infrastructure",
        scenario="new_construction",
    )
    assert dataset.truth_mask.any()
    assert dataset.truth_mask.sum() < dataset.baseline.scl.size
    outside = ~dataset.aoi.mask_for(dataset.transform, dataset.baseline.scl.shape)
    assert not (dataset.truth_mask & outside).any()


def test_unknown_scenario_and_site_are_rejected():
    with pytest.raises(DemoError):
        build_demo_dataset(bounds=(0, 0, 0.1, 0.1), scenario="not_a_scenario")
    with pytest.raises(DemoError):
        demo_site("atlantis")


def test_dataset_requires_an_aoi_or_bounds():
    with pytest.raises(DemoError):
        build_demo_dataset()


def test_demo_works_for_arbitrary_world_locations():
    """DEMO must not depend on the named sites: any AOI on Earth must work."""
    for lon, lat, label in ((0.0, 0.0, "null island"),
                            (-179.9, -70.0, "antarctic"),
                            (151.2, -33.9, "sydney")):
        dataset = build_demo_dataset(bounds=(lon, lat, lon + 0.1, lat + 0.1),
                                     monitoring_mode="infrastructure",
                                     scenario="new_construction")
        outcome = _detect(dataset, "infrastructure")
        assert _iou(outcome.anomaly_mask, dataset.truth_mask) > 0.5, label


@pytest.mark.parametrize("site_name", OPTICAL_SITES)
def test_regression_sites_are_detected_without_false_alarms(site_name):
    """
    The core acceptance criterion: on labelled data the detector must find the change
    and must not invent change where there is none.
    """
    site = demo_site(site_name)
    dataset = build_demo_dataset(bounds=site.bounds,
                                 monitoring_mode=site.monitoring_mode.value,
                                 scenario=site.scenario)
    outcome = _detect(dataset, site.monitoring_mode.value)

    assert not outcome.rejected, f"{site_name} was rejected: {outcome.reject_reason}"
    detected = outcome.anomaly_mask
    false_positives = int((detected & ~dataset.truth_mask).sum())

    assert _iou(detected, dataset.truth_mask) > 0.75, (
        f"{site_name}: IoU too low, recall {int((detected & dataset.truth_mask).sum())}"
        f"/{int(dataset.truth_mask.sum())}"
    )
    # Zero false positives on labelled data is the whole point of the exercise.
    assert false_positives == 0, f"{site_name} reported {false_positives} false pixels"
    assert outcome.severity.value != "none", f"{site_name} produced no operational severity"


def test_glacier_retreat_is_detected_not_swallowed():
    """
    Ice loss darkens the surface and exposes SWIR-absorbing ground, so NDSI falls while
    NBR rises. Rules with the wrong sign silently hid every glacier change.
    """
    site = demo_site("south_lhonak_glacier")
    dataset = build_demo_dataset(bounds=site.bounds, monitoring_mode="glacier",
                                 scenario="glacier_retreat")
    outcome = _detect(dataset, "glacier")
    detected = outcome.anomaly_mask
    assert detected.sum() > 0
    assert _iou(detected, dataset.truth_mask) > 0.75
    assert outcome.confidence > 0.5


def test_flood_monitoring_refuses_to_report_without_sar():
    """
    Flood extent cannot be judged from optical data alone, so the run must be rejected
    rather than returning a confident answer built on the wrong sensor.
    """
    site = demo_site("mumbai_coastal_flood")
    dataset = build_demo_dataset(bounds=site.bounds, monitoring_mode="flood",
                                 scenario="coastal_flooding")
    outcome = _detect(dataset, "flood")
    assert outcome.rejected
    assert outcome.reject_reason == "cross_sensor_unavailable"
    assert not outcome.anomaly_mask.any()


def test_available_sites_are_described_for_the_ui():
    sites = available_demo_sites()
    assert len(sites) == len(DEMO_SITES)
    for entry in sites:
        assert {"name", "monitoring_mode", "scenario", "description"} <= set(entry)


def test_scenarios_are_offered_per_monitoring_mode():
    assert scenarios_for_mode("glacier") == ["glacier_retreat"]
    assert "reservoir_expansion" in scenarios_for_mode("water_body")
    assert scenarios_for_mode("general")


def test_demo_accepts_polygon_and_point_aois():
    polygon = [[78.58, 30.28], [78.72, 30.28], [78.72, 30.40], [78.58, 30.40], [78.58, 30.28]]
    for aoi in (aoi_from_polygon(polygon, monitoring_mode="infrastructure"),
                aoi_from_bbox(78.58, 30.28, 78.72, 30.40, monitoring_mode="infrastructure")):
        dataset = build_demo_dataset(aoi=aoi, scenario="new_construction")
        assert dataset.truth_mask.sum() > 0