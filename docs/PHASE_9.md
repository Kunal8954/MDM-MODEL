# SATGUARD — Phase 9 Documentation
## Historical Intelligence & Trend Analytics

### 1. Executive Summary & Purpose
Phase 9 extends the SATGUARD platform from instantaneous current-state monitoring to longitudinal historical intelligence across government-designated critical locations (dams, reservoirs, glacial lakes, slopes, bridges, and critical infrastructure).

SATGUARD historical analytics answer:
1. What surface and backscatter changes have occurred at this location over time?
2. Is the observed change isolated, intermittent, or persistent?
3. How has SAR change evolved across multiple acquisitions?
4. How has optical visibility and cloud coverage behaved historically?
5. How has authoritative monitoring risk shifted across continuous cycles?
6. Are there recurring alert patterns or historical escalations?
7. What environmental and seismic context existed during observed anomalies?
8. Is the current signal statistically unusual relative to the location's historical baseline?

**Core Scientific Boundary**: Historical trend analysis is strictly an operational monitoring, prioritization, and decision-support tool. It does **NOT** claim exact disaster prediction or structural failure forecasting.

---

### 2. Historical Intelligence Architecture

```
                          Sovereign Critical Location
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
Sentinel-1 SAR Series         Sentinel-2 Optical Series     Evidence Snapshots (GPM/FIRMS/USGS)
(Mean ΔVV, ΔVH, Changed %)     (Usable vs Cloud Obscured)    (Strict Missing Semantics)
        │                              │                              │
        └──────────────────────────────┼──────────────────────────────┘
                                       ▼
                             Temporal Normalization
                    (Acquisition Timestamps vs DB Timestamps)
                                       │
                                       ▼
                       Deterministic Analytics Service
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        ▼                              ▼                              ▼
Persistence Detection        Baseline Construction          Trend Classification
- NO_SIGNAL                  - Location-Specific            - STABLE
- ISOLATED_SIGNAL            - Parametric/Non-parametric    - INCREASING
- INTERMITTENT_SIGNAL        - IQR & Tukey Fences           - DECREASING
- PERSISTENT_SIGNAL          - Z-score Deviations           - VOLATILE
- INSUFFICIENT_DATA                                         - INSUFFICIENT_DATA
        │                              │                              │
        └──────────────────────────────┼──────────────────────────────┘
                                       ▼
                     Historical Analytics Snapshot Record
                                       │
        ┌──────────────────────────────┴──────────────────────────────┐
        ▼                                                             ▼
Government Intelligence REST APIs                        Operator Intelligence Dashboard
(/api/locations/{id}/analytics/*)                        (Interactive Historical Panel & SVG Charts)
```

---

### 3. Data Sources & Schema Relationships

Phase 9 leverages existing persistent data without duplicating raw observations:
- **`critical_locations`**: Base registry defining AOI coordinates, perimeter radius, and cadence.
- **`satellite_observations`**: Multi-sensor catalog tracking `sensor` (`SAR-C` vs `MSI`), `acquisition_time`, and `cloud_cover`.
- **`sentinel1_change_detections`**: Polarimetric SAR change records (`delta_vv_statistics`, `delta_vh_statistics`, `changed_percentage`, `orbit_information`).
- **`evidence_snapshots`**: Multi-sensor fusion captures tracking NASA GPM precipitation, NASA FIRMS active fire detections, and USGS earthquake events.
- **`risk_assessments`**: Immutable deterministic risk records (`score`, `risk_level`, `monitoring_priority`, `evidence_strength`, `confidence_score`).
- **`alerts`**: Government surveillance alerts preserving lifecycle statuses (`ACTIVE`, `ACKNOWLEDGED`, `IN_REVIEW`, `RESOLVED`, `EXPIRED`, `SUPERSEDED`).
- **`historical_analytics_snapshots`**: Persistent analytics summary table for rapid dashboard queries and audit tracking.

---

### 4. Configurable Time Windows
The analytics service resolves explicit start and end timestamps (`HistoricalWindow`):
- `7D` (7 days): Immediate tactical comparison
- `30D` (30 days): Standard operational monitoring window (default)
- `90D` (90 days): Quarterly baseline comparison
- `180D` (180 days): Semi-annual seasonal cycle
- `365D` (1 year): Annual baseline
- **Custom date ranges**: Explicit `start_time` and `end_time` (ISO-8601).
- Every query result explicitly reports `start_time` and `end_time`. Unknown or silent time windows are disallowed.

---

### 5. Deterministic Persistence Methodology
Distinguishes transient noise and isolated artifacts from persistent ground deformation:

| Status | Deterministic Evaluation Rule |
| :--- | :--- |
| `INSUFFICIENT_DATA` | Evaluated observations count < 2 (or configurable `PERSISTENCE_MIN_OBSERVATIONS`). |
| `NO_SIGNAL` | 0 significant change observations across evaluated window. |
| `ISOLATED_SIGNAL` | Exactly 1 significant change observation among multiple observations. |
| `INTERMITTENT_SIGNAL` | ≥2 significant change observations, but non-consecutive or signal ratio < 0.60. |
| `PERSISTENT_SIGNAL` | ≥2 consecutive significant change observations and signal ratio ≥ 0.60. Signals elevated field verification priority. |

