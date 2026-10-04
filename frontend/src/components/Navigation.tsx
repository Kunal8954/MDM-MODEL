import React from 'react';
import { 
  LayoutDashboard, 
  MapPin, 
  Globe2,
  AlertTriangle, 
  Activity, 
  Layers,
  ChevronRight
} from 'lucide-react';

export type ActiveTab =
  | 'overview'
  | 'locations'
  | 'alerts'
  | 'monitoring'
  | 'evidence'
  | 'aoi';

interface NavigationProps {
  activeTab: ActiveTab;
  onTabChange: (tab: ActiveTab) => void;
  activeAlertsCount: number;
}

export const Navigation: React.FC<NavigationProps> = ({
  activeTab,
  onTabChange,
  activeAlertsCount,
}) => {
  const navItems = [
    { id: 'overview' as ActiveTab, label: 'Overview', icon: LayoutDashboard },
    { id: 'locations' as ActiveTab, label: 'Critical Locations', icon: MapPin },
    { 
      id: 'alerts' as ActiveTab, 
      label: 'Government Alerts', 
      icon: AlertTriangle, 
      badge: activeAlertsCount > 0 ? activeAlertsCount : null,
      isAlertBadge: true 
    },
    { id: 'monitoring' as ActiveTab, label: 'Monitoring Center', icon: Activity },
    { id: 'aoi' as ActiveTab, label: 'Area Monitoring', icon: Globe2 },
    { id: 'evidence' as ActiveTab, label: 'Evidence Explorer', icon: Layers },
  ];

  return (
    <nav className="gov-sidebar" aria-label="Main Navigation">
      <div style={{ padding: '0 8px 12px 8px', borderBottom: '1px solid var(--border-subtle)', marginBottom: '8px' }}>
        <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          Mission Control
        </span>
      </div>

      {navItems.map((item) => {
        const Icon = item.icon;
        const isActive = activeTab === item.id;
        return (
          <button
            key={item.id}
            className={`gov-nav-item ${isActive ? 'active' : ''}`}
            onClick={() => onTabChange(item.id)}
            aria-current={isActive ? 'page' : undefined}
          >
            <Icon size={16} />
            <span>{item.label}</span>
            {item.badge !== null && item.badge !== undefined && (
              <span className={`gov-nav-badge ${item.isAlertBadge ? 'alert-badge' : ''}`}>
                {item.badge}
              </span>
            )}
            {isActive && <ChevronRight size={14} style={{ marginLeft: item.badge ? '4px' : 'auto', color: 'var(--accent-cyan)' }} />}
          </button>
        );
      })}

      <div style={{ marginTop: 'auto', padding: '12px 8px', borderTop: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.4 }}>
          <div>CLASSIFICATION:</div>
          <div style={{ color: '#F87171', fontWeight: 600 }}>CONFIDENTIAL // GOV-ONLY</div>
          <div style={{ marginTop: '6px', fontSize: '10px' }}>DISCLAIMER: Non-autonomous decision support interface.</div>
        </div>
      </div>
    </nav>
  );
};
