/**
 * SATGUARD — Centralized Typed API Client
 * Organized by intelligence and operational domain.
 * Connects directly to backend endpoints. No hardcoded mock values.
 */

import {
  CriticalLocation,
  OverviewStats,
  RiskAssessment,
  Sentinel1Observation,
  Sentinel1Change,
  Sentinel2Observation,
  EvidenceSnapshot,
  AnalystReport,
  Alert,
  MonitoringRun,
  TimelineEvent,
  SystemDataStatus,
  HistoricalAnalyticsReport,
  UserProfile,
  AuthTokenResponse,
  PaginatedAuditLogs,
  SystemReadiness,
  OperationalMetrics,
} from '../types/api';

const API_BASE = import.meta.env.VITE_API_URL || '';

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  
  const token = typeof window !== 'undefined' ? sessionStorage.getItem('satguard_token') : null;
  const authHeaders: Record<string, string> = token ? { 'Authorization': `Bearer ${token}` } : {};

  const headers = {
    'Content-Type': 'application/json',
    ...authHeaders,
    ...options.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorDetail = `Request failed: HTTP ${response.status} ${response.statusText}`;
    try {
      const errJson = await response.json();
      if (errJson?.detail) {
        errorDetail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // Ignore json parse error on non-json error responses
    }
    throw new Error(errorDetail);
  }

  return response.json() as Promise<T>;
}

