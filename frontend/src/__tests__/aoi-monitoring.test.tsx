/**
 * Tests for the arbitrary-AOI monitoring view.
 *
 * The behaviours worth protecting: DEMO results are labelled as synthetic, a LIVE failure
 * is surfaced rather than replaced with demo data, and detection confidence, anomaly
 * confidence and severity are shown as three separate things.
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { AoiMonitoringView } from '../views/AoiMonitoringView';
import {
  AnomalyRecord,
  DemoSite,
  MonitoringArea,
  MonitoringJob,
  MonitoringRunResult,
} from '../types/monitoring';

const DEMO_SITES: DemoSite[] = [
  {
    name: 'tehri_dam_construction',
    monitoring_mode: 'infrastructure',
    scenario: 'new_construction',
    description: 'New built-up construction beside an existing dam.',
    bounds: [78.58, 30.28, 78.72, 30.4],
  },
];

const AREA: MonitoringArea = {
  id: 'aoi-test-1234',
  user_label: 'DEMO exploration area',
  monitoring_mode: 'infrastructure',
  geometry: { type: 'Polygon', coordinates: [[[78.58, 30.28], [78.72, 30.28], [78.72, 30.4]]] },
  bbox: [78.58, 30.28, 78.72, 30.4],
  center: { lon: 78.65, lat: 30.34 },
  area_km2: 179.08,
  crs: 'EPSG:4326',
  source: 'DEMO',
  created_at: '2026-10-04T00:00:00Z',
  metadata: { sensor_strategy: 'OPTICAL + SAR', required_indices: ['ndbi'] },
};

const ANOMALY: AnomalyRecord = {
  id: 'anom-1',
  area_id: AREA.id,
  run_id: 'run-1',
  region_id: 'region-0001',
  monitoring_mode: 'infrastructure',
  geometry: { type: 'Polygon', coordinates: [[[78.6, 30.3], [78.62, 30.3], [78.62, 30.32]]] },
  bbox: [78.6, 30.3, 78.62, 30.32],
  centroid: { lon: 78.61, lat: 30.31 },
  area_m2: 8_405_980,
  area_km2: 8.406,
  area_ha: 840.6,
  pixel_count: 676,
  detection_confidence: 0.8875,
  anomaly_confidence: 0.87,
  severity: 'critical',
  layer_agreement: { ndbi: 0.9 },
  evidence: [
    {
      source: 'detector',
      observation: 'Spatial extent of the change mask',
      value: 8.406,
      unit: 'km2',
      interpretation: '676 pixels changed.',
    },
  ],
  caveats: ['Single-scene comparison cannot confirm persistence.'],
  source: 'DEMO',
  detected_at: '2026-10-04T00:00:00Z',
};

const RESULT: MonitoringRunResult = {
  aoi_id: AREA.id,
  monitoring_mode: 'infrastructure',
  source: 'DEMO',
  crs: 'EPSG:4326',
  bounds: AREA.bbox,
  run_confidence: {
    detection_confidence: 0.8875,
    components: { usable_data: 1, cloud_screening: 1 },
    caveats: ['Only two dates were compared.'],
  },
  run_severity: 'high',
  max_anomaly_severity: 'critical',
  anomaly_count: 1,
  total_area_km2: 179.08,
  anomalies: [ANOMALY],
  detection: {},
  generated_at: '2026-10-04T00:00:00Z',
  provenance: {
    source: 'DEMO',
    synthetic: true,
    note: 'Synthetic demonstration data. Not satellite observations.',
    baseline: 'S2A demo',
    current: 'S2A demo',
    demo_truth: { changed_pixels: 676, intersection_over_union: 1.0 },
  },
};

const JOB: MonitoringJob = {
  job_id: 'mjob-1',
  area_id: AREA.id,
  source: 'DEMO',
  monitoring_mode: 'infrastructure',
  status: 'COMPLETED',
  stage: 'COMPLETED',
  progress_percent: 100,
  stage_history: [
    { stage: 'ACQUIRING', percent: 15, at: '2026-10-04T00:00:00Z' },
    { stage: 'COMPLETED', percent: 100, at: '2026-10-04T00:00:10Z' },
  ],
  anomaly_count: 1,
  error_code: null,
  error_message: null,
  created_at: '2026-10-04T00:00:00Z',
  started_at: '2026-10-04T00:00:01Z',
  completed_at: '2026-10-04T00:00:10Z',
  is_terminal: true,
  result: RESULT,
};

/** Builds a stub client; every test overrides only the calls it exercises. */
function makeApi(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    getDemoSites: vi.fn().mockResolvedValue({ source: 'DEMO', disclaimer: 'synthetic', sites: DEMO_SITES }),
    getDemoScenarios: vi.fn().mockResolvedValue({ scenarios: ['new_construction'] }),
    createArea: vi.fn().mockResolvedValue(AREA),
    listAreas: vi.fn().mockResolvedValue({ count: 1, areas: [AREA] }),
    getArea: vi.fn().mockResolvedValue(AREA),
    deleteArea: vi.fn().mockResolvedValue(undefined),
    run: vi.fn().mockResolvedValue(RESULT),
    queueRun: vi.fn().mockResolvedValue({
      job_id: 'mjob-1', status: 'QUEUED', stage: 'QUEUED', progress_percent: 0,
      area_id: AREA.id, source: 'DEMO',
    }),
    getJob: vi.fn().mockResolvedValue(JOB),
    listJobs: vi.fn().mockResolvedValue({ count: 0, jobs: [] }),
    listAnomalies: vi.fn().mockResolvedValue({
      count: 1,
      summary_by_severity: {
        critical: { count: 1, area_km2: 8.406 },
        high: { count: 0, area_km2: 0 },
        moderate: { count: 0, area_km2: 0 },
        low: { count: 0, area_km2: 0 },
        none: { count: 0, area_km2: 0 },
      },
      anomalies: [ANOMALY],
    }),
    getAnomaly: vi.fn().mockResolvedValue(ANOMALY),
    ...overrides,
  } as any;
}

