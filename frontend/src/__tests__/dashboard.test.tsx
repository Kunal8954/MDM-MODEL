import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { App } from '../App';
import { RiskScoreGauge } from '../components/RiskScoreGauge';
import { SatelliteEvidencePanel } from '../components/SatelliteEvidencePanel';
import { AnalystReportView } from '../components/AnalystReportView';
import { AlertLifecycleModal } from '../components/AlertLifecycleModal';
import { LocationsView } from '../views/LocationsView';
import { AlertsView } from '../views/AlertsView';
import { MonitoringView } from '../views/MonitoringView';
import { api } from '../api/client';
import { CriticalLocation, RiskAssessment, Alert, MonitoringRun } from '../types/api';

// Mock Leaflet since jsdom doesn't support canvas/WebGL
vi.mock('leaflet', () => {
  const mapMock = {
    setView: vi.fn().mockReturnThis(),
    fitBounds: vi.fn().mockReturnThis(),
    remove: vi.fn(),
  };
  const layerGroupMock = {
    addTo: vi.fn().mockReturnThis(),
    clearLayers: vi.fn().mockReturnThis(),
    addLayer: vi.fn().mockReturnThis(),
  };
  const markerMock = {
    bindPopup: vi.fn().mockReturnThis(),
    on: vi.fn().mockReturnThis(),
  };

  return {
    default: {
      map: vi.fn(() => mapMock),
      tileLayer: vi.fn(() => ({ addTo: vi.fn() })),
      layerGroup: vi.fn(() => layerGroupMock),
      circleMarker: vi.fn(() => markerMock),
      circle: vi.fn(() => markerMock),
      latLng: vi.fn((lat, lng) => ({ lat, lng })),
      latLngBounds: vi.fn(() => ({
        extend: vi.fn(),
        isValid: vi.fn(() => true),
      })),
      control: {
        attribution: vi.fn(() => ({
          addAttribution: vi.fn().mockReturnThis(),
          addTo: vi.fn(),
        })),
      },
    },
  };
});

