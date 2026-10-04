"""
satguard/processing/monitoring.py
End-to-end monitoring for an arbitrary AOI.

This is the composition point: it takes a user's AOI and monitoring mode, obtains
observations (LIVE from Sentinel Hub or labelled DEMO), masks unusable data, suppresses
artefact-driven false positives, runs the layered detector, and returns individually
reportable anomaly regions with separated confidence measures.

Data provenance is enforced here. LIVE mode never falls back to synthetic data: if
credentials are absent or acquisition fails, the run fails with an explicit error.
Producing a plausible-looking result from synthetic pixels would be indistinguishable
from a real detection to anyone reading the output later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from satguard.geospatial.area_of_interest import AOI
from satguard.geospatial.raster import GeoTransform
from satguard.processing.anomalies import (
    AnomalyRegion,
    DetectionReport,
    compute_run_confidence,
    extract_anomalies,
)
from satguard.processing.change_detection import (
    DetectionOutcome,
    Observation,
    TemporalBaseline,
    detect_change,
)
from satguard.processing.preprocess import build_quality_mask
from satguard.processing.suppression import (
    check_sensor_consistency,
    estimate_noise_floor,
    estimate_stability_mask,
    relative_radiometric_normalization,
    SensorMetadata,
    suppress_speckle,
)

logger = logging.getLogger("satguard.monitoring")

LIVE_SOURCE = "LIVE"
DEMO_SOURCE = "DEMO"


class MonitoringError(Exception):
    error_code = "MONITORING_FAILED"


class LiveDataUnavailable(MonitoringError):
    """LIVE was requested but real observations could not be obtained."""

    error_code = "LIVE_DATA_UNAVAILABLE"


@dataclass
class SceneBundle:
    """A scene from either source, normalised to one shape for the pipeline."""
    bands: Dict[str, np.ndarray]
    scl: Optional[np.ndarray]
    captured: datetime
    source: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def quality_mask(self, monitoring_mode: str) -> Any:
        mask = build_quality_mask(self.scl, self.shape_hw, bands=self.bands)
        return mask.reject_for_mode(monitoring_mode)

    @property
    def shape_hw(self) -> Tuple[int, int]:
        return next(iter(self.bands.values())).shape


@dataclass
class MonitoringRequest:
    """Everything needed to run one comparison for one AOI."""
    aoi: AOI
    monitoring_mode: Optional[str] = None
    source: str = DEMO_SOURCE
    # DEMO
    demo_scenario: Optional[str] = None
    demo_interval_days: int = 15
    # LIVE
    baseline_window_days: int = 30
    current_window_days: int = 15
    max_cloud_cover: Optional[float] = 20.0
    bands: Sequence[str] = ("B02", "B03", "B04", "B06", "B08", "B11", "B12")
    resolution_m: float = 10.0
    require_sar: bool = False
    orbit_direction: Optional[str] = None
    polarizations: Sequence[str] = ("VV", "VH")
    # Suppression
    normalization: str = "linear"
    speckle_filter: Optional[str] = "median"
    sar_change_mask: Optional[np.ndarray] = None
    grid_shape: Tuple[int, int] = (200, 200)

    @property
    def mode(self) -> str:
        return self.monitoring_mode or self.aoi.monitoring_mode.value


@dataclass
class MonitoringResult:
    """A complete, auditable monitoring run."""
    report: DetectionReport
    transform: GeoTransform
    crs: str
    source: str
    anomaly_mask: np.ndarray
    outcome: DetectionOutcome
    provenance: Dict[str, Any] = field(default_factory=dict)

    @property
    def anomalies(self) -> List[AnomalyRegion]:
        return self.report.anomalies

    def to_dict(self) -> Dict[str, Any]:
        payload = self.report.to_dict()
        payload["crs"] = self.crs
        payload["bounds"] = list(self.transform.bounds(1, 1))
        payload["provenance"] = self.provenance
        return payload


def _sar_metadata(
    baseline: Dict[str, Any], current: Dict[str, Any]
) -> Tuple[SensorMetadata, SensorMetadata]:
    def build(meta: Dict[str, Any]) -> SensorMetadata:
        return SensorMetadata(
            platform=meta.get("platform", ""),
            instrument=meta.get("instrument", "SAR"),
            collection=meta.get("collection", ""),
            processing_baseline=meta.get("processing_baseline"),
            resolution_m=meta.get("resolution_m"),
            orbit_direction=meta.get("orbit_direction"),
            polarizations=tuple(meta.get("polarizations", ()) or ()),
        )
    return build(baseline), build(current)


def _sar_change_from_log_ratio(
    baseline_db: np.ndarray,
    current_db: np.ndarray,
    valid: np.ndarray,
    speckle_filter: Optional[str],
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Derive a SAR change mask from a backscatter log-ratio.

    The threshold is derived from the scene's own noise floor rather than a fixed value,
    so it adapts to the incidence angle and radiometric terrain noise of the acquisition.
    """
    reference = baseline_db if speckle_filter in (None, "none") else suppress_speckle(
        baseline_db, speckle_filter
    )
    reference = current_db if speckle_filter in (None, "none") else suppress_speckle(
        current_db, speckle_filter
    )
    ratio = reference - baseline_db
    floor = estimate_noise_floor(ratio, valid)
    threshold = max(3.0 * floor["noise_sigma"], 1.0)
    mask = valid & np.isfinite(ratio) & (np.abs(ratio) > threshold)
    return mask, {
        "method": "log_ratio",
        "noise_sigma": round(floor["noise_sigma"], 4),
        "threshold_db": round(threshold, 4),
        "speckle_filter": speckle_filter,
    }