describe('AoiMonitoringView', () => {
  beforeEach(() => {
    vi.useRealTimers();
  });

  it('labels DEMO as synthetic and shows the disclaimer before any run', async () => {
    render(<AoiMonitoringView api={makeApi()} pollIntervalMs={10} />);

    await waitFor(() => expect(screen.getAllByText('DEMO').length).toBeGreaterThan(0));
    expect(screen.getByText(/renders synthetic data/i)).toBeInTheDocument();
  });

  it('creates an area from a bounding box the user typed', async () => {
    const api = makeApi();
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    const input = await screen.findByLabelText('Geometry value');
    await userEvent.clear(input);
    await userEvent.type(input, '78.58,30.28,78.72,30.4');
    await userEvent.click(screen.getByRole('button', { name: /create area/i }));

    await waitFor(() => expect(api.createArea).toHaveBeenCalled());
    const payload = api.createArea.mock.calls[0][0];
    expect(payload.bbox).toEqual([78.58, 30.28, 78.72, 30.4]);
    expect(payload.source).toBe('DEMO');
    expect(payload.monitoring_mode).toBe('general');
  });

  it('creates an area from a point as longitude and latitude', async () => {
    const api = makeApi();
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.selectOptions(await screen.findByLabelText('Geometry type'), 'point');
    const input = screen.getByLabelText('Geometry value');
    await userEvent.clear(input);
    await userEvent.type(input, '78.6,30.3');
    await userEvent.click(screen.getByRole('button', { name: /create area/i }));

    await waitFor(() => expect(api.createArea).toHaveBeenCalled());
    expect(api.createArea.mock.calls[0][0].point).toEqual({
      longitude: 78.6, latitude: 30.3, radius_m: 1000,
    });
  });

  it('builds an area from a sample DEMO site without losing the DEMO label', async () => {
    const api = makeApi();
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.click(await screen.findByText('tehri_dam_construction'));

    await waitFor(() => expect(api.createArea).toHaveBeenCalled());
    const payload = api.createArea.mock.calls[0][0];
    expect(payload.source).toBe('DEMO');
    expect(payload.bbox).toEqual(DEMO_SITES[0].bounds);
    expect(payload.monitoring_mode).toBe('infrastructure');
  });

  it('shows job progress while a run is in flight', async () => {
    const running: MonitoringJob = {
      ...JOB, status: 'RUNNING', stage: 'DETECTING', progress_percent: 75,
      is_terminal: false, result: undefined, anomaly_count: 0,
    };
    const api = makeApi({ getJob: vi.fn().mockResolvedValue(running) });
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.click(await screen.findByRole('button', { name: /run monitoring/i }));

    const progress = await screen.findByTestId('job-progress');
    // The first poll may land before the status has advanced past QUEUED.
    await within(progress).findByText('RUNNING');
    expect(within(progress).getByText('75%')).toBeInTheDocument();
    const reached = progress.querySelectorAll('.is-reached');
    expect(reached.length).toBeGreaterThan(0);
  });

  it('reports the three confidence measures separately', async () => {
    const api = makeApi();
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.click(await screen.findByRole('button', { name: /run monitoring/i }));

    await userEvent.click(await screen.findByText('region-0001'));

    const detail = await screen.findByTestId('anomaly-detail');
    // Anomaly confidence and run confidence are different numbers and both are shown.
    expect(within(detail).getByText('Anomaly confidence')).toBeInTheDocument();
    expect(within(detail).getByText('Run confidence')).toBeInTheDocument();
    expect(within(detail).getByText('87%')).toBeInTheDocument();
    expect(within(detail).getByText('89%')).toBeInTheDocument();
  });

  it('surfaces a LIVE failure instead of showing demonstration results', async () => {
    const { MonitoringApiError } = await import('../api/monitoring');
    const failed: MonitoringJob = {
      ...JOB, status: 'FAILED', stage: 'ACQUIRING', progress_percent: 15,
      is_terminal: true, result: undefined, anomaly_count: 0,
      error_code: 'LIVE_DATA_UNAVAILABLE',
      error_message: 'LIVE mode requires a Sentinel Hub acquirer.',
    };
    const api = makeApi({ getJob: vi.fn().mockResolvedValue(failed) });
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.selectOptions(await screen.findByLabelText('Data source'), 'LIVE');
    await userEvent.click(screen.getByRole('button', { name: /run monitoring/i }));

    const jobError = await screen.findByTestId('job-error');
    expect(jobError).toHaveTextContent('LIVE_DATA_UNAVAILABLE');
    // No run summary, because no result was produced.
    expect(screen.queryByTestId('run-summary')).not.toBeInTheDocument();
    expect(MonitoringApiError).toBeDefined();
  });

  it('shows the synthetic-data note and accuracy against truth for a DEMO run', async () => {
    const api = makeApi();
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.click(await screen.findByRole('button', { name: /run monitoring/i }));

    const summary = await screen.findByTestId('run-summary');
    // The synthetic-data note sits beside the summary, not inside it.
    expect(screen.getByText(/Not satellite observations/)).toBeInTheDocument();
    expect(within(summary).getByText(/IoU 100%/)).toBeInTheDocument();
  });

  it('orders anomalies by severity rather than alphabetically', async () => {
    const low: AnomalyRecord = {
      ...ANOMALY, id: 'anom-low', region_id: 'region-low', severity: 'low', area_m2: 900,
    };
    const critical: AnomalyRecord = { ...ANOMALY, id: 'anom-crit', region_id: 'region-crit' };
    const api = makeApi({
      listAnomalies: vi.fn().mockResolvedValue({
        count: 2,
        summary_by_severity: {
          critical: { count: 1, area_km2: 8.4 }, high: { count: 0, area_km2: 0 },
          moderate: { count: 0, area_km2: 0 }, low: { count: 1, area_km2: 0 },
          none: { count: 0, area_km2: 0 },
        },
        // Deliberately out of order: alphabetical sorting would put "low" after "crit".
        anomalies: [low, critical],
      }),
    });
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.click(await screen.findByRole('button', { name: /run monitoring/i }));

    await waitFor(() => expect(screen.getByText('region-crit')).toBeInTheDocument());
    const rows = screen.getAllByRole('row').filter((r) => r.textContent?.includes('region-'));
    expect(rows[0]).toHaveTextContent('region-crit');
    expect(rows[1]).toHaveTextContent('region-low');
  });

  it('refuses to create an under-specified polygon instead of guessing', async () => {
    const api = makeApi();
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.selectOptions(await screen.findByLabelText('Geometry type'), 'polygon');
    expect(screen.getByTestId('polygon-vertex-count')).toHaveTextContent('0 vertices');
    await userEvent.click(screen.getByRole('button', { name: /create area/i }));

    expect(await screen.findByText(/at least three vertices/i)).toBeInTheDocument();
    expect(api.createArea).not.toHaveBeenCalled();
  });

  it('deletes an area and clears the selection', async () => {
    const api = makeApi();
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.click(await screen.findByRole('button', { name: /delete/i }));

    await waitFor(() => expect(api.deleteArea).toHaveBeenCalledWith(AREA.id));
    await waitFor(() => expect(screen.queryByText(AREA.user_label)).not.toBeInTheDocument());
  });

  it('keeps the evidence behind each anomaly reachable', async () => {
    const api = makeApi();
    render(<AoiMonitoringView api={api} pollIntervalMs={10} />);

    await userEvent.click(await screen.findByRole('button', { name: /run monitoring/i }));
    await userEvent.click(await screen.findByText('region-0001'));

    const detail = await screen.findByTestId('anomaly-detail');
    expect(within(detail).getByText('Spatial extent of the change mask')).toBeInTheDocument();
    expect(within(detail).getByText(/676 pixels changed/)).toBeInTheDocument();
    expect(within(detail).getByText(/cannot confirm persistence/)).toBeInTheDocument();
  });
});