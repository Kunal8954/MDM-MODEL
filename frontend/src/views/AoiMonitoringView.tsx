import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Crosshair,
  Layers,
  Loader2,
  MapPin,
  Pencil,
  Play,
  Ruler,
  Trash2,
  XCircle,
} from 'lucide-react';
import { monitoringApi, MonitoringApiError } from '../api/monitoring';
import { GeospatialMap } from '../components/GeospatialMap';
import {
  AnomalyRecord,
  AnomalyRegion,
  DemoSite,
  MonitoringArea,
  MonitoringJob,
  MonitoringMode,
  MonitoringRunResult,
  MonitoringSource,
  MONITORING_MODES,
  SEVERITY_ORDER,
  Severity,
} from '../types/monitoring';

type GeometryKind = 'point' | 'bbox' | 'polygon' | 'geojson' | 'place';

/** Stages the backend reports, used to render the progress list in pipeline order. */
const PIPELINE_STAGES = ['ACQUIRING', 'PREPROCESSING', 'SUPPRESSING', 'DETECTING',
                         'EXTRACTING', 'PERSISTING', 'COMPLETED'];

const SEVERITY_CLASS: Record<Severity, string> = {
  critical: 'sev-crit',
  high: 'sev-high',
  moderate: 'sev-mod',
  low: 'sev-low',
  none: 'sev-none',
};

const pct = (value: number | undefined) =>
  value === undefined || value === null ? '—' : `${Math.round(value * 100)}%`;

interface Props {
  /** Injected in tests; defaults to the real client. */
  api?: typeof monitoringApi;
  pollIntervalMs?: number;
}

/**
 * Arbitrary-AOI monitoring.
 *
 * The AOI is whatever the user supplies, not a fixed site list. DEMO and LIVE are separate,
 * labelled paths: DEMO results carry a synthetic-data banner and their DEMO provenance is
 * shown, and a LIVE request that cannot reach real data surfaces the failure rather than
 * quietly rendering demonstration imagery.
 */
