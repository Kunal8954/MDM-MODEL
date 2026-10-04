import React, { useState, useEffect } from 'react';
import { 
  CriticalLocation, 
  RiskAssessment, 
  Sentinel1Change, 
  Sentinel1Observation, 
  Sentinel2Observation, 
  EvidenceSnapshot, 
  AnalystReport, 
  Alert, 
  TimelineEvent, 
  MonitoringRun 
} from '../types/api';
import { api } from '../api/client';
import { RiskScoreGauge } from '../components/RiskScoreGauge';
import { SatelliteEvidencePanel } from '../components/SatelliteEvidencePanel';
import { AnalystReportView } from '../components/AnalystReportView';
import { ChronologicalTimeline } from '../components/ChronologicalTimeline';
import { AlertLifecycleModal } from '../components/AlertLifecycleModal';
import { HistoricalIntelligencePanel } from '../components/HistoricalIntelligencePanel';
import { 
  ArrowLeft, 
  Play, 
  MapPin, 
  Radio, 
  AlertTriangle, 
  Activity, 
  Clock, 
  Layers, 
  ShieldCheck 
} from 'lucide-react';

interface LocationDetailViewProps {
  location: CriticalLocation;
  onBack: () => void;
  onAlertActionComplete?: () => void;
}

export const LocationDetailView: React.FC<LocationDetailViewProps> = ({
  location,
  onBack,
  onAlertActionComplete,
}) => {
  const [risk, setRisk] = useState<RiskAssessment | null>(location.latest_risk || null);
  const [s1Changes, setS1Changes] = useState<Sentinel1Change[]>([]);
  const [s1Obs, setS1Obs] = useState<Sentinel1Observation[]>([]);
  const [s2Obs, setS2Obs] = useState<Sentinel2Observation[]>([]);
  const [snapshot, setSnapshot] = useState<EvidenceSnapshot | null>(null);
  const [analystReport, setAnalystReport] = useState<AnalystReport | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggeringRun, setTriggeringRun] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);

  // Selected Alert for modal action
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [isAlertModalOpen, setIsAlertModalOpen] = useState(false);

  const fetchLocationIntelligence = async () => {
    setLoading(true);
    try {
      const [
        riskRes,
        s1ChangesRes,
        s1ObsRes,
        s2ObsRes,
        snapshotsRes,
        analystRes,
        alertsRes,
        timelineRes,
      ] = await Promise.allSettled([
        api.risk.getLatest(location.id),
        api.sar.getChanges(location.id),
        api.sar.getObservations(location.id),
        api.optical.getObservations(location.id),
        api.evidence.getSnapshots(location.id),
        api.analyst.getLatest(location.id),
        api.alerts.getLocationAlerts(location.id),
        api.timeline.getTimeline(location.id),
      ]);

      if (riskRes.status === 'fulfilled') setRisk(riskRes.value);
      if (s1ChangesRes.status === 'fulfilled') setS1Changes(s1ChangesRes.value);
      if (s1ObsRes.status === 'fulfilled') setS1Obs(s1ObsRes.value);
      if (s2ObsRes.status === 'fulfilled') setS2Obs(s2ObsRes.value);
      if (snapshotsRes.status === 'fulfilled' && snapshotsRes.value.length > 0) {
        setSnapshot(snapshotsRes.value[0]);
      }
      if (analystRes.status === 'fulfilled') setAnalystReport(analystRes.value);
      if (alertsRes.status === 'fulfilled') setAlerts(alertsRes.value);
      if (timelineRes.status === 'fulfilled') setTimeline(timelineRes.value);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLocationIntelligence();
  }, [location.id]);

  const handleTriggerRun = async () => {
    setTriggeringRun(true);
    setFeedbackMsg(null);
    try {
      const run = await api.monitoring.triggerRun(location.id, 'MANUAL_OPERATOR');
      setFeedbackMsg(`Monitoring run ${run.id} initiated successfully. Status: ${run.status}`);
      // Refresh intelligence after run
      await fetchLocationIntelligence();
    } catch (err: any) {
      setFeedbackMsg(`Run trigger failed: ${err?.message || 'Internal error'}`);
    } finally {
      setTriggeringRun(false);
    }
  };

  const handleAlertModalAction = async (
    alertId: string,
    action: 'acknowledge' | 'review' | 'resolve',
    note: string
  ) => {
    if (action === 'acknowledge') await api.alerts.acknowledge(alertId, note);
    else if (action === 'review') await api.alerts.review(alertId, note);
    else if (action === 'resolve') await api.alerts.resolve(alertId, note);

    // Refresh alerts and timeline
    const updatedAlerts = await api.alerts.getLocationAlerts(location.id);
    setAlerts(updatedAlerts);
    const updatedTimeline = await api.timeline.getTimeline(location.id);
    setTimeline(updatedTimeline);
    if (onAlertActionComplete) onAlertActionComplete();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Navigation & Location Banner */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <button className="gov-btn gov-btn-secondary" onClick={onBack}>
          <ArrowLeft size={14} />
          <span>Back to Directory</span>
        </button>

        <button
          className="gov-btn gov-btn-primary"
          onClick={handleTriggerRun}
          disabled={triggeringRun}
          style={{ background: '#0284C7' }}
        >
          <Play size={14} />
          <span>{triggeringRun ? 'Triggering Run...' : 'Run Automated Reassessment'}</span>
        </button>
      </div>

      {feedbackMsg && (
        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-active)', padding: '10px 14px', borderRadius: '6px', fontSize: '13px', color: '#FFF' }}>
          {feedbackMsg}
        </div>
      )}

      {/* Critical Location Header Card */}
      <div className="gov-panel">
        <div className="gov-panel-body" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
              <span className="mono" style={{ fontSize: '12px', color: '#38BDF8', fontWeight: 600 }}>{location.id}</span>
              <span className="badge-risk LOW" style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38BDF8', borderColor: 'rgba(56, 189, 248, 0.4)' }}>
                {location.location_type?.toUpperCase()}
              </span>
              <span className={`badge-status ${location.monitoring_status}`}>
                {location.monitoring_status}
              </span>
            </div>
            <h2 style={{ fontSize: '22px', fontWeight: 700, color: '#FFF' }}>{location.name}</h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
              <span>Coords: <strong className="mono" style={{ color: '#FFF' }}>{location.latitude.toFixed(4)}°N, {location.longitude.toFixed(4)}°E</strong></span>
              <span>Perimeter AOI: <strong className="mono" style={{ color: '#FFF' }}>{location.radius_m ? `${(location.radius_m / 1000).toFixed(1)} km` : '5.0 km'}</strong></span>
              <span>Cadence: <strong style={{ color: '#FFF' }}>Every {location.monitoring_interval_hours || 24}h</strong></span>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>AUTHORITATIVE RISK</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', justifyContent: 'flex-end' }}>
                <span className={`badge-risk ${risk?.risk_level || 'LOW'}`} style={{ fontSize: '14px' }}>
                  {risk?.risk_level || 'LOW'}
                </span>
                <span className="mono" style={{ fontSize: '24px', fontWeight: 700, color: '#FFF' }}>
                  {risk?.score?.toFixed(2) ?? '0.00'}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 1: Authoritative Risk Assessment Panel (Phase 4) */}
      <RiskScoreGauge risk={risk} loading={loading} />

      {/* SECTION 2: Multi-Sensor Satellite Evidence (S1, S2, Fusion, DEM, Rainfall, Seismic, Fire) */}
      <SatelliteEvidencePanel
        s1Changes={s1Changes}
        s1Obs={s1Obs}
        s2Obs={s2Obs}
        snapshot={snapshot}
        loading={loading}
      />

      {/* SECTION 3: Groq Evidence Analyst Report (Phase 5) */}
      <AnalystReportView report={analystReport} loading={loading} />

      {/* SECTION 4: Historical Intelligence & Trend Analytics (Phase 9) */}
      <HistoricalIntelligencePanel
        locationId={location.id}
        locationName={location.name}
      />

      {/* SECTION 5: Active Government Alerts for this Location */}
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">
            <AlertTriangle size={16} color="var(--risk-high)" />
            <span>Government Surveillance Alerts for this Location</span>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {alerts.length} Total Alerts Recorded
          </span>
        </div>

        <div className="gov-panel-body" style={{ padding: 0 }}>
          {alerts.length > 0 ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="gov-table">
                <thead>
                  <tr>
                    <th>Alert ID</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Title &amp; Summary</th>
                    <th>Created</th>
                    <th>Operator Action</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((al) => (
                    <tr key={al.id}>
                      <td className="mono" style={{ fontSize: '11px', color: '#38BDF8' }}>{al.id}</td>
                      <td><span className={`badge-risk ${al.priority}`}>{al.priority}</span></td>
                      <td><span className={`badge-status ${al.status}`}>{al.status}</span></td>
                      <td>
                        <div style={{ fontWeight: 600, color: '#FFF' }}>{al.title}</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{al.summary}</div>
                      </td>
                      <td className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {new Date(al.created_at).toLocaleString()}
                      </td>
                      <td>
                        <button
                          className="gov-btn gov-btn-secondary"
                          onClick={() => {
                            setSelectedAlert(al);
                            setIsAlertModalOpen(true);
                          }}
                          style={{ padding: '4px 8px', fontSize: '11px' }}
                        >
                          Review &amp; Transition
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
              No government alerts recorded for this location.
            </div>
          )}
        </div>
      </div>

      {/* SECTION 5: Chronological Evidence Timeline */}
      <ChronologicalTimeline events={timeline} loading={loading} />

      {/* Operator Alert Lifecycle Action Modal */}
      <AlertLifecycleModal
        alert={selectedAlert}
        isOpen={isAlertModalOpen}
        onClose={() => {
          setIsAlertModalOpen(false);
          setSelectedAlert(null);
        }}
        onAction={handleAlertModalAction}
      />
    </div>
  );
};
