import React, { useState, useMemo } from 'react';
import { MonitoringRun, CriticalLocation } from '../types/api';
import { api } from '../api/client';
import { 
  Activity, 
  Search, 
  Play, 
  CheckCircle2, 
  AlertCircle, 
  Clock, 
  ExternalLink, 
  X,
  Layers,
  ShieldAlert,
  FileText,
  AlertTriangle
} from 'lucide-react';

interface MonitoringViewProps {
  runs: MonitoringRun[];
  locations: CriticalLocation[];
  loading: boolean;
  onRefresh: () => void;
  onSelectLocation: (location: CriticalLocation) => void;
}

export const MonitoringView: React.FC<MonitoringViewProps> = ({
  runs,
  locations,
  loading,
  onRefresh,
  onSelectLocation,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [selectedRun, setSelectedRun] = useState<MonitoringRun | null>(null);
  const [selectedLocationForRun, setSelectedLocationForRun] = useState<string>(locations[0]?.id || '');
  const [triggering, setTriggering] = useState(false);
  const [runMessage, setRunMessage] = useState<string | null>(null);

  const filteredRuns = useMemo(() => {
    return runs.filter((r) => {
      const q = searchQuery.toLowerCase().trim();
      const matchesSearch =
        !q ||
        r.id.toLowerCase().includes(q) ||
        r.location_id.toLowerCase().includes(q) ||
        (r.outcome_code && r.outcome_code.toLowerCase().includes(q));

      const matchesStatus = statusFilter === 'ALL' || r.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [runs, searchQuery, statusFilter]);

  const handleTriggerManualRun = async () => {
    if (!selectedLocationForRun) return;
    setTriggering(true);
    setRunMessage(null);
    try {
      const result = await api.monitoring.triggerRun(selectedLocationForRun, 'MANUAL_OPERATOR');
      setRunMessage(`Monitoring run ${result.id} finished with status: ${result.status}`);
      onRefresh();
    } catch (err: any) {
      setRunMessage(`Trigger error: ${err?.message || 'Failed'}`);
    } finally {
      setTriggering(false);
    }
  };

  const getStageStatus = (stage: string, currentStage: string, runStatus: string) => {
    const stages = [
      'DISCOVERY',
      'OBSERVATION_PROCESSING',
      'EVIDENCE_FUSION',
      'RISK_ASSESSMENT',
      'ANALYST_REPORT',
      'ALERT_EVALUATION',
      'COMPLETED'
    ];
    const currentIndex = stages.indexOf(currentStage);
    const thisIndex = stages.indexOf(stage);

    if (runStatus === 'FAILED' && thisIndex === currentIndex) return 'FAILED';
    if (thisIndex <= currentIndex || runStatus === 'COMPLETED') return 'COMPLETED';
    return 'PENDING';
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Banner & Manual Trigger Console */}
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">
            <Activity size={16} color="var(--accent-cyan)" />
            <span>Continuous Monitoring &amp; Automated Reassessment Center (Phase 7)</span>
          </div>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            AUTOMATED REASSESSMENT PIPELINE
          </span>
        </div>

        <div className="gov-panel-body" style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#FFF' }}>
              Manual On-Demand Surveillance Trigger
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Execute end-to-end multi-sensor retrieval, fusion, risk assessment, and alert evaluation.
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <select
              className="gov-select"
              value={selectedLocationForRun}
              onChange={(e) => setSelectedLocationForRun(e.target.value)}
              style={{ minWidth: '220px' }}
            >
              {locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name} ({loc.id})
                </option>
              ))}
            </select>

            <button
              className="gov-btn gov-btn-primary"
              onClick={handleTriggerManualRun}
              disabled={triggering || !selectedLocationForRun}
              style={{ background: '#0284C7' }}
            >
              <Play size={14} />
              <span>{triggering ? 'Executing Pipeline...' : 'Trigger Pipeline Run'}</span>
            </button>
          </div>
        </div>
      </div>

      {runMessage && (
        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border-active)', padding: '10px 14px', borderRadius: '6px', fontSize: '13px', color: '#FFF' }}>
          {runMessage}
        </div>
      )}

      {/* Filter & Search Toolbar */}
      <div className="gov-panel">
        <div className="gov-panel-body" style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', justifyContent: 'space-between' }}>
          <div className="gov-search-bar">
            <Search size={16} color="var(--text-muted)" />
            <input
              type="text"
              placeholder="Search runs by ID, location, or outcome..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <select
            className="gov-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="ALL">All Run Statuses</option>
            <option value="COMPLETED">COMPLETED</option>
            <option value="FAILED">FAILED</option>
            <option value="RUNNING">RUNNING</option>
            <option value="SKIPPED">SKIPPED</option>
          </select>
        </div>
      </div>

      {/* Monitoring Runs Table */}
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">
            <span>Historical Monitoring Runs</span>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Showing {filteredRuns.length} of {runs.length} Runs
          </span>
        </div>

        <div className="gov-panel-body" style={{ padding: 0 }}>
          {filteredRuns.length > 0 ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="gov-table">
                <thead>
                  <tr>
                    <th>Run ID</th>
                    <th>Location</th>
                    <th>Trigger</th>
                    <th>Status</th>
                    <th>Final Stage</th>
                    <th>Outcome Code</th>
                    <th>Observations</th>
                    <th>Timestamp</th>
                    <th>Inspection</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRuns.map((r) => {
                    const matchedLoc = locations.find((l) => l.id === r.location_id);
                    return (
                      <tr key={r.id}>
                        <td className="mono" style={{ fontSize: '11px', color: '#38BDF8' }}>
                          {r.id}
                        </td>
                        <td>
                          {matchedLoc ? (
                            <button
                              onClick={() => onSelectLocation(matchedLoc)}
                              style={{ background: 'none', border: 'none', color: '#FFF', fontWeight: 600, cursor: 'pointer', textAlign: 'left' }}
                            >
                              {matchedLoc.name}
                            </button>
                          ) : (
                            <span style={{ color: '#FFF', fontWeight: 600 }}>{r.location_id}</span>
                          )}
                        </td>
                        <td>
                          <span className="badge-status">{r.trigger_type}</span>
                        </td>
                        <td>
                          <span className={`badge-risk ${r.status === 'COMPLETED' ? 'LOW' : r.status === 'FAILED' ? 'CRITICAL' : 'MODERATE'}`}>
                            {r.status}
                          </span>
                        </td>
                        <td style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                          {r.current_stage}
                        </td>
                        <td className="mono" style={{ fontSize: '11px', color: '#94A3B8' }}>
                          {r.outcome_code || 'N/A'}
                        </td>
                        <td style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          {r.observations_processed ?? 0} / {r.observations_checked ?? 0}
                        </td>
                        <td className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          {new Date(r.created_at).toLocaleString()}
                        </td>
                        <td>
                          <button
                            className="gov-btn gov-btn-secondary"
                            onClick={() => setSelectedRun(r)}
                            style={{ padding: '4px 8px', fontSize: '11px' }}
                          >
                            Trace
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '48px', color: 'var(--text-muted)' }}>
              No monitoring runs found matching the query.
            </div>
          )}
        </div>
      </div>

      {/* Monitoring Run Detail Modal / Stage Trace */}
      {selectedRun && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.75)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 2000,
            backdropFilter: 'blur(4px)',
          }}
        >
          <div
            style={{
              background: 'var(--bg-panel)',
              border: '1px solid var(--border-default)',
              borderRadius: '8px',
              width: '100%',
              maxWidth: '680px',
              maxHeight: '90vh',
              overflowY: 'auto',
              boxShadow: 'var(--shadow-lg)',
            }}
          >
            <div className="gov-panel-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div className="gov-panel-title">
                <Activity size={16} color="var(--accent-cyan)" />
                <span>Monitoring Run Audit Trace</span>
              </div>
              <button
                onClick={() => setSelectedRun(null)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
              >
                <X size={18} />
              </button>
            </div>

            <div className="gov-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                  <span className="mono" style={{ fontSize: '13px', fontWeight: 600, color: '#38BDF8' }}>
                    {selectedRun.id}
                  </span>
                  <span className={`badge-risk ${selectedRun.status === 'COMPLETED' ? 'LOW' : 'CRITICAL'}`}>
                    {selectedRun.status}
                  </span>
                  <span className="badge-status">{selectedRun.trigger_type}</span>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  Location Target: <strong>{selectedRun.location_id}</strong>
                </div>
              </div>

              {/* Sequential Pipeline Stages Timeline */}
              <div style={{ background: 'var(--bg-card)', padding: '16px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '12px' }}>
                  Sequential Pipeline Transition Stages
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {[
                    { id: 'DISCOVERY', label: '1. Satellite Observation Discovery (CDSE)' },
                    { id: 'OBSERVATION_PROCESSING', label: '2. Observation Preprocessing & Backscatter' },
                    { id: 'EVIDENCE_FUSION', label: '3. Multi-Sensor Evidence Fusion (Phase 3)' },
                    { id: 'RISK_ASSESSMENT', label: '4. Deterministic Risk Assessment (Phase 4)' },
                    { id: 'ANALYST_REPORT', label: '5. Groq Evidence Analyst Synthesis (Phase 5)' },
                    { id: 'ALERT_EVALUATION', label: '6. Government Alert Decision Support (Phase 6)' },
                    { id: 'COMPLETED', label: '7. Run Persistence & Outcome Code' },
                  ].map((stage) => {
                    const st = getStageStatus(stage.id, selectedRun.current_stage, selectedRun.status);
                    return (
                      <div key={stage.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px' }}>
                        <span style={{ color: st === 'COMPLETED' ? '#FFF' : 'var(--text-muted)' }}>{stage.label}</span>
                        <span className={`badge-risk ${st === 'COMPLETED' ? 'LOW' : st === 'FAILED' ? 'CRITICAL' : 'MODERATE'}`}>
                          {st}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Provenance References */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: '6px', fontSize: '12px' }}>
                  <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>EVIDENCE SNAPSHOT ID</div>
                  <div className="mono" style={{ color: '#FFF' }}>{selectedRun.evidence_snapshot_id || 'snap-none'}</div>
                </div>

                <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: '6px', fontSize: '12px' }}>
                  <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>RISK ASSESSMENT ID</div>
                  <div className="mono" style={{ color: '#FFF' }}>{selectedRun.risk_assessment_id || 'risk-none'}</div>
                </div>

                <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: '6px', fontSize: '12px' }}>
                  <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>ANALYST REPORT ID</div>
                  <div className="mono" style={{ color: '#FFF' }}>{selectedRun.analyst_report_id || 'rep-none'}</div>
                </div>

                <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: '6px', fontSize: '12px' }}>
                  <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>GENERATED ALERT ID</div>
                  <div className="mono" style={{ color: '#FFF' }}>{selectedRun.alert_id || 'alt-none'}</div>
                </div>
              </div>

              {selectedRun.error_message && (
                <div style={{ background: 'rgba(239, 68, 68, 0.2)', border: '1px solid var(--risk-crit)', padding: '10px 14px', borderRadius: '6px', color: '#F87171', fontSize: '12px' }}>
                  <strong>Error Message:</strong> {selectedRun.error_message}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <button className="gov-btn gov-btn-secondary" onClick={() => setSelectedRun(null)}>
                  Close Audit Trace
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