export const api = {
  overview: {
    getStats: (): Promise<OverviewStats> => request<OverviewStats>('/api/overview'),
    getDataStatus: (): Promise<SystemDataStatus> => request<SystemDataStatus>('/api/data-status'),
  },

  locations: {
    list: (): Promise<CriticalLocation[]> => request<CriticalLocation[]>('/api/locations'),
    get: (id: string): Promise<CriticalLocation> => request<CriticalLocation>(`/api/locations/${id}`),
    create: (data: {
      name: string;
      latitude: number;
      longitude: number;
      location_type?: string;
      radius_m?: number;
      description?: string;
    }): Promise<CriticalLocation> =>
      request<CriticalLocation>('/api/locations', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    check: (id: string): Promise<any> => request<any>(`/api/locations/${id}/check`, { method: 'POST' }),
    process: (id: string): Promise<any> => request<any>(`/api/locations/${id}/process`, { method: 'POST' }),
  },

  optical: {
    getObservations: (locationId: string): Promise<Sentinel2Observation[]> =>
      request<Sentinel2Observation[]>(`/api/locations/${locationId}/observations`),
  },

  sar: {
    getObservations: (locationId: string): Promise<Sentinel1Observation[]> =>
      request<Sentinel1Observation[]>(`/api/locations/${locationId}/sentinel-1/observations`),
    getChanges: (locationId: string): Promise<Sentinel1Change[]> =>
      request<Sentinel1Change[]>(`/api/locations/${locationId}/sentinel-1/changes`),
  },

  evidence: {
    getSnapshots: (locationId: string): Promise<EvidenceSnapshot[]> =>
      request<EvidenceSnapshot[]>(`/api/locations/${locationId}/evidence/snapshots`),
    getSnapshot: (locationId: string, snapshotId: string): Promise<EvidenceSnapshot> =>
      request<EvidenceSnapshot>(`/api/locations/${locationId}/evidence/snapshots/${snapshotId}`),
    fuse: (locationId: string): Promise<EvidenceSnapshot> =>
      request<EvidenceSnapshot>(`/api/locations/${locationId}/evidence/fuse`, { method: 'POST' }),
  },

  risk: {
    getLatest: (locationId: string): Promise<RiskAssessment> =>
      request<RiskAssessment>(`/api/locations/${locationId}/risk/latest`),
    assess: (locationId: string): Promise<RiskAssessment> =>
      request<RiskAssessment>(`/api/locations/${locationId}/risk/assess`, { method: 'POST' }),
  },

  analyst: {
    getLatest: (locationId: string): Promise<AnalystReport> =>
      request<AnalystReport>(`/api/locations/${locationId}/analysis/latest`),
    generate: (locationId: string): Promise<AnalystReport> =>
      request<AnalystReport>(`/api/locations/${locationId}/analysis`, { method: 'POST' }),
  },

  alerts: {
    list: (params?: {
      location_id?: string;
      status?: string;
      priority?: string;
      limit?: number;
      offset?: number;
    }): Promise<Alert[]> => {
      const query = new URLSearchParams();
      if (params?.location_id) query.set('location_id', params.location_id);
      if (params?.status) query.set('status', params.status);
      if (params?.priority) query.set('priority', params.priority);
      if (params?.limit) query.set('limit', String(params.limit));
      if (params?.offset) query.set('offset', String(params.offset));
      const qs = query.toString();
      return request<Alert[]>(`/api/alerts${qs ? `?${qs}` : ''}`);
    },

    getLocationAlerts: (locationId: string): Promise<Alert[]> =>
      request<Alert[]>(`/api/locations/${locationId}/alerts`),

    get: (alertId: string): Promise<Alert> =>
      request<Alert>(`/api/alerts/${alertId}`),

    acknowledge: (alertId: string, note?: string, actor = 'operator'): Promise<any> =>
      request<any>(`/api/alerts/${alertId}/acknowledge`, {
        method: 'POST',
        body: JSON.stringify({ note, actor }),
      }),

    review: (alertId: string, note?: string, actor = 'operator'): Promise<any> =>
      request<any>(`/api/alerts/${alertId}/review`, {
        method: 'POST',
        body: JSON.stringify({ note, actor }),
      }),

    resolve: (alertId: string, note?: string, actor = 'operator'): Promise<any> =>
      request<any>(`/api/alerts/${alertId}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ note, actor }),
      }),
  },

  monitoring: {
    listRuns: (params?: {
      location_id?: string;
      status?: string;
      trigger_type?: string;
      limit?: number;
      offset?: number;
    }): Promise<MonitoringRun[]> => {
      const query = new URLSearchParams();
      if (params?.location_id) query.set('location_id', params.location_id);
      if (params?.status) query.set('status', params.status);
      if (params?.trigger_type) query.set('trigger_type', params.trigger_type);
      if (params?.limit) query.set('limit', String(params.limit));
      if (params?.offset) query.set('offset', String(params.offset));
      const qs = query.toString();
      return request<MonitoringRun[]>(`/api/monitoring/runs${qs ? `?${qs}` : ''}`);
    },

    getRun: (runId: string): Promise<MonitoringRun> =>
      request<MonitoringRun>(`/api/monitoring/runs/${runId}`),

    getStatus: (locationId: string): Promise<any> =>
      request<any>(`/api/locations/${locationId}/monitoring/status`),

    triggerRun: (locationId: string, triggerType = 'MANUAL_OPERATOR'): Promise<MonitoringRun> =>
      request<MonitoringRun>(`/api/locations/${locationId}/monitoring/run`, {
        method: 'POST',
        body: JSON.stringify({ trigger_type: triggerType }),
      }),
  },

  timeline: {
    getTimeline: (locationId: string): Promise<TimelineEvent[]> =>
      request<TimelineEvent[]>(`/api/locations/${locationId}/timeline`),
  },

  analytics: {
    getHistory: (locationId: string, days = 30): Promise<HistoricalAnalyticsReport> =>
      request<HistoricalAnalyticsReport>(`/api/locations/${locationId}/analytics/history?days=${days}`),

    getTrends: (locationId: string, days = 30): Promise<any> =>
      request<any>(`/api/locations/${locationId}/analytics/trends?days=${days}`),

    getBaseline: (locationId: string, days = 90): Promise<any> =>
      request<any>(`/api/locations/${locationId}/analytics/baseline?days=${days}`),

    getPersistence: (locationId: string, days = 30): Promise<any> =>
      request<any>(`/api/locations/${locationId}/analytics/persistence?days=${days}`),

    getRiskHistory: (locationId: string, days = 90): Promise<any> =>
      request<any>(`/api/locations/${locationId}/analytics/risk-history?days=${days}`),

    getAlertsHistory: (locationId: string, days = 90): Promise<any> =>
      request<any>(`/api/locations/${locationId}/analytics/alerts-history?days=${days}`),

    getLatest: (locationId: string): Promise<any> =>
      request<any>(`/api/locations/${locationId}/analytics/latest`),

    compare: (locationIds: string[], days = 30): Promise<any> =>
      request<any>(`/api/analytics/compare?location_ids=${encodeURIComponent(locationIds.join(','))}&days=${days}`),

    exportReport: (locationId: string, days = 30): Promise<any> =>
      request<any>(`/api/locations/${locationId}/analytics/report?days=${days}`),
  },

  auth: {
    login: (username: string, password: string): Promise<AuthTokenResponse> =>
      request<AuthTokenResponse>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
    getMe: (): Promise<UserProfile> => request<UserProfile>('/api/auth/me'),
    getUsers: (): Promise<UserProfile[]> => request<UserProfile[]>('/api/auth/users'),
    createUser: (userData: any): Promise<UserProfile> =>
      request<UserProfile>('/api/auth/users', {
        method: 'POST',
        body: JSON.stringify(userData),
      }),
    logout: (): void => {
      if (typeof window !== 'undefined') {
        sessionStorage.removeItem('satguard_token');
        sessionStorage.removeItem('satguard_user');
      }
    },
  },

  audit: {
    getLogs: (params?: {
      limit?: number;
      offset?: number;
      actor?: string;
      action?: string;
      resource?: string;
    }): Promise<PaginatedAuditLogs> => {
      const query = new URLSearchParams();
      if (params?.limit) query.set('limit', String(params.limit));
      if (params?.offset) query.set('offset', String(params.offset));
      if (params?.actor) query.set('actor', params.actor);
      if (params?.action) query.set('action', params.action);
      if (params?.resource) query.set('resource', params.resource);
      const qs = query.toString();
      return request<PaginatedAuditLogs>(`/api/audit/logs${qs ? `?${qs}` : ''}`);
    },
  },

  system: {
    getLiveness: (): Promise<any> => request<any>('/api/health/live'),
    getReadiness: (): Promise<SystemReadiness> => request<SystemReadiness>('/api/health/ready'),
    getMetrics: (): Promise<OperationalMetrics> => request<OperationalMetrics>('/api/metrics'),
  },
};
