import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { CriticalLocation } from '../types/api';
import { MapPin, Info, Layers, Crosshair, RotateCcw, Radio } from 'lucide-react';

interface GeospatialMapProps {
  locations: CriticalLocation[];
  selectedLocationId?: string | null;
  onSelectLocation: (location: CriticalLocation) => void;
  onSelectCoordinates?: (coords: { lat: number; lng: number }) => void;
}

export const GeospatialMap: React.FC<GeospatialMapProps> = ({
  locations,
  selectedLocationId,
  onSelectLocation,
  onSelectCoordinates,
}) => {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const activeTileLayersRef = useRef<L.Layer[]>([]);
  const userPinLayerRef = useRef<L.LayerGroup | null>(null);

  const [basemap, setBasemap] = useState<'satellite' | 'dark'>('satellite');
  const [showSarSwath, setShowSarSwath] = useState<boolean>(true);
  const [clickedCoord, setClickedCoord] = useState<{ lat: number; lng: number } | null>(null);

  const getRiskColor = (level?: string) => {
    switch (level?.toUpperCase()) {
      case 'CRITICAL':
        return '#EF4444';
      case 'HIGH':
        return '#F97316';
      case 'MODERATE':
        return '#F59E0B';
      case 'LOW':
        return '#10B981';
      default:
        return '#64748B';
    }
  };

  // Initialize Map
  useEffect(() => {
    if (!mapContainerRef.current) return;
    if (mapInstanceRef.current) return;

    // Initialize Leaflet Map centered over India / Himalayan strategic corridors
    const map = L.map(mapContainerRef.current, {
      center: [28.5, 78.5],
      zoom: 6,
      zoomControl: true,
      attributionControl: false,
    });

    const markersLayer = L.layerGroup().addTo(map);
    const userPinLayer = L.layerGroup().addTo(map);
    markersLayerRef.current = markersLayer;
    userPinLayerRef.current = userPinLayer;
    mapInstanceRef.current = map;

    const timer = setTimeout(() => {
      try {
        if (mapContainerRef.current && (map as any)._mapPane && typeof map.invalidateSize === 'function') {
          map.invalidateSize();
        }
      } catch (e) {
        // Ignore pane detachment
      }
    }, 150);

    // Click anywhere on map to select coordinates
    if (typeof map.on === 'function') {
      map.on('click', (e: L.LeafletMouseEvent) => {
        const lat = parseFloat(e.latlng.lat.toFixed(5));
        const lng = parseFloat(e.latlng.lng.toFixed(5));
        setClickedCoord({ lat, lng });

        userPinLayer.clearLayers();
        const clickMarker = L.circleMarker([lat, lng], {
          radius: 8,
          fillColor: '#38BDF8',
          fillOpacity: 0.9,
          color: '#FFFFFF',
          weight: 2,
        });

        const popupContent = `
          <div style="font-family: Inter, sans-serif; color: #F8FAFC; background: #0F172A; padding: 10px; border-radius: 6px; min-width: 190px;">
            <div style="font-size: 11px; font-weight: 700; color: #38BDF8; margin-bottom: 4px;">OPERATOR PIN SELECTED</div>
            <div style="font-size: 12px; color: #E2E8F0; margin-bottom: 8px;">
              Lat: ${lat.toFixed(4)}°N<br/>Lng: ${lng.toFixed(4)}°E
            </div>
            <button id="btn-use-coords" style="width: 100%; background: #0284C7; border: none; color: #FFF; padding: 5px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; cursor: pointer;">
              Deploy Surveillance Here
            </button>
          </div>
        `;

        if (typeof clickMarker.bindPopup === 'function') {
          clickMarker.bindPopup(popupContent, { className: 'gov-leaflet-popup', closeButton: true });
        }
        userPinLayer.addLayer(clickMarker);
        if (typeof (clickMarker as any).openPopup === 'function') {
          (clickMarker as any).openPopup();
        }

        setTimeout(() => {
          const btn = document.getElementById('btn-use-coords');
          if (btn && onSelectCoordinates) {
            btn.onclick = () => onSelectCoordinates({ lat, lng });
          }
        }, 50);
      });
    }

    return () => {
      clearTimeout(timer);
      try {
        map.remove();
      } catch (e) {
        // Ignore unmount error
      }
      mapInstanceRef.current = null;
    };
  }, [onSelectCoordinates]);

  // Handle Basemap Switch (Satellite vs Dark)
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Remove existing tile layers
    if (typeof map.removeLayer === 'function') {
      activeTileLayersRef.current.forEach((layer) => {
        map.removeLayer(layer);
      });
    }
    activeTileLayersRef.current = [];

    if (basemap === 'satellite') {
      // ESRI High-Resolution True-Color Optical Satellite Imagery (0.5m resolution globally)
      const satLayer = L.tileLayer(
        'https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {
          maxZoom: 19,
          attribution: '&copy; Esri &copy; Maxar &copy; Earthstar Geographics',
        }
      ).addTo(map);

      // Boundaries & Place Labels overlay for high situational clarity
      const labelsLayer = L.tileLayer(
        'https://services.arcgisonline.com/arcgis/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        {
          maxZoom: 19,
          opacity: 0.85,
        }
      ).addTo(map);

      activeTileLayersRef.current = [satLayer, labelsLayer];
    } else {
      // Dark High-Contrast Tactical Canvas
      const darkLayer = L.tileLayer(
        'https://services.arcgisonline.com/arcgis/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
        {
          maxZoom: 16,
          attribution: '&copy; Esri Dark Gray Canvas',
        }
      ).addTo(map);

      activeTileLayersRef.current = [darkLayer];
    }
  }, [basemap]);

  // Update Markers & Sentinel SAR Swaths
  useEffect(() => {
    const map = mapInstanceRef.current;
    const layer = markersLayerRef.current;
    if (!map || !layer) return;

    layer.clearLayers();
    if (locations.length === 0) return;

    const bounds = L.latLngBounds([]);

    locations.forEach((loc) => {
      if (loc.latitude === undefined || loc.longitude === undefined) return;
      const latLng = L.latLng(loc.latitude, loc.longitude);
      bounds.extend(latLng);

      const riskLevel = loc.latest_risk?.risk_level || 'LOW';
      const color = getRiskColor(riskLevel);
      const isSelected = selectedLocationId === loc.id;

      // Primary Target Ring Marker
      const circleMarker = L.circleMarker(latLng, {
        radius: isSelected ? 13 : 9,
        fillColor: color,
        fillOpacity: 0.9,
        color: isSelected ? '#FFFFFF' : '#0F172A',
        weight: isSelected ? 3.5 : 2,
      });

      // AOI Radius Circle
      if (loc.radius_m && loc.radius_m > 0) {
        const aoiCircle = L.circle(latLng, {
          radius: Math.min(loc.radius_m, 20000),
          color: color,
          weight: isSelected ? 2 : 1,
          opacity: isSelected ? 0.8 : 0.4,
          fillColor: color,
          fillOpacity: isSelected ? 0.12 : 0.05,
          dashArray: isSelected ? undefined : '5, 5',
        });
        layer.addLayer(aoiCircle);
      }

      // Sentinel SAR Swath Representation (Simulated SAR-C Descending Orbit Footprint)
      if (showSarSwath && isSelected && typeof L.polygon === 'function') {
        const deltaLat = 0.08;
        const deltaLng = 0.12;
        const sarFootprint = L.polygon(
          [
            [loc.latitude - deltaLat, loc.longitude - deltaLng * 0.7],
            [loc.latitude - deltaLat * 0.4, loc.longitude + deltaLng * 1.1],
            [loc.latitude + deltaLat * 1.1, loc.longitude + deltaLng * 0.8],
            [loc.latitude + deltaLat * 0.6, loc.longitude - deltaLng],
          ],
          {
            color: '#38BDF8',
            weight: 1.5,
            dashArray: '3, 6',
            fillColor: '#0284C7',
            fillOpacity: 0.15,
          }
        );
        if (typeof sarFootprint.bindTooltip === 'function') {
          sarFootprint.bindTooltip('Sentinel-1 SAR Radar Swath (IW Orbit Pass)', {
            permanent: false,
            direction: 'top',
          });
        }
        layer.addLayer(sarFootprint);
      }

      // Interactive Popup
      const popupHtml = `
        <div style="font-family: Inter, sans-serif; color: #F8FAFC; background: #0F172A; padding: 12px; border-radius: 6px; min-width: 230px; border: 1px solid #334155;">
          <div style="font-size: 10px; font-weight: 700; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">
            ${loc.location_type || 'CRITICAL LOCATION'}
          </div>
          <div style="font-size: 14px; font-weight: 700; color: #FFF; margin-bottom: 8px;">
            ${loc.name}
          </div>
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-size: 12px;">
            <span style="color: #94A3B8;">Authoritative Risk:</span>
            <span style="background: ${color}25; color: ${color}; font-weight: 700; padding: 2px 7px; border-radius: 4px; border: 1px solid ${color}80;">
              ${riskLevel} ${loc.latest_risk?.score !== undefined ? `(${loc.latest_risk.score.toFixed(1)})` : ''}
            </span>
          </div>
          <div style="font-size: 11px; color: #94A3B8; margin-bottom: 10px;">
            Coords: ${loc.latitude.toFixed(4)}°N, ${loc.longitude.toFixed(4)}°E
          </div>
          <button id="btn-inspect-${loc.id}" style="width: 100%; background: #0284C7; border: none; color: #FFF; padding: 7px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; cursor: pointer; transition: background 0.2s;">
            Inspect Location Intelligence &rarr;
          </button>
        </div>
      `;

      circleMarker.bindPopup(popupHtml, {
        className: 'gov-leaflet-popup',
        closeButton: true,
      });

      circleMarker.on('popupopen', () => {
        const btn = document.getElementById(`btn-inspect-${loc.id}`);
        if (btn) {
          btn.onclick = () => onSelectLocation(loc);
        }
      });

      circleMarker.on('click', () => {
        onSelectLocation(loc);
      });

      layer.addLayer(circleMarker);
    });

    // View auto-focus behavior
    if (selectedLocationId) {
      const activeLoc = locations.find((l) => l.id === selectedLocationId);
      if (activeLoc && activeLoc.latitude && activeLoc.longitude) {
        if (typeof map.flyTo === 'function') {
          map.flyTo([activeLoc.latitude, activeLoc.longitude], 12, {
            duration: 1.2,
            easeLinearity: 0.25,
          });
        } else if (typeof map.setView === 'function') {
          map.setView([activeLoc.latitude, activeLoc.longitude], 12);
        }
      }
    }
  }, [locations, selectedLocationId, showSarSwath, onSelectLocation]);

  const resetBounds = () => {
    const map = mapInstanceRef.current;
    if (!map || locations.length === 0) return;
    const bounds = L.latLngBounds([]);
    locations.forEach((loc) => {
      if (loc.latitude !== undefined && loc.longitude !== undefined) {
        bounds.extend([loc.latitude, loc.longitude]);
      }
    });
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 8 });
    }
  };

  return (
    <div className="gov-panel" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div className="gov-panel-header" style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center', justifyContent: 'space-between' }}>
        <div className="gov-panel-title">
          <MapPin size={16} color="var(--accent-cyan)" />
          <span>Geospatial Earth Observation Surveillance</span>
        </div>

        {/* Map View & Layer Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          {/* Basemap Switcher */}
          <div style={{ display: 'flex', background: 'rgba(30, 41, 59, 0.8)', padding: '2px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
            <button
              onClick={() => setBasemap('satellite')}
              style={{
                background: basemap === 'satellite' ? 'var(--accent-blue)' : 'transparent',
                color: basemap === 'satellite' ? '#FFF' : 'var(--text-muted)',
                border: 'none',
                padding: '4px 10px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
              title="ESRI High-Resolution True-Color Optical Satellite Imagery"
            >
              🛰️ Satellite (True-Color)
            </button>
            <button
              onClick={() => setBasemap('dark')}
              style={{
                background: basemap === 'dark' ? 'var(--accent-blue)' : 'transparent',
                color: basemap === 'dark' ? '#FFF' : 'var(--text-muted)',
                border: 'none',
                padding: '4px 10px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
              title="ESRI High-Contrast Dark Tactical Basemap"
            >
              🗺️ Tactical Dark
            </button>
          </div>

          {/* SAR Footprint Toggle */}
          <button
            onClick={() => setShowSarSwath(!showSarSwath)}
            style={{
              background: showSarSwath ? 'rgba(56, 189, 248, 0.15)' : 'rgba(30, 41, 59, 0.6)',
              color: showSarSwath ? '#38BDF8' : 'var(--text-muted)',
              border: `1px solid ${showSarSwath ? '#38BDF8' : 'var(--border-default)'}`,
              padding: '4px 10px',
              borderRadius: '6px',
              fontSize: '11px',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
            title="Toggle Sentinel-1 Synthetic Aperture Radar Swath Footprint"
          >
            <Radio size={12} />
            <span>SAR Radar Footprint</span>
          </button>

          {/* Reset Extent */}
          <button
            onClick={resetBounds}
            style={{
              background: 'rgba(30, 41, 59, 0.6)',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border-default)',
              padding: '4px 8px',
              borderRadius: '6px',
              fontSize: '11px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
            title="Reset Extent to All Monitored Locations"
          >
            <RotateCcw size={12} />
            <span>Reset View</span>
          </button>
        </div>
      </div>

      <div style={{ position: 'relative', flex: 1, minHeight: '480px' }}>
        <div ref={mapContainerRef} style={{ width: '100%', height: '100%', minHeight: '480px' }} />

        {/* Legend Overlay */}
        <div
          style={{
            position: 'absolute',
            bottom: '12px',
            left: '12px',
            zIndex: 400,
            background: 'rgba(15, 23, 42, 0.94)',
            padding: '8px 14px',
            borderRadius: '6px',
            border: '1px solid var(--border-default)',
            fontSize: '11px',
            color: 'var(--text-secondary)',
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
            backdropFilter: 'blur(6px)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>Risk Hierarchy:</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
              <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#EF4444' }} /> CRIT
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
              <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#F97316' }} /> HIGH
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
              <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#F59E0B' }} /> MOD
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
              <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#10B981' }} /> LOW
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#94A3B8', fontSize: '10px' }}>
            <Info size={12} color="#38BDF8" />
            <span>Click any location point to inspect or click anywhere on terrain to set target pin</span>
          </div>
        </div>
      </div>
    </div>
  );
};
