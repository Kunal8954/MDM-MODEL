/**
 * SATGUARD — arbitrary-AOI monitoring API client.
 *
 * Every call goes to the real backend. There is no mock fallback: if a LIVE request fails
 * the error is surfaced, because silently returning synthetic data would let a user read a
 * demonstration result as a satellite observation.
 */

import {
  AnomalyListResponse,
  AnomalyRecord,
  CreateAreaPayload,
  DemoSiteCatalogue,
  MonitoringArea,
  MonitoringJob,
  MonitoringRunResult,
  MonitoringSource,
  RunMonitoringPayload,
} from '../types/monitoring';

const API_BASE = import.meta.env.VITE_API_URL || '';

/** Backend failures arrive as `{detail: {error_code, message}}` or `{detail: string}`. */
export class MonitoringApiError extends Error {
  readonly errorCode: string | null;
  readonly status: number;

  constructor(message: string, status: number, errorCode: string | null) {
    super(message);
    this.name = 'MonitoringApiError';
    this.status = status;
    this.errorCode = errorCode;
  }

  /** True when the request failed because real data was unavailable, not because of a bug. */
  get isLiveDataUnavailable(): boolean {
    return this.errorCode === 'LIVE_DATA_UNAVAILABLE';
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token =
    typeof window !== 'undefined' ? sessionStorage.getItem('satguard_token') : null;

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed: HTTP ${response.status}`;
    let errorCode: string | null = null;
    try {
      const body = await response.json();
      const detail = body?.detail;
      if (typeof detail === 'string') {
        message = detail;
      } else if (detail?.message) {
        message = detail.message;
        errorCode = detail.error_code ?? null;
      } else if (detail) {
        message = JSON.stringify(detail);
      }
    } catch {
      // Non-JSON error body: the status line is all we can report.
    }
    throw new MonitoringApiError(message, response.status, errorCode);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export const monitoringApi = {
  /** Sample areas for exploration. Explicitly synthetic. */
  getDemoSites: (): Promise<DemoSiteCatalogue> =>
    request<DemoSiteCatalogue>('/api/demo/sites'),

  getDemoScenarios: (monitoringMode: string): Promise<{ scenarios: string[] }> =>
    request<{ scenarios: string[] }>(
      `/api/demo/scenarios?monitoring_mode=${encodeURIComponent(monitoringMode)}`,
    ),

  createArea: (payload: CreateAreaPayload): Promise<MonitoringArea> =>
    request<MonitoringArea>('/api/aoi', { method: 'POST', body: JSON.stringify(payload) }),

  listAreas: (params?: { monitoring_mode?: string; source?: string }): Promise<{
    count: number;
    areas: MonitoringArea[];
  }> => {
    const query = new URLSearchParams();
    if (params?.monitoring_mode) query.set('monitoring_mode', params.monitoring_mode);
    if (params?.source) query.set('source', params.source);
    const qs = query.toString();
    return request(`/api/aoi${qs ? `?${qs}` : ''}`);
  },

  getArea: (areaId: string): Promise<MonitoringArea> =>
    request<MonitoringArea>(`/api/aoi/${encodeURIComponent(areaId)}`),

  deleteArea: (areaId: string): Promise<void> =>
    request<void>(`/api/aoi/${encodeURIComponent(areaId)}`, { method: 'DELETE' }),

  /** Blocking run. Use when the caller is happy to wait for the result. */
  run: (payload: RunMonitoringPayload): Promise<MonitoringRunResult> =>
    request<MonitoringRunResult>('/api/monitor', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Non-blocking run. Returns immediately with a job id to poll. */
  queueRun: (payload: RunMonitoringPayload): Promise<{
    job_id: string;
    status: string;
    stage: string;
    progress_percent: number;
    area_id: string;
    source: MonitoringSource;
  }> => request('/api/monitor/jobs', { method: 'POST', body: JSON.stringify(payload) }),

  getJob: (jobId: string, includeResult = true): Promise<MonitoringJob> =>
    request<MonitoringJob>(
      `/api/jobs/${encodeURIComponent(jobId)}?include_result=${includeResult}`,
    ),

  listJobs: (params?: { area_id?: string; status?: string; limit?: number }): Promise<{
    count: number;
    jobs: MonitoringJob[];
  }> => {
    const query = new URLSearchParams();
    if (params?.area_id) query.set('area_id', params.area_id);
    if (params?.status) query.set('status', params.status);
    if (params?.limit) query.set('limit', String(params.limit));
    const qs = query.toString();
    return request(`/api/jobs${qs ? `?${qs}` : ''}`);
  },

  listAnomalies: (params?: {
    area_id?: string;
    severity?: string;
    min_confidence?: number;
    source?: string;
    limit?: number;
  }): Promise<AnomalyListResponse> => {
    const query = new URLSearchParams();
    if (params?.area_id) query.set('area_id', params.area_id);
    if (params?.severity) query.set('severity', params.severity);
    if (params?.min_confidence !== undefined) {
      query.set('min_confidence', String(params.min_confidence));
    }
    if (params?.source) query.set('source', params.source);
    if (params?.limit) query.set('limit', String(params.limit));
    const qs = query.toString();
    return request(`/api/anomalies${qs ? `?${qs}` : ''}`);
  },

  getAnomaly: (anomalyId: string): Promise<AnomalyRecord> =>
    request<AnomalyRecord>(`/api/anomalies/${encodeURIComponent(anomalyId)}`),
};