def run_monitoring(
    request: MonitoringRequest,
    acquirer: Optional[Any] = None,
    baseline: Optional[SceneBundle] = None,
    current: Optional[SceneBundle] = None,
    sar_baseline: Optional[SceneBundle] = None,
    sar_current: Optional[SceneBundle] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> MonitoringResult:
    """
    Run one AOI monitoring comparison end to end.

    `baseline`, `current`, `sar_baseline` and `sar_current` allow pre-obtained scenes to
    be injected, which keeps the pipeline testable without network access.

    `progress` is called with a stage name as each stage starts, so a caller running this
    on a background thread can report where the run is rather than only its outcome.
    """

    def notify(stage: str) -> None:
        if progress is not None:
            progress(stage)

    mode = request.mode
    aoi = request.aoi
    bounds = tuple(aoi.geometry.bounds)
    width, height = request.grid_shape
    transform = GeoTransform.from_bounds(bounds, width, height)
    inside = aoi.mask_for(transform, (height, width))
    provenance: Dict[str, Any] = {
        "aoi_id": aoi.id,
        "monitoring_mode": mode,
        "requested_source": request.source,
        "crs": "EPSG:4326",
        "grid": {"width": width, "height": height},
    }

    truth_mask = None
    if request.source.upper() == DEMO_SOURCE:
        if baseline is None or current is None:
            baseline, current, truth_mask = _demo_scenes(request, transform, inside)
        provenance.update({
            "source": DEMO_SOURCE,
            "synthetic": True,
            "note": "Synthetic demonstration data. Not satellite observations.",
        })
    elif request.source.upper() == LIVE_SOURCE:
        if acquirer is None:
            raise LiveDataUnavailable(
                "LIVE mode requires a Sentinel Hub acquirer. No credentials are "
                "configured, and DEMO data is never substituted for real observations."
            )
        if baseline is None or current is None:
            baseline, current = _live_optical(request, acquirer)
        provenance.update({"source": LIVE_SOURCE, "synthetic": False})
        if sar_baseline is None and request.require_sar:
            sar_baseline, sar_current = _live_sar(request, acquirer)
    else:
        raise MonitoringError(f"Unknown source '{request.source}'; use LIVE or DEMO")

    notify("PREPROCESSING")
    # --- usable data ------------------------------------------------------
    quality_b = baseline.quality_mask(mode)
    quality_c = current.quality_mask(mode)
    pair_valid = quality_b.valid & quality_c.valid & inside

    if not pair_valid.any():
        raise MonitoringError(
            f"No pixel is usable in both scenes over the AOI "
            f"({float(quality_b.valid.mean()):.1%} valid in the baseline, "
            f"{float(quality_c.valid.mean()):.1%} in the current scene). "
            f"Abandoning rather than reporting change from unusable data."
        )

    notify("SUPPRESSING")
    # --- artefact suppression --------------------------------------------
    stable_mask = _joint_stability_mask(
        baseline.bands, current.bands, pair_valid
    )

    # Radiometry is corrected band by band: each spectral band has its own response, so a
    # single joint fit would apply one gain to bands that do not share one. The same
    # stable-pixel mask is used for every band so the correction stays consistent.
    baseline_bands = dict(baseline.bands)
    current_bands = dict(current.bands)
    radiometric_records = []
    for name in sorted(baseline.bands):
        corrected, record = relative_radiometric_normalization(
            baseline.bands[name], current.bands[name],
            stable_mask=stable_mask, valid=pair_valid, method=request.normalization,
        )
        current_bands[name] = corrected
        radiometric_records.append((name, record))
    radiometric = _summarize_radiometric(radiometric_records)

    sensor_checks = check_sensor_consistency(
        _optical_metadata(baseline), _optical_metadata(current)
    )
    provenance["suppression"] = {
        "radiometric": {
            "method": radiometric.method,
            "gain": radiometric.gain,
            "offset": radiometric.offset,
            "fit_quality": radiometric.fit_quality,
            "stable_pixels": radiometric.stable_pixel_count,
        },
        "sensor_checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail}
            for c in sensor_checks
        ],
    }
    for check in sensor_checks:
        if not check.passed and check.name == "instrument":
            raise MonitoringError(
                f"Scenes are not comparable: {check.detail}"
            )

    notify("DETECTING")
    # --- detection --------------------------------------------------------
    sar_mask = request.sar_change_mask
    sar_factors: Dict[str, Any] = {}
    if sar_baseline is not None and sar_current is not None:
        sar_mask, sar_factors = _sar_change_from_log_ratio(
            np.asarray(sar_baseline.bands["VV"], dtype=float),
            np.asarray(sar_current.bands["VV"], dtype=float),
            sar_baseline.quality_mask(mode).valid & sar_current.quality_mask(mode).valid,
            request.speckle_filter,
        )
    elif sar_mask is not None:
        sar_factors = {"method": "supplied_mask"}

    outcome = detect_change(
        TemporalBaseline(baseline_bands, [baseline.captured], quality_b, 1),
        Observation(current.captured, current_bands, quality_c),
        mode,
        pixel_area_m2=transform.pixel_area_m2(transform.f + transform.e / 2.0),
        sar_change_mask=sar_mask,
    )

    run_confidence = compute_run_confidence(
        outcome,
        scl_available=baseline.scl is not None and current.scl is not None,
        radiometric_applied=radiometric.method in ("linear", "cdf", "median"),
        radiometric_rejected=radiometric.method == "rejected",
        alignment_unverified=bool(outcome.factors.get("alignment_unverified")),
        persistence_available=len(TemporalBaseline(
            baseline_bands, [baseline.captured], quality_b, 1
        ).dates) > 1,
    )
    notify("EXTRACTING")
    anomalies = extract_anomalies(
        outcome, transform, crs="EPSG:4326", monitoring_mode=mode,
        run_confidence=run_confidence,
        index_evidence=(outcome.layers[0].details or {}).get("indices") if outcome.layers else None,
        source=request.source.upper(),
    )
    report = DetectionReport(
        aoi_id=aoi.id, monitoring_mode=mode, run_confidence=run_confidence,
        anomalies=anomalies, outcome=outcome, source=request.source.upper(),
    )

    provenance.update({
        "baseline": {**baseline.metadata, "source": baseline.source},
        "current": {**current.metadata, "source": current.source},
        "baseline_date": baseline.captured.isoformat(),
        "current_date": current.captured.isoformat(),
        "valid_fraction": round(float(pair_valid.mean()), 4),
        "sar": sar_factors or None,
        "anomaly_pixels": int(np.count_nonzero(outcome.anomaly_mask)),
    })
    if truth_mask is not None:
        detected = outcome.anomaly_mask
        intersection = int((detected & truth_mask).sum())
        union = int((detected | truth_mask).sum())
        provenance["demo_truth"] = {
            "changed_pixels": int(np.count_nonzero(truth_mask)),
            "intersection_over_union": round(intersection / union, 4) if union else 0.0,
            "note": "Scored against the synthetic ground truth this run was built from.",
        }

    return MonitoringResult(
        report=report, transform=transform, crs="EPSG:4326",
        source=request.source.upper(), anomaly_mask=outcome.anomaly_mask,
        outcome=outcome, provenance=provenance,
    )


