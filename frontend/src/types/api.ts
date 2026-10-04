/**
 * SATGUARD — Government-Grade Earth Observation & Intelligence Platform
 * Authoritative TypeScript Type Definitions
 */

export type RiskLevel = 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL';
export type MonitoringPriority = 'ROUTINE' | 'ELEVATED' | 'HIGH' | 'URGENT';
export type EvidenceStrength = 'WEAK' | 'MODERATE' | 'STRONG' | 'VERY_STRONG';

export type AlertPriority = 'INFO' | 'ROUTINE' | 'ELEVATED' | 'HIGH' | 'URGENT';
export type AlertStatus = 'ACTIVE' | 'ACKNOWLEDGED' | 'IN_REVIEW' | 'RESOLVED' | 'EXPIRED' | 'SUPPRESSED';

export type LocationType = 
  | 'dam' 
  | 'reservoir' 
  | 'glacier' 
  | 'glacial_lake' 
  | 'mountain_slope' 
  | 'slope'
  | 'landslide_zone' 
  | 'bridge' 
  | 'coastal_zone' 
  | 'forest' 
  | 'mine' 
  | 'urban_construction' 
  | 'other';

export interface CriticalLocation {
  id: string;
  name: string;
  location_type: string;
  latitude: number;
  longitude: number;
  radius_m: number;
  geometry?: any;
  priority?: string;
  risk_category?: string;
  monitoring_frequency?: string;
  monitoring_enabled: boolean;
  monitoring_interval_hours: number;
  monitoring_status: 'ACTIVE' | 'PAUSED' | 'DISABLED' | 'ERROR';
  last_successful_run?: string | null;
  last_attempted_run?: string | null;
  next_scheduled_run?: string | null;
  last_observation_check?: string | null;
  description?: string | null;
  created_at?: string;
  updated_at?: string;
  // Dynamic client joins
  latest_risk?: RiskAssessment | null;
  latest_alert?: Alert | null;
}

export interface OverviewStats {
  total_locations: number;
  active_monitoring_locations: number;
  high_risk_locations: number;
  critical_risk_locations: number;
  active_alerts_count: number;
  total_alerts_count: number;
  recent_runs_count: number;
  system_status: 'OPERATIONAL' | 'DEGRADED' | 'ERROR';
  mode: string;
  data_freshness: string;
  timestamp: string;
}

export interface RiskAssessment {
  id: string;
  location_id: string;
  evidence_snapshot_id?: string | null;
  score: number;
  risk_level: RiskLevel;
  monitoring_priority: MonitoringPriority;
  evidence_strength: EvidenceStrength;
  confidence_score: number;
  contributing_factors?: any;
  uncertainty_factors?: any;
  explanation: string;
  recommended_action: string;
  engine_version: string;
  provenance?: Record<string, any>;
  score_interpretation?: string;
  created_at: string;
}

export interface Sentinel1Observation {
  id: string;
  location_id: string;
  product_id: string;
  acquisition_time: string;
  orbit_direction?: string | null;
  relative_orbit?: number | null;
  polarisation?: string | null;
  status?: string | null;
  created_at?: string;
}

export interface Sentinel1Change {
  id: string;
  location_id: string;
  t1_observation_id?: string;
  t2_observation_id?: string;
  t1_product_id?: string;
  t2_product_id?: string;
  t1_acquisition_time?: string;
  t2_acquisition_time?: string;
  orbit_information?: {
    t1_orbit_direction?: string;
    t2_orbit_direction?: string;
    t1_relative_orbit?: number;
    t2_relative_orbit?: number;
  };
  delta_vv_statistics?: {
    min?: number;
    max?: number;
    mean?: number;
    median?: number;
    std?: number;
    valid_pixel_count?: number;
  };
  delta_vh_statistics?: {
    min?: number;
    max?: number;
    mean?: number;
    median?: number;
    std?: number;
    valid_pixel_count?: number;
  };
  changed_percentage?: number;
  thresholds?: {
    vv_threshold_db?: number;
    vh_threshold_db?: number;
  };
  change_raster_path?: string;
  status?: string;
  created_at?: string;
}

export interface Sentinel2Observation {
  id: string;
  location_id: string;
  product_id: string;
  acquisition_time: string;
  cloud_coverage_percentage?: number | null;
  ndwi_mean?: number | null;
  mndwi_mean?: number | null;
  water_surface_ratio?: number | null;
  status?: string | null;
  metadata?: Record<string, any>;
}

