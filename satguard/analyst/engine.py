"""
satguard/analyst/engine.py
Core Engine for Phase 5 Groq Evidence Analyst.
Coordinates evidence collation, LLM prompt construction, Groq inference,
hallucination validation, risk immutability enforcement, and report persistence.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from satguard.config import settings
from satguard.models.entities import CriticalLocation, EvidenceSnapshot, RiskAssessment
from satguard.fusion.schema import MultiSensorEvidence
from satguard.risk.schema import RiskAssessmentResult
from satguard.analyst.schema import (
    AnalystInput,
    AnalystReport,
    ObservedChangeItem,
    CrossSensorFindingItem,
)
from satguard.analyst.prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, PROMPT_VERSION

logger = logging.getLogger("satguard.analyst.engine")


class GroqConfigurationError(Exception):
    """Raised when Groq API key or client is not configured."""
    pass


class GroqInferenceError(Exception):
    """Raised when Groq API fails or times out."""
    pass


class ReportValidationError(Exception):
    """Raised when model output fails structured validation."""
    pass


class EvidenceAnalystEngine:
    """
    Evidence Analyst Engine powered by Groq LPU inference.
    Synthesizes multi-sensor evidence and deterministic risk scoring into structured briefings.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[Any] = None,
        prompt_version: str = PROMPT_VERSION,
    ):
        if api_key is not None:
            self.api_key = api_key
        else:
            self.api_key = settings.GROQ_API_KEY

        self.model = model or getattr(settings, "GROQ_PRIMARY_MODEL", "llama-3.3-70b-versatile")
        self.prompt_version = prompt_version

        if client is not None:
            self.client = client
        elif self.api_key and self.api_key != "gsk_your_groq_api_key_here":
            try:
                from groq import Groq
                self.client = Groq(api_key=self.api_key, timeout=30.0)
            except Exception as e:
                logger.warning(f"Failed to initialize Groq client: {e}")
                self.client = None
        else:
            self.client = None

    def is_configured(self) -> bool:
        return bool(self.client is not None and self.api_key and self.api_key != "gsk_your_groq_api_key_here")

    def build_analyst_input(
        self,
        location: CriticalLocation,
        evidence: Union[MultiSensorEvidence, EvidenceSnapshot],
        risk_assessment: Union[RiskAssessmentResult, RiskAssessment],
    ) -> AnalystInput:
        """
        Builds a strictly typed, auditable AnalystInput payload.
        """
        # Normalize location
        loc_dict = {
            "id": location.id,
            "name": location.name,
            "location_type": location.location_type,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "radius_m": location.radius_m,
            "risk_category": getattr(location, "risk_category", "general"),
            "priority": getattr(location, "priority", "routine"),
        }

        # Normalize evidence
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

            norm_evidence = MultiSensorEvidence(
                id=evidence.id,
                location_id=evidence.location_id,
                location_name=location.name,
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
                created_at=evidence.created_at,
            )
        else:
            norm_evidence = evidence

        # Normalize risk assessment
        if isinstance(risk_assessment, RiskAssessment):
            risk_dict = risk_assessment.to_dict()
        elif isinstance(risk_assessment, RiskAssessmentResult):
            risk_dict = json.loads(risk_assessment.model_dump_json())
        else:
            risk_dict = dict(risk_assessment)

        return AnalystInput(
            location=loc_dict,
            evidence=norm_evidence,
            risk_assessment=risk_dict,
        )

    def generate_analysis(self, analyst_input: AnalystInput) -> AnalystReport:
        """
        Executes zero-shot structured intelligence report synthesis via Groq LPU.
        Enforces strict hallucination validation and risk immutability.
        """
        if not self.is_configured():
            raise GroqConfigurationError(
                "GROQ_API_KEY is not configured or client is unavailable. "
                "Configure a valid key in .env or settings."
            )

        auth_risk = analyst_input.risk_assessment
        authoritative_score = float(auth_risk.get("score", 0.0))
        
        raw_level = auth_risk.get("risk_level", "LOW")
        authoritative_level = getattr(raw_level, "value", str(raw_level)).replace("RiskLevel.", "").upper()

        raw_priority = auth_risk.get("monitoring_priority", "ROUTINE")
        authoritative_priority = getattr(raw_priority, "value", str(raw_priority)).replace("MonitoringPriority.", "").upper()

        raw_strength = auth_risk.get("evidence_strength", "WEAK")
        authoritative_strength = getattr(raw_strength, "value", str(raw_strength)).replace("EvidenceStrength.", "").upper()

        risk_assessment_id = str(auth_risk.get("id", "UNKNOWN_ASSESSMENT"))
        location_id = str(analyst_input.location.get("id", "UNKNOWN_LOCATION"))

        # Build prompt
        input_json_str = analyst_input.model_dump_json(indent=2)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            analyst_input_json=input_json_str,
            authoritative_score=authoritative_score,
            authoritative_level=authoritative_level,
            authoritative_priority=authoritative_priority,
            authoritative_strength=authoritative_strength,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2500,
            )
            raw_content = response.choices[0].message.content
        except Exception as e:
            # Mask API keys if present in exception
            safe_err = str(e)
            if self.api_key and self.api_key in safe_err:
                safe_err = safe_err.replace(self.api_key, "[REDACTED_API_KEY]")
            logger.error(f"Groq API completion error: {safe_err}")
            raise GroqInferenceError(f"Groq API inference failed: {safe_err}")

        # Parse JSON
        try:
            data = json.loads(raw_content)
        except Exception as e:
            raise ReportValidationError(f"Groq model returned malformed non-JSON output: {e}")

        # Validate and build AnalystReport
        report = self._validate_and_build_report(
            data=data,
            location_id=location_id,
            risk_assessment_id=risk_assessment_id,
            authoritative_score=authoritative_score,
            authoritative_level=authoritative_level,
            authoritative_priority=authoritative_priority,
            authoritative_strength=authoritative_strength,
            analyst_input=analyst_input,
        )
        return report

    def _validate_and_build_report(
        self,
        data: Dict[str, Any],
        location_id: str,
        risk_assessment_id: str,
        authoritative_score: float,
        authoritative_level: str,
        authoritative_priority: str,
        authoritative_strength: str,
        analyst_input: AnalystInput,
    ) -> AnalystReport:
        """
        Validates model output against strict schema and enforces risk immutability.
        """
        validation_errors: List[str] = []
        validation_status = "VALIDATED"

        # Check required string fields
        required_fields = ["executive_summary", "monitoring_assessment"]
        for field in required_fields:
            if not data.get(field):
                validation_errors.append(f"Missing mandatory section '{field}'")
                validation_status = "VALIDATION_FAILED"

        # Check risk immutability: LLM must not modify or hallucinate risk values
        llm_score = data.get("authoritative_risk_score")
        if llm_score is not None:
            try:
                llm_score_float = float(llm_score)
                if abs(llm_score_float - authoritative_score) > 0.05:
                    validation_errors.append(
                        f"Risk score discrepancy detected: LLM returned {llm_score_float}, authoritative is {authoritative_score}."
                    )
                    validation_status = "VALIDATION_FAILED"
            except (ValueError, TypeError):
                validation_errors.append("Invalid non-numeric risk score returned by LLM.")
                validation_status = "VALIDATION_FAILED"

        llm_level = str(data.get("authoritative_risk_level", "")).upper()
        if llm_level and llm_level != authoritative_level.upper():
            validation_errors.append(
                f"Risk level discrepancy detected: LLM returned '{llm_level}', authoritative is '{authoritative_level}'."
            )
            validation_status = "VALIDATION_FAILED"

        # Parse observed changes
        observed_changes: List[ObservedChangeItem] = []
        raw_obs = data.get("observed_changes", [])
        if isinstance(raw_obs, list):
            for item in raw_obs:
                if isinstance(item, dict) and item.get("finding"):
                    observed_changes.append(
                        ObservedChangeItem(
                            category=str(item.get("category", "GENERAL")),
                            finding=str(item.get("finding", "")),
                            evidence_ids=item.get("evidence_ids", []) if isinstance(item.get("evidence_ids"), list) else [],
                            traceability_metric=item.get("traceability_metric"),
                        )
                    )

        # Parse cross-sensor findings
        cross_sensor_findings: List[CrossSensorFindingItem] = []
        raw_corr = data.get("cross_sensor_findings", [])
        if isinstance(raw_corr, list):
            for item in raw_corr:
                if isinstance(item, dict) and item.get("finding"):
                    try:
                        conf = float(item.get("confidence", 0.8))
                        conf = min(max(conf, 0.0), 1.0)
                    except (ValueError, TypeError):
                        conf = 0.8
                    cross_sensor_findings.append(
                        CrossSensorFindingItem(
                            correlation_type=str(item.get("correlation_type", "MULTI-SENSOR_CHANGE_SIGNAL")),
                            finding=str(item.get("finding", "")),
                            source_evidence_ids=item.get("source_evidence_ids", []) if isinstance(item.get("source_evidence_ids"), list) else [],
                            confidence=conf,
                            scientific_interpretation=str(item.get("scientific_interpretation", "")),
                        )
                    )

        # Extract supporting evidence mapping
        supporting_evidence = {
            "sentinel1_available": analyst_input.evidence.sentinel1.available,
            "sentinel2_available": analyst_input.evidence.sentinel2.available,
            "rainfall_available": analyst_input.evidence.rainfall.available,
            "fire_available": analyst_input.evidence.fire.available,
            "earthquake_available": analyst_input.evidence.earthquake.available,
            "terrain_available": analyst_input.evidence.terrain.available,
            "correlations_identified": len(analyst_input.evidence.correlations),
        }

        # Parse lists
        uncertainty = [str(u) for u in data.get("uncertainty", []) if isinstance(u, (str, int, float))]
        recommended_verification = [str(r) for r in data.get("recommended_verification", []) if isinstance(r, (str, int, float))]
        data_gaps = [str(g) for g in data.get("data_gaps", []) if isinstance(g, (str, int, float))]

        report_id = f"analyst-rep-{location_id}-{int(datetime.now(timezone.utc).timestamp())}"
        now_utc = datetime.now(timezone.utc)

        return AnalystReport(
            report_id=report_id,
            location_id=location_id,
            risk_assessment_id=risk_assessment_id,
            authoritative_risk_score=authoritative_score,  # Enforce authoritative score
            authoritative_risk_level=authoritative_level,  # Enforce authoritative level
            authoritative_monitoring_priority=authoritative_priority,
            authoritative_evidence_strength=authoritative_strength,
            executive_summary=str(data.get("executive_summary", "Executive summary not provided.")),
            observed_changes=observed_changes,
            supporting_evidence=supporting_evidence,
            cross_sensor_findings=cross_sensor_findings,
            uncertainty=uncertainty,
            monitoring_assessment=str(data.get("monitoring_assessment", "")),
            recommended_verification=recommended_verification,
            data_gaps=data_gaps,
            validation_status=validation_status,
            validation_errors=validation_errors,
            model=self.model,
            prompt_version=self.prompt_version,
            generated_at=now_utc,
        )

    def generate_and_persist(
        self,
        db: Session,
        location_id: str,
        snapshot_id: Optional[str] = None,
        assessment_id: Optional[str] = None,
    ) -> AnalystReport:
        """
        Coordinates full pipeline: loads evidence + risk assessment, runs Groq analyst,
        validates output, and persists the AnalystReport record to the database.
        """
        from satguard.models.entities import AnalystReport as DBAnalystReport
        from satguard.fusion.engine import EvidenceFusionEngine
        from satguard.risk.engine import RiskAssessmentEngine

        # 1. Load CriticalLocation
        loc = db.query(CriticalLocation).filter(CriticalLocation.id == location_id).first()
        if not loc:
            raise ValueError(f"Critical location '{location_id}' not found.")

        # 2. Load or compute EvidenceSnapshot
        if snapshot_id:
            snap = db.query(EvidenceSnapshot).filter(
                EvidenceSnapshot.id == snapshot_id,
                EvidenceSnapshot.location_id == location_id,
            ).first()
            if not snap:
                raise ValueError(f"Evidence snapshot '{snapshot_id}' not found for location '{location_id}'.")
        else:
            snap = db.query(EvidenceSnapshot).filter(
                EvidenceSnapshot.location_id == location_id
            ).order_by(EvidenceSnapshot.created_at.desc()).first()
            if not snap:
                logger.info(f"No existing EvidenceSnapshot for {location_id}; running fusion...")
                fusion_engine = EvidenceFusionEngine()
                snap_obj = fusion_engine.fuse_location_evidence(db=db, location_id=location_id)
                snap = db.query(EvidenceSnapshot).filter(EvidenceSnapshot.id == snap_obj.id).first()

        if not snap:
            raise ValueError(f"Failed to load or generate multi-sensor evidence for '{location_id}'.")

        # 3. Load or compute RiskAssessment
        if assessment_id:
            assessment = db.query(RiskAssessment).filter(
                RiskAssessment.id == assessment_id,
                RiskAssessment.location_id == location_id,
            ).first()
            if not assessment:
                raise ValueError(f"Risk assessment '{assessment_id}' not found for location '{location_id}'.")
        else:
            assessment = db.query(RiskAssessment).filter(
                RiskAssessment.location_id == location_id,
                RiskAssessment.evidence_snapshot_id == snap.id,
            ).order_by(RiskAssessment.created_at.desc()).first()

            if not assessment:
                assessment = db.query(RiskAssessment).filter(
                    RiskAssessment.location_id == location_id
                ).order_by(RiskAssessment.created_at.desc()).first()

            if not assessment:
                logger.info(f"No existing RiskAssessment for {location_id}; computing risk assessment...")
                risk_engine = RiskAssessmentEngine()
                assess_result = risk_engine.assess_and_persist(db=db, evidence=snap, location_name=loc.name)
                assessment = db.query(RiskAssessment).filter(RiskAssessment.id == assess_result.id).first()

        if not assessment:
            raise ValueError(f"Failed to load or generate risk assessment for '{location_id}'.")

        # 4. Collate AnalystInput and call Groq
        analyst_input = self.build_analyst_input(location=loc, evidence=snap, risk_assessment=assessment)
        report = self.generate_analysis(analyst_input)

        # 5. Persist to database
        db_report = DBAnalystReport(
            id=report.report_id,
            location_id=report.location_id,
            risk_assessment_id=report.risk_assessment_id,
            executive_summary=report.executive_summary,
            report_data=report.model_dump_json(),
            model=report.model,
            prompt_version=report.prompt_version,
            validation_status=report.validation_status,
            validation_errors=json.dumps(report.validation_errors),
            created_at=report.generated_at,
        )
        db.merge(db_report)
        db.commit()

        logger.info(
            f"Successfully generated and persisted AnalystReport {report.report_id} for {location_id}: "
            f"status={report.validation_status} (Authoritative Risk: {report.authoritative_risk_score}/100, {report.authoritative_risk_level})."
        )
        return report