# ----------------------------------------------------------------------
# Source helpers
# ----------------------------------------------------------------------


def _demo_scenes(
    request: MonitoringRequest, transform: GeoTransform, inside: np.ndarray
):
    from satguard.processing import demo as demo_module

    dataset = demo_module.build_demo_dataset(
        aoi=request.aoi,
        monitoring_mode=request.mode,
        scenario=request.demo_scenario or (
            demo_module.scenarios_for_mode(request.mode)[0]
        ),
        interval_days=request.demo_interval_days,
        shape=(int(request.grid_shape[0]), int(request.grid_shape[1])),
        crs="EPSG:4326",
    )
    return (
        SceneBundle(
            bands=dataset.baseline.bands, scl=dataset.baseline.scl,
            captured=dataset.baseline.captured, source=DEMO_SOURCE,
            metadata=dataset.baseline.to_dict(),
        ),
        SceneBundle(
            bands=dataset.current.bands, scl=dataset.current.scl,
            captured=dataset.current.captured, source=DEMO_SOURCE,
            metadata=dataset.current.to_dict(),
        ),
        dataset.truth_mask,
    )


def _live_optical(request: MonitoringRequest, acquirer: Any):
    now = datetime.now(timezone.utc)
    current_window = (
        now - timedelta(days=request.current_window_days), now
    )
    baseline_window = (
        now - timedelta(days=request.baseline_window_days + request.current_window_days),
        now - timedelta(days=request.current_window_days),
    )
    bbox = tuple(request.aoi.geometry.bounds)
    common = {
        "bands": list(request.bands),
        "resolution_m": request.resolution_m,
        "include_scl": True,
        "max_cloud_cover": request.max_cloud_cover,
    }
    current_result = acquirer.acquire_sentinel2(bbox, current_window, **common)
    baseline_result = acquirer.acquire_sentinel2(bbox, baseline_window, **common)
    return (
        _bundle_from_acquisition(baseline_result),
        _bundle_from_acquisition(current_result),
    )


