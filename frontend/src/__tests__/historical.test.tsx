import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { HistoricalIntelligencePanel } from '../components/HistoricalIntelligencePanel';
import { api } from '../api/client';
import { HistoricalAnalyticsReport } from '../types/api';

describe('SATGUARD Phase 9 — Historical Intelligence Panel Test Suite', () => {
  const mockReport: HistoricalAnalyticsReport = {
    id: 'hist_loc-001-tehri-dam_12345',
    location_id: 'loc-001-tehri-dam',
    location_name: 'Tehri Dam and Reservoir',
    window: {
      days: 30,
      start_time: '2026-09-04T00:00:00Z',
      end_time: '2026-10-04T00:00:00Z',
    },
    data_sufficiency: 'SUFFICIENT',
    persistence: {
      persistence_status: 'PERSISTENT_SIGNAL',
      significant_observations_count: 3,
      total_evaluated_observations: 3,
      signal_ratio: 1.0,
      consecutive_significant_count: 3,
      explanation: 'Persistent change signal detected: 3/3 observations showed significant change.',
    },
    sar_trends: {
      observation_count: 3,
      valid_change_count: 3,
      mean_delta_vv: -0.2694,
      median_delta_vv: -0.2694,
      mean_delta_vh: -0.5605,
      median_delta_vh: -0.5605,
      mean_changed_percentage: 24.91,
      max_changed_percentage: 31.44,
      signal_trend: 'STABLE',
      points: [
        {
          change_id: 'ch-1',
          observation_id: 'obs-1',
          delta_vv_mean: -0.25,
          delta_vh_mean: -0.55,
          changed_percentage: 24.5,
          is_significant_change: true,
        },
        {
          change_id: 'ch-2',
          observation_id: 'obs-2',
          delta_vv_mean: -0.27,
          delta_vh_mean: -0.56,
          changed_percentage: 25.1,
          is_significant_change: true,
        },
      ],
    },
    optical_trends: {
      total_scenes: 4,
      usable_scenes: 3,
      cloud_obscured_scenes: 1,
      mean_cloud_cover: 18.5,
      optical_stability: 'STABLE',
      points: [
        {
          observation_id: 's2-1',
          acquisition_time: '2026-09-10T05:00:00Z',
          cloud_cover: 12.0,
          is_cloud_obscured: false,
          quality_status: 'USABLE',
        },
      ],
    },
    environmental_history: {
      rainfall_status: 'UNAVAILABLE',
      rainfall_observation_count: 0,
      rainfall_mean_mm: null,
      fire_status: 'VALID_ZERO_OBSERVATION',
      fire_detection_count: 0,
      seismic_status: 'NO_EVENTS_DETECTED',
      seismic_event_count: 0,
      nearest_earthquake_distance_km: null,
    },
    risk_trends: {
      assessment_count: 4,
      latest_score: 63.28,
      average_score: 58.4,
      min_score: 52.0,
      max_score: 65.0,
      score_delta: 5.28,
      level_transitions_count: 1,
      high_level_count: 3,
      critical_level_count: 0,
      classification: 'INCREASING',
      points: [
        {
          risk_assessment_id: 'risk-1',
          timestamp: '2026-09-05T00:00:00Z',
          score: 55.0,
          risk_level: 'MODERATE',
          monitoring_priority: 'ELEVATED',
          evidence_strength: 'MODERATE',
          confidence_score: 0.9,
          engine_version: 'risk_engine_v1',
        },
        {
          risk_assessment_id: 'risk-2',
          timestamp: '2026-10-02T00:00:00Z',
          score: 63.28,
          risk_level: 'HIGH',
          monitoring_priority: 'HIGH',
          evidence_strength: 'STRONG',
          confidence_score: 0.95,
          engine_version: 'risk_engine_v1',
        },
      ],
    },
    alert_trends: {
      total_alerts: 1,
      active_alerts: 1,
      acknowledged_alerts: 0,
      in_review_alerts: 0,
      resolved_alerts: 0,
      recurrence_detected: false,
      recurrence_pattern: null,
      points: [],
    },
    baseline_comparison: {
      comparison_status: 'ABOVE_BASELINE',
      current_value: 63.28,
      baseline_mean: 58.4,
      baseline_median: 58.0,
      deviation_value: 1.85,
      deviation_status: 'UNUSUAL_RELATIVE_TO_BASELINE',
      explanation: 'Current value (63.28) is unusual relative to historical baseline.',
    },
    engine_version: 'analytics_v1',
    disclaimer: 'Historical trend analysis is an operational monitoring tool. It does NOT claim exact disaster prediction.',
    generated_at: '2026-10-04T12:00:00Z',
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('1. Renders historical intelligence panel and loads report', async () => {
    vi.spyOn(api.analytics, 'getHistory').mockResolvedValue(mockReport);

    render(
      <HistoricalIntelligencePanel
        locationId="loc-001-tehri-dam"
        locationName="Tehri Dam and Reservoir"
      />
    );

    expect(screen.getByText(/HISTORICAL INTELLIGENCE & TREND ANALYTICS/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/PERSISTENT SIGNAL/i)).toBeInTheDocument();
      expect(screen.getByText(/UNUSUAL RELATIVE TO BASELINE/i)).toBeInTheDocument();
      expect(screen.getByText(/SUFFICIENT/i)).toBeInTheDocument();
    });
  });

  it('2. Renders time window selector buttons (7D, 30D, 90D, 180D, 1Y)', async () => {
    const getHistorySpy = vi.spyOn(api.analytics, 'getHistory').mockResolvedValue(mockReport);

    render(
      <HistoricalIntelligencePanel
        locationId="loc-001-tehri-dam"
        locationName="Tehri Dam and Reservoir"
      />
    );

    await waitFor(() => {
      expect(screen.getByText('7D')).toBeInTheDocument();
      expect(screen.getByText('30D')).toBeInTheDocument();
      expect(screen.getByText('90D')).toBeInTheDocument();
      expect(screen.getByText('180D')).toBeInTheDocument();
      expect(screen.getByText('1Y')).toBeInTheDocument();
    });

    // Clicking 90D triggers reload with days=90
    await act(async () => {
      fireEvent.click(screen.getByText('90D'));
    });
    expect(getHistorySpy).toHaveBeenCalledWith('loc-001-tehri-dam', 90);
  });

  it('3. Preserves strict missing rainfall semantics (UNAVAILABLE)', async () => {
    vi.spyOn(api.analytics, 'getHistory').mockResolvedValue(mockReport);

    render(
      <HistoricalIntelligencePanel
        locationId="loc-001-tehri-dam"
        locationName="Tehri Dam and Reservoir"
      />
    );

    await waitFor(() => {
      // Must display UNAVAILABLE, not 0 mm
      const unavailables = screen.getAllByText('UNAVAILABLE');
      expect(unavailables.length).toBeGreaterThan(0);
    });
  });

  it('4. Renders conservative scientific integrity notice', async () => {
    vi.spyOn(api.analytics, 'getHistory').mockResolvedValue(mockReport);

    render(
      <HistoricalIntelligencePanel
        locationId="loc-001-tehri-dam"
        locationName="Tehri Dam and Reservoir"
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/SCIENTIFIC INTEGRITY & DECISION-SUPPORT NOTICE/i)).toBeInTheDocument();
      expect(screen.getByText(/does NOT claim exact disaster prediction/i)).toBeInTheDocument();
    });
  });
});
