/**
 * SATGUARD — Arbitrary-AOI monitoring types.
 *
 * Mirrors the response shapes of `satguard/api/monitoring_router.py`. The distinction that
 * matters most here is `source`: DEMO results are synthetic and must never be presented as
 * satellite observations, so the type forces the value to be explicit rather than optional.
 */

export type MonitoringSource = 'LIVE' | 'DEMO';

export type MonitoringMode =
  | 'general'
  | 'infrastructure'
  | 'glacier'
  | 'water_body'
  | 'vegetation'
  | 'flood';

export const MONITORING_MODES: { value: MonitoringMode; label: string }[] = [
  { value: 'general', label: 'General' },
  { value: 'infrastructure', label: 'Infrastructure' },
  { value: 'glacier', label: 'Glacier' },
  { value: 'water_body', label: 'Water body' },
  { value: 'vegetation', label: 'Vegetation' },
  { value: 'flood', label: 'Flood' },
];

export type Severity = 'none' | 'low' | 'moderate' | 'high' | 'critical';

/** Ordered most to least severe. Never sort severities alphabetically: "critical" sorts before
 *  "low" as text, so the UI keeps its own explicit order. */
export const SEVERITY_ORDER: Severity[] = ['critical', 'high', 'moderate', 'low', 'none'];

export const SEVERITY_RANK: Record<Severity, number> = {
  critical: 4,
  high: 3,
  moderate: 2,
  low: 1,
  none: 0,
};

export interface GeoJSONPolygon {
  type: 'Polygon' | 'MultiPolygon';
  coordinates: number[][][] | number[][][][];
}

export interface MonitoringArea {
  id: string;
  user_label: string;
  monitoring_mode: MonitoringMode;
  geometry: GeoJSONPolygon;
  bbox: number[];
  center: { lon: number; lat: number };
  area_km2: number;
  crs: string;
  source: MonitoringSource;
  created_at: string | null;
  metadata: {
    sensor_strategy?: string | null;
    required_indices?: string[] | null;
  };
}

/** Exactly one geometry input must be supplied, matching the backend contract. */
export type AreaGeometryInput =
  | { point: { latitude: number; longitude: number; radius_m?: number } }
  | { bbox: [number, number, number, number] }
  | { polygon: number[][] }
  | { geometry: { type: string; coordinates: any } }
  | { place_name: string };

export interface CreateAreaPayload {
  monitoring_mode: MonitoringMode;
  user_label?: string;
  source: MonitoringSource;
  point?: { latitude: number; longitude: number; radius_m?: number };
  bbox?: [number, number, number, number];
  polygon?: number[][];
  geometry?: { type: string; coordinates: any };
  place_name?: string;
}

export interface CreateAreaRequest extends CreateAreaPayload {
  demo_scenario?: string;
  grid_size?: number;
  require_sar?: boolean;
}

export interface RunMonitoringPayload {
  area_id: string;
  source: MonitoringSource;
  monitoring_mode?: MonitoringMode;
  demo_scenario?: string;
  demo_interval_days?: number;
  grid_size?: number;
  max_cloud_cover?: number | null;
  require_sar?: boolean;
  normalization?: string;
  speckle_filter?: string | null;
}

/**
 * The three scores are reported separately and must stay separate in the UI: run-level
 * detection confidence, per-region anomaly confidence, and operational severity.
 */
export interface AnomalyRegion {
  region_id: string;
  monitoring_mode: MonitoringMode;
  geometry: GeoJSONPolygon;
  centroid_lon: number;
  centroid_lat: number;
  bbox: number[];
  centroid: { lon: number; lat: number };
  area_m2: number;
  area_km2: number;
  area_ha: number;
  pixel_count: number;
  detection_confidence: number;
  anomaly_confidence: number;
  severity: Severity;
  layer_agreement: Record<string, number>;
  evidence: EvidenceItem[];
  caveats: string[];
  source: MonitoringSource;
  detected_at: string | null;
}

/** Evidence states what was measured and what it means, rather than exposing raw scores. */
export interface EvidenceItem {
  source: string;
  observation: string;
  value: number | string;
  unit?: string | null;
  interpretation?: string;
}

export interface AnomalyRecord extends AnomalyRegion {
  id: string;
  area_id: string;
  run_id: string | null;
}

export interface RunConfidence {
  detection_confidence: number;
  components: Record<string, number>;
  caveats: string[];
}

export interface MonitoringRunResult {
  aoi_id: string;
  monitoring_mode: MonitoringMode;
  source: MonitoringSource;
  crs: string;
  bounds: number[];
  run_confidence: RunConfidence;
  run_severity: Severity;
  max_anomaly_severity: Severity;
  anomaly_count: number;
  total_area_km2: number;
  anomalies: AnomalyRegion[];
  detection: Record<string, any>;
  generated_at: string;
  provenance: {
    source: MonitoringSource;
    synthetic?: boolean;
    note?: string;
    requested_source?: MonitoringSource;
    monitoring_mode?: MonitoringMode;
    grid?: { width: number; height: number };
    baseline?: string | null;
    current?: string | null;
    baseline_date?: string | null;
    current_date?: string | null;
    valid_fraction?: number;
    suppression?: Record<string, any>;
    demo_truth?: {
      changed_pixels?: number;
      intersection_over_union?: number;
      note?: string;
    };
  };
  run_id?: string;
  persisted_anomaly_ids?: string[];
  started_at?: string;
  completed_at?: string;
}

export type JobStatus = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';

export interface JobStageEntry {
  stage: string;
  percent: number;
  at: string;
}

export interface MonitoringJob {
  job_id: string;
  area_id: string;
  source: MonitoringSource;
  monitoring_mode: MonitoringMode;
  status: JobStatus;
  stage: string;
  progress_percent: number;
  stage_history: JobStageEntry[];
  anomaly_count: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  is_terminal: boolean;
  result?: MonitoringRunResult;
}

export interface DemoSite {
  /** The site's identifier, and what an AOI is created from via its `bounds`. */
  name: string;
  monitoring_mode: MonitoringMode;
  scenario: string;
  description: string;
  bounds: [number, number, number, number];
}

export interface DemoSiteCatalogue {
  source: 'DEMO';
  disclaimer: string;
  sites: DemoSite[];
}

export interface AnomalySummaryBucket {
  count: number;
  area_km2: number;
}

export interface AnomalyListResponse {
  count: number;
  summary_by_severity: Record<Severity, AnomalySummaryBucket>;
  anomalies: AnomalyRecord[];
}

/** A failed request carries a structured detail from the backend; keep both cases readable. */
export interface ApiErrorDetail {
  error_code: string;
  message: string;
}