---

### 6. Baseline Construction & Statistical Deviation
Historical baselines are location-specific, time-bounded, and reproducible:
- **Descriptive Statistics**: Sample count ($n$), Mean, Median, Standard Deviation ($\sigma$), Min, Max, 25th percentile ($P_{25}$), 75th percentile ($P_{75}$), and Interquartile Range ($IQR = P_{75} - P_{25}$).
- **Minimum Sample Threshold**: Requires $n \ge 3$ for deviation testing; returns `INSUFFICIENT_DATA` otherwise.
- **Deviation Classifications**:
  - `NORMAL`: Value within standard distribution ($|Z| < 1.5$).
  - `HISTORICAL_DEVIATION`: Moderate shift ($1.5 \le |Z| < 2.0$).
  - `UNUSUAL_RELATIVE_TO_BASELINE`: Unusual deviation ($2.0 \le |Z| < 3.0$ or above Tukey upper fence $P_{75} + 1.5 \cdot IQR$).
  - `ABOVE_HISTORICAL_RANGE`: Outlier deviation ($|Z| \ge 3.0$ or above extreme fence $P_{75} + 3.0 \cdot IQR$).

---

### 7. Data Sufficiency Framework
To avoid manufacturing false trends from sparse satellite passes:
- **`SUFFICIENT`**: Total valid observations across sensors $\ge 5$, or $\ge 3$ SAR changes and $\ge 2$ risk assessments.
- **`LIMITED`**: Total valid observations between 2 and 4.
- **`INSUFFICIENT`**: Total valid observations $< 2$.

---

### 8. Strict Missing-Data Semantics
- **Rainfall (NASA GPM IMERG)**: If no granules are detected in the AOI or coverage is unavailable, the system strictly returns `UNAVAILABLE`. It **never** defaults to `0.0 mm` unless an actual valid sensor granule explicitly reports `0.0 mm`.
- **Thermal Fire (NASA FIRMS)**: When the instrument is operational with 0 detections in the perimeter, returns `VALID_ZERO_OBSERVATION`.
- **Seismic (USGS)**: When 0 events $\ge M2.5$ occur within the radius, returns `NO_EVENTS_DETECTED`.

---

### 9. REST API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/locations/{location_id}/analytics/history?days=30` | Full historical intelligence report (SAR, Optical, Risk, Baseline, Persistence). |
| `GET` | `/api/locations/{location_id}/analytics/trends?days=30` | Descriptive trends across sensors and risk assessments. |
| `GET` | `/api/locations/{location_id}/analytics/baseline?days=90` | Baseline distribution statistics and current deviation comparison. |
| `GET` | `/api/locations/{location_id}/analytics/persistence?days=30` | Deterministic persistence classification. |
| `GET` | `/api/locations/{location_id}/analytics/risk-history?days=90` | Chronological immutable risk trajectory. |
| `GET` | `/api/locations/{location_id}/analytics/alerts-history?days=90` | Alert lifecycle distribution and recurrence detection. |
| `GET` | `/api/locations/{location_id}/analytics/latest` | Latest cached snapshot for fast operator loading. |
| `GET` | `/api/analytics/compare?location_ids=loc1,loc2&days=30` | Multi-location deterministic comparative analytics. |
| `GET` | `/api/locations/{location_id}/analytics/report?days=30` | Downloadable government-grade JSON report with scientific disclaimers. |

---

### 10. Dashboard Integration
Integrated directly into `LocationDetailView.tsx` via `HistoricalIntelligencePanel.tsx`:
- Interactive time-window controls: `7D`, `30D`, `90D`, `180D`, `1Y`.
- Top operational badges: Persistence, Baseline Deviation, Risk Classification, Data Sufficiency.
- Interactive SVG charts:
  - SAR Surface-Change Trend (ΔVV / ΔVH in dB and changed %).
  - Authoritative Risk Score Trajectory (0–100 scale over time).
  - Sentinel-2 Optical Cloud-Filtering & scene usability summary.
  - Environmental context cards (GPM rainfall, FIRMS thermal, USGS seismic).
- "Export Report" button downloading full structured audit report.
- Prominent Scientific Integrity notice.

---

### 11. Verification & Test Suite Summary
- **Backend Tests**: 23/23 tests in `tests/test_phase9.py` passing.
- **Full Backend Regression**: 153/153 tests passing across Phases 1–9.
- **Frontend Tests**: 18/18 tests in `frontend/src/__tests__/` passing (including `historical.test.tsx`).
- **Frontend Production Build**: `npm run build` succeeds (1,913 modules bundled in 866ms).
- **Real Tehri Dam Verification**: `scripts/verify_phase9.py` passed with actual database history for `loc-001-tehri-dam`.
