import React from 'react';
import { TimelineEvent } from '../types/api';
import { 
  Satellite, 
  Eye, 
  Layers, 
  ShieldAlert, 
  FileText, 
  AlertTriangle, 
  Activity, 
  Clock 
} from 'lucide-react';

interface ChronologicalTimelineProps {
  events: TimelineEvent[];
  loading?: boolean;
}

export const ChronologicalTimeline: React.FC<ChronologicalTimelineProps> = ({ events, loading }) => {
  if (loading) {
    return (
      <div className="gov-panel">
        <div className="gov-panel-body" style={{ display: 'flex', justifyContent: 'center', padding: '32px' }}>
          <div className="gov-spinner" />
        </div>
      </div>
    );
  }

  if (!events || events.length === 0) {
    return (
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">
            <Clock size={16} color="var(--accent-cyan)" />
            <span>Chronological Evidence Timeline</span>
          </div>
        </div>
        <div className="gov-panel-body" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '32px' }}>
          No chronological surveillance events recorded yet.
        </div>
      </div>
    );
  }

  const getEventIcon = (type: string) => {
    switch (type) {
      case 'SENTINEL_1_OBSERVATION':
      case 'SAR_CHANGE_DETECTION':
        return <Satellite size={14} color="#38BDF8" />;
      case 'SENTINEL_2_OBSERVATION':
        return <Eye size={14} color="#10B981" />;
      case 'EVIDENCE_FUSION':
        return <Layers size={14} color="#A855F7" />;
      case 'RISK_ASSESSMENT':
        return <ShieldAlert size={14} color="#F97316" />;
      case 'ANALYST_REPORT':
        return <FileText size={14} color="#0EA5E9" />;
      case 'GOVERNMENT_ALERT':
        return <AlertTriangle size={14} color="#EF4444" />;
      case 'MONITORING_RUN':
        return <Activity size={14} color="#F59E0B" />;
      default:
        return <Clock size={14} color="#94A3B8" />;
    }
  };

  return (
    <div className="gov-panel" aria-label="Location Evidence Timeline">
      <div className="gov-panel-header">
        <div className="gov-panel-title">
          <Clock size={16} color="var(--accent-cyan)" />
          <span>Chronological Surveillance &amp; Intelligence Timeline</span>
        </div>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          {events.length} TOTAL AUDITED EVENTS
        </span>
      </div>

      <div className="gov-panel-body" style={{ padding: '20px 24px' }}>
        <div style={{ position: 'relative', borderLeft: '2px solid var(--border-default)', marginLeft: '12px', paddingLeft: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {events.map((evt, idx) => (
            <div key={evt.id || idx} style={{ position: 'relative' }}>
              {/* Timeline Bullet Node */}
              <div
                style={{
                  position: 'absolute',
                  left: '-32px',
                  top: '0px',
                  width: '18px',
                  height: '18px',
                  borderRadius: '50%',
                  background: 'var(--bg-panel)',
                  border: '2px solid var(--border-active)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {getEventIcon(evt.event_type)}
              </div>

              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '2px' }}>
                  <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                    {new Date(evt.timestamp).toLocaleString()}
                  </span>
                  <span className="badge-status" style={{ fontSize: '10px' }}>
                    {evt.event_type}
                  </span>
                </div>

                <div style={{ fontSize: '13px', fontWeight: 600, color: '#FFF' }}>
                  {evt.title}
                </div>

                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                  {evt.summary}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