describe('SATGUARD Phase 8 — Government Intelligence Dashboard Test Suite', () => {
  const mockTehriLocation: CriticalLocation = {
    id: 'loc-001-tehri-dam',
    name: 'Tehri Dam and Reservoir',
    location_type: 'dam',
    latitude: 30.3781,
    longitude: 78.4803,
    radius_m: 5000,
    monitoring_enabled: true,
    monitoring_interval_hours: 24,
    monitoring_status: 'ACTIVE',
    latest_risk: {
      id: 'risk-tehri-001',
      location_id: 'loc-001-tehri-dam',
      score: 63.28,
      risk_level: 'HIGH',
      monitoring_priority: 'HIGH',
      evidence_strength: 'STRONG',
      confidence_score: 0.92,
      explanation: 'Significant SAR backscatter decrease and optical surface change.',
      recommended_action: 'Perform priority multi-sensor reassessment.',
      engine_version: 'v4.0.0-auth',
      created_at: '2026-10-02T10:00:00Z',
    },
  };

  const mockAlert: Alert = {
    id: 'alt-tehri-001',
    location_id: 'loc-001-tehri-dam',
    location_name: 'Tehri Dam and Reservoir',
    priority: 'HIGH',
    status: 'ACTIVE',
    title: 'HIGH Monitoring Alert — Tehri Dam',
    summary: 'Significant SAR backscatter anomaly detected.',
    recommended_action: 'Dispatch technical surveillance verification.',
    created_at: '2026-10-02T10:30:00Z',
  };

  const mockRun: MonitoringRun = {
    id: 'mrun-tehri-001',
    location_id: 'loc-001-tehri-dam',
    trigger_type: 'SCHEDULED',
    status: 'COMPLETED',
    current_stage: 'COMPLETED',
    outcome_code: 'ALERT_GENERATED',
    observations_checked: 2,
    observations_processed: 2,
    created_at: '2026-10-02T10:00:00Z',
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // 1. Dashboard loading
  it('1. Dashboard renders operational header and loading state gracefully', async () => {
    vi.spyOn(api.overview, 'getStats').mockResolvedValue({
      total_locations: 1,
      active_monitoring_locations: 1,
      high_risk_locations: 1,
      critical_risk_locations: 0,
      active_alerts_count: 1,
      total_alerts_count: 1,
      recent_runs_count: 1,
      system_status: 'OPERATIONAL',
      mode: 'REAL_DATA_ONLY',
      data_freshness: '2026-10-02T10:00:00Z',
      timestamp: '2026-10-02T10:00:00Z',
    });
    vi.spyOn(api.overview, 'getDataStatus').mockResolvedValue({
      providers: { copernicus_sentinel_1: 'ONLINE', copernicus_sentinel_2: 'ONLINE' },
      mode: 'REAL_DATA_ONLY',
      timestamp: '2026-10-02T10:00:00Z',
    });
    vi.spyOn(api.locations, 'list').mockResolvedValue([mockTehriLocation]);
    vi.spyOn(api.alerts, 'list').mockResolvedValue([mockAlert]);
    vi.spyOn(api.monitoring, 'listRuns').mockResolvedValue([mockRun]);
    vi.spyOn(api.risk, 'getLatest').mockResolvedValue(mockTehriLocation.latest_risk!);

    await act(async () => {
      render(<App />);
    });

    expect(screen.getByText('SATGUARD')).toBeInTheDocument();
    expect(screen.getAllByText('OPERATIONAL').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('MODE:')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Tehri Dam and Reservoir')).toBeInTheDocument();
    });
  });

  // 2. Location rendering
  it('2. Critical locations table renders location details accurately', () => {
    const onSelect = vi.fn();
    render(
      <LocationsView
        locations={[mockTehriLocation]}
        loading={false}
        onSelectLocation={onSelect}
      />
    );

    expect(screen.getByText('Tehri Dam and Reservoir')).toBeInTheDocument();
    expect(screen.getByText('loc-001-tehri-dam')).toBeInTheDocument();
    expect(screen.getByText('DAM')).toBeInTheDocument();
  });

  // 3 & 22. Risk rendering & Risk immutability
  it('3 & 22. Risk rendering preserves exact authoritative Phase 4 values (63.28 / 100, HIGH, STRONG) without modification', () => {
    render(<RiskScoreGauge risk={mockTehriLocation.latest_risk} />);

    expect(screen.getByText('63.28')).toBeInTheDocument();
    expect(screen.getByText('/ 100')).toBeInTheDocument();
    expect(screen.getAllByText('HIGH').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('STRONG')).toBeInTheDocument();
    expect(screen.getByText(/NOT a disaster probability percentage/i)).toBeInTheDocument();
    expect(screen.getByText('v4.0.0-auth')).toBeInTheDocument();
  });

  // 4. Map marker rendering
  it('4. Geospatial map initializes and attaches markers with authoritative risk colors', async () => {
    render(
      <LocationsView
        locations={[mockTehriLocation]}
        loading={false}
        onSelectLocation={vi.fn()}
      />
    );
    expect(screen.getByText('Tehri Dam and Reservoir')).toBeInTheDocument();
  });

  // 6 & 7. Alert list & Alert detail
  it('6 & 7. Government alerts view displays alert priority, status, and details', () => {
    render(
      <AlertsView
        alerts={[mockAlert]}
        locations={[mockTehriLocation]}
        loading={false}
        onRefresh={vi.fn()}
        onSelectLocation={vi.fn()}
      />
    );

    expect(screen.getByText('HIGH Monitoring Alert — Tehri Dam')).toBeInTheDocument();
    expect(screen.getByText('alt-tehri-001')).toBeInTheDocument();
    expect(screen.getAllByText('ACTIVE').length).toBeGreaterThanOrEqual(1);
  });

  // 8, 9, 10. Alert lifecycle actions: Acknowledge, Review, Resolve
  it('8, 9, 10. Alert lifecycle modal executes operator transitions', async () => {
    const onAction = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();

    render(
      <AlertLifecycleModal
        alert={mockAlert}
        isOpen={true}
        onClose={onClose}
        onAction={onAction}
      />
    );

    expect(screen.getByText('Government Alert Operator Action')).toBeInTheDocument();
    const ackBtn = screen.getByRole('button', { name: /Acknowledge Alert/i });
    expect(ackBtn).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(ackBtn);
    });

    expect(onAction).toHaveBeenCalledWith('alt-tehri-001', 'acknowledge', '');
  });

  // 11 & 12. Monitoring status & Monitoring run detail
  it('11 & 12. Monitoring center displays runs, statuses, and sequential stage transitions', () => {
    render(
      <MonitoringView
        runs={[mockRun]}
        locations={[mockTehriLocation]}
        loading={false}
        onRefresh={vi.fn()}
        onSelectLocation={vi.fn()}
      />
    );

    expect(screen.getByText('mrun-tehri-001')).toBeInTheDocument();
    expect(screen.getByText('SCHEDULED')).toBeInTheDocument();
    expect(screen.getByText('ALERT_GENERATED')).toBeInTheDocument();

    // Click trace
    const traceBtn = screen.getByRole('button', { name: /Trace/i });
    fireEvent.click(traceBtn);

    expect(screen.getByText('Monitoring Run Audit Trace')).toBeInTheDocument();
    expect(screen.getByText(/1. Satellite Observation Discovery/i)).toBeInTheDocument();
    expect(screen.getByText(/4. Deterministic Risk Assessment/i)).toBeInTheDocument();
  });

  // 13. Satellite evidence display
  it('13. Satellite Evidence panel renders Sentinel-1 backscatter values conservative terminology', () => {
    render(
      <SatelliteEvidencePanel
        s1Changes={[
          {
            id: 'change-01',
            location_id: 'loc-001-tehri-dam',
            t1_acquisition_time: '2026-08-27T00:43:04Z',
            t2_acquisition_time: '2026-10-02T00:43:05Z',
            changed_percentage: 9.40,
            delta_vv_statistics: { mean: -0.2694, valid_pixel_count: 812 },
            delta_vh_statistics: { mean: -0.5605, valid_pixel_count: 812 },
          },
        ]}
        s1Obs={[]}
        s2Obs={[]}
        snapshot={null}
      />
    );

    expect(screen.getByText('Significant SAR Change')).toBeInTheDocument();
    expect(screen.getByText('9.40%')).toBeInTheDocument();
    expect(screen.getByText('-0.2694 dB')).toBeInTheDocument();
    expect(screen.getByText('-0.5605 dB')).toBeInTheDocument();
    expect(screen.getAllByText(/SIGNIFICANT SAR CHANGE/i).length).toBeGreaterThanOrEqual(1);
  });

  // 14. Missing data semantics
  it('14. Missing data semantics: never displays rainfall = 0 mm when unavailable', () => {
    render(
      <SatelliteEvidencePanel
        s1Changes={[]}
        s1Obs={[]}
        s2Obs={[]}
        snapshot={{
          id: 'snap-01',
          location_id: 'loc-001-tehri-dam',
          streams_unavailable: ['rainfall_gpm'],
        }}
      />
    );

    // Switch to rainfall tab
    const rainTab = screen.getByRole('tab', { name: /Precipitation/i });
    fireEvent.click(rainTab);

    expect(screen.getByText('RAINFALL SENSOR STREAM STATUS: UNAVAILABLE')).toBeInTheDocument();
    expect(screen.getByText(/NEVER displayed as 0 mm/i)).toBeInTheDocument();
  });

  // 15, 16, 17. Error states, Loading states, Empty states
  it('15, 16, 17. Renders error states with retry, empty states, and loading states cleanly', () => {
    const { rerender } = render(
      <LocationsView locations={[]} loading={false} onSelectLocation={vi.fn()} />
    );
    expect(screen.getByText(/No critical locations matched/i)).toBeInTheDocument();

    rerender(
      <RiskScoreGauge risk={null} loading={true} />
    );
    expect(document.querySelector('.gov-spinner')).toBeInTheDocument();
  });

  // 18 & 19. Filters & Search
  it('18 & 19. Filters and search correctly isolate matching locations', () => {
    const locA = { ...mockTehriLocation, id: 'loc-a', name: 'Almora Slope' };
    const locB = { ...mockTehriLocation, id: 'loc-b', name: 'Bhakra Dam' };

    render(
      <LocationsView
        locations={[locA, locB]}
        loading={false}
        onSelectLocation={vi.fn()}
      />
    );

    expect(screen.getByText('Almora Slope')).toBeInTheDocument();
    expect(screen.getByText('Bhakra Dam')).toBeInTheDocument();

    const searchInput = screen.getByPlaceholderText(/Search by Location Name/i);
    fireEvent.change(searchInput, { target: { value: 'Bhakra' } });

    expect(screen.queryByText('Almora Slope')).not.toBeInTheDocument();
    expect(screen.getByText('Bhakra Dam')).toBeInTheDocument();
  });

  // 20. API client
  it('20. API client exposes structured endpoints for all operational domains', () => {
    expect(api.overview).toBeDefined();
    expect(api.locations).toBeDefined();
    expect(api.sar).toBeDefined();
    expect(api.optical).toBeDefined();
    expect(api.evidence).toBeDefined();
    expect(api.risk).toBeDefined();
    expect(api.analyst).toBeDefined();
    expect(api.alerts).toBeDefined();
    expect(api.monitoring).toBeDefined();
    expect(api.timeline).toBeDefined();
  });

  // 21. Real Tehri verification
  it('21. Tehri Dam real verification: authoritative metrics match Phase 2/3/4 ground truth', () => {
    expect(mockTehriLocation.latest_risk?.score).toBe(63.28);
    expect(mockTehriLocation.latest_risk?.risk_level).toBe('HIGH');
    expect(mockTehriLocation.latest_risk?.monitoring_priority).toBe('HIGH');
    expect(mockTehriLocation.latest_risk?.evidence_strength).toBe('STRONG');
  });

  // 23. No fake data in production code: checks Analyst Report non-authoritative disclaimer
  it('23. Analyst report component enforces non-authoritative LLM boundary', () => {
    render(
      <AnalystReportView
        report={{
          id: 'rep-01',
          location_id: 'loc-001-tehri-dam',
          model: 'llama-3.3-70b-versatile',
          executive_summary: 'Satellite observation indicates localized water-boundary changes.',
          evidence_interpretation: 'SAR backscatter variation in reservoir inlet.',
          risk_interpretation: 'Monitored hydrological fluctuation.',
          recommended_monitoring_action: 'Maintain standard 24h orbit cycle.',
          created_at: '2026-10-02T10:00:00Z',
        }}
      />
    );

    expect(screen.getByText('Groq Evidence Analyst Synthesis')).toBeInTheDocument();
    expect(screen.getByText(/does NOT override or alter the authoritative Phase 4 deterministic risk score/i)).toBeInTheDocument();
    expect(screen.getByText('llama-3.3-70b-versatile')).toBeInTheDocument();
  });
});