export interface EvidenceSnapshot {
  id: string;
  location_id: string;
  streams_available?: string[];
  streams_unavailable?: string[];
  evidence_strength?: string;
  confidence_score?: number;
  correlations?: any;
  temporal_alignment?: any;
  spatial_alignment?: any;
  optical_evidence?: any;
  sar_evidence?: any;
  terrain_evidence?: any;
  rainfall_evidence?: any;
  earthquake_evidence?: any;
  fire_evidence?: any;
  created_at?: string;
}

export interface AnalystReport {
  id: string;
  location_id: string;
  risk_assessment_id?: string | null;
  model: string;
  executive_summary: string;
  evidence_interpretation: string;
  risk_interpretation: string;
  contributing_evidence?: string[];
  uncertainties?: string[];
  recommended_monitoring_action: string;
  prompt_version?: string;
  validation_status?: string;
  created_at: string;
}

export interface AlertEvent {
  id: string;
  alert_id: string;
  event_type: string;
  from_status?: string | null;
  to_status?: string | null;
  actor?: string | null;
  note?: string | null;
  created_at: string;
}

export interface Alert {
  id: string;
  location_id: string;
  location_name?: string;
  priority: AlertPriority;
  status: AlertStatus;
  title: string;
  summary: string;
  reason?: string;
  risk_level?: string;
  risk_score?: number;
  risk_assessment_id?: string;
  analyst_report_id?: string;
  evidence_snapshot_id?: string;
  monitoring_run_id?: string;
  contributing_factors?: any;
  uncertainty_factors?: any;
  recommended_action?: string;
  disclaimer?: string;
  fingerprint?: string;
  source_engines?: Record<string, string>;
  expires_at?: string;
  created_at: string;
  updated_at?: string;
  events?: AlertEvent[];
}

export interface MonitoringRun {
  id: string;
  location_id: string;
  trigger_type: string;
  status: string;
  current_stage: string;
  outcome_code?: string | null;
  alert_action?: string | null;
  alert_id?: string | null;
  risk_assessment_id?: string | null;
  analyst_report_id?: string | null;
  evidence_snapshot_id?: string | null;
  observations_checked?: number;
  observations_processed?: number;
  error_message?: string | null;
  retry_count?: number;
  stage_timestamps?: Record<string, string>;
  created_at: string;
  completed_at?: string | null;
}

export interface TimelineEvent {
  id: string;
  event_type: string;
  timestamp: string;
  title: string;
  summary: string;
  details?: any;
}

export interface SystemDataStatus {
  providers: Record<string, string>;
  mode: string;
  timestamp: string;
}

// ==============================================================================
// PHASE 9 — HISTORICAL INTELLIGENCE & TREND ANALYTICS
// ==============================================================================

export type DataSufficiency = 'SUFFICIENT' | 'LIMITED' | 'INSUFFICIENT';
export type PersistenceStatus = 'NO_SIGNAL' | 'ISOLATED_SIGNAL' | 'INTERMITTENT_SIGNAL' | 'PERSISTENT_SIGNAL' | 'INSUFFICIENT_DATA';
export type RiskTrendClassification = 'STABLE' | 'INCREASING' | 'DECREASING' | 'VOLATILE' | 'INSUFFICIENT_DATA';
export type BaselineComparisonStatus = 'ABOVE_BASELINE' | 'WITHIN_BASELINE' | 'BELOW_BASELINE' | 'INSUFFICIENT_DATA';
export type DeviationStatus = 'NORMAL' | 'HISTORICAL_DEVIATION' | 'UNUSUAL_RELATIVE_TO_BASELINE' | 'ABOVE_HISTORICAL_RANGE';

export interface HistoricalWindow {
  days: number;
  start_time: string;
  end_time: string;
}

export interface SARHistoricalPoint {
  change_id?: string;
  observation_id: string;
  t1_acquisition_time?: string | null;
  t2_acquisition_time?: string | null;
  relative_orbit?: number | null;
  orbit_direction?: string | null;
  delta_vv_mean?: number | null;
  delta_vh_mean?: number | null;
  changed_percentage?: number | null;
  valid_pixel_count?: number | null;
  is_significant_change: boolean;
}

export interface SARTrendSummary {
  observation_count: number;
  valid_change_count: number;
  mean_delta_vv?: number | null;
  median_delta_vv?: number | null;
  mean_delta_vh?: number | null;
  median_delta_vh?: number | null;
  mean_changed_percentage?: number | null;
  max_changed_percentage?: number | null;
  signal_trend: string;
  points: SARHistoricalPoint[];
}

export interface OpticalHistoricalPoint {
  observation_id: string;
  acquisition_time: string;
  cloud_cover?: number | null;
  is_cloud_obscured: boolean;
  quality_status?: string | null;
}

