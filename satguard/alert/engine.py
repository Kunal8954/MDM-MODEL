"""
satguard/alert/engine.py
Phase 6: Deterministic Alert Decision Engine for SATGUARD.

Consumes Phase 4 RiskAssessment and Phase 5 AnalystReport to formulate
auditable government monitoring alerts with lifecycle state transitions,
duplicate suppression, escalation/de-escalation, and human acknowledgement.
STRICT BOUNDARY:
- An alert is an operational decision-support directive for monitoring officials.
- NEVER issues evacuation orders, emergency declarations, or claims confirmed damage.
"""

import json
import hashlib
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from satguard.models.entities import (
    CriticalLocation,
    EvidenceSnapshot,
    RiskAssessment,
    AnalystReport as DBAnalystReport,
    Alert as DBAlert,
    AlertEvent as DBAlertEvent,
)
from satguard.alert.schema import (
    AlertLevel,
    AlertStatus,
    AlertPriority,
    AlertAuditEventType,
    AlertResult,
    AlertLifecycleRequest,
)
from satguard.alert.config import AlertEngineConfig, default_alert_config

logger = logging.getLogger("satguard.alert.engine")


class AlertDecisionEngine:
    """
    Deterministic Alert Decision Engine.
    Transforms multi-sensor risk assessments and analyst findings into
    traceable government surveillance alerts.
    """

    def __init__(self, config: Optional[AlertEngineConfig] = None):
        self.config = config or default_alert_config

    def compute_fingerprint(
        self,
        location_id: str,
        risk_assessment_id: str,
        alert_level: str,
        priority: str,
    ) -> str:
        """
        Generates a deterministic hash for deduplicating identical alert conditions.
        """
        raw = f"{location_id}:{risk_assessment_id}:{alert_level}:{priority}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def generate_alert_result(
        self,
        location: CriticalLocation,
        risk_assessment: RiskAssessment,
        evidence_snapshot: EvidenceSnapshot,
        analyst_report: Optional[DBAnalystReport] = None,
        existing_active_alert: Optional[DBAlert] = None,
    ) -> AlertResult:
        """
        Determines alert parameters, title, summary, references, and escalation status.
        """
        # 1. Authoritative Risk Assessment attributes (Phase 4 is strictly authoritative)
        risk_score = float(risk_assessment.score)
        risk_level_str = str(risk_assessment.risk_level).upper().replace("RISKLEVEL.", "")
        monitoring_priority_str = str(risk_assessment.monitoring_priority).upper().replace("MONITORINGPRIORITY.", "")
        evidence_strength_str = str(risk_assessment.evidence_strength).upper().replace("EVIDENCESTRENGTH.", "")

        # 2. Map to Alert Level & Priority
        alert_level_str = self.config.risk_to_alert_level_mapping.get(risk_level_str, "INFO")
        alert_level = AlertLevel(alert_level_str)

        priority_str = self.config.alert_to_priority_mapping.get(alert_level.value, "ROUTINE")
        priority = AlertPriority(priority_str)

        # 3. Check Duplicate Fingerprint
        fingerprint = self.compute_fingerprint(
            location_id=location.id,
            risk_assessment_id=risk_assessment.id,
            alert_level=alert_level.value,
            priority=priority.value,
        )

        now_utc = datetime.now(timezone.utc)
        ttl_hours = self.config.alert_ttl_hours.get(alert_level.value, 48.0)
        expires_at = now_utc + timedelta(hours=ttl_hours)

        # Check for exact duplicate active alert
        if existing_active_alert and existing_active_alert.fingerprint == fingerprint:
            return self._db_alert_to_result(existing_active_alert, location_name=location.name, is_duplicate=True)

        # 4. Check Escalation / De-escalation
        escalation_history: List[Dict[str, Any]] = []
        if existing_active_alert:
            old_rank = self.config.alert_level_severity_rank.get(existing_active_alert.alert_level, 1)
            new_rank = self.config.alert_level_severity_rank.get(alert_level.value, 1)

            if new_rank > old_rank:
                escalation_history.append({
                    "type": "ESCALATION",
                    "previous_level": existing_active_alert.alert_level,
                    "new_level": alert_level.value,
                    "previous_score": existing_active_alert.risk_assessment.score if existing_active_alert.risk_assessment else None,
                    "new_score": risk_score,
                    "timestamp": now_utc.isoformat(),
                    "reason": f"Operational escalation: Monitoring risk score increased to {risk_score:.2f}/100 ({risk_level_str}).",
                })
            elif new_rank < old_rank:
                escalation_history.append({
                    "type": "DE_ESCALATION",
                    "previous_level": existing_active_alert.alert_level,
                    "new_level": alert_level.value,
                    "previous_score": existing_active_alert.risk_assessment.score if existing_active_alert.risk_assessment else None,
                    "new_score": risk_score,
                    "timestamp": now_utc.isoformat(),
                    "reason": f"Operational de-escalation: Monitoring risk score stabilized at {risk_score:.2f}/100 ({risk_level_str}).",
                })

        # 5. Extract Evidence Traceability References
        evidence_references = self._build_evidence_references(
            evidence_snapshot=evidence_snapshot,
            risk_assessment=risk_assessment,
            analyst_report=analyst_report,
        )

        # 6. Uncertainties & Requirement 23 (Rainfall Semantics)
        uncertainties = self._build_uncertainties(evidence_snapshot, risk_assessment)

        # 7. Compose Title, Summary, Reason, and Recommended Action
        title = f"{alert_level.value} Monitoring Alert — {location.name}"

        # If validated Phase 5 report exists, incorporate its executive summary
        if analyst_report and analyst_report.validation_status == "VALIDATED":
            analyst_id = analyst_report.id
            summary = analyst_report.executive_summary
            action = risk_assessment.recommended_action
        else:
            analyst_id = None
            summary = (
                f"Multi-sensor surveillance of {location.name} indicates an authoritative monitoring risk score "
                f"of {risk_score:.2f}/100 ({risk_level_str} risk tier, {evidence_strength_str} evidence strength)."
            )
            action = risk_assessment.recommended_action

        reason = (
            f"Phase 4 deterministic assessment assigned {risk_level_str} monitoring priority "
            f"(Score: {risk_score:.2f}/100) based on coherent surface change indicators."
        )

        if risk_assessment.contributing_factors:
            contributing_factors = (
                json.loads(risk_assessment.contributing_factors)
                if isinstance(risk_assessment.contributing_factors, str)
                else risk_assessment.contributing_factors
            )
        else:
            contributing_factors = []

        alert_id = f"alert-{location.id}-{int(now_utc.timestamp() * 1000)}"

        source_engine_versions = {
            "alert_engine": self.config.alert_version,
            "risk_engine": getattr(risk_assessment, "engine_version", None) or "risk_engine_v1",
            "analyst_engine": (getattr(analyst_report, "prompt_version", None) if analyst_report else None) or "none",
        }

        return AlertResult(
            alert_id=alert_id,
            location_id=location.id,
            location_name=location.name,
            risk_assessment_id=risk_assessment.id,
            analyst_report_id=analyst_id,
            alert_level=alert_level,
            priority=priority,
            status=AlertStatus.ACTIVE,
            title=title,
            summary=summary,
            reason=reason,
            evidence_references=evidence_references,
            contributing_factors=contributing_factors,
            uncertainty=uncertainties,
            recommended_action=action,
            fingerprint=fingerprint,
            escalation_history=escalation_history,
            acknowledgement_details=None,
            resolution_details=None,
            created_at=now_utc,
            acknowledged_at=None,
            resolved_at=None,
            expires_at=expires_at,
            alert_version=self.config.alert_version,
            source_engine_versions=source_engine_versions,
            is_duplicate=False,
        )

    def generate_and_persist(
        self,
        db: Session,
        location_id: str,
        risk_assessment_id: Optional[str] = None,
        analyst_report_id: Optional[str] = None,
    ) -> AlertResult:
        """
        Coordinates full alert decision pipeline:
        1. Loads location, risk assessment, evidence snapshot, and optional analyst report.
        2. Checks duplicate suppression.
        3. Handles escalation/de-escalation of existing active alerts.
        4. Persists the alert and creates auditable lifecycle events in alert_events.
        """
        # 1. Load CriticalLocation
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
        if not loc:
            raise ValueError(f"Critical location '{location_id}' not found.")

        # 2. Load RiskAssessment
        if risk_assessment_id:
            risk_rec = db.query(RiskAssessment).filter(
                RiskAssessment.id == risk_assessment_id,
                RiskAssessment.location_id == location_id,
            ).first()
            if not risk_rec:
                raise ValueError(f"Risk assessment '{risk_assessment_id}' not found.")
        else:
            risk_rec = db.query(RiskAssessment).filter(
                RiskAssessment.location_id == location_id
            ).order_by(RiskAssessment.created_at.desc()).first()

        if not risk_rec:
            raise ValueError(f"No RiskAssessment available for location '{location_id}'. Run Phase 4 first.")

        risk_score = float(risk_rec.score)

        # 3. Load EvidenceSnapshot
        snap = db.query(EvidenceSnapshot).filter(
            EvidenceSnapshot.id == risk_rec.evidence_snapshot_id
        ).first()
        if not snap:
            raise ValueError(f"Evidence snapshot '{risk_rec.evidence_snapshot_id}' not found.")

        # 4. Load optional AnalystReport
        if analyst_report_id:
            analyst_rec = db.query(DBAnalystReport).filter(
                DBAnalystReport.id == analyst_report_id,
                DBAnalystReport.location_id == location_id,
            ).first()
        else:
            analyst_rec = db.query(DBAnalystReport).filter(
                DBAnalystReport.location_id == location_id,
                DBAnalystReport.risk_assessment_id == risk_rec.id,
            ).order_by(DBAnalystReport.created_at.desc()).first()

        # 5. Check for currently ACTIVE alert for this location
        existing_active = db.query(DBAlert).filter(
            DBAlert.location_id == location_id,
            DBAlert.status == AlertStatus.ACTIVE.value,
        ).order_by(DBAlert.created_at.desc()).first()

        # Check if existing active alert is expired
        now_utc = datetime.now(timezone.utc)
        if existing_active and existing_active.expires_at:
            exp_at = existing_active.expires_at.replace(tzinfo=timezone.utc) if existing_active.expires_at.tzinfo is None else existing_active.expires_at
            if exp_at < now_utc:
                existing_active.status = AlertStatus.EXPIRED.value
                self._record_audit_event(
                    db=db,
                    alert_id=existing_active.id,
                    event_type=AlertAuditEventType.ALERT_EXPIRED,
                    previous_status=AlertStatus.ACTIVE.value,
                    new_status=AlertStatus.EXPIRED.value,
                    reason="Alert exceeded configured TTL without operational re-escalation.",
                )
                db.commit()
                existing_active = None

        # 6. Generate Alert Result
        alert_res = self.generate_alert_result(
            location=loc,
            risk_assessment=risk_rec,
            evidence_snapshot=snap,
            analyst_report=analyst_rec,
            existing_active_alert=existing_active,
        )

        # If duplicate, return existing active alert directly
        if alert_res.is_duplicate:
            logger.info(f"Active alert duplicate suppressed for {location_id}: {alert_res.alert_id}")
            return alert_res

        # If replacing/escalating an existing active alert, supersede it
        if existing_active and existing_active.id != alert_res.alert_id:
            old_status = existing_active.status
            existing_active.status = AlertStatus.SUPERSEDED.value
            event_type = AlertAuditEventType.ALERT_ESCALATED if alert_res.escalation_history else AlertAuditEventType.ALERT_SUPERSEDED

            self._record_audit_event(
                db=db,
                alert_id=existing_active.id,
                event_type=event_type,
                previous_status=old_status,
                new_status=AlertStatus.SUPERSEDED.value,
                previous_level=existing_active.alert_level,
                new_level=alert_res.alert_level.value,
                reason=f"Superseded by new alert {alert_res.alert_id} ({alert_res.alert_level.value}).",
            )

        # 7. Persist New Alert to Database
        db_alert = DBAlert(
            id=alert_res.alert_id,
            location_id=alert_res.location_id,
            risk_assessment_id=alert_res.risk_assessment_id,
            analyst_report_id=alert_res.analyst_report_id,
            alert_level=alert_res.alert_level.value,
            priority=alert_res.priority.value,
            status=alert_res.status.value,
            title=alert_res.title,
            summary=alert_res.summary,
            reason=alert_res.reason,
            evidence_references=json.dumps(alert_res.evidence_references),
            contributing_factors=json.dumps(alert_res.contributing_factors),
            uncertainty=json.dumps(alert_res.uncertainty),
            recommended_action=alert_res.recommended_action,
            fingerprint=alert_res.fingerprint,
            escalation_history=json.dumps(alert_res.escalation_history),
            created_at=alert_res.created_at,
            expires_at=alert_res.expires_at,
            alert_version=alert_res.alert_version,
            source_engine_versions=json.dumps(alert_res.source_engine_versions),
            disclaimer=alert_res.disclaimer,
        )
        db.merge(db_alert)

        # 8. Record ALERT_CREATED audit event
        self._record_audit_event(
            db=db,
            alert_id=alert_res.alert_id,
            event_type=AlertAuditEventType.ALERT_CREATED,
            previous_status=None,
            new_status=AlertStatus.ACTIVE.value,
            new_level=alert_res.alert_level.value,
            reason=f"Operational alert generated from Phase 4 RiskAssessment ({risk_rec.risk_level}, Score {risk_score:.2f}).",
            metadata={"fingerprint": alert_res.fingerprint, "authoritative_score": risk_score},
        )
        db.commit()

        logger.info(
            f"Successfully generated and persisted Alert {alert_res.alert_id} for {location_id}: "
            f"Level={alert_res.alert_level.value}, Priority={alert_res.priority.value}."
        )
        return alert_res

    def acknowledge_alert(
        self,
        db: Session,
        alert_id: str,
        actor: str = "operator",
        note: Optional[str] = None,
    ) -> AlertResult:
        """
        Transitions alert state: ACTIVE -> ACKNOWLEDGED.
        """
        alert = db.query(DBAlert).filter(DBAlert.id == alert_id).first()
        if not alert:
            raise ValueError(f"Alert '{alert_id}' not found.")

        old_status = alert.status
        now_utc = datetime.now(timezone.utc)
        alert.status = AlertStatus.ACKNOWLEDGED.value
        alert.acknowledged_at = now_utc
        ack_data = {"actor": actor, "note": note, "timestamp": now_utc.isoformat()}
        alert.acknowledgement_details = json.dumps(ack_data)

        self._record_audit_event(
            db=db,
            alert_id=alert.id,
            event_type=AlertAuditEventType.ALERT_ACKNOWLEDGED,
            previous_status=old_status,
            new_status=AlertStatus.ACKNOWLEDGED.value,
            actor=actor,
            reason=note or "Alert acknowledged by operator.",
            metadata=ack_data,
        )
        db.commit()
        return self._db_alert_to_result(alert)

    def start_review(
        self,
        db: Session,
        alert_id: str,
        actor: str = "operator",
        note: Optional[str] = None,
    ) -> AlertResult:
        """
        Transitions alert state: ACKNOWLEDGED / ACTIVE -> IN_REVIEW.
        """
        alert = db.query(DBAlert).filter(DBAlert.id == alert_id).first()
        if not alert:
            raise ValueError(f"Alert '{alert_id}' not found.")

        old_status = alert.status
        alert.status = AlertStatus.IN_REVIEW.value

        self._record_audit_event(
            db=db,
            alert_id=alert.id,
            event_type=AlertAuditEventType.ALERT_REVIEW_STARTED,
            previous_status=old_status,
            new_status=AlertStatus.IN_REVIEW.value,
            actor=actor,
            reason=note or "Analyst investigation initiated.",
        )
        db.commit()
        return self._db_alert_to_result(alert)

    def resolve_alert(
        self,
        db: Session,
        alert_id: str,
        actor: str = "operator",
        note: Optional[str] = None,
    ) -> AlertResult:
        """
        Transitions alert state to RESOLVED.
        """
        alert = db.query(DBAlert).filter(DBAlert.id == alert_id).first()
        if not alert:
            raise ValueError(f"Alert '{alert_id}' not found.")

        old_status = alert.status
        now_utc = datetime.now(timezone.utc)
        alert.status = AlertStatus.RESOLVED.value
        alert.resolved_at = now_utc
        res_data = {"actor": actor, "note": note, "timestamp": now_utc.isoformat()}
        alert.resolution_details = json.dumps(res_data)

        self._record_audit_event(
            db=db,
            alert_id=alert.id,
            event_type=AlertAuditEventType.ALERT_RESOLVED,
            previous_status=old_status,
            new_status=AlertStatus.RESOLVED.value,
            actor=actor,
            reason=note or "Operational monitoring alert marked as resolved by analyst.",
            metadata=res_data,
        )
        db.commit()
        return self._db_alert_to_result(alert)

    # ------------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------------

    def _build_evidence_references(
        self,
        evidence_snapshot: EvidenceSnapshot,
        risk_assessment: RiskAssessment,
        analyst_report: Optional[DBAnalystReport] = None,
    ) -> Dict[str, Any]:
        s1 = json.loads(evidence_snapshot.sentinel1_evidence) if isinstance(evidence_snapshot.sentinel1_evidence, str) else evidence_snapshot.sentinel1_evidence
        s2 = json.loads(evidence_snapshot.sentinel2_evidence) if isinstance(evidence_snapshot.sentinel2_evidence, str) else evidence_snapshot.sentinel2_evidence
        rain = json.loads(evidence_snapshot.rainfall_evidence) if isinstance(evidence_snapshot.rainfall_evidence, str) else evidence_snapshot.rainfall_evidence
        quake = json.loads(evidence_snapshot.earthquake_evidence) if isinstance(evidence_snapshot.earthquake_evidence, str) else evidence_snapshot.earthquake_evidence
        fire = json.loads(evidence_snapshot.fire_evidence) if isinstance(evidence_snapshot.fire_evidence, str) else evidence_snapshot.fire_evidence
        dem = json.loads(evidence_snapshot.terrain_evidence) if isinstance(evidence_snapshot.terrain_evidence, str) else evidence_snapshot.terrain_evidence

        return {
            "evidence_snapshot_id": evidence_snapshot.id,
            "risk_assessment_id": risk_assessment.id,
            "analyst_report_id": analyst_report.id if analyst_report else None,
            "sentinel1": {
                "available": s1.get("available", False),
                "t1_observation_id": s1.get("t1_observation_id"),
                "t2_observation_id": s1.get("t2_observation_id"),
                "changed_pct": s1.get("changed_percentage"),
                "joint_changed_pct": s1.get("joint_changed_percent"),
                "regions_count": s1.get("significant_region_count", 0),
            },
            "sentinel2": {
                "available": s2.get("available", False),
                "observation_id": s2.get("observation_id"),
                "water_change_pct": s2.get("water_change_percentage"),
                "cloud_cover": s2.get("cloud_cover"),
            },
            "rainfall": {
                "available": rain.get("available", False),
                "source": rain.get("source", "NASA GPM IMERG"),
                "granules_found": rain.get("total_granules_found", 0),
                "status": "UNAVAILABLE" if rain.get("total_granules_found", 0) == 0 else "OBSERVED",
            },
            "earthquake": {
                "available": quake.get("available", False),
                "events_count": quake.get("events_found_count", 0),
                "nearest_event_id": quake.get("nearest_event_id"),
                "nearest_magnitude": quake.get("nearest_magnitude"),
                "distance_km": quake.get("distance_km"),
            },
            "fire": {
                "available": fire.get("available", False),
                "fire_count": fire.get("fire_count", 0),
            },
            "terrain": {
                "available": dem.get("available", False),
                "elevation_m": dem.get("elevation_m"),
                "slope_deg": dem.get("slope_degrees"),
            },
        }

    def _build_uncertainties(
        self, evidence_snapshot: EvidenceSnapshot, risk_assessment: RiskAssessment
    ) -> List[str]:
        """
        Consolidates uncertainties and strictly enforces Requirement 23 rainfall semantics:
        No Data != 0.0 mm rainfall.
        """
        uncertainties: List[str] = []

        # From risk assessment
        if risk_assessment.uncertainty_factors:
            raw_unc = json.loads(risk_assessment.uncertainty_factors) if isinstance(risk_assessment.uncertainty_factors, str) else risk_assessment.uncertainty_factors
            for u in raw_unc:
                if u not in uncertainties:
                    uncertainties.append(u)

        # Check rainfall data specifically (Requirement 23)
        rain = json.loads(evidence_snapshot.rainfall_evidence) if isinstance(evidence_snapshot.rainfall_evidence, str) else evidence_snapshot.rainfall_evidence
        granules = rain.get("total_granules_found", 0)
        if granules == 0 or not rain.get("available", False):
            rain_msg = "Precipitation data unavailable in observation window; rainfall amount cannot be confirmed."
            if rain_msg not in uncertainties:
                uncertainties.append(rain_msg)

        return uncertainties

    def _record_audit_event(
        self,
        db: Session,
        alert_id: str,
        event_type: AlertAuditEventType,
        new_status: str,
        previous_status: Optional[str] = None,
        previous_level: Optional[str] = None,
        new_level: Optional[str] = None,
        actor: str = "system",
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DBAlertEvent:
        event_id = f"event-{alert_id}-{int(datetime.now(timezone.utc).timestamp() * 1000)}-{event_type.value}"
        db_event = DBAlertEvent(
            id=event_id,
            alert_id=alert_id,
            event_type=event_type.value,
            previous_status=previous_status,
            new_status=new_status,
            previous_level=previous_level,
            new_level=new_level,
            actor=actor,
            reason=reason,
            event_metadata=json.dumps(metadata or {}),
            created_at=datetime.now(timezone.utc),
        )
        db.merge(db_event)
        return db_event

    def _db_alert_to_result(
        self, db_alert: DBAlert, location_name: Optional[str] = None, is_duplicate: bool = False
    ) -> AlertResult:
        ev_refs = json.loads(db_alert.evidence_references) if isinstance(db_alert.evidence_references, str) else db_alert.evidence_references
        factors = json.loads(db_alert.contributing_factors) if isinstance(db_alert.contributing_factors, str) else db_alert.contributing_factors
        unc = json.loads(db_alert.uncertainty) if isinstance(db_alert.uncertainty, str) else db_alert.uncertainty
        esc = json.loads(db_alert.escalation_history) if isinstance(db_alert.escalation_history, str) else db_alert.escalation_history
        ack = json.loads(db_alert.acknowledgement_details) if (db_alert.acknowledgement_details and isinstance(db_alert.acknowledgement_details, str)) else db_alert.acknowledgement_details
        res = json.loads(db_alert.resolution_details) if (db_alert.resolution_details and isinstance(db_alert.resolution_details, str)) else db_alert.resolution_details
        src_ver = json.loads(db_alert.source_engine_versions) if isinstance(db_alert.source_engine_versions, str) else db_alert.source_engine_versions

        return AlertResult(
            alert_id=db_alert.id,
            location_id=db_alert.location_id,
            location_name=location_name or (db_alert.location.name if db_alert.location else db_alert.location_id),
            risk_assessment_id=db_alert.risk_assessment_id,
            analyst_report_id=db_alert.analyst_report_id,
            alert_level=AlertLevel(db_alert.alert_level),
            priority=AlertPriority(db_alert.priority),
            status=AlertStatus(db_alert.status),
            title=db_alert.title,
            summary=db_alert.summary,
            reason=db_alert.reason,
            evidence_references=ev_refs,
            contributing_factors=factors,
            uncertainty=unc,
            recommended_action=db_alert.recommended_action,
            fingerprint=db_alert.fingerprint,
            escalation_history=esc,
            acknowledgement_details=ack,
            resolution_details=res,
            created_at=db_alert.created_at,
            acknowledged_at=db_alert.acknowledged_at,
            resolved_at=db_alert.resolved_at,
            expires_at=db_alert.expires_at,
            alert_version=db_alert.alert_version,
            source_engine_versions=src_ver,
            is_duplicate=is_duplicate,
            disclaimer=db_alert.disclaimer,
        )
