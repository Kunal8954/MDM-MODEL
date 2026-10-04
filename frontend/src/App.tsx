import React, { useState, useEffect, useCallback } from 'react';
import { 
  OverviewStats, 
  SystemDataStatus, 
  CriticalLocation, 
  Alert, 
  MonitoringRun 
} from './types/api';
import { api } from './api/client';
import { Header } from './components/Header';
import { Navigation, ActiveTab } from './components/Navigation';
import { OverviewView } from './views/OverviewView';
import { LocationsView } from './views/LocationsView';
import { LocationDetailView } from './views/LocationDetailView';
import { AlertsView } from './views/AlertsView';
import { MonitoringView } from './views/MonitoringView';
import { EvidenceExplorerView } from './views/EvidenceExplorerView';
import { AoiMonitoringView } from './views/AoiMonitoringView';
import { AlertCircle, RefreshCw } from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [selectedLocation, setSelectedLocation] = useState<CriticalLocation | null>(null);

  const [stats, setStats] = useState<OverviewStats | null>(null);
  const [dataStatus, setDataStatus] = useState<SystemDataStatus | null>(null);
  const [locations, setLocations] = useState<CriticalLocation[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [runs, setRuns] = useState<MonitoringRun[]>([]);

  const [loading, setLoading] = useState<boolean>(true);
  const [syncing, setSyncing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchGlobalData = useCallback(async (isManual = false) => {
    if (isManual) setSyncing(true);
    try {
      const [statsRes, statusRes, locsRes, alertsRes, runsRes] = await Promise.all([
        api.overview.getStats(),
        api.overview.getDataStatus(),
        api.locations.list(),
        api.alerts.list({ limit: 100 }),
        api.monitoring.listRuns({ limit: 100 }),
      ]);

      // Use enriched locations returned directly by /api/locations
      const enrichedLocs = locsRes;

      setStats(statsRes);
      setDataStatus(statusRes);
      setLocations(enrichedLocs);
      setAlerts(alertsRes);
      setRuns(runsRes);
      setError(null);

      // If a location is currently selected, update its reference
      if (selectedLocation) {
        const updated = enrichedLocs.find((l) => l.id === selectedLocation.id);
        if (updated) setSelectedLocation(updated);
      }
    } catch (err: any) {
      if (isManual) setError(err?.message || 'SATGUARD Surveillance Backend API unavailable');
    } finally {
      setLoading(false);
      if (isManual) setSyncing(false);
    }
  }, [selectedLocation?.id]);

  useEffect(() => {
    fetchGlobalData(false);
    // Continuous real-time telemetry polling every 5 seconds
    const interval = setInterval(() => {
      fetchGlobalData(false);
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchGlobalData]);


  const handleSelectLocation = (loc: CriticalLocation) => {
    setSelectedLocation(loc);
  };

  const handleBackFromDetail = () => {
    setSelectedLocation(null);
  };

  const handleTabChange = (tab: ActiveTab) => {
    setSelectedLocation(null);
    setActiveTab(tab);
  };

  const activeAlertsCount = stats?.active_alerts_count ?? alerts.filter((a) => a.status === 'ACTIVE').length;

  return (
    <div className="gov-app-container">
      {/* Global Command Header */}
      <Header
        stats={stats}
        dataStatus={dataStatus}
        loading={syncing}
        onRefresh={() => fetchGlobalData(true)}
      />


      <div className="gov-body-layout">
        {/* Mission Control Sidebar */}
        <Navigation
          activeTab={activeTab}
          onTabChange={handleTabChange}
          activeAlertsCount={activeAlertsCount}
        />

        {/* Main Operational Viewport */}
        <main className="gov-main-viewport" role="main">
          {error ? (
            <div className="gov-panel">
              <div className="gov-state-container">
                <AlertCircle size={36} color="var(--risk-crit)" />
                <div className="gov-state-title" style={{ color: 'var(--risk-crit)' }}>
                  Backend Surveillance Service Unavailable
                </div>
                <div className="gov-state-desc">
                  {error}
                </div>
                <button
                  className="gov-btn gov-btn-primary"
                  onClick={() => fetchGlobalData(true)}
                  style={{ marginTop: '8px' }}

                >
                  <RefreshCw size={14} />
                  <span>Retry Connection</span>
                </button>
              </div>
            </div>
          ) : selectedLocation ? (
            <LocationDetailView
              location={selectedLocation}
              onBack={handleBackFromDetail}
              onAlertActionComplete={fetchGlobalData}
            />
          ) : activeTab === 'overview' ? (
            <OverviewView
              stats={stats}
              locations={locations}
              alerts={alerts}
              runs={runs}
              loading={loading}
              onSelectLocation={handleSelectLocation}
              onNavigateTab={handleTabChange}
              onRefresh={fetchGlobalData}
            />
          ) : activeTab === 'locations' ? (
            <LocationsView
              locations={locations}
              loading={loading}
              onSelectLocation={handleSelectLocation}
            />
          ) : activeTab === 'alerts' ? (
            <AlertsView
              alerts={alerts}
              locations={locations}
              loading={loading}
              onRefresh={fetchGlobalData}
              onSelectLocation={(loc) => {
                setSelectedLocation(loc);
              }}
            />
          ) : activeTab === 'monitoring' ? (
            <MonitoringView
              runs={runs}
              locations={locations}
              loading={loading}
              onRefresh={fetchGlobalData}
              onSelectLocation={(loc) => {
                setSelectedLocation(loc);
              }}
            />
          ) : activeTab === 'aoi' ? (
            <AoiMonitoringView />
          ) : (
            <EvidenceExplorerView
              dataStatus={dataStatus}
              locations={locations}
              onSelectLocation={handleSelectLocation}
            />
          )}
        </main>
      </div>
    </div>
  );
};

export default App;
