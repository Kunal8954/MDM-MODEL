import React, { useState, useEffect } from 'react';
import { OverviewStats, SystemDataStatus } from '../types/api';
import { Shield, RefreshCw, Radio, UserCheck, Clock } from 'lucide-react';

interface HeaderProps {
  stats: OverviewStats | null;
  dataStatus: SystemDataStatus | null;
  loading: boolean;
  onRefresh: () => void;
}

export const Header: React.FC<HeaderProps> = ({ stats, loading, onRefresh }) => {
  const statusClass = stats?.system_status ? stats.system_status.toLowerCase() : 'operational';
  const statusLabel = stats?.system_status || 'OPERATIONAL';

  // Live real-time military clock ticking every 1000ms
  const [currentTime, setCurrentTime] = useState<Date>(new Date());
  useEffect(() => {
    const timer = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const utcTimeStr = currentTime.toISOString().slice(11, 19) + ' UTC';
  const localTimeStr = currentTime.toLocaleTimeString([], { hour12: false }) + ' LOCAL';

  // Compute sync age in seconds
  const syncDate = stats?.data_freshness || stats?.timestamp ? new Date(stats.data_freshness || stats.timestamp!) : null;
  const syncAgeSeconds = syncDate ? Math.max(0, Math.floor((currentTime.getTime() - syncDate.getTime()) / 1000)) : 0;

  const formatSyncTime = (ts?: string) => {
    if (!ts) return 'LIVE';
    try {
      const d = new Date(ts);
      return d.toISOString().slice(11, 19) + ' UTC';
    } catch {
      return ts;
    }
  };

  return (
    <header className="gov-header" role="banner">
      <div className="gov-logo-group">
        <Shield size={26} color="#38BDF8" aria-hidden="true" />
        <div className="gov-title-area">
          <h1>
            SATGUARD
            <span className="gov-badge-emblem">GEOINT DEFENSE</span>
          </h1>
          <p>Critical Location Earth Observation &amp; Early-Warning System</p>
        </div>
      </div>

      <div className="gov-header-status-group">
        {/* Live Military Clock */}
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          gap: '6px', 
          background: 'rgba(15, 23, 42, 0.75)',
          padding: '4px 10px',
          borderRadius: '4px',
          border: '1px solid rgba(56, 189, 248, 0.25)',
          fontSize: '11px',
        }}>
          <Clock size={13} color="#38BDF8" />
          <span className="mono" style={{ color: '#F1F5F9', fontWeight: 600 }}>{utcTimeStr}</span>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span className="mono" style={{ color: 'var(--text-secondary)' }}>{localTimeStr}</span>
        </div>

        {/* System Status Pill */}
        <div className={`gov-status-pill ${statusClass}`} title="Authoritative System Health State">
          <span className="gov-indicator-dot" />
          <span>{statusLabel}</span>
        </div>

        {/* Freshness / Mode Indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', color: 'var(--text-secondary)' }}>
          <Radio size={14} color="#0EA5E9" />
          <span>MODE: <strong style={{ color: '#FFF' }}>{stats?.mode || 'REAL_DATA_ONLY'}</strong></span>
        </div>

        {/* Real-time Data Sync */}
        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          <span>LAST SYNC: </span>
          <span className="mono" style={{ color: 'var(--text-secondary)' }}>
            {formatSyncTime(stats?.data_freshness || stats?.timestamp)}
          </span>
          <span style={{ fontSize: '10px', color: syncAgeSeconds < 10 ? '#10B981' : '#F59E0B', marginLeft: '4px' }}>
            ({syncAgeSeconds === 0 ? 'now' : `${syncAgeSeconds}s ago`})
          </span>
        </div>

        {/* Manual Refresh Button */}
        <button
          className="gov-btn gov-btn-secondary"
          onClick={onRefresh}
          disabled={loading}
          aria-label="Refresh telemetry and system intelligence"
          title="Refresh telemetry"
          style={{ padding: '6px 12px', fontSize: '12px' }}
        >
          <RefreshCw size={13} className={loading ? 'gov-spinner' : ''} style={loading ? { width: '13px', height: '13px', borderTopColor: '#38BDF8' } : {}} />
          <span>Sync</span>
        </button>

        {/* Operator Badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderLeft: '1px solid var(--border-default)', paddingLeft: '16px' }}>
          <UserCheck size={16} color="#10B981" />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>OPERATOR</span>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>STATION 01</span>
          </div>
        </div>
      </div>
    </header>
  );
};
