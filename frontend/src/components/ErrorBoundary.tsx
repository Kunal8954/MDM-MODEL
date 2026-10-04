import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('SATGUARD Uncaught Dashboard Exception:', error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#0B1320',
            color: '#F8FAFC',
            padding: '20px',
            fontFamily: 'Inter, sans-serif',
          }}
        >
          <div
            style={{
              maxWidth: '540px',
              width: '100%',
              background: '#162032',
              border: '1px solid rgba(239, 68, 68, 0.4)',
              borderRadius: '8px',
              padding: '24px',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#EF4444', marginBottom: '14px' }}>
              <AlertTriangle size={24} />
              <h2 style={{ fontSize: '18px', fontWeight: 700, margin: 0 }}>
                SATGUARD Interface Recovery
              </h2>
            </div>
            <p style={{ fontSize: '13px', color: '#94A3B8', marginBottom: '14px', lineHeight: 1.5 }}>
              A UI rendering exception was captured. Mission Control state remains active and preserved.
            </p>
            {this.state.error && (
              <pre
                style={{
                  background: '#0B1320',
                  padding: '12px',
                  borderRadius: '4px',
                  fontSize: '11px',
                  color: '#F87171',
                  overflowX: 'auto',
                  border: '1px solid #334155',
                  marginBottom: '18px',
                }}
              >
                {this.state.error.message}
              </pre>
            )}
            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                onClick={() => {
                  this.setState({ hasError: false, error: null });
                  window.location.reload();
                }}
                style={{
                  background: '#0284C7',
                  border: 'none',
                  color: '#FFF',
                  padding: '8px 16px',
                  borderRadius: '4px',
                  fontSize: '12px',
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                <RefreshCw size={14} />
                <span>Reload Dashboard</span>
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
