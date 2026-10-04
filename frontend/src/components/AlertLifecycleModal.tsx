import React, { useState } from 'react';
import { Alert } from '../types/api';
import { AlertTriangle, CheckCircle, Clock, ShieldAlert, X } from 'lucide-react';

interface AlertLifecycleModalProps {
  alert: Alert | null;
  isOpen: boolean;
  onClose: () => void;
  onAction: (alertId: string, action: 'acknowledge' | 'review' | 'resolve', note: string) => Promise<void>;
}

export const AlertLifecycleModal: React.FC<AlertLifecycleModalProps> = ({
  alert,
  isOpen,
  onClose,
  onAction,
}) => {
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isOpen || !alert) return null;

  const handleAction = async (action: 'acknowledge' | 'review' | 'resolve') => {
    setLoading(true);
    setError(null);
    try {
      await onAction(alert.id, action, note);
      setNote('');
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to update alert state');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="alert-modal-title"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.75)',
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
          maxWidth: '540px',
          boxShadow: 'var(--shadow-lg)',
          overflow: 'hidden',
        }}
      >
        <div className="gov-panel-header" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div className="gov-panel-title" id="alert-modal-title">
            <ShieldAlert size={18} color="var(--risk-high)" />
            <span>Government Alert Operator Action</span>
          </div>
          <button
            onClick={onClose}
            aria-label="Close modal"
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
          >
            <X size={18} />
          </button>
        </div>

        <div className="gov-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <span className={`badge-risk ${alert.priority}`}>{alert.priority}</span>
              <span className={`badge-status ${alert.status}`}>{alert.status}</span>
              <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{alert.id}</span>
            </div>
            <h3 style={{ fontSize: '15px', fontWeight: 700, color: '#FFF' }}>{alert.title}</h3>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
              Location: <strong>{alert.location_name || alert.location_id}</strong>
            </p>
          </div>

          <div style={{ background: 'var(--bg-card)', padding: '12px', borderRadius: '6px', fontSize: '12px' }}>
            <span style={{ color: 'var(--text-muted)' }}>Recommended Action: </span>
            <span style={{ color: 'var(--text-primary)' }}>{alert.recommended_action || 'Verify with regional monitoring desk.'}</span>
          </div>

          {error && (
            <div style={{ background: 'rgba(239, 68, 68, 0.2)', border: '1px solid var(--risk-crit)', padding: '8px 12px', borderRadius: '4px', color: '#F87171', fontSize: '12px' }}>
              {error}
            </div>
          )}

          <div>
            <label htmlFor="operator-note" style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Operational Audit Note (Optional)
            </label>
            <textarea
              id="operator-note"
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g., Reviewed SAR backscatter change with Tehri field observatory. Continued monitoring ordered."
              style={{
                width: '100%',
                background: 'var(--bg-input)',
                border: '1px solid var(--border-default)',
                borderRadius: '6px',
                color: 'var(--text-primary)',
                padding: '8px 12px',
                fontSize: '12px',
                outline: 'none',
                resize: 'vertical',
                fontFamily: 'var(--font-sans)',
              }}
            />
          </div>

          {/* Action Buttons depending on current status */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '10px', marginTop: '8px' }}>
            <button className="gov-btn gov-btn-secondary" onClick={onClose} disabled={loading}>
              Cancel
            </button>

            {alert.status === 'ACTIVE' && (
              <button
                className="gov-btn gov-btn-primary"
                onClick={() => handleAction('acknowledge')}
                disabled={loading}
                style={{ background: '#0284C7' }}
              >
                <Clock size={14} />
                <span>Acknowledge Alert</span>
              </button>
            )}

            {(alert.status === 'ACTIVE' || alert.status === 'ACKNOWLEDGED') && (
              <button
                className="gov-btn gov-btn-primary"
                onClick={() => handleAction('review')}
                disabled={loading}
                style={{ background: '#D97706' }}
              >
                <AlertTriangle size={14} />
                <span>Start Formal Review</span>
              </button>
            )}

            {alert.status !== 'RESOLVED' && (
              <button
                className="gov-btn gov-btn-primary"
                onClick={() => handleAction('resolve')}
                disabled={loading}
                style={{ background: '#059669' }}
              >
                <CheckCircle size={14} />
                <span>Resolve Alert</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
