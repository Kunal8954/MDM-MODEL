import React from 'react';
import { RiskAssessment } from '../types/api';
import { AlertCircle, CheckCircle2, HelpCircle, ShieldAlert, Cpu } from 'lucide-react';

interface RiskScoreGaugeProps {
  risk: RiskAssessment | null | undefined;
  loading?: boolean;
}

export const RiskScoreGauge: React.FC<RiskScoreGaugeProps> = ({ risk, loading }) => {
  if (loading) {
    return (
      <div className="gov-panel">
        <div className="gov-panel-body" style={{ display: 'flex', justifyContent: 'center', padding: '32px' }}>
          <div className="gov-spinner" />
        </div>
      </div>
    );
  }

  if (!risk) {
    return (
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">Authoritative Deterministic Risk Assessment</div>
        </div>
        <div className="gov-panel-body" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '32px' }}>
          No risk assessment recorded for this critical location yet.
        </div>
      </div>
    );
  }

  const score = risk.score ?? 0;
  const level = risk.risk_level || 'LOW';
  const percentage = Math.min(Math.max(score, 0), 100);

  const formatFactorItem = (item: any): string => {
    if (typeof item === 'string') return item;
    if (typeof item === 'number') return item.toString();
    if (item && typeof item === 'object') {
      const factorName = item.factor || item.name || '';
      const reason = item.reason || item.description || '';
      const contrib = item.contribution !== undefined
        ? ` (+${typeof item.contribution === 'number' ? (item.contribution * 100).toFixed(0) : item.contribution}%)`
        : '';
      if (factorName || reason) {
        return [factorName, reason].filter(Boolean).join(': ') + contrib;
      }
      return Object.entries(item)
        .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
        .join(', ');
    }
    return String(item ?? '');
  };

  // Normalize contributing factors and uncertainties (could be list of strings, list of objects, or dict)
  const contributingList: string[] = Array.isArray(risk.contributing_factors)
    ? risk.contributing_factors.map(formatFactorItem)
    : risk.contributing_factors && typeof risk.contributing_factors === 'object'
    ? Object.entries(risk.contributing_factors).map(([k, v]) => `${k}: ${typeof v === 'object' ? formatFactorItem(v) : v}`)
    : [];

  const uncertaintyList: string[] = Array.isArray(risk.uncertainty_factors)
    ? risk.uncertainty_factors.map(formatFactorItem)
    : risk.uncertainty_factors && typeof risk.uncertainty_factors === 'object'
    ? Object.entries(risk.uncertainty_factors).map(([k, v]) => `${k}: ${typeof v === 'object' ? formatFactorItem(v) : v}`)
    : [];

  return (
    <div className="gov-panel" aria-label="Authoritative Risk Assessment Panel">
      <div className="gov-panel-header">
        <div className="gov-panel-title">
          <ShieldAlert size={16} color="var(--accent-cyan)" />
          <span>Authoritative Risk Assessment Engine</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: 'var(--text-muted)' }}>
          <Cpu size={13} />
          <span>ENGINE: <strong style={{ color: 'var(--text-secondary)' }}>{risk.engine_version || 'v4.0.0-auth'}</strong></span>
        </div>
      </div>

      <div className="gov-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {/* Core Score Bar & Badges */}
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '8px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span className={`badge-risk ${level}`} style={{ fontSize: '13px', padding: '4px 10px' }}>
                {level}
              </span>
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Monitoring Priority: <strong style={{ color: '#FFF' }}>{risk.monitoring_priority}</strong>
              </span>
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                Evidence Strength: <strong style={{ color: '#FFF' }}>{risk.evidence_strength}</strong>
              </span>
            </div>
            <div>
              <span style={{ fontSize: '28px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                {score.toFixed(2)}
              </span>
              <span style={{ fontSize: '14px', color: 'var(--text-muted)', marginLeft: '4px' }}>/ 100</span>
            </div>
          </div>

          {/* Progress Bar (0 - 100) */}
          <div className="gov-risk-bar-container" role="progressbar" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100}>
            <div className={`gov-risk-bar-fill ${level}`} style={{ width: `${percentage}%` }} />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
            <span>0 LOW (Routine)</span>
            <span>25 MODERATE</span>
            <span>50 HIGH</span>
            <span>75 CRITICAL (Urgent)</span>
            <span>100</span>
          </div>

          {/* Explicit Scientific Disclaimer */}
          <div className="gov-disclaimer-box">
            <strong>CRITICAL INTERPRETATION:</strong> This score is a deterministic{' '}
            <span style={{ color: '#FFF' }}>operational monitoring prioritization metric</span>. It reflects detected
            multi-sensor satellite anomalies and environmental indicators.{' '}
            <strong style={{ color: '#F87171' }}>It is NOT a disaster probability percentage.</strong>
          </div>
        </div>

        {/* Deterministic Explanation & Recommended Action */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
          <div style={{ background: 'var(--bg-card)', padding: '14px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
            <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '6px' }}>
              Deterministic Assessment Explanation
            </div>
            <p style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
              {risk.explanation || 'Anomaly observed across multi-temporal satellite backscatter analysis.'}
            </p>
          </div>

          <div style={{ background: 'var(--bg-card)', padding: '14px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
            <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--accent-cyan)', textTransform: 'uppercase', marginBottom: '6px' }}>
              Recommended Operational Action
            </div>
            <p style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.5 }}>
              {risk.recommended_action || 'Continue standard periodic surveillance.'}
            </p>
          </div>
        </div>

        {/* Contributing Factors vs Uncertainty Factors */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px' }}>
          {/* Contributing Factors */}
          <div style={{ background: 'var(--bg-card)', padding: '14px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '8px' }}>
              <CheckCircle2 size={14} color="#10B981" />
              <span>Contributing Evidence Factors ({contributingList.length})</span>
            </div>
            {contributingList.length > 0 ? (
              <ul style={{ paddingLeft: '18px', fontSize: '12px', color: 'var(--text-primary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {contributingList.map((factor, idx) => (
                  <li key={idx}>{factor}</li>
                ))}
              </ul>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>None recorded</div>
            )}
          </div>

          {/* Uncertainty Factors */}
          <div style={{ background: 'var(--bg-card)', padding: '14px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 600, color: '#F59E0B', textTransform: 'uppercase', marginBottom: '8px' }}>
              <HelpCircle size={14} color="#F59E0B" />
              <span>Uncertainty &amp; Observational Factors ({uncertaintyList.length})</span>
            </div>
            {uncertaintyList.length > 0 ? (
              <ul style={{ paddingLeft: '18px', fontSize: '12px', color: 'var(--text-primary)', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {uncertaintyList.map((factor, idx) => (
                  <li key={idx}>{factor}</li>
                ))}
              </ul>
            ) : (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>No significant uncertainties identified</div>
            )}
          </div>
        </div>

        {/* Confidence & Provenance Footer */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px' }}>
          <span>Confidence Score: <strong style={{ color: 'var(--text-primary)' }}>{((risk.confidence_score ?? 1) * 100).toFixed(1)}%</strong></span>
          <span>Timestamp: <span className="mono">{new Date(risk.created_at).toLocaleString()}</span></span>
          <span>Risk ID: <span className="mono">{risk.id}</span></span>
        </div>
      </div>
    </div>
  );
};
