import React, { useState, useEffect } from 'react';
import {
  HistoricalAnalyticsReport,
  PersistenceStatus,
  BaselineComparisonStatus,
  DeviationStatus,
  DataSufficiency,
} from '../types/api';
import { api } from '../api/client';
import {
  TrendingUp,
  History,
  Activity,
  AlertCircle,
  Download,
  Calendar,
  CloudRain,
  Flame,
  Zap,
  CheckCircle2,
  HelpCircle,
} from 'lucide-react';

interface HistoricalIntelligencePanelProps {
  locationId: string;
  locationName: string;
}

export const HistoricalIntelligencePanel: React.FC<HistoricalIntelligencePanelProps> = ({
  locationId,
  locationName,
}) => {
  const [selectedDays, setSelectedDays] = useState<number>(30);
  const [report, setReport] = useState<HistoricalAnalyticsReport | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState<boolean>(false);

  useEffect(() => {
    let isMounted = true;
    const loadAnalytics = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.analytics.getHistory(locationId, selectedDays);
        if (isMounted) {
          setReport(data);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || 'Failed to retrieve historical intelligence.');
        }
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    loadAnalytics();
    return () => {
      isMounted = false;
    };
  }, [locationId, selectedDays]);

  const handleExportReport = async () => {
    setIsExporting(true);
    try {
      const reportData = await api.analytics.exportReport(locationId, selectedDays);
      const dataStr = 'data:text/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(reportData, null, 2));
      const downloadAnchor = document.createElement('a');
      downloadAnchor.setAttribute('href', dataStr);
      downloadAnchor.setAttribute('download', `SATGUARD_${locationId}_${selectedDays}D_Historical_Report.json`);
      document.body.appendChild(downloadAnchor);
      downloadAnchor.click();
      downloadAnchor.remove();
    } catch (e: any) {
      alert(`Export failed: ${e.message}`);
    } finally {
      setIsExporting(false);
    }
  };

  const getPersistenceBadge = (status: PersistenceStatus) => {
    switch (status) {
      case 'PERSISTENT_SIGNAL':
        return <span className="badge-risk HIGH" style={{ fontWeight: 600 }}>PERSISTENT SIGNAL</span>;
      case 'INTERMITTENT_SIGNAL':
        return <span className="badge-risk MODERATE" style={{ fontWeight: 600 }}>INTERMITTENT SIGNAL</span>;
      case 'ISOLATED_SIGNAL':
        return <span className="badge-risk LOW" style={{ fontWeight: 600 }}>ISOLATED SIGNAL</span>;
      case 'NO_SIGNAL':
        return <span className="badge-status RESOLVED" style={{ fontWeight: 600 }}>NO SIGNAL</span>;
      default:
        return <span className="badge-status EXPIRED" style={{ fontWeight: 600 }}>INSUFFICIENT DATA</span>;
    }
  };

  const getBaselineBadge = (status: BaselineComparisonStatus, deviation: DeviationStatus) => {
    if (deviation === 'ABOVE_HISTORICAL_RANGE') {
      return <span className="badge-risk CRITICAL">ABOVE HISTORICAL RANGE</span>;
    }
    if (deviation === 'UNUSUAL_RELATIVE_TO_BASELINE') {
      return <span className="badge-risk HIGH">UNUSUAL RELATIVE TO BASELINE</span>;
    }
    if (deviation === 'HISTORICAL_DEVIATION') {
      return <span className="badge-risk MODERATE">HISTORICAL DEVIATION</span>;
    }
    if (status === 'WITHIN_BASELINE') {
      return <span className="badge-status RESOLVED">WITHIN BASELINE</span>;
    }
    return <span className="badge-status EXPIRED">{status}</span>;
  };

  const getSufficiencyBadge = (sufficiency: DataSufficiency) => {
    switch (sufficiency) {
      case 'SUFFICIENT':
        return <span className="badge-status ACTIVE">SUFFICIENT</span>;
      case 'LIMITED':
        return <span className="badge-status IN_REVIEW">LIMITED</span>;
      default:
        return <span className="badge-status EXPIRED">INSUFFICIENT</span>;
    }
  };

  return (
    <div className="gov-panel" style={{ marginTop: '24px' }}>
      {/* Panel Header */}
      <div className="gov-panel-header" style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
        <div className="gov-panel-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <History size={18} color="var(--accent-cyan)" />
          <span style={{ fontSize: '16px', fontWeight: 700, letterSpacing: '0.5px' }}>
            HISTORICAL INTELLIGENCE &amp; TREND ANALYTICS
          </span>
        </div>

        {/* Controls: Time Window selector & Export button */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ display: 'flex', background: 'var(--bg-root)', padding: '2px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
            {[7, 30, 90, 180, 365].map((d) => (
              <button
                key={d}
                onClick={() => setSelectedDays(d)}
                style={{
                  background: selectedDays === d ? 'var(--accent-cyan)' : 'transparent',
                  color: selectedDays === d ? '#FFF' : 'var(--text-secondary)',
                  border: 'none',
                  padding: '4px 10px',
                  borderRadius: '4px',
                  fontSize: '12px',
                  fontWeight: selectedDays === d ? 700 : 500,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                {d === 365 ? '1Y' : `${d}D`}
              </button>
            ))}
          </div>

          <button
            className="gov-btn gov-btn-secondary"
            onClick={handleExportReport}
            disabled={isExporting || loading}
            style={{ padding: '6px 12px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <Download size={14} />
            <span>{isExporting ? 'Exporting...' : 'Export Report'}</span>
          </button>
        </div>
      </div>

      <div className="gov-panel-body">
        {loading && (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <Activity size={24} className="spin" style={{ margin: '0 auto 12px' }} />
            <div>Loading multi-sensor historical trends for {locationName}...</div>
          </div>
        )}

        {error && (
          <div style={{ background: 'var(--risk-crit-bg)', border: '1px solid var(--risk-crit-border)', padding: '14px', borderRadius: '6px', color: '#FFF' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
              <AlertCircle size={16} color="var(--risk-crit)" />
              <span>Historical Analytics Error</span>
            </div>
            <div style={{ fontSize: '12px', marginTop: '4px' }}>{error}</div>
          </div>
        )}

        {!loading && !error && report && (
          <div>
            {/* Top Operational Status Summary Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px', marginBottom: '20px' }}>
              {/* Persistence Card */}
              <div style={{ background: 'var(--bg-root)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                  Persistence Status
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  {getPersistenceBadge(report.persistence.persistence_status)}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  {report.persistence.explanation}
                </div>
              </div>

              {/* Baseline Comparison Card */}
              <div style={{ background: 'var(--bg-root)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                  Baseline Comparison
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                  {getBaselineBadge(report.baseline_comparison.comparison_status, report.baseline_comparison.deviation_status)}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  {report.baseline_comparison.explanation}
                </div>
              </div>

              {/* Risk Trend Card */}
              <div style={{ background: 'var(--bg-root)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                  Risk Trend Classification
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                  <span className="badge-risk HIGH" style={{ fontWeight: 600 }}>
                    {report.risk_trends.classification}
                  </span>
                  <span className="mono" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    (Δ: {report.risk_trends.score_delta !== null && report.risk_trends.score_delta !== undefined ? `${report.risk_trends.score_delta > 0 ? '+' : ''}${report.risk_trends.score_delta.toFixed(1)}` : '0.0'})
                  </span>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  Evaluated {report.risk_trends.assessment_count} risk records. {report.risk_trends.level_transitions_count} level transitions recorded.
                </div>
              </div>

              {/* Data Sufficiency & Alert Recurrence */}
              <div style={{ background: 'var(--bg-root)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
                  Data Sufficiency &amp; Recurrence
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                  {getSufficiencyBadge(report.data_sufficiency)}
                  {report.alert_trends.recurrence_detected ? (
                    <span className="badge-risk CRITICAL" style={{ fontSize: '11px' }}>RECURRING ALERTS</span>
                  ) : (
                    <span className="badge-status RESOLVED" style={{ fontSize: '11px' }}>NO RECURRENCE</span>
                  )}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  Window: {new Date(report.window.start_time).toLocaleDateString()} to {new Date(report.window.end_time).toLocaleDateString()} ({report.window.days} days).
                </div>
              </div>
            </div>

            {/* Historical Charts Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(460px, 1fr))', gap: '16px', marginBottom: '20px' }}>
              {/* Chart 1: SAR Surface-Change Signal Series */}
              <div style={{ background: 'var(--bg-card)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <div>
                    <h4 style={{ fontSize: '14px', fontWeight: 600, color: '#FFF' }}>
                      Sentinel-1 SAR Surface-Change Trend
                    </h4>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      Backscatter Mean Shift (ΔVV / ΔVH in dB) &amp; Pixel Change %
                    </span>
                  </div>
                  <span className="badge-status ACTIVE" style={{ fontSize: '11px' }}>
                    {report.sar_trends.signal_trend}
                  </span>
                </div>

                {report.sar_trends.points.length > 0 ? (
                  <div>
                    {/* SVG Visualization */}
                    <div style={{ width: '100%', height: '140px', background: 'var(--bg-root)', borderRadius: '6px', padding: '10px 14px', position: 'relative' }}>
                      <svg width="100%" height="100%" viewBox="0 0 400 110" preserveAspectRatio="none">
                        {/* Grid lines */}
                        <line x1="0" y1="20" x2="400" y2="20" stroke="var(--border-subtle)" strokeDasharray="3,3" />
                        <line x1="0" y1="55" x2="400" y2="55" stroke="var(--border-subtle)" strokeDasharray="3,3" />
                        <line x1="0" y1="90" x2="400" y2="90" stroke="var(--border-subtle)" strokeDasharray="3,3" />

                        {/* Data Points */}
                        {report.sar_trends.points.map((pt, idx) => {
                          const n = report.sar_trends.points.length;
                          const x = n === 1 ? 200 : 30 + (idx * (340 / (n - 1)));
                          const pct = pt.changed_percentage || 0;
                          const y = Math.max(15, Math.min(95, 100 - (pct * 0.8)));
                          return (
                            <g key={idx}>
                              <circle
                                cx={x}
                                cy={y}
                                r={pt.is_significant_change ? 6 : 4}
                                fill={pt.is_significant_change ? 'var(--risk-high)' : 'var(--accent-cyan)'}
                                stroke="#FFF"
                                strokeWidth="1.5"
                              />
                              <text x={x} y={y - 8} fill="var(--text-secondary)" fontSize="9" textAnchor="middle" className="mono">
                                {pct.toFixed(1)}%
                              </text>
                            </g>
                          );
                        })}
                      </svg>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px', fontSize: '11px', color: 'var(--text-secondary)' }}>
                      <span>Evaluated: <strong className="mono" style={{ color: '#FFF' }}>{report.sar_trends.valid_change_count} Change Detections</strong></span>
                      <span>Mean ΔVV: <strong className="mono" style={{ color: '#FFF' }}>{report.sar_trends.mean_delta_vv !== null ? `${report.sar_trends.mean_delta_vv} dB` : 'N/A'}</strong></span>
                      <span>Max Changed: <strong className="mono" style={{ color: 'var(--risk-high)' }}>{report.sar_trends.max_changed_percentage !== null ? `${report.sar_trends.max_changed_percentage}%` : 'N/A'}</strong></span>
                    </div>
                  </div>
                ) : (
                  <div style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
                    No SAR change detections in the selected {selectedDays}D window.
                  </div>
                )}
              </div>

              {/* Chart 2: Authoritative Risk Assessment Trajectory */}
              <div style={{ background: 'var(--bg-card)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <div>
                    <h4 style={{ fontSize: '14px', fontWeight: 600, color: '#FFF' }}>
                      Authoritative Risk Score Trajectory
                    </h4>
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      Deterministic 0–100 Scale (Immutable Assessments)
                    </span>
                  </div>
                  <span className={`badge-risk ${report.risk_trends.classification}`} style={{ fontSize: '11px' }}>
                    {report.risk_trends.classification}
                  </span>
                </div>

                {report.risk_trends.points.length > 0 ? (
                  <div>
                    <div style={{ width: '100%', height: '140px', background: 'var(--bg-root)', borderRadius: '6px', padding: '10px 14px', position: 'relative' }}>
                      <svg width="100%" height="100%" viewBox="0 0 400 110" preserveAspectRatio="none">
                        {/* Reference lines */}
                        <line x1="0" y1="25" x2="400" y2="25" stroke="rgba(239, 68, 68, 0.3)" strokeDasharray="3,3" />
                        <line x1="0" y1="50" x2="400" y2="50" stroke="rgba(249, 115, 22, 0.3)" strokeDasharray="3,3" />
                        <line x1="0" y1="80" x2="400" y2="80" stroke="rgba(16, 185, 129, 0.3)" strokeDasharray="3,3" />

                        {/* Trajectory Polyline */}
                        {report.risk_trends.points.length > 1 && (
                          <polyline
                            fill="none"
                            stroke="var(--accent-cyan)"
                            strokeWidth="2"
                            points={report.risk_trends.points
                              .map((p, idx) => {
                                const n = report.risk_trends.points.length;
                                const x = 30 + (idx * (340 / (n - 1)));
                                const y = Math.max(15, Math.min(95, 100 - p.score));
                                return `${x},${y}`;
                              })
                              .join(' ')}
                          />
                        )}

                        {/* Points */}
                        {report.risk_trends.points.map((p, idx) => {
                          const n = report.risk_trends.points.length;
                          const x = n === 1 ? 200 : 30 + (idx * (340 / (n - 1)));
                          const y = Math.max(15, Math.min(95, 100 - p.score));
                          return (
                            <g key={idx}>
                              <circle
                                cx={x}
                                cy={y}
                                r={5}
                                fill={p.score >= 60 ? 'var(--risk-high)' : 'var(--accent-cyan)'}
                                stroke="#FFF"
                                strokeWidth="1.5"
                              />
                              <text x={x} y={y - 8} fill="#FFF" fontSize="9" textAnchor="middle" className="mono">
                                {p.score.toFixed(1)}
                              </text>
                            </g>
                          );
                        })}
                      </svg>
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '8px', fontSize: '11px', color: 'var(--text-secondary)' }}>
                      <span>Latest: <strong className="mono" style={{ color: '#FFF' }}>{report.risk_trends.latest_score?.toFixed(1) ?? 'N/A'}</strong></span>
                      <span>Average: <strong className="mono" style={{ color: '#FFF' }}>{report.risk_trends.average_score?.toFixed(1) ?? 'N/A'}</strong></span>
                      <span>High Periods: <strong className="mono" style={{ color: 'var(--risk-high)' }}>{report.risk_trends.high_level_count}</strong></span>
                    </div>
                  </div>
                ) : (
                  <div style={{ padding: '36px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
                    No risk assessment records in the selected {selectedDays}D window.
                  </div>
                )}
              </div>
            </div>

            {/* Environmental & Optical Context Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px', marginBottom: '16px' }}>
              {/* Optical Observation Health */}
              <div style={{ background: 'var(--bg-root)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#FFF', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  <Activity size={14} color="#38BDF8" />
                  <span>Optical Cloud Filtering (Sentinel-2)</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Total Scenes:</span>
                  <strong className="mono" style={{ color: '#FFF' }}>{report.optical_trends.total_scenes}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Usable (Clear Sky):</span>
                  <strong className="mono" style={{ color: '#10B981' }}>{report.optical_trends.usable_scenes}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Cloud Obscured (&gt;50%):</span>
                  <strong className="mono" style={{ color: 'var(--risk-mod)' }}>{report.optical_trends.cloud_obscured_scenes}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)' }}>
                  <span>Optical Stability:</span>
                  <strong style={{ color: '#FFF' }}>{report.optical_trends.optical_stability}</strong>
                </div>
              </div>

              {/* GPM IMERG Rainfall Context */}
              <div style={{ background: 'var(--bg-root)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#FFF', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  <CloudRain size={14} color="#38BDF8" />
                  <span>NASA GPM (IMERG) Precipitation</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Data Status:</span>
                  <strong style={{ color: report.environmental_history.rainfall_status === 'UNAVAILABLE' ? 'var(--text-muted)' : '#10B981' }}>
                    {report.environmental_history.rainfall_status}
                  </strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Observations:</span>
                  <strong className="mono" style={{ color: '#FFF' }}>{report.environmental_history.rainfall_observation_count}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)' }}>
                  <span>Mean Accumulated mm:</span>
                  <strong className="mono" style={{ color: '#FFF' }}>
                    {report.environmental_history.rainfall_mean_mm !== null ? `${report.environmental_history.rainfall_mean_mm} mm` : 'UNAVAILABLE'}
                  </strong>
                </div>
              </div>

              {/* NASA FIRMS & USGS Seismic Context */}
              <div style={{ background: 'var(--bg-root)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#FFF', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  <Flame size={14} color="var(--risk-high)" />
                  <span>FIRMS Thermal &amp; USGS Seismic</span>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Active Fires (AOI):</span>
                  <strong className="mono" style={{ color: '#FFF' }}>{report.environmental_history.fire_detection_count} ({report.environmental_history.fire_status})</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  <span>Seismic Events Detected:</span>
                  <strong className="mono" style={{ color: '#FFF' }}>{report.environmental_history.seismic_event_count}</strong>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)' }}>
                  <span>Nearest Earthquake:</span>
                  <strong className="mono" style={{ color: '#FFF' }}>
                    {report.environmental_history.nearest_earthquake_distance_km !== null ? `${report.environmental_history.nearest_earthquake_distance_km} km` : 'None within AOI'}
                  </strong>
                </div>
              </div>
            </div>

            {/* Scientific Boundaries Disclaimer */}
            <div style={{ background: 'rgba(56, 189, 248, 0.05)', border: '1px solid rgba(56, 189, 248, 0.2)', padding: '12px 16px', borderRadius: '6px', fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              <div style={{ fontWeight: 600, color: 'var(--accent-cyan)', marginBottom: '2px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <HelpCircle size={14} />
                <span>SCIENTIFIC INTEGRITY &amp; DECISION-SUPPORT NOTICE</span>
              </div>
              <div>{report.disclaimer}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
