# SATGUARD — Production Deployment Guide

**Target Environment:** Linux Server (Ubuntu 22.04 LTS / RHEL 9) or Docker / Kubernetes  
**Audience:** DevSecOps Engineers, Platform Administrators  
**Phase:** 10 Production Hardening  

---

## 1. System Prerequisites

### Hardware Requirements
- **CPU:** 4+ Physical Cores (x86_64 or ARM64)
- **RAM:** Minimum 16 GB (Recommended 32 GB for Sentinel-1 GRD SAR raster calibration)
- **Disk:** 250 GB NVMe SSD for local raster cache and spatial database

### Software Prerequisites
- Docker Engine 24+ and Docker Compose v2+ **OR**:
  - Python 3.12+
  - Node.js 22 LTS
  - PostgreSQL 16 with PostGIS 3.4
  - Nginx 1.24+

---

## 2. Environment Configuration

1. Clone repository to deployment directory:
   ```bash
   git clone <repository_url> /opt/satguard
   cd /opt/satguard
   ```

2. Generate production secrets:
   ```bash
   cp .env.example .env
   # Generate 64-character random key for JWT:
   openssl rand -hex 32
   ```

3. Configure variables in `/opt/satguard/.env`:
   - `SATGUARD_ENV=production`
   - `JWT_SECRET_KEY=<your_generated_hex_key>`
   - `DATABASE_URL=postgresql://satguard_admin:<db_password>@localhost:5432/satguard_db`
   - `CORS_ALLOWED_ORIGINS=https://satguard.gov.in`
   - `CDSE_CLIENT_ID` and `CDSE_CLIENT_SECRET`
   - `GROQ_API_KEY`
   - `FIRMS_MAP_KEY`
   - `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`

---

## 3. Database Initialization & Migrations

For native PostgreSQL deployments:
```bash
# Connect as postgres superuser and create database with PostGIS
sudo -u postgres psql << EOF
CREATE USER satguard_admin WITH ENCRYPTED PASSWORD 'your_strong_password';
CREATE DATABASE satguard_db OWNER satguard_admin;
\c satguard_db
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOF

# Execute versioned migrations in sequential order:
for f in migrations/*.sql; do
    echo "Applying $f..."
    psql -U satguard_admin -d satguard_db -h localhost -f "$f"
done
```

---

## 4. Reverse Proxy & TLS Configuration (Nginx)

Place the following configuration in `/etc/nginx/sites-available/satguard.conf`:

```nginx
server {
    listen 80;
    server_name satguard.gov.in;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name satguard.gov.in;

    ssl_certificate /etc/letsencrypt/live/satguard.gov.in/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/satguard.gov.in/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Frontend Dashboard
    location / {
        root /opt/satguard/frontend/dist;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # Backend API Proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90s;
    }

    # Health & Metrics Probes
    location ~ ^/(health|live|ready|metrics) {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }
}
```

---

## 5. Post-Deployment Verification

Execute the automated verification test on the live deployment:
```bash
# 1. Verify process liveness
curl -I https://satguard.gov.in/live
# Expected: HTTP/2 200

# 2. Verify system readiness
curl -s https://satguard.gov.in/ready | jq .
# Expected: status == "READY"

# 3. Verify operator authentication
curl -X POST https://satguard.gov.in/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "operator", "password": "<password>"}'
# Expected: Returns JWT access_token
```

---

## 6. Rollback Plan

If post-deployment verification fails:
1. Revert backend systemd service / docker container to previous release tag.
2. Restore database schema using backup snapshot taken before deployment:
   ```bash
   pg_restore -U satguard_admin -d satguard_db --clean /backups/pre_deployment_snapshot.dump
   ```
3. Restart backend service and verify `/ready`.
