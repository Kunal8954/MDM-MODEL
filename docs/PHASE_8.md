# SATGUARD Phase 8 — Government Intelligence Dashboard Documentation

## Overview

The **Government Intelligence Dashboard** serves as the operator-facing mission control and observation interface for the SATGUARD platform. Built as a sovereign, high-trust, desktop-optimized command-and-monitoring workstation, the dashboard connects directly to authoritative backend APIs to visualize:
- Sovereign Government Critical Locations & AOI perimeters
- Geospatial multi-sensor satellite surveillance (Copernicus Sentinel-1 SAR & Sentinel-2 Optical)
- Deterministic Phase 4 Risk Assessments & Prioritization
- Phase 5 Groq Evidence Analyst Narrative Syntheses
- Phase 6 Government Early-Warning Alerts & Lifecycle Transitions
- Phase 7 Continuous Monitoring Pipeline Audits & Sequential Stage Execution Traces
- Chronological Multi-Sensor Surveillance Timelines

---

## Architecture

```
                    SATGUARD FASTAPI BACKEND
                               │
               ┌───────────────┼────────────────┐
               │               │                │
          Locations        Monitoring        Alerts
               │               │                │
          Evidence          Risk            Analyst
               │               │                │
               └───────────────┼────────────────┘
                               │
                       RESTful JSON API
                     (CORS & Reverse Proxy)
                               │
                               ▼
               GOVERNMENT OPERATOR DASHBOARD
                 (React 19 + TypeScript + Vite)
                               │
               ┌───────────────┼────────────────┐
               │               │                │
          Leaflet Map     Risk Overview      Alerts
               │               │                │
          Location         Satellite       Continuous
          Detail           Evidence        Monitoring
               │               │                │
               └───────────────┼────────────────┘
                               ▼
                        Human Operator
              (Observation & Decision-Support)
```

---

## Frontend Routes & View Modes

The single-page mission control application provides five operational views and a dedicated detail inspection workspace:

| View / Route | Purpose | Key Capabilities |
| :--- | :--- | :--- |
| **Mission Control (`/`)** | High-level situational awareness | KPI metric summary, geospatial map, active alerts feed, recent monitoring audits |
| **Critical Locations (`/locations`)** | Critical sites directory | Multi-criteria search (name, ID, type), filtering by Risk Level, Status, and Location Type |
| **Location Intelligence (`/locations/:id`)** | Dedicated deep-dive intelligence | Authoritative Phase 4 Risk Score (0–100), Multi-Sensor Evidence (S1, S2, Fusion, DEM, Rainfall, Seismic, Fire), Groq Analyst report, Alert management, Chronological Timeline, On-demand reassessment trigger |
| **Alert Center (`/alerts`)** | Government surveillance alert management | Filter by status (`ACTIVE`, `ACKNOWLEDGED`, `IN_REVIEW`, `RESOLVED`) and priority (`URGENT`, `HIGH`, `ELEVATED`, `ROUTINE`, `INFO`), operator action modal |
| **Monitoring Center (`/monitoring`)** | Continuous reassessment operations | Run execution trigger, historical audit table, sequential stage transition inspection (`DISCOVERY` → `COMPLETED`) |
| **Evidence Explorer (`/evidence`)** | Cross-location stream telemetry | Live provider status (Copernicus S1, S2, DEM GLO-30, USGS, NASA FIRMS, Groq LPU), missing-data governance rules |

---

## Component Directory

```
frontend/src/
├── api/
│   └── client.ts                 # Centralized typed API client organized by domain
├── types/
│   └── api.ts                    # Authoritative TypeScript data models
├── components/
│   ├── Header.tsx                # Classification, operational status pill, telemetry sync
│   ├── Navigation.tsx            # Mission Control navigation with live badge counts
│   ├── GeospatialMap.tsx         # Leaflet geospatial surveillance map with risk color codes
│   ├── RiskScoreGauge.tsx        # Phase 4 authoritative risk visualization (0-100) & disclaimer
│   ├── SatelliteEvidencePanel.tsx# Multi-sensor tabs (S1, S2, Fusion, DEM, Rainfall, Fire, Quake)
│   ├── AnalystReportView.tsx     # Groq Evidence Analyst synthesis (non-authoritative boundary)
│   ├── AlertLifecycleModal.tsx   # Operator audit modal for Acknowledge / Review / Resolve
│   └── ChronologicalTimeline.tsx # Chronological multi-sensor surveillance events timeline
├── views/
│   ├── OverviewView.tsx          # Executive dashboard with map and live alert/run widgets
│   ├── LocationsView.tsx         # Critical locations directory with search and multi-filtering
│   ├── LocationDetailView.tsx    # Comprehensive location intelligence workspace
│   ├── AlertsView.tsx            # Alert center with filtering, search, and lifecycle controls
│   ├── MonitoringView.tsx        # Pipeline run management & stage transition audit trace
│   └── EvidenceExplorerView.tsx  # Telemetry stream status & missing-data semantics
├── __tests__/
│   └── dashboard.test.tsx        # 14 unit & integration tests covering all Phase 8 requirements
├── index.css                     # Command center design system (vanilla CSS, dark navy theme)
├── App.tsx                       # Root application container & global state management
└── main.tsx                      # React root entry point
```

