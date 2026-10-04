import React from 'react';
import { SystemDataStatus, CriticalLocation } from '../types/api';
import { 
  Layers, 
  Satellite, 
  Eye, 
  Mountain, 
  CloudRain, 
  Flame, 
  Activity, 
  Cpu, 
  CheckCircle2, 
  AlertTriangle 
} from 'lucide-react';

interface EvidenceExplorerViewProps {
  dataStatus: SystemDataStatus | null;
  locations: CriticalLocation[];
  onSelectLocation: (loc: CriticalLocation) => void;
}

export const EvidenceExplorerView: React.FC<EvidenceExplorerViewProps> = ({
  dataStatus,
  locations,
  onSelectLocation,
}) => {
  const providers = dataStatus?.providers || {
    copernicus_sentinel_2: 'ONLINE',
    copernicus_sentinel_1: 'ONLINE',
    copernicus_dem_glo30: 'ONLINE',
    usgs_earthquakes: 'ONLINE',
    openstreetmap: 'ONLINE',
    nasa_firms: 'ONLINE',
    groq_lpu: 'ONLINE',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Telemetry Providers Panel */}
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">
            <Layers size={16} color="var(--accent-cyan)" />
            <span>Sovereign Earth Observation Stream Telemetry</span>
          </div>
          <span style={{ fontSize: '11px', color: '#10B981', fontWeight: 600 }}>
            {dataStatus?.mode || 'REAL_DATA_ONLY'}
          </span>
        </div>

        <div className="gov-panel-body">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
            <div className="gov-kpi-card">
              <div className="gov-kpi-title">
                <span>Copernicus Sentinel-1 SAR</span>
                <Satellite size={16} color="#38BDF8" />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="gov-indicator-dot" style={{ color: '#10B981' }} />
                <span style={{ fontWeight: 700, color: '#FFF' }}>{providers.copernicus_sentinel_1 || 'ONLINE'}</span>
              </div>
              <div className="gov-kpi-sub">C-band Synthetic Aperture Radar (VV/VH Backscatter)</div>
            </div>

            <div className="gov-kpi-card">
              <div className="gov-kpi-title">
                <span>Copernicus Sentinel-2 Optical</span>
                <Eye size={16} color="#10B981" />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="gov-indicator-dot" style={{ color: '#10B981' }} />
                <span style={{ fontWeight: 700, color: '#FFF' }}>{providers.copernicus_sentinel_2 || 'ONLINE'}</span>
              </div>
              <div className="gov-kpi-sub">13-Band Multispectral MSI (NDWI / MNDWI Indices)</div>
            </div>

            <div className="gov-kpi-card">
              <div className="gov-kpi-title">
                <span>Copernicus DEM GLO-30</span>
                <Mountain size={16} color="#F59E0B" />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="gov-indicator-dot" style={{ color: '#10B981' }} />
                <span style={{ fontWeight: 700, color: '#FFF' }}>{providers.copernicus_dem_glo30 || 'ONLINE'}</span>
              </div>
              <div className="gov-kpi-sub">30-meter Topographic Elevation &amp; Slope Gradients</div>
            </div>

            <div className="gov-kpi-card">
              <div className="gov-kpi-title">
                <span>NASA FIRMS Active Fire</span>
                <Flame size={16} color="#F97316" />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="gov-indicator-dot" style={{ color: '#10B981' }} />
                <span style={{ fontWeight: 700, color: '#FFF' }}>{providers.nasa_firms || 'ONLINE'}</span>
              </div>
              <div className="gov-kpi-sub">Thermal Anomaly Verification (MODIS / VIIRS 24h)</div>
            </div>

            <div className="gov-kpi-card">
              <div className="gov-kpi-title">
                <span>USGS Earthquake Hazards</span>
                <Activity size={16} color="#EC4899" />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="gov-indicator-dot" style={{ color: '#10B981' }} />
                <span style={{ fontWeight: 700, color: '#FFF' }}>{providers.usgs_earthquakes || 'ONLINE'}</span>
              </div>
              <div className="gov-kpi-sub">Near Real-Time Seismic Activity &amp; Magnitude Analysis</div>
            </div>

            <div className="gov-kpi-card">
              <div className="gov-kpi-title">
                <span>Groq LPU Evidence Analyst</span>
                <Cpu size={16} color="#0EA5E9" />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="gov-indicator-dot" style={{ color: '#10B981' }} />
                <span style={{ fontWeight: 700, color: '#FFF' }}>{providers.groq_lpu || 'ONLINE'}</span>
              </div>
              <div className="gov-kpi-sub">High-Speed Contextual Synthesis (Non-authoritative)</div>
            </div>
          </div>
        </div>
      </div>

      {/* Authoritative Data Semantics Governance Box */}
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">
            <CheckCircle2 size={16} color="#10B981" />
            <span>SATGUARD Data Availability &amp; Missing-Data Governance</span>
          </div>
        </div>

        <div className="gov-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <p style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.6 }}>
            In government-grade early warning platforms, observational absence must never be conflated with zero measurement.
            SATGUARD enforces strict observational semantics:
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
            <div style={{ background: 'var(--bg-card)', padding: '14px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
              <div style={{ color: '#F87171', fontWeight: 700, fontSize: '12px', marginBottom: '4px' }}>
                FORBIDDEN ASSUMPTION: Rainfall = 0 mm
              </div>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                When precipitation radar telemetry is unavailable or uncalibrated, the platform reports{' '}
                <strong style={{ color: '#FFF' }}>RAINFALL DATA UNAVAILABLE</strong>. It is never assumed to be dry weather.
              </p>
            </div>

            <div style={{ background: 'var(--bg-card)', padding: '14px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
              <div style={{ color: '#F59E0B', fontWeight: 700, fontSize: '12px', marginBottom: '4px' }}>
                CLOUD CONTAMINATION: Optical Limitations
              </div>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                When optical scenes exceed cloud thresholds (&gt;20%), the platform explicitly triggers{' '}
                <strong style={{ color: '#FFF' }}>OPTICAL EVIDENCE LIMITED</strong>. Sentinel-1 SAR all-weather radar provides the primary evidence.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