export interface OpticalTrendSummary {
  total_scenes: number;
  usable_scenes: number;
  cloud_obscured_scenes: number;
  mean_cloud_cover?: number | null;
  optical_stability: string;
  points: OpticalHistoricalPoint[];
}

export interface EnvironmentalHistorySummary {
  rainfall_status: string;
  rainfall_observation_count: number;
  rainfall_mean_mm?: number | null;
  fire_status: string;
  fire_detection_count: number;
  seismic_status: string;
  seismic_event_count: number;
  nearest_earthquake_distance_km?: number | null;
}

export interface RiskHistoricalPoint {
  risk_assessment_id: string;
  timestamp: string;
  score: number;
  risk_level: string;
  monitoring_priority: string;
  evidence_strength: string;
  confidence_score: number;
  engine_version: string;
}

export interface RiskTrendSummary {
  assessment_count: number;
  latest_score?: number | null;
  average_score?: number | null;
  min_score?: number | null;
  max_score?: number | null;
  score_delta?: number | null;
  level_transitions_count: number;
  high_level_count: number;
  critical_level_count: number;
  classification: RiskTrendClassification;
  points: RiskHistoricalPoint[];
}

export interface AlertHistoricalPoint {
  alert_id: string;
  created_at: string;
  priority: string;
  status: string;
  title: string;
  resolved_at?: string | null;
}

export interface AlertTrendSummary {
  total_alerts: number;
  active_alerts: number;
  acknowledged_alerts: number;
  in_review_alerts: number;
  resolved_alerts: number;
  recurrence_detected: boolean;
  recurrence_pattern?: string | null;
  points: AlertHistoricalPoint[];
}

export interface PersistenceResult {
  persistence_status: PersistenceStatus;
  significant_observations_count: number;
  total_evaluated_observations: number;
  signal_ratio: number;
  consecutive_significant_count: number;
  explanation: string;
}

export interface BaselineComparisonResult {
  comparison_status: BaselineComparisonStatus;
  current_value?: number | null;
  baseline_mean?: number | null;
  baseline_median?: number | null;
  deviation_value?: number | null;
  deviation_status: DeviationStatus;
  explanation: string;
}

export interface HistoricalAnalyticsReport {
  id: string;
  location_id: string;
  location_name?: string | null;
  window: HistoricalWindow;
  data_sufficiency: DataSufficiency;
  persistence: PersistenceResult;
  sar_trends: SARTrendSummary;
  optical_trends: OpticalTrendSummary;
  environmental_history: EnvironmentalHistorySummary;
  risk_trends: RiskTrendSummary;
  alert_trends: AlertTrendSummary;
  baseline_comparison: BaselineComparisonResult;
  engine_version: string;
  disclaimer: string;
  generated_at: string;
}

export type UserRole = 'VIEWER' | 'ANALYST' | 'OPERATOR' | 'SUPERVISOR' | 'ADMIN';

export interface UserProfile {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  full_name?: string | null;
  department?: string | null;
  is_active: boolean;
  created_at?: string;
  last_login?: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  expires_in_seconds: number;
  role: UserRole;
  username: string;
}

export interface AuditLog {
  id: string;
  event_id: string;
  timestamp: string;
  actor: string;
  role: string;
  action: string;
  resource: string;
  resource_id?: string | null;
  result: string;
  ip_address?: string | null;
  request_id?: string | null;
  metadata?: Record<string, any>;
}

export interface PaginatedAuditLogs {
  total: number;
  limit: number;
  offset: number;
  logs: AuditLog[];
}

export interface DependencyStatus {
  status: 'AVAILABLE' | 'DEGRADED' | 'UNAVAILABLE' | 'UNKNOWN';
  [key: string]: any;
}

export interface SystemReadiness {
  status: 'READY' | 'DEGRADED' | 'UNHEALTHY';
  dependencies: {
    database: DependencyStatus;
    scheduler: DependencyStatus;
    providers: Record<string, 'AVAILABLE' | 'DEGRADED'>;
  };
  timestamp: string;
}

export interface OperationalMetrics {
  uptime_seconds: number;
  api_metrics: {
    requests_total: number;
    errors_total: number;
    error_rate_pct: number;
    latency_p50_ms: number;
    latency_p95_ms: number;
    latency_p99_ms: number;
    latency_avg_ms: number;
  };
  monitoring_pipeline_metrics: {
    runs_total: number;
    runs_success: number;
    runs_failed: number;
  };
  system: {
    python_version: string;
    environment: string;
    rate_limiting_enabled: boolean;
    audit_logging_enabled: boolean;
  };
}
