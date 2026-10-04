import React, { useState, useMemo } from 'react';
import { CriticalLocation } from '../types/api';
import { Search, Filter, MapPin, Eye, ShieldAlert, ArrowRight } from 'lucide-react';

interface LocationsViewProps {
  locations: CriticalLocation[];
  loading: boolean;
  onSelectLocation: (location: CriticalLocation) => void;
}

export const LocationsView: React.FC<LocationsViewProps> = ({
  locations,
  loading,
  onSelectLocation,
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [riskFilter, setRiskFilter] = useState('ALL');
  const [typeFilter, setTypeFilter] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');

  // Distinct types from data
  const distinctTypes = useMemo(() => {
    const set = new Set<string>();
    locations.forEach((l) => {
      if (l.location_type) set.add(l.location_type);
    });
    return Array.from(set).sort();
  }, [locations]);

  const filteredLocations = useMemo(() => {
    return locations.filter((loc) => {
      const q = searchQuery.toLowerCase().trim();
      const matchesSearch =
        !q ||
        loc.name.toLowerCase().includes(q) ||
        loc.id.toLowerCase().includes(q) ||
        loc.location_type?.toLowerCase().includes(q);

      const locRisk = loc.latest_risk?.risk_level || 'LOW';
      const matchesRisk = riskFilter === 'ALL' || locRisk.toUpperCase() === riskFilter;

      const matchesType = typeFilter === 'ALL' || loc.location_type === typeFilter;

      const matchesStatus =
        statusFilter === 'ALL' || loc.monitoring_status?.toUpperCase() === statusFilter;

      return matchesSearch && matchesRisk && matchesType && matchesStatus;
    });
  }, [locations, searchQuery, riskFilter, typeFilter, statusFilter]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Search & Filter Toolbar */}
      <div className="gov-panel">
        <div className="gov-panel-body" style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', justifyContent: 'space-between' }}>
          {/* Search Box */}
          <div className="gov-search-bar">
            <Search size={16} color="var(--text-muted)" />
            <input
              type="text"
              placeholder="Search by Location Name, ID, or Type..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Search critical locations"
            />
          </div>

          {/* Filters Group */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
            {/* Risk Filter */}
            <select
              className="gov-select"
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              aria-label="Filter by Risk Level"
            >
              <option value="ALL">All Risk Levels</option>
              <option value="CRITICAL">CRITICAL Risk</option>
              <option value="HIGH">HIGH Risk</option>
              <option value="MODERATE">MODERATE Risk</option>
              <option value="LOW">LOW Risk</option>
            </select>

            {/* Type Filter */}
            <select
              className="gov-select"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              aria-label="Filter by Location Type"
            >
              <option value="ALL">All Location Types</option>
              {distinctTypes.map((t) => (
                <option key={t} value={t}>
                  {t.toUpperCase()}
                </option>
              ))}
            </select>

            {/* Status Filter */}
            <select
              className="gov-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              aria-label="Filter by Surveillance Status"
            >
              <option value="ALL">All Surveillance States</option>
              <option value="ACTIVE">ACTIVE Surveillance</option>
              <option value="PAUSED">PAUSED</option>
              <option value="DISABLED">DISABLED</option>
            </select>
          </div>
        </div>
      </div>

      {/* Locations Table / Grid */}
      <div className="gov-panel">
        <div className="gov-panel-header">
          <div className="gov-panel-title">
            <MapPin size={16} color="var(--accent-cyan)" />
            <span>Government Critical Locations Directory</span>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Showing {filteredLocations.length} of {locations.length} Sites
          </span>
        </div>

        <div className="gov-panel-body" style={{ padding: 0 }}>
          {filteredLocations.length > 0 ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="gov-table">
                <thead>
                  <tr>
                    <th>Location ID &amp; Name</th>
                    <th>Category</th>
                    <th>Coordinates</th>
                    <th>Authoritative Risk</th>
                    <th>Monitoring State</th>
                    <th>Surveillance Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLocations.map((loc) => {
                    const risk = loc.latest_risk;
                    const riskLevel = risk?.risk_level || 'LOW';
                    const score = risk?.score;

                    return (
                      <tr key={loc.id} style={{ cursor: 'pointer' }} onClick={() => onSelectLocation(loc)}>
                        <td>
                          <div style={{ display: 'flex', flexDirection: 'column' }}>
                            <span style={{ fontWeight: 600, color: '#FFF' }}>{loc.name}</span>
                            <span className="mono" style={{ fontSize: '11px', color: '#38BDF8' }}>{loc.id}</span>
                          </div>
                        </td>
                        <td>
                          <span style={{ textTransform: 'uppercase', fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)' }}>
                            {loc.location_type}
                          </span>
                        </td>
                        <td>
                          <span className="mono" style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            {loc.latitude.toFixed(4)}°N, {loc.longitude.toFixed(4)}°E
                          </span>
                        </td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span className={`badge-risk ${riskLevel}`}>
                              {riskLevel}
                            </span>
                            {score !== undefined && (
                              <span className="mono" style={{ fontSize: '12px', fontWeight: 600 }}>
                                {score.toFixed(2)}
                              </span>
                            )}
                          </div>
                        </td>
                        <td>
                          <span className={`badge-status ${loc.monitoring_status}`}>
                            {loc.monitoring_status}
                          </span>
                        </td>
                        <td>
                          <button
                            className="gov-btn gov-btn-secondary"
                            onClick={(e) => {
                              e.stopPropagation();
                              onSelectLocation(loc);
                            }}
                            style={{ padding: '4px 10px', fontSize: '11px' }}
                          >
                            <span>Inspect</span>
                            <ArrowRight size={12} />
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
              No critical locations matched the specified filter criteria.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