export const AoiMonitoringView: React.FC<Props> = ({
  api = monitoringApi,
  pollIntervalMs = 700,
}) => {
  const [areas, setAreas] = useState<MonitoringArea[]>([]);
  const [selectedArea, setSelectedArea] = useState<MonitoringArea | null>(null);
  const [anomalies, setAnomalies] = useState<AnomalyRecord[]>([]);
  const [job, setJob] = useState<MonitoringJob | null>(null);
  const [result, setResult] = useState<MonitoringRunResult | null>(null);
  const [selectedAnomaly, setSelectedAnomaly] = useState<AnomalyRegion | null>(null);

  const [demoSites, setDemoSites] = useState<DemoSite[]>([]);
  const [source, setSource] = useState<MonitoringSource>('DEMO');
  const [mode, setMode] = useState<MonitoringMode>('general');
  const [geometryKind, setGeometryKind] = useState<GeometryKind>('bbox');
  const [polygonPoints, setPolygonPoints] = useState<[number, number][]>([]);
  const [textInput, setTextInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /**
   * Anomalies in the shape the map draws, taken from the same records the results table
   * shows so a polygon and its row always refer to one finding. The map is coloured by
   * anomaly confidence, so a weak detection stays visibly weaker than a strong one
   * instead of being flattened into a severity bucket.
   */
  const mapAnomalies = useMemo(
    () =>
      anomalies.map((anomaly) => ({
        regionId: anomaly.region_id,
        geometry: anomaly.geometry,
        anomalyConfidence: anomaly.anomaly_confidence,
        areaKm2: anomaly.area_km2,
      })),
    [anomalies]
  );

  useEffect(() => {
    api.getDemoSites()
      .then((data) => setDemoSites(data.sites))
      .catch(() => setDemoSites([]));
    api.listAreas()
      .then((data) => {
        setAreas(data.areas);
        if (data.areas.length > 0) setSelectedArea(data.areas[0]);
      })
      .catch(() => setAreas([]));
    // Areas are re-fetched after every mutation instead.
  }, [api]);

  // Stop polling when the component unmounts so a run cannot outlive the view.
  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  const describeError = useCallback((err: unknown): string => {
    if (err instanceof MonitoringApiError) {
      return err.isLiveDataUnavailable
        ? `LIVE data unavailable: ${err.message}`
        : err.message;
    }
    return err instanceof Error ? err.message : String(err);
  }, []);

  const refreshAnomalies = useCallback(async (areaId: string) => {
    try {
      const data = await api.listAnomalies({ area_id: areaId, limit: 200 });
      setAnomalies(data.anomalies);
    } catch {
      setAnomalies([]);
    }
  }, [api]);

  const buildPayload = useCallback(() => {
    const raw = textInput.trim();
    switch (geometryKind) {
      case 'point': {
        const [lon, lat] = raw.split(',').map((v) => Number(v.trim()));
        return { point: { longitude: lon, latitude: lat, radius_m: 1000 } };
      }
      case 'bbox': {
        const nums = raw.split(',').map((v) => Number(v.trim()));
        return { bbox: nums as [number, number, number, number] };
      }
      case 'polygon': {
        if (polygonPoints.length < 3) {
          throw new Error('A polygon needs at least three vertices. Click the map to add them.');
        }
        // Close the ring; the backend expects a valid linear ring.
        const ring = polygonPoints.map(([lon, lat]) => [lon, lat]);
        return { polygon: [[...ring, ring[0]]] };
      }
      case 'geojson':
        return { geometry: JSON.parse(raw) };
      case 'place':
        return { place_name: raw };
      default:
        return {};
    }
  }, [geometryKind, polygonPoints, textInput]);

  const handleCreateArea = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const geometry = buildPayload();
      const area = await api.createArea({
        monitoring_mode: mode,
        user_label: source === 'DEMO' ? 'DEMO exploration area' : 'Monitoring area',
        source,
        ...(geometry as object),
      });
      setAreas((prev) => [area, ...prev.filter((a) => a.id !== area.id)]);
      setSelectedArea(area);
      setAnomalies([]);
      setResult(null);
      setSelectedAnomaly(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }, [api, buildPayload, describeError, mode, source]);

  const handleUseDemoSite = useCallback(async (site: DemoSite) => {
    setBusy(true);
    setError(null);
    try {
      // DEMO sites are always DEMO; the badge must never show LIVE for synthetic data.
      setSource('DEMO');
      setMode(site.monitoring_mode);
      const area = await api.createArea({
        monitoring_mode: site.monitoring_mode,
        user_label: site.name,
        source: 'DEMO',
        bbox: site.bounds,
      });
      setAreas((prev) => [area, ...prev.filter((a) => a.id !== area.id)]);
      setSelectedArea(area);
      setAnomalies([]);
      setResult(null);
      setTextInput(site.bounds.join(', '));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }, [api, describeError]);

  const startPolling = useCallback((jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const current = await api.getJob(jobId);
        setJob(current);
        if (current.is_terminal) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          if (current.status === 'COMPLETED' && current.result) {
            setResult(current.result);
            if (selectedArea) await refreshAnomalies(selectedArea.id);
          } else {
            setError(current.error_message ?? 'Monitoring run failed.');
          }
        }
      } catch (err) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setError(describeError(err));
      }
    }, pollIntervalMs);
  }, [api, describeError, pollIntervalMs, refreshAnomalies, selectedArea]);

  const handleRun = useCallback(async () => {
    if (!selectedArea) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setSelectedAnomaly(null);
    setJob(null);
    try {
      const scenario = demoSites.find(
        (s) => s.monitoring_mode === selectedArea.monitoring_mode,
      )?.scenario;
      const queued = await api.queueRun({
        area_id: selectedArea.id,
        source,
        monitoring_mode: selectedArea.monitoring_mode,
        demo_scenario: source === 'DEMO' ? scenario : undefined,
        grid_size: 200,
      });
      setJob({
        job_id: queued.job_id,
        area_id: queued.area_id,
        source: queued.source,
        monitoring_mode: selectedArea.monitoring_mode,
        status: queued.status as MonitoringJob['status'],
        stage: queued.stage,
        progress_percent: queued.progress_percent,
        stage_history: [],
        anomaly_count: 0,
        error_code: null,
        error_message: null,
        created_at: null,
        started_at: null,
        completed_at: null,
        is_terminal: false,
      });
      startPolling(queued.job_id);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }, [api, demoSites, describeError, selectedArea, source, startPolling]);

  const handleDeleteArea = useCallback(async (areaId: string) => {
    setBusy(true);
    try {
      await api.deleteArea(areaId);
      setAreas((prev) => prev.filter((a) => a.id !== areaId));
      if (selectedArea?.id === areaId) {
        setSelectedArea(null);
        setAnomalies([]);
        setResult(null);
      }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }, [api, describeError, selectedArea]);

  const sortedAnomalies = useMemo(
    () => [...anomalies].sort((a, b) => {
      const bySeverity = SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity);
      return bySeverity !== 0 ? bySeverity : b.area_m2 - a.area_m2;
    }),
    [anomalies],
  );

  const reachedStages = useMemo(() => {
    const reached = new Set<string>();
    job?.stage_history.forEach((entry) => reached.add(entry.stage));
    if (job?.stage) reached.add(job.stage);
    return reached;
  }, [job]);

  const isRunning = job !== null && !job.is_terminal;

  return (
    <div className="gov-body-layout">
      <section className="gov-panel">
        <header className="gov-panel-header">
          <h2 className="gov-panel-title">Area of interest</h2>
          <span className={`source-badge source-${source.toLowerCase()}`}>{source}</span>
        </header>
        <div className="gov-panel-body">
          {source === 'DEMO' && (
            <p className="gov-disclaimer-box">
              DEMO mode renders synthetic data for exploration. Results are not satellite
              observations.
            </p>
          )}

          <label className="gov-field">
            <span>Monitoring mode</span>
            <select
              className="gov-select"
              value={mode}
              onChange={(e) => setMode(e.target.value as MonitoringMode)}
              aria-label="Monitoring mode"
            >
              {MONITORING_MODES.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </label>

          <label className="gov-field">
            <span>Data source</span>
            <select
              className="gov-select"
              value={source}
              onChange={(e) => setSource(e.target.value as MonitoringSource)}
              aria-label="Data source"
            >
              <option value="DEMO">DEMO (synthetic)</option>
              <option value="LIVE">LIVE (satellite)</option>
            </select>
          </label>

          <label className="gov-field">
            <span>Geometry</span>
            <select
              className="gov-select"
              value={geometryKind}
              onChange={(e) => setGeometryKind(e.target.value as GeometryKind)}
              aria-label="Geometry type"
            >
              <option value="bbox">Bounding box</option>
              <option value="point">Point</option>
              <option value="polygon">Polygon (click map)</option>
              <option value="geojson">GeoJSON</option>
              <option value="place">Place name</option>
            </select>
          </label>

          {geometryKind === 'polygon' ? (
            <div className="gov-field-hint" data-testid="polygon-vertex-count">
              <Pencil size={12} /> {polygonPoints.length}{' '}
              {polygonPoints.length === 1 ? 'vertex' : 'vertices'} placed
              {polygonPoints.length > 0 && (
                <button
                  className="gov-icon-btn"
                  onClick={() => setPolygonPoints([])}
                  aria-label="Clear polygon vertices"
                >
                  Clear
                </button>
              )}
            </div>
          ) : (
            <input
              className="gov-input"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder={
                geometryKind === 'point' ? 'lon, lat'
                  : geometryKind === 'bbox' ? 'minLon, minLat, maxLon, maxLat'
                    : geometryKind === 'place' ? 'Place name'
                      : '{"type":"Polygon","coordinates":[…]}'
              }
              aria-label="Geometry value"
            />
          )}

          <button
            className="gov-btn gov-btn-primary"
            onClick={handleCreateArea}
            disabled={busy}
          >
            <MapPin size={14} /> Create area
          </button>

          {demoSites.length > 0 && (
            <>
              <h3 className="gov-section-title">Sample areas</h3>
              <ul className="gov-list" aria-label="Sample areas">
                {demoSites.map((site) => (
                  <li key={site.name}>
                    <button
                      className="gov-list-item"
                      onClick={() => handleUseDemoSite(site)}
                      disabled={busy}
                    >
                      <span className="gov-list-item-title">{site.name}</span>
                      <span className="gov-list-item-sub">
                        {site.monitoring_mode} · {site.description}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </section>

      <section className="gov-panel">
        <header className="gov-panel-header">
          <h2 className="gov-panel-title">Run</h2>
          {selectedArea && (
            <span className={`source-badge source-${selectedArea.source.toLowerCase()}`}>
              {selectedArea.source}
            </span>
          )}
        </header>
        <div className="gov-panel-body">
          {areas.length > 0 && (
            <ul className="gov-list" aria-label="Saved areas">
              {areas.map((area) => (
                <li key={area.id} className="gov-list-row">
                  <button
                    className={`gov-list-item ${selectedArea?.id === area.id ? 'is-selected' : ''}`}
                    onClick={() => {
                      setSelectedArea(area);
                      setResult(null);
                      setSelectedAnomaly(null);
                      refreshAnomalies(area.id);
                    }}
                  >
                    <span className="gov-list-item-title">
                      {area.user_label || area.id}
                    </span>
                    <span className="gov-list-item-sub">
                      {area.monitoring_mode} · {area.area_km2.toFixed(2)} km²
                    </span>
                  </button>
                  <button
                    className="gov-icon-btn"
                    onClick={() => handleDeleteArea(area.id)}
                    aria-label={`Delete ${area.user_label || area.id}`}
                    disabled={busy}
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <button
            className="gov-btn gov-btn-primary"
            onClick={handleRun}
            disabled={!selectedArea || isRunning || busy}
          >
            {isRunning ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
            Run monitoring
          </button>

          {job && (
            <div className="gov-progress" data-testid="job-progress">
              <div className="gov-progress-head">
                <span>{job.status}</span>
                <span>{job.progress_percent}%</span>
              </div>
              <progress value={job.progress_percent} max={100} />
              <ul className="gov-stage-list">
                {PIPELINE_STAGES.map((stage) => (
                  <li
                    key={stage}
                    className={reachedStages.has(stage) ? 'is-reached' : ''}
                  >
                    {stage}
                  </li>
                ))}
              </ul>
              {job.status === 'FAILED' && (
                <p className="gov-error" data-testid="job-error">
                  <XCircle size={14} /> {job.error_code ?? 'FAILED'}: {job.error_message}
                </p>
              )}
            </div>
          )}

          {error && <p className="gov-error"><AlertTriangle size={14} /> {error}</p>}
        </div>
      </section>

      <section className="gov-panel gov-panel-wide">
        <header className="gov-panel-header">
          <h2 className="gov-panel-title">Anomalies</h2>
          {result && (
            <span className={`source-badge source-${result.source.toLowerCase()}`}>
              {result.source}
            </span>
          )}
        </header>
        <div className="gov-panel-body">
          {result && (
            <div className="gov-kpi-grid" data-testid="run-summary">
              <div className="gov-kpi-card">
                <span className="gov-kpi-title">Run confidence</span>
                <span className="gov-kpi-value">
                  {pct(result.run_confidence.detection_confidence)}
                </span>
                <span className="gov-kpi-sub">scene-level detection</span>
              </div>
              <div className="gov-kpi-card">
                <span className="gov-kpi-title">Anomalies</span>
                <span className="gov-kpi-value">{result.anomaly_count}</span>
                <span className="gov-kpi-sub">{result.total_area_km2.toFixed(2)} km² AOI</span>
              </div>
              <div className="gov-kpi-card">
                <span className="gov-kpi-title">Run severity</span>
                <span className={`sev-pill ${SEVERITY_CLASS[result.run_severity]}`}>
                  {result.run_severity}
                </span>
                <span className="gov-kpi-sub">
                  max region: {result.max_anomaly_severity}
                </span>
              </div>
              {result.provenance.demo_truth && (
                <div className="gov-kpi-card">
                  <span className="gov-kpi-title">Accuracy vs truth</span>
                  <span className="gov-kpi-value">
                    IoU {pct(result.provenance.demo_truth.intersection_over_union)}
                  </span>
                  <span className="gov-kpi-sub">
                    {result.provenance.demo_truth.changed_pixels} true change pixels
                  </span>
                </div>
              )}
            </div>
          )}

          {result?.provenance.note && (
            <p className="gov-disclaimer-box">{result.provenance.note}</p>
          )}

          {sortedAnomalies.length === 0 ? (
            <p className="gov-empty">No anomalies reported for this area.</p>
          ) : (
            <table className="gov-table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Region</th>
                  <th>Area</th>
                  <th>Anomaly confidence</th>
                  <th>Run confidence</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {sortedAnomalies.map((anomaly) => (
                  <tr
                    key={anomaly.id}
                    onClick={() => setSelectedAnomaly(anomaly)}
                    className="gov-table-row"
                  >
                    <td>
                      <span className={`sev-pill ${SEVERITY_CLASS[anomaly.severity]}`}>
                        {anomaly.severity}
                      </span>
                    </td>
                    <td>{anomaly.region_id}</td>
                    <td>{anomaly.area_km2.toFixed(3)} km²</td>
                    <td>{pct(anomaly.anomaly_confidence)}</td>
                    <td>{pct(anomaly.detection_confidence)}</td>
                    <td>{anomaly.evidence.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {selectedAnomaly && (
            <aside className="gov-detail" data-testid="anomaly-detail">
              <header className="gov-detail-head">
                <h3>{selectedAnomaly.region_id}</h3>
                <span className={`sev-pill ${SEVERITY_CLASS[selectedAnomaly.severity]}`}>
                  {selectedAnomaly.severity}
                </span>
              </header>
              <dl className="gov-kv">
                <dt>Anomaly confidence</dt><dd>{pct(selectedAnomaly.anomaly_confidence)}</dd>
                <dt>Run confidence</dt><dd>{pct(selectedAnomaly.detection_confidence)}</dd>
                <dt>Area</dt><dd>{selectedAnomaly.area_km2.toFixed(3)} km²</dd>
                <dt>Centroid</dt>
                <dd>
                  {selectedAnomaly.centroid.lat.toFixed(4)},
                  {' '}{selectedAnomaly.centroid.lon.toFixed(4)}
                </dd>
                <dt>Pixels</dt><dd>{selectedAnomaly.pixel_count}</dd>
              </dl>
              <h4 className="gov-detail-title">Evidence</h4>
              <ul className="gov-evidence">
                {selectedAnomaly.evidence.map((item, index) => (
                  <li key={`${item.observation}-${index}`}>
                    <span className="gov-evidence-value">
                      {item.value}{item.unit ? ` ${item.unit}` : ''}
                    </span>
                    <span className="gov-evidence-text">
                      <strong>{item.observation}</strong>
                      {item.interpretation ? ` — ${item.interpretation}` : ''}
                    </span>
                  </li>
                ))}
              </ul>
              {selectedAnomaly.caveats.length > 0 && (
                <>
                  <h4 className="gov-detail-title">Caveats</h4>
                  <ul className="gov-caveats">
                    {selectedAnomaly.caveats.map((caveat, index) => (
                      <li key={index}>{caveat}</li>
                    ))}
                  </ul>
                </>
              )}
            </aside>
          )}
        </div>
      </section>

      <section className="gov-panel">
        <header className="gov-panel-header">
          <h2 className="gov-panel-title">Geometry</h2>
          <Crosshair size={14} />
        </header>
        <div className="gov-panel-body">
          <div className="gov-map-frame">
            <GeospatialMap
              locations={[]}
              onSelectLocation={() => undefined}
              aoi={
                selectedArea
                  ? {
                      geometry: selectedArea.geometry,
                      label: selectedArea.user_label,
                      areaKm2: selectedArea.area_km2,
                    }
                  : null
              }
              anomalies={mapAnomalies}
              highlightedRegionId={selectedAnomaly?.region_id ?? null}
              onSelectAnomaly={(regionId) => {
                const match = anomalies.find((a) => a.region_id === regionId);
                if (match) setSelectedAnomaly(match);
              }}
              onSelectCoordinates={(coords) => {
                // Clicks only build a polygon when polygon input is selected, so an
                // accidental click cannot quietly change a bbox the user already typed.
                if (geometryKind !== 'polygon') return;
                setPolygonPoints((prev) => [...prev, [coords.lng, coords.lat]]);
              }}
            />
          </div>

          {selectedArea ? (
            <>
              <p className="gov-field-hint">
                <Ruler size={12} /> {selectedArea.area_km2.toFixed(2)} km² ·{' '}
                {selectedArea.geometry.type}
              </p>
              <dl className="gov-kv">
                <dt>Centre</dt>
                <dd>
                  {selectedArea.center.lat.toFixed(4)}, {selectedArea.center.lon.toFixed(4)}
                </dd>
                <dt>CRS</dt><dd>{selectedArea.crs}</dd>
                <dt>Mode</dt><dd>{selectedArea.monitoring_mode}</dd>
                <dt>Source</dt><dd>{selectedArea.source}</dd>
              </dl>
              {result?.run_confidence.caveats.map((caveat, index) => (
                <p key={index} className="gov-field-hint">{caveat}</p>
              ))}
              <p className="gov-field-hint">
                <Layers size={12} />{' '}
                {result
                  ? `${result.provenance.baseline ?? 'baseline'} → ${result.provenance.current ?? 'current'}`
                  : 'No run yet'}
              </p>
            </>
          ) : (
            <p className="gov-empty">
              {isRunning
                ? <><Loader2 size={12} className="spin" /> Running…</>
                : 'Create or select an area to begin.'}
            </p>
          )}
        </div>
      </section>

    </div>
  );
};