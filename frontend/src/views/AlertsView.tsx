import React, { useState, useMemo } from 'react';
import { Alert, CriticalLocation } from '../types/api';
import { api } from '../api/client';
import { AlertLifecycleModal } from '../components/AlertLifecycleModal';
import { 
  AlertTriangle, 
  Search, 
  Filter, 
  CheckCircle2, 
  Clock, 
  ShieldAlert, 
  ExternalLink 
} from 'lucide-react';

interface AlertsViewProps {
  alerts: Alert[];
  locations: CriticalLocation[];
  loading: boolean;
  onRefresh: () => void;
  onSelectLocation: (location: CriticalLocation) => void;
}

export const AlertsView: React.FC<AlertsViewProps> = ({
  alerts,
  locations,
  loading,
  onRefresh,
  onSelectLocation,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [priorityFilter, setPriorityFilter] = useState('ALL');
  const [selectedAlert, setSelectedAlert] = useState<Alert | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const filteredAlerts = useMemo(() => {
    return alerts.filter((al) => {
      const q = searchQuery.toLowerCase().trim();
      const matchesSearch =
        !q ||
        al.id.toLowerCase().includes(q) ||
        al.title.toLowerCase().includes(q) ||
        (al.location_name && al.location_name.toLowerCase().includes(q)) ||
        al.location_id.toLowerCase().includes(q);

      const matchesStatus = statusFilter === 'ALL' || al.status === statusFilter;
      const matchesPriority = priorityFilter === 'ALL' || al.priority === priorityFilter;

      return matchesSearch && matchesStatus && matchesPriority;
    });
  }, [alerts, searchQuery, statusFilter, priorityFilter]);

  const handleAlertAction = async (
    alertId: string,
    action: 'acknowledge' | 'review' | 'resolve',
    note: string
  ) => {
    if (action === 'acknowledge') await api.alerts.acknowledge(alertId, note);
    else if (action === 'review') await api.alerts.review(alertId, note);
    else if (action === 'resolve') await api.alerts.resolve(alertId, note);
    onRefresh();
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Search & Filter Bar */}
      <div className="gov-panel">
        <div className="gov-panel-body" style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', justifyContent: 'space-between' }}>
          <div className="gov-search-bar">
            <Search size={16} color="var(--text-muted)" />
            <input
              type="text"
              placeholder="Search by Alert ID, Title, or Location..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Search alerts"
            />
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
            <select
              className="gov-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              aria-label="Filter by Alert Status"
            >
              <option value="ALL">All Lifecycle States</option>
              <option value="ACTIVE">ACTIVE</option>
              <option value="ACKNOWLEDGED">ACKNOWLEDGED</option>
              <option value="IN_REVIEW">IN_REVIEW</option>
              <option value="RESOLVED">RESOLVED</option>
            </select>

            <select
              className="gov-select"
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value)}
              aria-label="Filter by Alert Priority"
            >
              <option value="ALL">All Priorities</option>
              <option value="URGENT">URGENT</option>
              <option value="HIGH">HIGH</option>
              <option value="ELEVATED">ELEVATED</option>
              <option value="ROUTINE">ROUTINE</option>
              <option value="INFO">INFO</option>
            </select>
          </div>
        </div>
      </div>

      {/* Alerts Table */}
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">
            <AlertTriangle size={16} color="var(--risk-high)" />
            <span>Government Surveillance Alerts Center</span>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Showing {filteredAlerts.length} of {alerts.length} Alerts
          </span>
        </div>

        <div className="gov-panel-body" style={{ padding: 0 }}>
          {filteredAlerts.length > 0 ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="gov-table">
                <thead>
                  <tr>
                    <th>Alert ID</th>
                    <th>Location</th>
                    <th>Priority</th>
                    <th>Lifecycle State</th>
                    <th>Title &amp; Recommended Action</th>
                    <th>Created</th>
                    <th>Operator Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredAlerts.map((al) => {
                    const matchedLoc = locations.find((l) => l.id === al.location_id);
                    return (
                      <tr key={al.id}>
                        <td className="mono" style={{ fontSize: '11px', color: '#38BDF8' }}>
                          {al.id}
                        </td>
                        <td>
                          {matchedLoc ? (
                            <button
                              onClick={() => onSelectLocation(matchedLoc)}
                              style={{ background: 'none', border: 'none', color: '#FFF', fontWeight: 600, cursor: 'pointer', textAlign: 'left', display: 'flex', alignItems: 'center', gap: '4px' }}
                            >
                              <span>{al.location_name || matchedLoc.name}</span>
                              <ExternalLink size={12} color="var(--accent-cyan)" />
                            </button>
                          ) : (
                            <span style={{ color: '#FFF', fontWeight: 600 }}>{al.location_name || al.location_id}</span>
                          )}
                          <span className="mono" style={{ fontSize: '10px', color: 'var(--text-muted)', display: 'block' }}>
                            {al.location_id}
                          </span>
                        </td>
                        <td>
                          <span className={`badge-risk ${al.priority}`}>{al.priority}</span>
                        </td>
                        <td>
                          <span className={`badge-status ${al.status}`}>{al.status}</span>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600, color: '#FFF' }}>{al.title}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                            {al.recommended_action || al.summary}
                          </div>
                        </td>
                        <td className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          {new Date(al.created_at).toLocaleString()}
                        </td>
                        <td>
                          <button
                            className="gov-btn gov-btn-secondary"
                            onClick={() => {
                              setSelectedAlert(al);
                              setIsModalOpen(true);
                            }}
                            style={{ padding: '5px 10px', fontSize: '11px' }}
                          >
                            <span>Manage</span>
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
              No government alerts matched the current filters.
            </div>
          )}
        </div>
      </div>

      {/* Operator Alert Lifecycle Action Modal */}
      <AlertLifecycleModal
        alert={selectedAlert}
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setSelectedAlert(null);
        }}
        onAction={handleAlertAction}
      />
    </div>
  );
};
