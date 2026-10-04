# SATGUARD — Operations Runbook (Standard Operating Procedure)

**Classification:** OFFICIAL — GOVERNMENT SURVEILLANCE OPERATIONS  
**Version:** 1.0 (Phase 10 Production Hardened)  
**System Target:** Critical Infrastructure Early-Warning & Earth Observation Surveillance Platform  

---

## 1. System Architecture & Component Overview

SATGUARD is a multi-tier geospatial surveillance and risk assessment system:
- **Backend API & Processing Engine:** FastAPI / Python 3.12 (Port `8000`)
- **Authoritative Database:** PostgreSQL 16 + PostGIS 3.4 (Port `5432`)
- **Continuous Monitoring Scheduler:** Background Async APScheduler (Runs automated reassessments per location frequency)
- **Frontend Dashboard:** React 19 + TypeScript + Vite + Tailwind/Vanilla CSS (Served via Nginx on Port `5173`/`80`)
- **External Satellite & Sensor Providers:**
  - Copernicus Data Space Ecosystem (Sentinel-1 SAR, Sentinel-2 Optical)
  - NASA Earthdata (GPM IMERG 72-hour precipitation)
  - NASA FIRMS (Thermal anomaly / active fire detection)
  - USGS Earthquake Hazards Program (Seismic event feed)
  - OpenStreetMap & Copernicus DEM GLO-30 (Topographic slope & valley infrastructure)
  - Groq Cloud LPU (LLaMA 3.3 70B Versatile for evidence analysis and SITREP generation)

---

## 2. Standard Service Lifecycle

### 2.1 Startup Procedure

#### Containerized (Docker Compose)
```bash
# 1. Ensure production environment variables are configured
test -f .env || cp .env.example .env

# 2. Start services in detached mode
docker compose up -d

# 3. Verify health probes
curl -s http://localhost:8000/live | jq .
curl -s http://localhost:8000/ready | jq .
```

#### Bare-Metal / Virtual Machine
```bash
# 1. Activate virtual environment
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# 2. Validate configuration and verify migrations
python -m satguard.db.session

# 3. Start backend service
uvicorn satguard.api.main:app --host 0.0.0.0 --port 8000 --workers 4

# 4. Start frontend dashboard
cd frontend && npm run preview -- --port 5173
```

### 2.2 Graceful Shutdown Procedure

```bash
# Stop receiving new HTTP traffic and allow active surveillance pipelines to finalize
kill -SIGTERM $(pgrep -f "uvicorn satguard.api.main:app")

# For dockerized environments:
docker compose down --timeout 30
```

---

## 3. Health Monitoring & Observability

### 3.1 Health Endpoints

| Endpoint | Method | Expected HTTP | Purpose |
|---|---|---|---|
| `/live` or `/api/health/live` | GET | `200 OK` | Liveness probe: verifies Python process is alive |
| `/ready` or `/api/health/ready` | GET | `200 OK` (or `503 Service Unavailable`) | Readiness probe: validates DB connection, scheduler state, and credential presence |
| `/metrics` or `/api/metrics` | GET | `200 OK` | Real-time latency (P50, P95, P99), error rates, monitoring run counters |
| `/api/data-status` | GET | `200 OK` | Provider connectivity status |

### 3.2 Health Check Inspection Command
```bash
# Comprehensive readiness check
curl -X GET "http://localhost:8000/ready" -H "Accept: application/json"
```

---

## 4. Incident Response & Failure Recovery

### 4.1 External Provider Outage (CDSE / NASA / Groq)
- **Symptom:** Observation download times out, or Groq analyst generation fails with `PROVIDER_UNAVAILABLE`.
- **System Behavior:**
  - SATGUARD's deterministic risk engine **never blocks** on Groq LLM failure. If Groq is down, Phase 4 deterministic risk scoring (0-100) and alert generation proceed unhindered.
  - If GPM precipitation data is temporarily unavailable, rainfall evidence records `status: UNAVAILABLE` with `rainfall_mm: null` (never fabricated as 0).
- **Remediation:**
  1. Check provider status via `curl http://localhost:8000/ready`.
  2. Verify network connectivity to `eodata.dataspace.copernicus.eu` or `api.groq.com`.
  3. No database rollback is needed; runs record `PARTIAL_SUCCESS` or `DEGRADED`.

### 4.2 Database Outage / Reconnection Failure
- **Symptom:** Readiness probe returns `503 Service Unavailable`, logs report connection timeouts.
- **Remediation:**
  1. Inspect PostgreSQL service: `docker compose logs -n 50 db`.
  2. Check disk space: `df -h /var/lib/postgresql/data`.
  3. The backend pool automatically retries using `pool_pre_ping=True` and connection recycling.
  4. Once PostgreSQL recovers, backend resumes serving without requiring process restarts.

### 4.3 Scheduler Failure / Hung Monitoring Run
- **Symptom:** Locations not triggering automated surveillance at configured intervals.
- **Remediation:**
  1. Check scheduler state via `/ready`.
  2. Query active monitoring runs: `curl -H "Authorization: Bearer <token>" "http://localhost:8000/api/monitoring/runs?status=RUNNING"`.
  3. Trigger manual reassessment for critical site:
     `curl -X POST -H "Authorization: Bearer <token>" "http://localhost:8000/api/locations/loc-001-tehri-dam/monitoring/run"`

### 4.4 Authentication Failure / Locked Out
- **Symptom:** Operator unable to log into dashboard (`401 Unauthorized`).
- **Remediation:**
  1. Confirm default seed account credentials (`admin`, `supervisor`, `operator`, `analyst`, `viewer`).
  2. Query audit logs for failed logins:
     `curl -H "Authorization: Bearer <admin_token>" "http://localhost:8000/api/audit/logs?action=LOGIN_FAILURE"`.

---

## 5. Backup & Disaster Recovery Procedures

### 5.1 Database Backup
Perform hot physical/logical backups daily:
```bash
# Export full database schema and surveillance evidence
pg_dump -U satguard_admin -h localhost -d satguard_db -Fc -f "/backups/satguard_$(date +%Y%m%d_%H%M%S).dump"
```

### 5.2 Database Restoration
```bash
# Drop current schema in disaster recovery sandbox
pg_restore -U satguard_admin -h localhost -d satguard_db --clean --if-exists "/backups/satguard_target_backup.dump"
```

### 5.3 Storage Artifact Backup
- Synchronize `/app/storage/data` (GeoTIFFs and change masks) to remote tape or offsite S3-compatible cold storage daily using `rsync` or `aws s3 sync`.

---

## 6. Audit Log Inspection & Forensics
All operator actions (acknowledgments, reviews, resolutions, manual triggers, logins) are recorded immutably in `audit_logs`:
```bash
# Retrieve latest 20 security and operator events
curl -s -H "Authorization: Bearer <admin_token>" \
  "http://localhost:8000/api/audit/logs?limit=20" | jq .
```
