import React, { useState } from 'react';
import { OverviewStats, CriticalLocation, Alert, MonitoringRun } from '../types/api';
import { GeospatialMap } from '../components/GeospatialMap';
import { api } from '../api/client';
import { 
  Building2, 
  AlertTriangle, 
  ShieldAlert, 
  Activity, 
  ArrowRight,
  Plus,
  Navigation,
  CheckCircle2,
  X
} from 'lucide-react';

interface OverviewViewProps {
  stats: OverviewStats | null;
  locations: CriticalLocation[];
  alerts: Alert[];
  runs: MonitoringRun[];
  loading: boolean;
  onSelectLocation: (loc: CriticalLocation) => void;
  onNavigateTab: (tab: 'locations' | 'alerts' | 'monitoring' | 'evidence') => void;
  onRefresh?: () => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  stats,
  locations,
  alerts,
  runs,
  loading,
  onSelectLocation,
  onNavigateTab,
  onRefresh,
}) => {
  const activeAlerts = alerts.filter((a) => a.status === 'ACTIVE');

  // Interactive Map Focus State
  const [selectedMapLocId, setSelectedMapLocId] = useState<string | null>(
    locations.length > 0 ? locations[0].id : null
  );

  // Custom Location Modal State
  const [showAddModal, setShowAddModal] = useState<boolean>(false);
  const [customName, setCustomName] = useState<string>('');
  const [customLat, setCustomLat] = useState<string>('');
  const [customLng, setCustomLng] = useState<string>('');
  const [customType, setCustomType] = useState<string>('CRITICAL_INFRASTRUCTURE');
  const [customRadius, setCustomRadius] = useState<number>(5000);
  const [addLoading, setAddLoading] = useState<boolean>(false);
  const [addError, setAddError] = useState<string | null>(null);
  const [addSuccess, setAddSuccess] = useState<string | null>(null);

  const selectedMapLocation = locations.find((l) => l.id === selectedMapLocId) || locations[0];

  const handleCreateCustomLocation = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddError(null);
    setAddSuccess(null);

    const lat = parseFloat(customLat);
    const lng = parseFloat(customLng);

    if (!customName.trim()) {
      setAddError('Location name is required.');
      return;
    }
    if (isNaN(lat) || lat < -90 || lat > 90) {
      setAddError('Valid Latitude (-90 to +90) is required.');
      return;
    }
    if (isNaN(lng) || lng < -180 || lng > 180) {
      setAddError('Valid Longitude (-180 to +180) is required.');
      return;
    }

    try {
      setAddLoading(true);
      const newLoc = await api.locations.create({
        name: customName.trim(),
        latitude: lat,
        longitude: lng,
        location_type: customType,
        radius_m: customRadius,
        description: `Operator created surveillance target at ${lat}°N, ${lng}°E`,
      });
      setAddSuccess(`Site '${newLoc.name}' deployed successfully!`);
      if (onRefresh) onRefresh();
      setSelectedMapLocId(newLoc.id);
      setTimeout(() => {
        setShowAddModal(false);
        setCustomName('');
        setCustomLat('');
        setCustomLng('');
        setAddSuccess(null);
      }, 1200);
    } catch (err: any) {
      setAddError(err.message || 'Failed to create location.');
    } finally {
      setAddLoading(false);
    }
  };

  const handleCoordsPickedFromMap = (coords: { lat: number; lng: number }) => {
    setCustomLat(coords.lat.toString());
    setCustomLng(coords.lng.toString());
    setShowAddModal(true);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* KPI Stats Grid */}
      <div className="gov-kpi-grid">
        <div className="gov-kpi-card" onClick={() => onNavigateTab('locations')} style={{ cursor: 'pointer' }}>
          <div className="gov-kpi-title">
            <span>Critical Sites</span>
            <Building2 size={16} color="var(--accent-cyan)" />
          </div>
          <div className="gov-kpi-value">{stats?.total_locations ?? locations.length}</div>
          <div className="gov-kpi-sub">
            {stats?.active_monitoring_locations ?? locations.filter(l => l.monitoring_status === 'ACTIVE').length} Under Active Surveillance
          </div>
        </div>

        <div className="gov-kpi-card high-alert" onClick={() => onNavigateTab('locations')} style={{ cursor: 'pointer' }}>
          <div className="gov-kpi-title">
            <span>High Risk Sites</span>
            <ShieldAlert size={16} color="var(--risk-high)" />
          </div>
          <div className="gov-kpi-value" style={{ color: 'var(--risk-high)' }}>
            {stats?.high_risk_locations ?? locations.filter(l => l.latest_risk?.risk_level === 'HIGH').length}
          </div>
          <div className="gov-kpi-sub">Authoritative Score &gt; 50</div>
        </div>

        <div className="gov-kpi-card crit-alert" onClick={() => onNavigateTab('locations')} style={{ cursor: 'pointer' }}>
          <div className="gov-kpi-title">
            <span>Critical Sites</span>
            <AlertTriangle size={16} color="var(--risk-crit)" />
          </div>
          <div className="gov-kpi-value" style={{ color: 'var(--risk-crit)' }}>
            {stats?.critical_risk_locations ?? locations.filter(l => l.latest_risk?.risk_level === 'CRITICAL').length}
          </div>
          <div className="gov-kpi-sub">Urgent Reassessment Priority</div>
        </div>

        <div className="gov-kpi-card" onClick={() => onNavigateTab('alerts')} style={{ cursor: 'pointer' }}>
          <div className="gov-kpi-title">
            <span>Active Alerts</span>
            <AlertTriangle size={16} color="#F59E0B" />
          </div>
          <div className="gov-kpi-value" style={{ color: '#F59E0B' }}>
            {stats?.active_alerts_count ?? activeAlerts.length}
          </div>
          <div className="gov-kpi-sub">Awaiting Operator Verification</div>
        </div>

        <div className="gov-kpi-card" onClick={() => onNavigateTab('monitoring')} style={{ cursor: 'pointer' }}>
          <div className="gov-kpi-title">
            <span>Monitoring Engine</span>
            <Activity size={16} color="#10B981" />
          </div>
          <div className="gov-kpi-value" style={{ fontSize: '18px', color: '#10B981', paddingTop: '6px' }}>
            {stats?.system_status || 'OPERATIONAL'}
          </div>
          <div className="gov-kpi-sub">{stats?.recent_runs_count ?? runs.length} Automated Runs Audited</div>
        </div>
      </div>

      {/* Operator Target Selection Toolbar */}
      <div
        className="gov-panel"
        style={{
          padding: '12px 16px',
          background: 'linear-gradient(90deg, #111C2E 0%, #17243B 100%)',
          border: '1px solid var(--border-default)',
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', justifyContent: 'space-between' }}>
          {/* Site Selector Dropdown */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: '1 1 320px' }}>
            <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--accent-cyan)', display: 'flex', alignItems: 'center', gap: '5px', whiteSpace: 'nowrap' }}>
              <Navigation size={14} /> SELECT LOCATION:
            </span>
            <select
              className="gov-select"
              style={{ flex: 1, minWidth: '220px', padding: '7px 12px', background: '#0B1320', color: '#F8FAFC', border: '1px solid #334155' }}
              value={selectedMapLocId || ''}
              onChange={(e) => {
                const id = e.target.value;
                setSelectedMapLocId(id);
              }}
            >
              {locations.map((loc) => {
                const risk = loc.latest_risk?.risk_level || 'LOW';
                return (
                  <option key={loc.id} value={loc.id}>
                    [{risk}] {loc.name} — ({loc.latitude.toFixed(2)}°N, {loc.longitude.toFixed(2)}°E)
                  </option>
                );
              })}
            </select>
          </div>

          {/* Action CTAs */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {selectedMapLocation && (
              <button
                className="gov-btn gov-btn-primary"
                onClick={() => onSelectLocation(selectedMapLocation)}
                style={{ padding: '7px 14px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}
                title="Inspect in-depth multi-sensor intelligence and SitRep"
              >
                <span>Inspect Intelligence</span>
                <ArrowRight size={13} />
              </button>
            )}

            <button
              className="gov-btn gov-btn-secondary"
              onClick={() => {
                setCustomLat('');
                setCustomLng('');
                setShowAddModal(true);
              }}
              style={{ padding: '7px 14px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px', background: 'rgba(56, 189, 248, 0.1)', color: '#38BDF8', borderColor: '#38BDF8' }}
              title="Add a custom coordinate or new site to monitor"
            >
              <Plus size={14} />
              <span>+ Add Custom Site</span>
            </button>
          </div>
        </div>

        {/* Quick-Jump Site Chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '10px', alignItems: 'center' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginRight: '4px' }}>Quick Jump:</span>
          {locations.slice(0, 8).map((loc) => {
            const isTarget = selectedMapLocId === loc.id;
            const risk = loc.latest_risk?.risk_level || 'LOW';
            const riskColor = risk === 'CRITICAL' ? '#EF4444' : risk === 'HIGH' ? '#F97316' : risk === 'MODERATE' ? '#F59E0B' : '#10B981';
            return (
              <button
                key={loc.id}
                onClick={() => setSelectedMapLocId(loc.id)}
                style={{
                  background: isTarget ? `${riskColor}22` : 'rgba(30, 41, 59, 0.6)',
                  color: isTarget ? '#FFF' : 'var(--text-secondary)',
                  border: `1px solid ${isTarget ? riskColor : 'var(--border-subtle)'}`,
                  borderRadius: '4px',
                  padding: '3px 8px',
                  fontSize: '11px',
                  fontWeight: isTarget ? 700 : 500,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  transition: 'all 0.15s ease',
                }}
              >
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: riskColor }} />
                <span>{loc.name.split(' ')[0]}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Geospatial Central Surveillance Map with True-Color Satellite Imagery */}
      <GeospatialMap
        locations={locations}
        selectedLocationId={selectedMapLocId}
        onSelectLocation={(loc) => {
          setSelectedMapLocId(loc.id);
          onSelectLocation(loc);
        }}
        onSelectCoordinates={handleCoordsPickedFromMap}
      />

      {/* Custom Location Modal */}
      {showAddModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            zIndex: 1000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
            backdropFilter: 'blur(4px)',
          }}
        >
          <div
            className="gov-panel"
            style={{
              width: '100%',
              maxWidth: '520px',
              background: '#0F172A',
              border: '1px solid var(--border-default)',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)',
            }}
          >
            <div className="gov-panel-header">
              <div className="gov-panel-title">
                <Navigation size={16} color="var(--accent-cyan)" />
                <span>Deploy Custom Surveillance Site</span>
              </div>
              <button
                onClick={() => setShowAddModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleCreateCustomLocation} className="gov-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Register any critical infrastructure site, glacial lake, dam, or custom coordinates into SATGUARD continuous satellite monitoring.
              </div>

              {addError && (
                <div style={{ padding: '8px 12px', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid #EF4444', borderRadius: '4px', color: '#FCA5A5', fontSize: '12px' }}>
                  {addError}
                </div>
              )}

              {addSuccess && (
                <div style={{ padding: '8px 12px', background: 'rgba(16, 185, 129, 0.15)', border: '1px solid #10B981', borderRadius: '4px', color: '#6EE7B7', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <CheckCircle2 size={14} />
                  <span>{addSuccess}</span>
                </div>
              )}

              <div>
                <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                  LOCATION / SITE NAME *
                </label>
                <input
                  type="text"
                  className="gov-search-bar input"
                  style={{ width: '100%', background: '#1E293B', color: '#FFF', border: '1px solid #334155', padding: '8px 12px', borderRadius: '4px' }}
                  placeholder="e.g. Pangong Tso Outpost, Nanda Devi Glacier"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  required
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                    LATITUDE (°N) *
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    className="gov-search-bar input"
                    style={{ width: '100%', background: '#1E293B', color: '#FFF', border: '1px solid #334155', padding: '8px 12px', borderRadius: '4px' }}
                    placeholder="e.g. 30.3780"
                    value={customLat}
                    onChange={(e) => setCustomLat(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                    LONGITUDE (°E) *
                  </label>
                  <input
                    type="number"
                    step="0.0001"
                    className="gov-search-bar input"
                    style={{ width: '100%', background: '#1E293B', color: '#FFF', border: '1px solid #334155', padding: '8px 12px', borderRadius: '4px' }}
                    placeholder="e.g. 78.4800"
                    value={customLng}
                    onChange={(e) => setCustomLng(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                    LOCATION TYPE
                  </label>
                  <select
                    className="gov-select"
                    style={{ width: '100%', background: '#1E293B', color: '#FFF', border: '1px solid #334155', padding: '8px' }}
                    value={customType}
                    onChange={(e) => setCustomType(e.target.value)}
                  >
                    <option value="DAM">Dam / Reservoir</option>
                    <option value="GLACIAL_LAKE">Glacial Lake (GLOF Risk)</option>
                    <option value="CRITICAL_INFRASTRUCTURE">Bridge / Critical Infrastructure</option>
                    <option value="LANDSLIDE_SLOPE">Subsidence / Mountain Slope</option>
                    <option value="MILITARY_BASE">Strategic Outpost / Border</option>
                    <option value="COASTAL">Coastal Corridor</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                    AOI SURVEILLANCE RADIUS (METERS)
                  </label>
                  <input
                    type="number"
                    step="500"
                    min="500"
                    max="50000"
                    className="gov-search-bar input"
                    style={{ width: '100%', background: '#1E293B', color: '#FFF', border: '1px solid #334155', padding: '8px 12px', borderRadius: '4px' }}
                    value={customRadius}
                    onChange={(e) => setCustomRadius(parseInt(e.target.value) || 5000)}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                <button
                  type="button"
                  className="gov-btn gov-btn-secondary"
                  onClick={() => setShowAddModal(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="gov-btn gov-btn-primary"
                  disabled={addLoading}
                  style={{ minWidth: '130px' }}
                >
                  {addLoading ? 'Deploying...' : 'Deploy Target'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Dual Activity Panels: Active Alerts & Recent Monitoring Runs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '20px' }}>
        {/* Active Alerts List */}
        <div className="gov-panel">
          <div className="gov-panel-header">
            <div className="gov-panel-title">
              <AlertTriangle size={16} color="var(--risk-high)" />
              <span>Active Government Surveillance Alerts</span>
            </div>
            <button
              className="gov-btn gov-btn-secondary"
              onClick={() => onNavigateTab('alerts')}
              style={{ padding: '4px 8px', fontSize: '11px' }}
            >
              <span>View All</span>
              <ArrowRight size={12} />
            </button>
          </div>

          <div className="gov-panel-body" style={{ padding: '0' }}>
            {activeAlerts.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {activeAlerts.slice(0, 4).map((alert) => (
                  <div
                    key={alert.id}
                    onClick={() => {
                      const matchedLoc = locations.find((l) => l.id === alert.location_id);
                      if (matchedLoc) onSelectLocation(matchedLoc);
                    }}
                    style={{
                      padding: '12px 16px',
                      borderBottom: '1px solid var(--border-subtle)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-card)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                        <span className={`badge-risk ${alert.priority}`}>{alert.priority}</span>
                        <span style={{ fontSize: '13px', fontWeight: 600, color: '#FFF' }}>
                          {alert.location_name || alert.location_id}
                        </span>
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                        {alert.title}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        {new Date(alert.created_at).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
                No active government alerts at this time.
              </div>
            )}
          </div>
        </div>

        {/* Recent Monitoring Runs */}
        <div className="gov-panel">
          <div className="gov-panel-header">
            <div className="gov-panel-title">
              <Activity size={16} color="var(--accent-cyan)" />
              <span>Recent Automated Monitoring Audits</span>
            </div>
            <button
              className="gov-btn gov-btn-secondary"
              onClick={() => onNavigateTab('monitoring')}
              style={{ padding: '4px 8px', fontSize: '11px' }}
            >
              <span>View All</span>
              <ArrowRight size={12} />
            </button>
          </div>

          <div className="gov-panel-body" style={{ padding: '0' }}>
            {runs.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {runs.slice(0, 4).map((run) => (
                  <div
                    key={run.id}
                    onClick={() => {
                      const matchedLoc = locations.find((l) => l.id === run.location_id);
                      if (matchedLoc) onSelectLocation(matchedLoc);
                    }}
                    style={{
                      padding: '12px 16px',
                      borderBottom: '1px solid var(--border-subtle)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                      transition: 'background 0.15s',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-card)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
                        <span className="mono" style={{ fontSize: '11px', color: '#38BDF8' }}>
                          {run.location_id}
                        </span>
                        <span className="badge-status" style={{ fontSize: '10px' }}>
                          {run.trigger_type}
                        </span>
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        Stage: {run.current_stage} • Outcome: {run.outcome_code || 'COMPLETED'}
                      </div>
                    </div>
                    <div>
                      <span className={`badge-risk ${run.status === 'COMPLETED' ? 'LOW' : run.status === 'FAILED' ? 'CRITICAL' : 'MODERATE'}`}>
                        {run.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
                No recent monitoring runs logged.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