---

## Backend Endpoints Consumed

| Domain | Method & Endpoint | Description |
| :--- | :--- | :--- |
| **System** | `GET /api/overview` | Live operational statistics (locations count, high/critical risk count, alerts, freshness) |
| **System** | `GET /api/data-status` | Sovereign provider connectivity and `REAL_DATA_ONLY` operational mode |
| **Locations**| `GET /api/locations` | All sovereign critical locations |
| **Locations**| `GET /api/locations/{id}` | Single critical location metadata |
| **Risk** | `GET /api/locations/{id}/risk/latest` | Authoritative Phase 4 deterministic risk assessment |
| **SAR** | `GET /api/locations/{id}/sentinel-1/changes` | Sentinel-1 differential backscatter changes (ΔVV, ΔVH dB, changed %) |
| **SAR** | `GET /api/locations/{id}/sentinel-1/observations`| Sentinel-1 raw observations catalog |
| **Optical** | `GET /api/locations/{id}/observations` | Sentinel-2 optical observations catalog & cloud cover metrics |
| **Fusion** | `GET /api/locations/{id}/evidence/snapshots` | Phase 3 multi-sensor evidence snapshots |
| **Analyst** | `GET /api/locations/{id}/analysis/latest` | Phase 5 Groq Evidence Analyst synthesis report |
| **Alerts** | `GET /api/alerts` | Unified government alerts with search & filter parameters |
| **Alerts** | `GET /api/locations/{id}/alerts` | Government alerts specific to a critical location |
| **Alerts** | `POST /api/alerts/{id}/acknowledge` | Transition alert state: `ACTIVE` → `ACKNOWLEDGED` |
| **Alerts** | `POST /api/alerts/{id}/review` | Transition alert state: `ACKNOWLEDGED` → `IN_REVIEW` |
| **Alerts** | `POST /api/alerts/{id}/resolve` | Transition alert state to `RESOLVED` |
| **Monitoring**| `GET /api/monitoring/runs` | Paginated history of continuous monitoring runs |
| **Monitoring**| `GET /api/monitoring/runs/{id}` | Full stage transition trace for a specific monitoring run |
| **Monitoring**| `POST /api/locations/{id}/monitoring/run` | Trigger on-demand continuous monitoring pipeline execution |
| **Timeline** | `GET /api/locations/{id}/timeline` | Unified chronological surveillance timeline |

---

## Observational Governance & Scientific Constraints

1. **Risk Immutability**:
   The frontend **never** calculates or modifies the risk score. It displays the authoritative values calculated by the Phase 4 Deterministic Risk Assessment Engine (`score`, `risk_level`, `monitoring_priority`, `evidence_strength`).
2. **Operational Meaning**:
   The risk score (0–100) is explicitly documented in the UI as an **operational monitoring prioritization score**, NOT disaster probability.
3. **Conservative Terminology**:
   Sentinel-1 SAR backscatter variations are reported strictly as **SIGNIFICANT SAR CHANGE**. The terms "landslide", "collapse", or "damage" are forbidden unless backed by validated ground truth.
4. **Missing-Data Semantics**:
   When precipitation data is unavailable, the UI displays **RAINFALL DATA UNAVAILABLE**; it is never assumed to be 0 mm.
5. **Analyst Synthesis Boundary**:
   Phase 5 Groq Evidence Analyst outputs are labeled as **LLM-Assisted Synthesis** and cannot override or modify authoritative Phase 4 metrics.

---

## Development & Production Commands

### Frontend Development Server
```bash
cd frontend
npm install
npm run dev
# Vite runs at http://localhost:5173 with proxy to backend at http://localhost:8000
```

### Production Build
```bash
cd frontend
npm run build
# Generates production bundle in frontend/dist/
```

### Frontend Tests
```bash
cd frontend
npm run test
# Runs 14 Vitest unit and integration tests
```

### Backend Verification & Full Regression
```bash
# Verify live API and Tehri Dam ground truth
$env:PYTHONPATH="."; python scripts/verify_phase8.py

# Run full backend regression suite (all 130 tests across Phases 1–8)
python -m pytest tests/ -q
```