def _live_sar(request: MonitoringRequest, acquirer: Any):
    now = datetime.now(timezone.utc)
    bbox = tuple(request.aoi.geometry.bounds)
    common = {
        "resolution_m": request.resolution_m,
        "orbit_direction": request.orbit_direction,
        "polarizations": tuple(request.polarizations),
    }
    current = acquirer.acquire_sentinel1(
        bbox,
        (now - timedelta(days=request.current_window_days), now),
        **common,
    )
    baseline = acquirer.acquire_sentinel1(
        bbox,
        (now - timedelta(days=request.baseline_window_days + request.current_window_days),
         now - timedelta(days=request.current_window_days)),
        **common,
    )
    return _bundle_from_acquisition(baseline), _bundle_from_acquisition(current)


def _bundle_from_acquisition(result: Any) -> SceneBundle:
    """Convert an acquisition into the pipeline's scene shape."""
    profile = result.profile
    names = result.band_names or profile.band_names or []
    stack = np.asarray(profile.array, dtype=np.float64)
    if stack.ndim == 2:
        stack = stack[..., np.newaxis]
    bands = {
        name: stack[..., index] for index, name in enumerate(names)
    } if names else {f"band_{i}": stack[..., i] for i in range(stack.shape[-1])}

    return SceneBundle(
        bands=bands,
        scl=result.scl,
        captured=result.acquisition_time,
        source=getattr(result, "source", LIVE_SOURCE),
        metadata={
            "platform": result.platform,
            "instrument": result.instrument,
            "collection": result.collection,
            "product_id": result.product_id,
            "cloud_cover": result.cloud_cover,
            "resolution_m": result.profile.pixel_size[0] if result.profile else None,
        },
    )


def _optical_metadata(bundle: SceneBundle) -> SensorMetadata:
    meta = bundle.metadata or {}
    return SensorMetadata(
        platform=meta.get("platform", ""),
        instrument=meta.get("instrument", "MSI"),
        collection=meta.get("collection", ""),
        processing_baseline=meta.get("processing_baseline"),
        resolution_m=meta.get("resolution_m"),
        orbit_direction=meta.get("orbit_direction"),
        polarizations=tuple(meta.get("polarizations", ()) or ()),
    )


def _summarize_radiometric(records: Sequence[Tuple[str, Any]]) -> Any:
    """Collapse per-band radiometric outcomes into one auditable record."""
    from satguard.processing.suppression import RadiometricNormalization

    methods = {record.method for _, record in records}
    if "rejected" in methods:
        method = "rejected"
    elif len(methods) == 1:
        method = methods.pop()
    else:
        method = "mixed"

    gains = [r.gain for _, r in records if np.isfinite(r.gain)]
    offsets = [r.offset for _, r in records if np.isfinite(r.offset)]
    qualities = [
        r.fit_quality for _, r in records
        if r.fit_quality is not None and np.isfinite(r.fit_quality)
    ]
    return RadiometricNormalization(
        method=method,
        gain=float(np.mean(gains)) if gains else float("nan"),
        offset=float(np.mean(offsets)) if offsets else float("nan"),
        fit_quality=float(np.min(qualities)) if qualities else None,
        stable_pixel_count=int(records[0][1].stable_pixel_count) if records else 0,
    )


def _joint_stability_mask(
    baseline_bands: Dict[str, np.ndarray],
    current_bands: Dict[str, np.ndarray],
    valid: np.ndarray,
) -> np.ndarray:
    """
    Stability across all bands jointly.

    `estimate_stability_mask` works on a single band, so stability is evaluated per band
    and a pixel is accepted for calibration only if most bands agree it is unchanged. A
    pixel that is stable in one band but changing in another is not a safe calibration
    target, because the correction would be fitted on a mixed signal.
    """
    votes = []
    for name in sorted(baseline_bands):
        per_band = estimate_stability_mask(
            [baseline_bands[name], current_bands[name]], valid
        )
        votes.append(per_band)
    if not votes:
        return valid.copy()
    stacked = np.stack(votes, axis=0)
    return stacked.mean(axis=0) >= 0.5
