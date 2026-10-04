"""
satguard/models/entities.py
SQLAlchemy Declarative Models for SATGUARD Platform.
Supports PostgreSQL + PostGIS with graceful local SQLite compatibility.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class CriticalLocation(Base):
    __tablename__ = "critical_locations"

    id = Column(String(100), primary_key=True)
    name = Column(String(255), nullable=False)
    location_type = Column(String(100), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius_m = Column(Integer, nullable=False)
    geometry = Column(Text, nullable=False)  # GeoJSON / WKT representation
    priority = Column(String(50), nullable=False, default="routine")
    risk_category = Column(String(100), nullable=False)
    monitoring_frequency = Column(String(50), nullable=False, default="continuous_pass")
    monitoring_enabled = Column(Boolean, nullable=False, default=True)
    monitoring_interval_hours = Column(Float, nullable=False, default=24.0)
    last_successful_run = Column(DateTime(timezone=True), nullable=True)
    last_attempted_run = Column(DateTime(timezone=True), nullable=True)
    next_scheduled_run = Column(DateTime(timezone=True), nullable=True)
    last_observation_check = Column(DateTime(timezone=True), nullable=True)
    monitoring_status = Column(String(50), nullable=False, default="ACTIVE")
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    observations = relationship("SatelliteObservation", back_populates="location", cascade="all, delete-orphan")
    change_detections = relationship("ChangeDetection", back_populates="location", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "location_type": self.location_type,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "radius_m": self.radius_m,
            "geometry": self.geometry,
            "priority": self.priority,
            "risk_category": self.risk_category,
            "monitoring_frequency": self.monitoring_frequency,
            "monitoring_enabled": self.monitoring_enabled,
            "monitoring_interval_hours": self.monitoring_interval_hours,
            "last_successful_run": self.last_successful_run.isoformat() if self.last_successful_run else None,
            "last_attempted_run": self.last_attempted_run.isoformat() if self.last_attempted_run else None,
            "next_scheduled_run": self.next_scheduled_run.isoformat() if self.next_scheduled_run else None,
            "last_observation_check": self.last_observation_check.isoformat() if self.last_observation_check else None,
            "monitoring_status": self.monitoring_status,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SatelliteObservation(Base):
    __tablename__ = "satellite_observations"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(255), nullable=False)
    collection = Column(String(100), nullable=False)
    sensor = Column(String(50), nullable=False)
    acquisition_time = Column(DateTime(timezone=True), nullable=False)
    processing_time = Column(DateTime(timezone=True), nullable=True)
    cloud_cover = Column(Float, nullable=True)
    quality_status = Column(String(50), nullable=False, default="NEW_OBSERVATION_AVAILABLE")
    rejection_reason = Column(String(255), nullable=True)
    raw_metadata = Column(Text, default="{}")
    raster_artifact_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    location = relationship("CriticalLocation", back_populates="observations")
    jobs = relationship("ProcessingJob", back_populates="observation", cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "location_id": self.location_id,
            "product_id": self.product_id,
            "collection": self.collection,
            "sensor": self.sensor,
            "acquisition_time": self.acquisition_time.isoformat() if self.acquisition_time else None,
            "processing_time": self.processing_time.isoformat() if self.processing_time else None,
            "cloud_cover": self.cloud_cover,
            "quality_status": self.quality_status,
            "rejection_reason": self.rejection_reason,
            "raster_artifact_path": self.raster_artifact_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(String(100), primary_key=True)
    observation_id = Column(String(100), ForeignKey("satellite_observations.id", ondelete="CASCADE"), nullable=False)
    job_type = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="QUEUED")  # QUEUED, RUNNING, COMPLETED, FAILED
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    observation = relationship("SatelliteObservation", back_populates="jobs")


class ChangeDetection(Base):
    __tablename__ = "change_detections"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    current_observation_id = Column(String(100), ForeignKey("satellite_observations.id"), nullable=False)
    baseline_observation_id = Column(String(100), ForeignKey("satellite_observations.id"), nullable=False)
    change_type = Column(String(100), nullable=False, default="WATER_EXTENT_CHANGE")
    baseline_water_area_m2 = Column(Float, nullable=False)
    current_water_area_m2 = Column(Float, nullable=False)
    water_change_area_m2 = Column(Float, nullable=False)
    water_change_percentage = Column(Float, nullable=False)
    mean_delta_ndwi = Column(Float, nullable=False)
    max_delta_ndwi = Column(Float, nullable=False)
    change_mask_path = Column(String(500), nullable=True)
    summary_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    location = relationship("CriticalLocation", back_populates="change_detections")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "location_id": self.location_id,
            "current_observation_id": self.current_observation_id,
            "baseline_observation_id": self.baseline_observation_id,
            "change_type": self.change_type,
            "baseline_water_area_m2": round(self.baseline_water_area_m2, 2),
            "current_water_area_m2": round(self.current_water_area_m2, 2),
            "water_change_area_m2": round(self.water_change_area_m2, 2),
            "water_change_percentage": round(self.water_change_percentage, 2),
            "mean_delta_ndwi": round(self.mean_delta_ndwi, 4),
            "max_delta_ndwi": round(self.max_delta_ndwi, 4),
            "change_mask_path": self.change_mask_path,
            "summary_notes": self.summary_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Sentinel1Retrieval(Base):
    __tablename__ = "sentinel1_retrievals"

    id = Column(String(100), primary_key=True)
    observation_id = Column(String(100), ForeignKey("satellite_observations.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(255), nullable=False)
    storage_path = Column(String(500), nullable=False)
    source_url = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    retrieved_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status = Column(String(50), nullable=False, default="SUCCESS")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "observation_id": self.observation_id,
            "product_id": self.product_id,
            "storage_path": self.storage_path,
            "source_url": self.source_url,
            "file_size_bytes": self.file_size_bytes,
            "sha256": self.sha256,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "status": self.status,
        }


class Sentinel1ProcessingResult(Base):
    __tablename__ = "sentinel1_processing_results"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    observation_id = Column(String(100), ForeignKey("satellite_observations.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(255), nullable=False)
    acquisition_time = Column(DateTime(timezone=True), nullable=False)
    vv_statistics = Column(Text, nullable=False, default="{}")
    vh_statistics = Column(Text, nullable=False, default="{}")
    vv_raster_path = Column(String(500), nullable=False)
    vh_raster_path = Column(String(500), nullable=False)
    processing_version = Column(String(50), nullable=False, default="1.0.0")
    status = Column(String(50), nullable=False, default="SUCCESS")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        import json
        return {
            "id": self.id,
            "location_id": self.location_id,
            "observation_id": self.observation_id,
            "product_id": self.product_id,
            "acquisition_time": self.acquisition_time.isoformat() if self.acquisition_time else None,
            "vv_statistics": json.loads(self.vv_statistics) if isinstance(self.vv_statistics, str) else self.vv_statistics,
            "vh_statistics": json.loads(self.vh_statistics) if isinstance(self.vh_statistics, str) else self.vh_statistics,
            "vv_raster_path": self.vv_raster_path,
            "vh_raster_path": self.vh_raster_path,
            "processing_version": self.processing_version,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Sentinel1ChangeDetection(Base):
    __tablename__ = "sentinel1_change_detections"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    t1_observation_id = Column(String(100), ForeignKey("satellite_observations.id"), nullable=False)
    t2_observation_id = Column(String(100), ForeignKey("satellite_observations.id"), nullable=False)
    t1_product_id = Column(String(255), nullable=False)
    t2_product_id = Column(String(255), nullable=False)
    t1_acquisition_time = Column(DateTime(timezone=True), nullable=False)
    t2_acquisition_time = Column(DateTime(timezone=True), nullable=False)
    orbit_information = Column(Text, nullable=False, default="{}")
    delta_vv_statistics = Column(Text, nullable=False, default="{}")
    delta_vh_statistics = Column(Text, nullable=False, default="{}")
    changed_percentage = Column(Float, nullable=False, default=0.0)
    thresholds = Column(Text, nullable=False, default="{}")
    change_raster_path = Column(String(500), nullable=True)
    status = Column(String(50), nullable=False, default="SUCCESS")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        import json
        return {
            "id": self.id,
            "location_id": self.location_id,
            "t1_observation_id": self.t1_observation_id,
            "t2_observation_id": self.t2_observation_id,
            "t1_product_id": self.t1_product_id,
            "t2_product_id": self.t2_product_id,
            "t1_acquisition_time": self.t1_acquisition_time.isoformat() if self.t1_acquisition_time else None,
            "t2_acquisition_time": self.t2_acquisition_time.isoformat() if self.t2_acquisition_time else None,
            "orbit_information": json.loads(self.orbit_information) if isinstance(self.orbit_information, str) else self.orbit_information,
            "delta_vv_statistics": json.loads(self.delta_vv_statistics) if isinstance(self.delta_vv_statistics, str) else self.delta_vv_statistics,
            "delta_vh_statistics": json.loads(self.delta_vh_statistics) if isinstance(self.delta_vh_statistics, str) else self.delta_vh_statistics,
            "changed_percentage": round(self.changed_percentage, 2),
            "thresholds": json.loads(self.thresholds) if isinstance(self.thresholds, str) else self.thresholds,
            "change_raster_path": self.change_raster_path,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvidenceSnapshot(Base):
    __tablename__ = "evidence_snapshots"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    evidence_window_start = Column(DateTime(timezone=True), nullable=False)
    evidence_window_end = Column(DateTime(timezone=True), nullable=False)
    reference_time = Column(DateTime(timezone=True), nullable=False)
    sentinel1_evidence = Column(Text, nullable=False, default="{}")
    sentinel2_evidence = Column(Text, nullable=False, default="{}")
    rainfall_evidence = Column(Text, nullable=False, default="{}")
    fire_evidence = Column(Text, nullable=False, default="{}")
    earthquake_evidence = Column(Text, nullable=False, default="{}")
    terrain_evidence = Column(Text, nullable=False, default="{}")
    correlations = Column(Text, nullable=False, default="[]")
    provenance = Column(Text, nullable=False, default="{}")
    processing_metadata = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    location = relationship("CriticalLocation")

    def to_dict(self) -> Dict[str, Any]:
        import json
        return {
            "id": self.id,
            "location_id": self.location_id,
            "evidence_window_start": self.evidence_window_start.isoformat() if self.evidence_window_start else None,
            "evidence_window_end": self.evidence_window_end.isoformat() if self.evidence_window_end else None,
            "reference_time": self.reference_time.isoformat() if self.reference_time else None,
            "sentinel1_evidence": json.loads(self.sentinel1_evidence) if isinstance(self.sentinel1_evidence, str) else self.sentinel1_evidence,
            "sentinel2_evidence": json.loads(self.sentinel2_evidence) if isinstance(self.sentinel2_evidence, str) else self.sentinel2_evidence,
            "rainfall_evidence": json.loads(self.rainfall_evidence) if isinstance(self.rainfall_evidence, str) else self.rainfall_evidence,
            "fire_evidence": json.loads(self.fire_evidence) if isinstance(self.fire_evidence, str) else self.fire_evidence,
            "earthquake_evidence": json.loads(self.earthquake_evidence) if isinstance(self.earthquake_evidence, str) else self.earthquake_evidence,
            "terrain_evidence": json.loads(self.terrain_evidence) if isinstance(self.terrain_evidence, str) else self.terrain_evidence,
            "correlations": json.loads(self.correlations) if isinstance(self.correlations, str) else self.correlations,
            "provenance": json.loads(self.provenance) if isinstance(self.provenance, str) else self.provenance,
            "processing_metadata": json.loads(self.processing_metadata) if isinstance(self.processing_metadata, str) else self.processing_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    evidence_snapshot_id = Column(String(100), ForeignKey("evidence_snapshots.id", ondelete="CASCADE"), nullable=False)
    score = Column(Float, nullable=False)
    risk_level = Column(String(50), nullable=False)
    monitoring_priority = Column(String(50), nullable=False)
    evidence_strength = Column(String(50), nullable=False)
    confidence_score = Column(Float, nullable=False, default=1.0)
    contributing_factors = Column(Text, nullable=False, default="[]")
    uncertainty_factors = Column(Text, nullable=False, default="[]")
    explanation = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    engine_version = Column(String(50), nullable=False, default="risk_engine_v1")
    provenance = Column(Text, nullable=False, default="{}")
    score_interpretation = Column(
        String(255),
        nullable=False,
        default="Monitoring risk score (0-100 scale). This is NOT a probability of disaster or confirmation of damage."
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    location = relationship("CriticalLocation")
    evidence_snapshot = relationship("EvidenceSnapshot")

    def to_dict(self) -> Dict[str, Any]:
        import json
        return {
            "id": self.id,
            "location_id": self.location_id,
            "location_name": self.location.name if self.location else None,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "score": self.score,
            "risk_level": self.risk_level,
            "monitoring_priority": self.monitoring_priority,
            "evidence_strength": self.evidence_strength,
            "confidence_score": self.confidence_score,
            "contributing_factors": json.loads(self.contributing_factors) if isinstance(self.contributing_factors, str) else self.contributing_factors,
            "uncertainty_factors": json.loads(self.uncertainty_factors) if isinstance(self.uncertainty_factors, str) else self.uncertainty_factors,
            "explanation": self.explanation,
            "recommended_action": self.recommended_action,
            "engine_version": self.engine_version,
            "provenance": json.loads(self.provenance) if isinstance(self.provenance, str) else self.provenance,
            "score_interpretation": self.score_interpretation,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AnalystReport(Base):
    __tablename__ = "analyst_reports"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    risk_assessment_id = Column(String(100), ForeignKey("risk_assessments.id", ondelete="CASCADE"), nullable=False)
    executive_summary = Column(Text, nullable=False)
    report_data = Column(Text, nullable=False, default="{}")
    model = Column(String(100), nullable=False)
    prompt_version = Column(String(50), nullable=False, default="evidence_analyst_v1")
    validation_status = Column(String(50), nullable=False, default="VALIDATED")
    validation_errors = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    location = relationship("CriticalLocation")
    risk_assessment = relationship("RiskAssessment")

    def to_dict(self) -> Dict[str, Any]:
        import json
        parsed_data = json.loads(self.report_data) if isinstance(self.report_data, str) else self.report_data
        return {
            "id": self.id,
            "location_id": self.location_id,
            "location_name": self.location.name if self.location else None,
            "risk_assessment_id": self.risk_assessment_id,
            "executive_summary": self.executive_summary,
            "report_data": parsed_data,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "validation_status": self.validation_status,
            "validation_errors": json.loads(self.validation_errors) if isinstance(self.validation_errors, str) else self.validation_errors,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    risk_assessment_id = Column(String(100), ForeignKey("risk_assessments.id", ondelete="CASCADE"), nullable=False)
    analyst_report_id = Column(String(100), ForeignKey("analyst_reports.id", ondelete="SET NULL"), nullable=True)
    alert_level = Column(String(50), nullable=False)  # INFO, MONITOR, ELEVATED, HIGH, URGENT
    priority = Column(String(50), nullable=False)     # ROUTINE, ELEVATED, HIGH, URGENT
    status = Column(String(50), nullable=False, default="ACTIVE")  # ACTIVE, ACKNOWLEDGED, IN_REVIEW, RESOLVED, EXPIRED, SUPERSEDED
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
    evidence_references = Column(Text, nullable=False, default="{}")
    contributing_factors = Column(Text, nullable=False, default="[]")
    uncertainty = Column(Text, nullable=False, default="[]")
    recommended_action = Column(Text, nullable=False)
    fingerprint = Column(String(100), nullable=False)
    escalation_history = Column(Text, nullable=False, default="[]")
    acknowledgement_details = Column(Text, nullable=True)
    resolution_details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    alert_version = Column(String(50), nullable=False, default="alert_engine_v1")
    source_engine_versions = Column(Text, nullable=False, default="{}")
    disclaimer = Column(
        String(255),
        nullable=False,
        default="Operational decision-support alert. Does not constitute a disaster declaration, structural damage confirmation, or evacuation order."
    )

    location = relationship("CriticalLocation")
    risk_assessment = relationship("RiskAssessment")
    analyst_report = relationship("AnalystReport")
    events = relationship("AlertEvent", back_populates="alert", cascade="all, delete-orphan", order_by="AlertEvent.created_at.desc()")

    def to_dict(self) -> Dict[str, Any]:
        import json
        loc_name = None
        try:
            loc_name = self.location.name if self.location else None
        except Exception:
            pass
        return {
            "id": self.id,
            "location_id": self.location_id,
            "location_name": loc_name,
            "risk_assessment_id": self.risk_assessment_id,
            "analyst_report_id": self.analyst_report_id,
            "alert_level": self.alert_level,
            "priority": self.priority,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "reason": self.reason,
            "evidence_references": json.loads(self.evidence_references) if isinstance(self.evidence_references, str) else self.evidence_references,
            "contributing_factors": json.loads(self.contributing_factors) if isinstance(self.contributing_factors, str) else self.contributing_factors,
            "uncertainty": json.loads(self.uncertainty) if isinstance(self.uncertainty, str) else self.uncertainty,
            "recommended_action": self.recommended_action,
            "fingerprint": self.fingerprint,
            "escalation_history": json.loads(self.escalation_history) if isinstance(self.escalation_history, str) else self.escalation_history,
            "acknowledgement_details": json.loads(self.acknowledgement_details) if (self.acknowledgement_details and isinstance(self.acknowledgement_details, str)) else self.acknowledgement_details,
            "resolution_details": json.loads(self.resolution_details) if (self.resolution_details and isinstance(self.resolution_details, str)) else self.resolution_details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "alert_version": self.alert_version,
            "source_engine_versions": json.loads(self.source_engine_versions) if isinstance(self.source_engine_versions, str) else self.source_engine_versions,
            "disclaimer": self.disclaimer,
        }


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id = Column(String(100), primary_key=True)
    alert_id = Column(String(100), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)
    previous_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    previous_level = Column(String(50), nullable=True)
    new_level = Column(String(50), nullable=True)
    actor = Column(String(100), nullable=True, default="system")
    reason = Column(Text, nullable=False)
    event_metadata = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    alert = relationship("Alert", back_populates="events")

    def to_dict(self) -> Dict[str, Any]:
        import json
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "event_type": self.event_type,
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "previous_level": self.previous_level,
            "new_level": self.new_level,
            "actor": self.actor,
            "reason": self.reason,
            "metadata": json.loads(self.event_metadata) if isinstance(self.event_metadata, str) else self.event_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(50), nullable=False, default="PENDING")  # PENDING, RUNNING, COMPLETED, PARTIAL, FAILED, SKIPPED
    trigger_type = Column(String(50), nullable=False, default="SCHEDULED")  # SCHEDULED, MANUAL, RETRY
    triggered_by = Column(String(100), nullable=False, default="scheduler")
    current_stage = Column(String(50), nullable=False, default="INITIALIZING")
    stage_history = Column(Text, nullable=False, default="[]")
    observations_checked = Column(Integer, nullable=False, default=0)
    observations_processed = Column(Integer, nullable=False, default=0)
    new_observations_found = Column(Integer, nullable=False, default=0)
    evidence_snapshot_id = Column(String(100), ForeignKey("evidence_snapshots.id", ondelete="SET NULL"), nullable=True)
    risk_assessment_id = Column(String(100), ForeignKey("risk_assessments.id", ondelete="SET NULL"), nullable=True)
    analyst_report_id = Column(String(100), ForeignKey("analyst_reports.id", ondelete="SET NULL"), nullable=True)
    alert_id = Column(String(100), ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True)
    alert_action = Column(String(50), nullable=True)
    outcome_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    run_metadata = Column(Text, nullable=False, default="{}")
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    location = relationship("CriticalLocation")
    evidence_snapshot = relationship("EvidenceSnapshot")
    risk_assessment = relationship("RiskAssessment")
    analyst_report = relationship("AnalystReport")
    alert = relationship("Alert")

    def __init__(self, **kwargs):
        import json
        if "stage_history" in kwargs and not isinstance(kwargs["stage_history"], str):
            kwargs["stage_history"] = json.dumps(kwargs["stage_history"])
        if "run_metadata" in kwargs and not isinstance(kwargs["run_metadata"], str):
            kwargs["run_metadata"] = json.dumps(kwargs["run_metadata"])
        super().__init__(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        import json
        loc_name = None
        try:
            loc_name = self.location.name if self.location else None
        except Exception:
            pass
        return {
            "id": self.id,
            "location_id": self.location_id,
            "location_name": loc_name,
            "status": self.status,
            "trigger_type": self.trigger_type,
            "triggered_by": self.triggered_by,
            "current_stage": self.current_stage,
            "stage_history": json.loads(self.stage_history) if isinstance(self.stage_history, str) else (self.stage_history or []),
            "observations_checked": self.observations_checked or 0,
            "observations_processed": self.observations_processed or 0,
            "new_observations_found": self.new_observations_found or 0,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "risk_assessment_id": self.risk_assessment_id,
            "analyst_report_id": self.analyst_report_id,
            "alert_id": self.alert_id,
            "alert_action": self.alert_action,
            "outcome_code": self.outcome_code,
            "error_message": self.error_message,
            "retry_count": self.retry_count if self.retry_count is not None else 0,
            "run_metadata": json.loads(self.run_metadata) if isinstance(self.run_metadata, str) else (self.run_metadata or {}),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==============================================================================
# PHASE 9 — HISTORICAL INTELLIGENCE & TREND ANALYTICS
# ==============================================================================

class HistoricalAnalyticsSnapshot(Base):
    __tablename__ = "historical_analytics_snapshots"

    id = Column(String(100), primary_key=True)
    location_id = Column(String(100), ForeignKey("critical_locations.id", ondelete="CASCADE"), nullable=False, index=True)
    window_days = Column(Integer, nullable=False, default=30)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    data_sufficiency = Column(String(50), nullable=False, default="INSUFFICIENT")
    persistence_status = Column(String(50), nullable=False, default="INSUFFICIENT_DATA")
    risk_trend = Column(String(50), nullable=False, default="INSUFFICIENT_DATA")
    baseline_comparison = Column(String(50), nullable=False, default="INSUFFICIENT_DATA")
    deviation_status = Column(String(50), nullable=False, default="NORMAL")

    sar_summary = Column(Text, nullable=True)
    optical_summary = Column(Text, nullable=True)
    environmental_summary = Column(Text, nullable=True)
    risk_summary = Column(Text, nullable=True)
    alert_summary = Column(Text, nullable=True)
    persistence_summary = Column(Text, nullable=True)
    baseline_summary = Column(Text, nullable=True)
    deviation_summary = Column(Text, nullable=True)

    engine_version = Column(String(50), nullable=False, default="analytics_v1")
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    location = relationship("CriticalLocation")

    def __init__(self, **kwargs):
        import json
        json_fields = [
            "sar_summary", "optical_summary", "environmental_summary",
            "risk_summary", "alert_summary", "persistence_summary",
            "baseline_summary", "deviation_summary"
        ]
        for field in json_fields:
            if field in kwargs and not isinstance(kwargs[field], str):
                kwargs[field] = json.dumps(kwargs[field])
        super().__init__(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        import json
        def _parse(val):
            if val is None:
                return None
            if isinstance(val, (dict, list)):
                return val
            try:
                return json.loads(val)
            except Exception:
                return val

        loc_name = None
        try:
            loc_name = self.location.name if self.location else None
        except Exception:
            pass
        return {
            "id": self.id,
            "location_id": self.location_id,
            "location_name": loc_name,
            "window_days": self.window_days,
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "data_sufficiency": self.data_sufficiency,
            "persistence_status": self.persistence_status,
            "risk_trend": self.risk_trend,
            "baseline_comparison": self.baseline_comparison,
            "deviation_status": self.deviation_status,
            "sar_summary": _parse(self.sar_summary),
            "optical_summary": _parse(self.optical_summary),
            "environmental_summary": _parse(self.environmental_summary),
            "risk_summary": _parse(self.risk_summary),
            "alert_summary": _parse(self.alert_summary),
            "persistence_summary": _parse(self.persistence_summary),
            "baseline_summary": _parse(self.baseline_summary),
            "deviation_summary": _parse(self.deviation_summary),
            "engine_version": self.engine_version,
            "explanation": self.explanation,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==============================================================================
# PHASE 10 — PRODUCTION HARDENING, SECURITY, RBAC & AUDIT LOGGING
# ==============================================================================

class User(Base):
    __tablename__ = "users"

    id = Column(String(100), primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    department = Column(String(255), nullable=True)
    role = Column(String(50), nullable=False, default="OPERATOR", index=True)  # VIEWER, ANALYST, OPERATOR, SUPERVISOR, ADMIN
    is_active = Column(Boolean, nullable=False, default=True)
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "department": self.department,
            "role": self.role,
            "is_active": self.is_active,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(100), primary_key=True)
    event_id = Column(String(100), unique=True, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    actor = Column(String(100), nullable=False, index=True)
    role = Column(String(50), nullable=False)
    action = Column(String(100), nullable=False, index=True)
    resource = Column(String(100), nullable=False)
    resource_id = Column(String(100), nullable=True, index=True)
    result = Column(String(50), nullable=False, default="SUCCESS")
    ip_address = Column(String(100), nullable=True)
    request_id = Column(String(100), nullable=True, index=True)
    event_metadata = Column(Text, nullable=False, default="{}")

    def __init__(self, **kwargs):
        import json
        if "event_metadata" in kwargs and not isinstance(kwargs["event_metadata"], str):
            kwargs["event_metadata"] = json.dumps(kwargs["event_metadata"])
        super().__init__(**kwargs)

    def to_dict(self) -> Dict[str, Any]:
        import json
        parsed_metadata = {}
        if self.event_metadata:
            try:
                parsed_metadata = json.loads(self.event_metadata) if isinstance(self.event_metadata, str) else self.event_metadata
            except Exception:
                parsed_metadata = {"raw": self.event_metadata}

        return {
            "id": self.id,
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "actor": self.actor,
            "role": self.role,
            "action": self.action,
            "resource": self.resource,
            "resource_id": self.resource_id,
            "result": self.result,
            "ip_address": self.ip_address,
            "request_id": self.request_id,
            "metadata": parsed_metadata,
        }





