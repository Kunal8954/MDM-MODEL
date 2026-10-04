"""
satguard/risk/engine.py
Phase 4: Deterministic, Explainable Risk Assessment Engine for SATGUARD.

Transforms multi-sensor evidence produced in Phase 3 into normalized monitoring risk
assessments, operational surveillance priorities, and auditable explanations.
STRICTLY ENFORCES:
- Score != Probability of disaster
- Risk level != Confirmed disaster
- SAR change != Landslide
- Optical change != Flood
- Independent of Groq, LLMs, and non-deterministic ML models.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from satguard.models.entities import CriticalLocation, EvidenceSnapshot, RiskAssessment
from satguard.fusion.schema import MultiSensorEvidence, Sentinel1Evidence, Sentinel2Evidence
from satguard.risk.schema import (
    RiskLevel,
    MonitoringPriority,
    EvidenceStrength,
    RecencyStatus,
    FactorType,
    ContributingFactor,
    RiskAssessmentResult,
)
from satguard.risk.config import RiskEngineConfig, default_risk_config

logger = logging.getLogger("satguard.risk.engine")


class RiskAssessmentEngine:
    """
    Deterministic, transparent, rule-based Risk Assessment Engine.
    Converts multi-sensor evidence into explainable monitoring risk classifications.
    """

    def __init__(self, config: Optional[RiskEngineConfig] = None):
        self.config = config or default_risk_config

    def assess(
        self,
        evidence: Union[MultiSensorEvidence, EvidenceSnapshot, Dict[str, Any]],
        location_name: Optional[str] = None,
    ) -> RiskAssessmentResult:
        """
        Calculates deterministic monitoring risk score, level, priority, evidence strength,
        contributing factors, and uncertainty declarations.
        """
        # 1. Normalize input to MultiSensorEvidence if needed
        norm_ev = self._normalize_evidence(evidence, location_name)

        contributing_factors: List[ContributingFactor] = []
        uncertainty_factors: List[str] = []

        # 2. Evaluate SAR Signal Contribution
        sar_pts, sar_factors, sar_uncertainties = self._evaluate_sar(norm_ev.sentinel1)
        contributing_factors.extend(sar_factors)
        uncertainty_factors.extend(sar_uncertainties)

        # 3. Evaluate Optical Signal Contribution
        opt_pts, opt_factors, opt_uncertainties = self._evaluate_optical(norm_ev.sentinel2)
        contributing_factors.extend(opt_factors)
        uncertainty_factors.extend(opt_uncertainties)

        # 4. Evaluate Multi-Sensor Correlations
        corr_pts, corr_factors = self._evaluate_correlations(norm_ev.correlations)
        contributing_factors.extend(corr_factors)

        # 5. Evaluate Contextual Environmental Factors
        rain_pts, rain_factors, rain_uncertainties = self._evaluate_rainfall(norm_ev.rainfall)
        contributing_factors.extend(rain_factors)
        uncertainty_factors.extend(rain_uncertainties)

        quake_pts, quake_factors, quake_uncertainties = self._evaluate_earthquake(norm_ev.earthquake)
        contributing_factors.extend(quake_factors)
        uncertainty_factors.extend(quake_uncertainties)

        fire_pts, fire_factors = self._evaluate_fire(norm_ev.fire)
        contributing_factors.extend(fire_factors)

        dem_pts, dem_factors = self._evaluate_terrain(norm_ev.terrain)
        contributing_factors.extend(dem_factors)

        # 6. Evaluate Cross-Sensor Corroboration Uncertainties
        cross_uncertainties = self._evaluate_cross_sensor_uncertainties(norm_ev)
        uncertainty_factors.extend(cross_uncertainties)

        # 7. Calculate Normalized Score [0.0, 100.0]
        raw_score = sar_pts + opt_pts + corr_pts + rain_pts + quake_pts + fire_pts + dem_pts
        score = round(float(min(max(raw_score, 0.0), 100.0)), 2)

        # 8. Assign Risk Level
        risk_level = self._classify_risk_level(score)

        # 9. Assign Monitoring Priority
        monitoring_priority = self._assign_monitoring_priority(risk_level)

        # 10. Calculate Evidence Strength
        evidence_strength, confidence_score = self._calculate_evidence_strength(norm_ev)
        if evidence_strength == EvidenceStrength.WEAK:
            uncertainty_factors.append("Overall evidence strength is WEAK due to sparse or stale sensor observations.")

        # 11. Generate Deterministic Explanation & Recommended Action
        explanation = self._generate_explanation(
            location_name=norm_ev.location_name or norm_ev.location_id,
            score=score,
            risk_level=risk_level,
            monitoring_priority=monitoring_priority,
            evidence_strength=evidence_strength,
            contributing_factors=contributing_factors,
            uncertainty_factors=uncertainty_factors,
        )
        recommended_action = self._determine_recommended_action(risk_level)

        # 12. Build RiskAssessmentResult
        assessment_id = f"risk-assess-{norm_ev.location_id}-{int(datetime.now(timezone.utc).timestamp())}"
        now_utc = datetime.now(timezone.utc)

        provenance = {
            "engine_version": self.config.engine_version,
            "evidence_snapshot_id": norm_ev.id,
            "assessed_at": now_utc.isoformat(),
            "raw_score_components": {
                "sar_points": sar_pts,
                "optical_points": opt_pts,
                "correlation_points": corr_pts,
                "rainfall_points": rain_pts,
                "earthquake_points": quake_pts,
                "fire_points": fire_pts,
                "terrain_points": dem_pts,
                "total_raw": raw_score,
            },
            "sensor_counts": {
                "sentinel1_available": norm_ev.sentinel1.available,
                "sentinel2_available": norm_ev.sentinel2.available,
                "rainfall_available": norm_ev.rainfall.available,
                "fire_available": norm_ev.fire.available,
                "earthquake_available": norm_ev.earthquake.available,
                "terrain_available": norm_ev.terrain.available,
                "correlations_count": len(norm_ev.correlations),
            },
        }

        return RiskAssessmentResult(
            id=assessment_id,
            location_id=norm_ev.location_id,
            location_name=norm_ev.location_name,
            evidence_snapshot_id=norm_ev.id,
            score=score,
            risk_level=risk_level,
            monitoring_priority=monitoring_priority,
            evidence_strength=evidence_strength,
            confidence_score=confidence_score,
            contributing_factors=contributing_factors,
            uncertainty_factors=uncertainty_factors,
            explanation=explanation,
            recommended_action=recommended_action,
            engine_version=self.config.engine_version,
            provenance=provenance,
            created_at=now_utc,
        )

    def assess_and_persist(
        self,
        db: Session,
        evidence: Union[MultiSensorEvidence, EvidenceSnapshot],
        location_name: Optional[str] = None,
    ) -> RiskAssessmentResult:
        """
        Computes risk assessment and atomically persists it to the risk_assessments database table.
        """
        result = self.assess(evidence=evidence, location_name=location_name)

        db_record = RiskAssessment(
            id=result.id,
            location_id=result.location_id,
            evidence_snapshot_id=result.evidence_snapshot_id,
            score=result.score,
            risk_level=result.risk_level.value,
            monitoring_priority=result.monitoring_priority.value,
            evidence_strength=result.evidence_strength.value,
            confidence_score=result.confidence_score,
            contributing_factors=json.dumps([f.model_dump() for f in result.contributing_factors]),
            uncertainty_factors=json.dumps(result.uncertainty_factors),
            explanation=result.explanation,
            recommended_action=result.recommended_action,
            engine_version=result.engine_version,
            provenance=json.dumps(result.provenance),
            score_interpretation=result.score_interpretation,
            created_at=result.created_at,
        )
        db.merge(db_record)
        db.commit()

        logger.info(
            f"Successfully assessed and persisted RiskAssessment {result.id} for location {result.location_id}: "
            f"Score={result.score} ({result.risk_level.value}, {result.monitoring_priority.value})."
        )
        return result

    # ------------------------------------------------------------------
    # EVALUATION HELPERS
    # ------------------------------------------------------------------

    def _evaluate_sar(
        self, s1: Sentinel1Evidence
    ) -> tuple[float, List[ContributingFactor], List[str]]:
        factors: List[ContributingFactor] = []
        uncertainties: List[str] = []

        if not s1.available:
            uncertainties.append("Sentinel-1 SAR evidence unavailable; radar surface change verification cannot be confirmed.")
            return 0.0, factors, uncertainties

        points = 0.0
        details = []

        # 1. Joint or changed percentage
        joint_pct = s1.joint_changed_percent or 0.0
        changed_pct = s1.changed_percentage or 0.0
        metric_pct = max(joint_pct, changed_pct * 0.3)

        if metric_pct >= self.config.sar_joint_change_thresholds["tier1"]:
            pts = 18.0
            points += pts
            details.append(f"significant joint change ({metric_pct:.2f}% >= {self.config.sar_joint_change_thresholds['tier1']}%)")
        elif metric_pct >= self.config.sar_joint_change_thresholds["tier2"]:
            pts = 12.0
            points += pts
            details.append(f"substantial joint change ({metric_pct:.2f}% >= {self.config.sar_joint_change_thresholds['tier2']}%)")
        elif metric_pct >= self.config.sar_joint_change_thresholds["tier3"]:
            pts = 8.0
            points += pts
            details.append(f"moderate joint change ({metric_pct:.2f}% >= {self.config.sar_joint_change_thresholds['tier3']}%)")
        elif metric_pct >= self.config.sar_joint_change_thresholds["tier4"]:
            pts = 4.0
            points += pts
            details.append(f"low joint change detected ({metric_pct:.2f}% >= {self.config.sar_joint_change_thresholds['tier4']}%)")

        # 2. Significant Region Clustering
        regions = s1.significant_region_count
        if regions >= self.config.sar_region_count_thresholds["tier1"]:
            pts = 8.0
            points += pts
            details.append(f"extensive clustering ({regions} contiguous regions)")
        elif regions >= self.config.sar_region_count_thresholds["tier2"]:
            pts = 5.0
            points += pts
            details.append(f"clustered change ({regions} contiguous regions)")
        elif regions >= self.config.sar_region_count_thresholds["tier3"]:
            pts = 3.0
            points += pts
            details.append(f"{regions} contiguous change region detected")

        # 3. Mean Backscatter Magnitude Shift
        delta_vv = abs(s1.mean_delta_vv_db or 0.0)
        delta_vh = abs(s1.mean_delta_vh_db or 0.0)
        max_shift = max(delta_vv, delta_vh)
        if max_shift >= 2.0:
            pts = 4.0
            points += pts
            details.append(f"large mean backscatter shift ({max_shift:.2f} dB >= 2.0 dB)")
        elif max_shift >= self.config.sar_backscatter_shift_db:
            pts = 2.0
            points += pts
            details.append(f"mean backscatter shift ({max_shift:.2f} dB >= {self.config.sar_backscatter_shift_db} dB)")

        # Temporal recency / staleness damping
        is_stale = s1.temporal_alignment and s1.temporal_alignment.status == "STALE"
        if is_stale:
            points *= self.config.stale_damping_factor
            uncertainties.append("Sentinel-1 SAR observation is STALE; temporal damping applied.")
            details.append("stale data damping applied (0.5x)")

        points = min(points, self.config.max_sar_points)

        if points > 0.0:
            factors.append(
                ContributingFactor(
                    factor=FactorType.SAR_CHANGE.value,
                    contribution=round(points, 2),
                    evidence_id=s1.t2_observation_id,
                    reason=f"Significant SAR backscatter difference observed: {', '.join(details)}.",
                )
            )

        return points, factors, uncertainties

    def _evaluate_optical(
        self, s2: Sentinel2Evidence
    ) -> tuple[float, List[ContributingFactor], List[str]]:
        factors: List[ContributingFactor] = []
        uncertainties: List[str] = []

        if not s2.available:
            uncertainties.append("Sentinel-2 optical evidence unavailable; water and vegetation extent cannot be verified.")
            return 0.0, factors, uncertainties

        # Cloud cover check
        cloud = s2.cloud_cover or 0.0
        if cloud > self.config.cloud_rejection_threshold:
            uncertainties.append(f"Sentinel-2 cloud cover ({cloud:.1f}%) exceeds quality threshold ({self.config.cloud_rejection_threshold}%); optical signal rejected.")
            return 0.0, factors, uncertainties

        points = 0.0
        details = []

        delta_water_pct = abs(s2.water_change_percentage or 0.0)
        status = s2.optical_change_status or ""

        if delta_water_pct >= self.config.optical_change_pct_thresholds["tier1"] or "SIGNIFICANT" in status:
            pts = 18.0
            points += pts
            details.append(f"significant surface water variance ({delta_water_pct:.1f}% >= {self.config.optical_change_pct_thresholds['tier1']}%)")
        elif delta_water_pct >= self.config.optical_change_pct_thresholds["tier2"] or "MODERATE" in status:
            pts = 10.0
            points += pts
            details.append(f"moderate surface water variance ({delta_water_pct:.1f}% >= {self.config.optical_change_pct_thresholds['tier2']}%)")
        elif delta_water_pct >= self.config.optical_change_pct_thresholds["tier3"]:
            pts = 5.0
            points += pts
            details.append(f"minor surface water variance ({delta_water_pct:.1f}% >= {self.config.optical_change_pct_thresholds['tier3']}%)")

        # Cloud damping if between 20% and 50%
        if cloud > 20.0:
            points *= 0.7
            uncertainties.append(f"Sentinel-2 partial cloud cover ({cloud:.1f}%) introduces spectral uncertainty.")
            details.append("partial cloud damping applied (0.7x)")

        # Temporal recency damping
        is_stale = s2.temporal_alignment and s2.temporal_alignment.status == "STALE"
        if is_stale:
            points *= self.config.stale_damping_factor
            uncertainties.append("Sentinel-2 optical observation is STALE; temporal damping applied.")
            details.append("stale data damping applied (0.5x)")

        points = min(points, self.config.max_optical_points)

        if points > 0.0:
            factors.append(
                ContributingFactor(
                    factor=FactorType.OPTICAL_CHANGE.value,
                    contribution=round(points, 2),
                    evidence_id=s2.observation_id,
                    reason=f"Optical multispectral surface extent change: {', '.join(details)}.",
                )
            )

        return points, factors, uncertainties

    def _evaluate_correlations(
        self, correlations: List[Any]
    ) -> tuple[float, List[ContributingFactor]]:
        factors: List[ContributingFactor] = []
        if not correlations:
            return 0.0, factors

        total_pts = 0.0
        for corr in correlations:
            corr_type = getattr(corr, "correlation_type", None) or corr.get("correlation_type")
            conf = getattr(corr, "confidence_score", 1.0) or (corr.get("confidence_score", 1.0) if isinstance(corr, dict) else 1.0)
            sources = getattr(corr, "source_evidence_ids", []) or (corr.get("source_evidence_ids", []) if isinstance(corr, dict) else [])
            sci_note = getattr(corr, "scientific_note", "") or (corr.get("scientific_note", "") if isinstance(corr, dict) else "")

            base_pts = self.config.correlation_points.get(corr_type, 0.0)
            if base_pts > 0.0:
                weighted_pts = round(base_pts * float(conf), 2)
                total_pts += weighted_pts
                factors.append(
                    ContributingFactor(
                        factor=FactorType.MULTI_SENSOR_CORRELATION.value,
                        contribution=weighted_pts,
                        evidence_id=",".join(sources) if sources else None,
                        reason=f"Cross-sensor corroboration [{corr_type}] (conf: {conf:.2f}): {sci_note}",
                    )
                )

        total_pts = min(total_pts, self.config.max_correlation_points)
        return total_pts, factors

    def _evaluate_rainfall(
        self, rain: Any
    ) -> tuple[float, List[ContributingFactor], List[str]]:
        factors: List[ContributingFactor] = []
        uncertainties: List[str] = []

        if not rain or not getattr(rain, "available", False):
            uncertainties.append("Precipitation data unavailable or lacking local coverage in observation window.")
            return 0.0, factors, uncertainties

        amount_mm = getattr(rain, "estimated_rainfall_mm", 0.0) or 0.0
        granules = getattr(rain, "total_granules_found", 0) or 0

        if granules == 0 and amount_mm == 0.0:
            uncertainties.append("No precipitation granules identified over critical location in monitoring window.")
            return 0.0, factors, uncertainties

        points = 0.0
        if amount_mm >= 50.0:
            points = 10.0
            reason = f"Heavy precipitation recorded ({amount_mm:.1f} mm >= 50 mm)"
        elif amount_mm >= 25.0:
            points = 6.0
            reason = f"Moderate-to-heavy precipitation recorded ({amount_mm:.1f} mm >= 25 mm)"
        elif amount_mm >= 10.0:
            points = 3.0
            reason = f"Low-to-moderate precipitation recorded ({amount_mm:.1f} mm >= 10 mm)"
        else:
            return 0.0, factors, uncertainties

        # Staleness check
        temp_align = getattr(rain, "temporal_alignment", None)
        if temp_align and getattr(temp_align, "status", "") == "STALE":
            points *= self.config.stale_damping_factor
            reason += " (stale precipitation damping applied)"
            uncertainties.append("Rainfall observation is STALE relative to satellite pass.")

        points = min(points, self.config.max_rainfall_points)

        factors.append(
            ContributingFactor(
                factor=FactorType.RAINFALL.value,
                contribution=round(points, 2),
                evidence_id="NASA_GPM_IMERG",
                reason=reason,
            )
        )
        return points, factors, uncertainties

    def _evaluate_earthquake(
        self, quake: Any
    ) -> tuple[float, List[ContributingFactor], List[str]]:
        factors: List[ContributingFactor] = []
        uncertainties: List[str] = []

        if not quake or not getattr(quake, "available", False):
            uncertainties.append("No regional seismic monitoring data available.")
            return 0.0, factors, uncertainties

        events_count = getattr(quake, "events_found_count", 0) or 0
        if events_count == 0:
            return 0.0, factors, uncertainties

        mag = getattr(quake, "nearest_magnitude", 0.0) or 0.0
        dist_km = getattr(quake, "distance_km", 999.0) or 999.0
        event_id = getattr(quake, "nearest_event_id", "SEISMIC_EVENT")

        points = 0.0
        if mag >= 5.0 and dist_km <= 50.0:
            points = 10.0
            reason = f"Major local earthquake (M{mag:.1f} at {dist_km:.1f} km <= 50 km)"
        elif mag >= 4.0 and dist_km <= 50.0:
            points = 7.0
            reason = f"Moderate local earthquake (M{mag:.1f} at {dist_km:.1f} km <= 50 km)"
        elif mag >= 4.0 and dist_km <= 150.0:
            points = 4.0
            reason = f"Regional earthquake (M{mag:.1f} at {dist_km:.1f} km <= 150 km)"
        elif mag >= 3.0 and dist_km <= 50.0:
            points = 3.0
            reason = f"Minor local earthquake (M{mag:.1f} at {dist_km:.1f} km <= 50 km)"
        else:
            points = 1.0
            reason = f"Distant or minor seismic event detected (M{mag:.1f} at {dist_km:.1f} km)"

        points = min(points, self.config.max_earthquake_points)

        factors.append(
            ContributingFactor(
                factor=FactorType.EARTHQUAKE.value,
                contribution=round(points, 2),
                evidence_id=str(event_id),
                reason=reason,
            )
        )
        return points, factors, uncertainties

    def _evaluate_fire(
        self, fire: Any
    ) -> tuple[float, List[ContributingFactor]]:
        factors: List[ContributingFactor] = []
        if not fire or not getattr(fire, "available", False):
            return 0.0, factors

        count = getattr(fire, "fire_count", 0) or 0
        max_frp = getattr(fire, "max_frp_mw", 0.0) or 0.0

        if count == 0:
            return 0.0, factors

        points = 0.0
        if count >= 5 or max_frp >= 50.0:
            points = 10.0
            reason = f"Elevated thermal anomalies detected ({count} fires, max FRP: {max_frp:.1f} MW)"
        elif count >= 2 or max_frp >= 20.0:
            points = 6.0
            reason = f"Moderate thermal anomalies detected ({count} fires, max FRP: {max_frp:.1f} MW)"
        else:
            points = 3.0
            reason = f"Isolated thermal anomaly detected (1 fire, max FRP: {max_frp:.1f} MW)"

        points = min(points, self.config.max_fire_points)
        factors.append(
            ContributingFactor(
                factor=FactorType.FIRE.value,
                contribution=round(points, 2),
                evidence_id="NASA_FIRMS",
                reason=reason,
            )
        )
        return points, factors

    def _evaluate_terrain(
        self, dem: Any
    ) -> tuple[float, List[ContributingFactor]]:
        factors: List[ContributingFactor] = []
        if not dem or not getattr(dem, "available", False):
            return 0.0, factors

        slope = getattr(dem, "slope_degrees", 0.0) or 0.0
        elev = getattr(dem, "elevation_m", 0.0) or 0.0

        points = 0.0
        if slope >= 25.0:
            points = 5.0
            reason = f"Steep terrain slope ({slope:.1f} deg >= 25 deg, elev {elev:.0f} m) predisposed to surface movement"
        elif slope >= 15.0:
            points = 2.0
            reason = f"Moderate terrain slope ({slope:.1f} deg >= 15 deg, elev {elev:.0f} m)"
        else:
            return 0.0, factors

        points = min(points, self.config.max_terrain_points)
        factors.append(
            ContributingFactor(
                factor=FactorType.TERRAIN_SLOPE.value,
                contribution=round(points, 2),
                evidence_id="COPERNICUS_DEM_GLO30",
                reason=reason,
            )
        )
        return points, factors

    def _evaluate_cross_sensor_uncertainties(self, norm_ev: MultiSensorEvidence) -> List[str]:
        uncertainties = []
        s1 = norm_ev.sentinel1
        s2 = norm_ev.sentinel2

        # SAR available but Optical missing
        if s1.available and not s2.available:
            uncertainties.append("Single-sensor SAR observation lacks optical multispectral corroboration.")
        # Optical available but SAR missing
        elif s2.available and not s1.available:
            uncertainties.append("Single-sensor optical observation lacks all-weather radar penetration.")

        # Temporal distance gap between primary sensors
        if s1.available and s2.available:
            if s1.temporal_alignment and s2.temporal_alignment:
                t1_dist = s1.temporal_alignment.temporal_distance_hours or 0.0
                t2_dist = s2.temporal_alignment.temporal_distance_hours or 0.0
                gap = abs(t1_dist - t2_dist)
                if gap > 72.0:
                    uncertainties.append(f"Temporal gap between SAR and optical acquisitions ({gap:.1f} hrs) exceeds 72h window.")

        return uncertainties

    def _classify_risk_level(self, score: float) -> RiskLevel:
        if score <= self.config.low_max_score:
            return RiskLevel.LOW
        elif score <= self.config.moderate_max_score:
            return RiskLevel.MODERATE
        elif score <= self.config.high_max_score:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL

    def _assign_monitoring_priority(self, risk_level: RiskLevel) -> MonitoringPriority:
        mapping = {
            RiskLevel.LOW: MonitoringPriority.ROUTINE,
            RiskLevel.MODERATE: MonitoringPriority.ELEVATED,
            RiskLevel.HIGH: MonitoringPriority.HIGH,
            RiskLevel.CRITICAL: MonitoringPriority.URGENT,
        }
        return mapping[risk_level]

    def _determine_recommended_action(self, risk_level: RiskLevel) -> str:
        actions = {
            RiskLevel.LOW: "Continue routine monitoring. All observed satellite and environmental signals remain within nominal baseline variations.",
            RiskLevel.MODERATE: "Increase monitoring attention. Elevated surface backscatter or spectral variance detected; review next scheduled satellite pass.",
            RiskLevel.HIGH: "Prioritize analyst review and field verification. Multi-sensor or significant surface change signals detected across critical location AOI.",
            RiskLevel.CRITICAL: "Prioritize immediate analyst review and field verification. Coherent multi-sensor anomalies and significant environmental signals detected across critical infrastructure AOI.",
        }
        return actions[risk_level]

    def _calculate_evidence_strength(
        self, norm_ev: MultiSensorEvidence
    ) -> tuple[EvidenceStrength, float]:
        """
        Determines evidence robustness and sensor corroboration independently from the risk score.
        """
        active_sensor_count = 0
        aligned_sensor_count = 0

        # Check Sentinel-1
        if norm_ev.sentinel1.available:
            active_sensor_count += 1
            if norm_ev.sentinel1.temporal_alignment and norm_ev.sentinel1.temporal_alignment.status == "ALIGNED":
                aligned_sensor_count += 1

        # Check Sentinel-2
        if norm_ev.sentinel2.available and (norm_ev.sentinel2.cloud_cover or 0.0) <= self.config.cloud_rejection_threshold:
            active_sensor_count += 1
            if norm_ev.sentinel2.temporal_alignment and norm_ev.sentinel2.temporal_alignment.status == "ALIGNED":
                aligned_sensor_count += 1

        # Check Rainfall
        if norm_ev.rainfall.available and norm_ev.rainfall.total_granules_found > 0:
            active_sensor_count += 1
            if norm_ev.rainfall.temporal_alignment and norm_ev.rainfall.temporal_alignment.status == "ALIGNED":
                aligned_sensor_count += 1

        # Check Fire
        if norm_ev.fire.available:
            active_sensor_count += 1
            aligned_sensor_count += 1

        # Check Earthquake
        if norm_ev.earthquake.available and norm_ev.earthquake.events_found_count > 0:
            active_sensor_count += 1
            aligned_sensor_count += 1

        # Check Terrain
        if norm_ev.terrain.available:
            active_sensor_count += 1
            aligned_sensor_count += 1

        # Correlations presence
        correlations_count = len(norm_ev.correlations)

        # Baseline Confidence score [0.0, 1.0]
        # Maximum possible active channels = 6
        confidence = min(round((aligned_sensor_count * 0.15) + (active_sensor_count * 0.05) + (min(correlations_count, 3) * 0.1), 2), 1.0)
        confidence = max(confidence, 0.10)

        # Classification rule:
        # STRONG: Both S1 & S2 available and aligned, OR >= 3 aligned channels + correlations
        if (norm_ev.sentinel1.available and norm_ev.sentinel2.available and aligned_sensor_count >= 2) or (aligned_sensor_count >= 3 and correlations_count >= 1):
            return EvidenceStrength.STRONG, max(confidence, 0.75)
        elif active_sensor_count >= 2 or aligned_sensor_count >= 1:
            return EvidenceStrength.MODERATE, max(confidence, 0.45)
        else:
            return EvidenceStrength.WEAK, min(confidence, 0.40)

    def _generate_explanation(
        self,
        location_name: str,
        score: float,
        risk_level: RiskLevel,
        monitoring_priority: MonitoringPriority,
        evidence_strength: EvidenceStrength,
        contributing_factors: List[ContributingFactor],
        uncertainty_factors: List[str],
    ) -> str:
        parts = [
            f"Deterministic Risk Assessment for {location_name}:",
            f"Monitoring risk score is {score:.1f}/100, resulting in a {risk_level.value} monitoring risk level and {monitoring_priority.value} monitoring priority.",
            f"Evidence strength is classified as {evidence_strength.value}.",
        ]

        if contributing_factors:
            top_factors = sorted(contributing_factors, key=lambda f: f.contribution, reverse=True)
            factor_descs = [f"{f.factor} (+{f.contribution:.1f} pts: {f.reason})" for f in top_factors[:4]]
            parts.append(f"Primary contributing indicators: {'; '.join(factor_descs)}.")
        else:
            parts.append("No active anomalous indicators detected across the monitored evidence window.")

        if uncertainty_factors:
            parts.append(f"Recorded uncertainties ({len(uncertainty_factors)}): {'; '.join(uncertainty_factors[:3])}.")

        parts.append(
            "SCIENTIFIC NOTICE: This assessment represents an auditable monitoring prioritization metric based on physical "
            "backscatter, spectral indices, and environmental co-occurrence. It does not constitute a disaster prediction, structural damage declaration, or hazard probability."
        )

        return " ".join(parts)

    def _normalize_evidence(
        self,
        evidence: Union[MultiSensorEvidence, EvidenceSnapshot, Dict[str, Any]],
        location_name: Optional[str] = None,
    ) -> MultiSensorEvidence:
        """
        Guarantees that input is parsed into a clean MultiSensorEvidence object.
        """
        if isinstance(evidence, MultiSensorEvidence):
            return evidence

        if isinstance(evidence, EvidenceSnapshot):
            s1_data = json.loads(evidence.sentinel1_evidence) if isinstance(evidence.sentinel1_evidence, str) else evidence.sentinel1_evidence
            s2_data = json.loads(evidence.sentinel2_evidence) if isinstance(evidence.sentinel2_evidence, str) else evidence.sentinel2_evidence
            rain_data = json.loads(evidence.rainfall_evidence) if isinstance(evidence.rainfall_evidence, str) else evidence.rainfall_evidence
            fire_data = json.loads(evidence.fire_evidence) if isinstance(evidence.fire_evidence, str) else evidence.fire_evidence
            quake_data = json.loads(evidence.earthquake_evidence) if isinstance(evidence.earthquake_evidence, str) else evidence.earthquake_evidence
            dem_data = json.loads(evidence.terrain_evidence) if isinstance(evidence.terrain_evidence, str) else evidence.terrain_evidence
            corr_data = json.loads(evidence.correlations) if isinstance(evidence.correlations, str) else evidence.correlations
            prov_data = json.loads(evidence.provenance) if isinstance(evidence.provenance, str) else evidence.provenance
            meta_data = json.loads(evidence.processing_metadata) if isinstance(evidence.processing_metadata, str) else evidence.processing_metadata

            return MultiSensorEvidence(
                id=evidence.id,
                location_id=evidence.location_id,
                location_name=location_name or (evidence.location.name if getattr(evidence, "location", None) else evidence.location_id),
                evidence_window_start=evidence.evidence_window_start,
                evidence_window_end=evidence.evidence_window_end,
                reference_time=evidence.reference_time,
                sentinel1=s1_data,
                sentinel2=s2_data,
                rainfall=rain_data,
                fire=fire_data,
                earthquake=quake_data,
                terrain=dem_data,
                correlations=corr_data,
                summary_designations=meta_data.get("summary_designations", []),
                provenance=prov_data,
                processing_metadata=meta_data,
                created_at=evidence.created_at or datetime.now(timezone.utc),
            )

        if isinstance(evidence, dict):
            return MultiSensorEvidence.model_validate(evidence)

        raise ValueError(f"Unsupported evidence type: {type(evidence)}")
