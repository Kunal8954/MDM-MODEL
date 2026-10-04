"""
satguard/analytics/historical.py
Historical Intelligence Service for SATGUARD.
Orchestrates temporal normalization, time-window filtering, SAR/Optical series construction,
environmental context aggregation, persistence detection, baseline computation, and risk/alert trends.
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
import json
import uuid
import logging
from sqlalchemy.orm import Session

from satguard.models.entities import (
    CriticalLocation,
    SatelliteObservation,
    Sentinel1ChangeDetection,
    EvidenceSnapshot,
    RiskAssessment,
    Alert,
    HistoricalAnalyticsSnapshot,
)
from satguard.analytics.schemas import (
    HistoricalWindow,
    DataSufficiencyEnum,
    PersistenceStatusEnum,
    RiskTrendClassificationEnum,
    BaselineComparisonStatusEnum,
    DeviationStatusEnum,
    SARHistoricalPoint,
    SARTrendSummary,
    OpticalHistoricalPoint,
    OpticalTrendSummary,
    EnvironmentalHistorySummary,
    RiskHistoricalPoint,
    RiskTrendSummary,
    AlertHistoricalPoint,
    AlertTrendSummary,
    PersistenceResult,
    BaselineStatistics,
    BaselineComparisonResult,
    HistoricalAnalyticsReport,
)
from satguard.analytics.baseline import calculate_descriptive_stats, compare_value_to_baseline
from satguard.analytics.persistence import evaluate_persistence
from satguard.analytics.trends import (
    analyze_sar_trends,
    analyze_optical_trends,
    analyze_risk_trends,
    analyze_alert_trends,
)

logger = logging.getLogger("satguard.analytics")


class HistoricalAnalyticsService:
    """
    Core service delivering deterministic historical intelligence across multi-sensor satellite
    observations, environmental context, risk assessments, and alert lifecycles.
    """

    def __init__(self, db: Session):
        self.db = db

    def resolve_time_window(
        self,
        days: int = 30,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> HistoricalWindow:
        """
        Resolves explicit start and end timestamps.
        Never silently uses an unknown time range.
        """
        now = datetime.now(timezone.utc)
        if start_time and end_time:
            # Normalize to UTC
            s = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
            e = end_time if end_time.tzinfo else end_time.replace(tzinfo=timezone.utc)
            delta_days = max(1, (e - s).days)
            return HistoricalWindow(days=delta_days, start_time=s, end_time=e)

        effective_days = days if days > 0 else 30
        end_dt = end_time.replace(tzinfo=timezone.utc) if (end_time and end_time.tzinfo is None) else (end_time or now)
        start_dt = end_dt - timedelta(days=effective_days)
        return HistoricalWindow(days=effective_days, start_time=start_dt, end_time=end_dt)

    def get_sar_series(
        self, location_id: str, window: HistoricalWindow
    ) -> List[SARHistoricalPoint]:
        """
        Queries Sentinel-1 change detections using acquisition timestamps for temporal normalization.
        """
        records = (
            self.db.query(Sentinel1ChangeDetection)
            .filter(
                Sentinel1ChangeDetection.location_id == location_id,
                Sentinel1ChangeDetection.t2_acquisition_time >= window.start_time,
                Sentinel1ChangeDetection.t2_acquisition_time <= window.end_time,
            )
            .order_by(Sentinel1ChangeDetection.t2_acquisition_time.asc())
            .all()
        )

        points: List[SARHistoricalPoint] = []
        for r in records:
            vv_stats = json.loads(r.delta_vv_statistics) if isinstance(r.delta_vv_statistics, str) else (r.delta_vv_statistics or {})
            vh_stats = json.loads(r.delta_vh_statistics) if isinstance(r.delta_vh_statistics, str) else (r.delta_vh_statistics or {})
            orbit_info = json.loads(r.orbit_information) if isinstance(r.orbit_information, str) else (r.orbit_information or {})

            delta_vv_mean = vv_stats.get("mean")
            delta_vh_mean = vh_stats.get("mean")
            changed_pct = r.changed_percentage
            valid_pixels = vv_stats.get("valid_pixel_count")

            # Check significance: changed_percentage > 5% or large mean shift
            is_sig = False
            if changed_pct is not None and changed_pct >= 5.0:
                is_sig = True
            elif delta_vv_mean is not None and abs(delta_vv_mean) >= 1.5:
                is_sig = True

            rel_orbit = orbit_info.get("t2_relative_orbit") or orbit_info.get("relative_orbit")
            direction = orbit_info.get("t2_orbit_direction") or orbit_info.get("orbit_direction")

            points.append(
                SARHistoricalPoint(
                    change_id=r.id,
                    observation_id=r.t2_observation_id,
                    t1_acquisition_time=r.t1_acquisition_time,
                    t2_acquisition_time=r.t2_acquisition_time,
                    relative_orbit=rel_orbit,
                    orbit_direction=direction,
                    delta_vv_mean=round(delta_vv_mean, 4) if delta_vv_mean is not None else None,
                    delta_vh_mean=round(delta_vh_mean, 4) if delta_vh_mean is not None else None,
                    changed_percentage=round(changed_pct, 2) if changed_pct is not None else None,
                    valid_pixel_count=valid_pixels,
                    is_significant_change=is_sig,
                )
            )
        return points

    def get_optical_series(
        self, location_id: str, window: HistoricalWindow
    ) -> List[OpticalHistoricalPoint]:
        """
        Queries Sentinel-2 optical observations using acquisition timestamps.
        Applies cloud filtering so cloud-obscured scenes are not treated as clear measurements.
        """
        records = (
            self.db.query(SatelliteObservation)
            .filter(
                SatelliteObservation.location_id == location_id,
                SatelliteObservation.sensor != "SAR-C",
                SatelliteObservation.acquisition_time >= window.start_time,
                SatelliteObservation.acquisition_time <= window.end_time,
            )
            .order_by(SatelliteObservation.acquisition_time.asc())
            .all()
        )

        points: List[OpticalHistoricalPoint] = []
        for r in records:
            cloud_val = r.cloud_cover
            is_obscured = (cloud_val is not None and cloud_val > 50.0)
            points.append(
                OpticalHistoricalPoint(
                    observation_id=r.id,
                    acquisition_time=r.acquisition_time,
                    cloud_cover=round(cloud_val, 2) if cloud_val is not None else None,
                    is_cloud_obscured=is_obscured,
                    quality_status="CLOUD_OBSCURED" if is_obscured else "USABLE",
                )
            )
        return points

    def get_environmental_history(
        self, location_id: str, window: HistoricalWindow
    ) -> EnvironmentalHistorySummary:
        """
        Aggregates environmental context (GPM rainfall, FIRMS fire, USGS seismic)
        from EvidenceSnapshot records.
        Strictly preserves semantics: missing rainfall is 'UNAVAILABLE', NEVER 0 mm.
        """
        snapshots = (
            self.db.query(EvidenceSnapshot)
            .filter(
                EvidenceSnapshot.location_id == location_id,
                EvidenceSnapshot.created_at >= window.start_time,
                EvidenceSnapshot.created_at <= window.end_time,
            )
            .order_by(EvidenceSnapshot.created_at.asc())
            .all()
        )

        rainfall_vals = []
        rainfall_available = False
        fire_detections = 0
        fire_observed = False
        seismic_events = 0
        min_quake_dist: Optional[float] = None

        for s in snapshots:
            # Rainfall
            rf = json.loads(s.rainfall_evidence) if isinstance(s.rainfall_evidence, str) else (s.rainfall_evidence or {})
            if rf and rf.get("available") is True:
                # Check data coverage and alignment - not unavailable
                temporal_status = (rf.get("temporal_alignment") or {}).get("status")
                granules = rf.get("total_granules_found", 0)
                if temporal_status != "UNAVAILABLE" and granules > 0:
                    amt = rf.get("accumulated_precipitation_mm") or rf.get("rainfall_amount_mm") or rf.get("estimated_rainfall_mm")
                    if amt is not None:
                        rainfall_vals.append(float(amt))
                        rainfall_available = True

            # Fire
            fe = json.loads(s.fire_evidence) if isinstance(s.fire_evidence, str) else (s.fire_evidence or {})
            if fe and fe.get("available") is True:
                fire_observed = True
                fire_detections += int(fe.get("active_fires_detected", 0) or fe.get("fire_detection_count", 0))

            # Seismic
            se = json.loads(s.earthquake_evidence) if isinstance(s.earthquake_evidence, str) else (s.earthquake_evidence or {})
            if se and se.get("available") is True:
                quakes = se.get("nearby_earthquakes", [])
                seismic_events += len(quakes)
                for q in quakes:
                    dist = q.get("distance_km")
                    if dist is not None:
                        if min_quake_dist is None or dist < min_quake_dist:
                            min_quake_dist = float(dist)

        rainfall_status = "MEASURED" if (rainfall_available and rainfall_vals) else "UNAVAILABLE"
        rainfall_mean = round(sum(rainfall_vals) / len(rainfall_vals), 2) if rainfall_vals else None

        fire_status = "VALID_ZERO_OBSERVATION" if (fire_observed and fire_detections == 0) else (
            "FIRE_DETECTED" if fire_detections > 0 else "UNAVAILABLE"
        )

        seismic_status = "EVENTS_DETECTED" if seismic_events > 0 else "NO_EVENTS_DETECTED"

        return EnvironmentalHistorySummary(
            rainfall_status=rainfall_status,
            rainfall_observation_count=len(rainfall_vals),
            rainfall_mean_mm=rainfall_mean,
            fire_status=fire_status,
            fire_detection_count=fire_detections,
            seismic_status=seismic_status,
            seismic_event_count=seismic_events,
            nearest_earthquake_distance_km=round(min_quake_dist, 2) if min_quake_dist is not None else None,
        )

    def get_risk_series(
        self, location_id: str, window: HistoricalWindow
    ) -> List[RiskHistoricalPoint]:
        """
        Retrieves immutable historical risk assessments within the window.
        Historical assessments are strictly NOT recomputed.
        """
        records = (
            self.db.query(RiskAssessment)
            .filter(
                RiskAssessment.location_id == location_id,
                RiskAssessment.created_at >= window.start_time,
                RiskAssessment.created_at <= window.end_time,
            )
            .order_by(RiskAssessment.created_at.asc())
            .all()
        )

        points: List[RiskHistoricalPoint] = []
        for r in records:
            points.append(
                RiskHistoricalPoint(
                    risk_assessment_id=r.id,
                    timestamp=r.created_at,
                    score=round(r.score, 2),
                    risk_level=r.risk_level,
                    monitoring_priority=r.monitoring_priority,
                    evidence_strength=r.evidence_strength,
                    confidence_score=round(r.confidence_score, 2) if r.confidence_score is not None else 1.0,
                    engine_version=r.engine_version or "risk_engine_v1",
                )
            )
        return points

    def get_alert_series(
        self, location_id: str, window: HistoricalWindow
    ) -> List[AlertHistoricalPoint]:
        """
        Retrieves historical alerts preserving the Phase 6 lifecycle.
        """
        records = (
            self.db.query(Alert)
            .filter(
                Alert.location_id == location_id,
                Alert.created_at >= window.start_time,
                Alert.created_at <= window.end_time,
            )
            .order_by(Alert.created_at.asc())
            .all()
        )

        points: List[AlertHistoricalPoint] = []
        for r in records:
            points.append(
                AlertHistoricalPoint(
                    alert_id=r.id,
                    created_at=r.created_at,
                    priority=r.priority,
                    status=r.status,
                    title=r.title,
                    resolved_at=r.resolved_at,
                )
            )
        return points

    def evaluate_data_sufficiency(
        self,
        sar_count: int,
        optical_count: int,
        risk_count: int,
    ) -> DataSufficiencyEnum:
        """
        Evaluates data sufficiency deterministically.
        Prevents manufacturing trends from sparse data.
        """
        total = sar_count + optical_count + risk_count
        if total >= 5 or (sar_count >= 3 and risk_count >= 2):
            return DataSufficiencyEnum.SUFFICIENT
        elif total >= 2:
            return DataSufficiencyEnum.LIMITED
        else:
            return DataSufficiencyEnum.INSUFFICIENT

    def generate_report(
        self,
        location_id: str,
        days: int = 30,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        persist_snapshot: bool = True,
    ) -> HistoricalAnalyticsReport:
        """
        Generates a comprehensive historical analytics report for the critical location.
        Adheres to conservative scientific boundaries:
        - Never claims disaster prediction.
        - Provides explainable persistence and deterministic baseline comparison.
        """
        loc = self.db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
        loc_name = loc.name if loc else None

        window = self.resolve_time_window(days=days, start_time=start_time, end_time=end_time)

        # 1. Series retrieval
        sar_pts = self.get_sar_series(location_id, window)
        optical_pts = self.get_optical_series(location_id, window)
        risk_pts = self.get_risk_series(location_id, window)
        alert_pts = self.get_alert_series(location_id, window)
        env_hist = self.get_environmental_history(location_id, window)

        # 2. Analytics calculations
        sar_trends = analyze_sar_trends(sar_pts)
        optical_trends = analyze_optical_trends(optical_pts)
        risk_trends = analyze_risk_trends(risk_pts)
        alert_trends = analyze_alert_trends(alert_pts)
        persistence = evaluate_persistence(sar_pts)

        # 3. Data sufficiency
        sufficiency = self.evaluate_data_sufficiency(
            sar_count=sar_trends.valid_change_count,
            optical_count=optical_trends.usable_scenes,
            risk_count=risk_trends.assessment_count,
        )

        # 4. Baseline & Deviation Comparison
        # Use historical risk scores as baseline distribution
        all_scores = [p.score for p in risk_pts]
        baseline_stats = calculate_descriptive_stats(all_scores, "historical_risk_score")
        latest_val = risk_trends.latest_score

        baseline_comp = compare_value_to_baseline(
            current_value=latest_val,
            baseline=baseline_stats,
            min_samples=3,
        )

        # Composite report
        report_id = f"hist_{location_id}_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:6]}"
        report = HistoricalAnalyticsReport(
            id=report_id,
            location_id=location_id,
            location_name=loc_name,
            window=window,
            data_sufficiency=sufficiency,
            persistence=persistence,
            sar_trends=sar_trends,
            optical_trends=optical_trends,
            environmental_history=env_hist,
            risk_trends=risk_trends,
            alert_trends=alert_trends,
            baseline_comparison=baseline_comp,
            engine_version="analytics_v1",
            generated_at=datetime.now(timezone.utc),
        )

        if persist_snapshot:
            self._save_snapshot(report)

        return report

    def _save_snapshot(self, report: HistoricalAnalyticsReport):
        """
        Saves a queryable HistoricalAnalyticsSnapshot without duplicating raw observations.
        """
        try:
            snapshot = HistoricalAnalyticsSnapshot(
                id=report.id,
                location_id=report.location_id,
                window_days=report.window.days,
                window_start=report.window.start_time,
                window_end=report.window.end_time,
                data_sufficiency=report.data_sufficiency.value,
                persistence_status=report.persistence.persistence_status.value,
                risk_trend=report.risk_trends.classification.value,
                baseline_comparison=report.baseline_comparison.comparison_status.value,
                deviation_status=report.baseline_comparison.deviation_status.value,
                sar_summary=report.sar_trends.model_dump_json(),
                optical_summary=report.optical_trends.model_dump_json(),
                environmental_summary=report.environmental_history.model_dump_json(),
                risk_summary=report.risk_trends.model_dump_json(),
                alert_summary=report.alert_trends.model_dump_json(),
                persistence_summary=report.persistence.model_dump_json(),
                baseline_summary=report.baseline_comparison.model_dump_json(),
                deviation_summary=json.dumps({"deviation_status": report.baseline_comparison.deviation_status.value}),
                engine_version=report.engine_version,
                explanation=report.persistence.explanation,
                created_at=report.generated_at,
            )
            self.db.add(snapshot)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.warning(f"Could not persist historical analytics snapshot: {e}")

    def get_latest_snapshot(self, location_id: str) -> Optional[HistoricalAnalyticsSnapshot]:
        """
        Fetches the latest stored snapshot for the location.
        """
        return (
            self.db.query(HistoricalAnalyticsSnapshot)
            .filter(HistoricalAnalyticsSnapshot.location_id == location_id)
            .order_by(HistoricalAnalyticsSnapshot.created_at.desc())
            .first()
        )
