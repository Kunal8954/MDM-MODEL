# SATGUARD — Platform Security Architecture & Guidelines

**Classification:** CONFIDENTIAL / GOVERNMENT USE ONLY  
**Standard:** ISO/IEC 27001 & CERT-In Compliance Architecture  
**Phase:** 10 Production Hardened  

---

## 1. Authentication Architecture

SATGUARD utilizes industry-standard token-based authentication designed for multi-operator government intelligence operations:

```
[ Operator ] ---> POST /api/auth/login (username, password)
                        |
                        v
               Bcrypt Verification (salt rounds = 12)
                        |
                        v
               JWT Bearer Token Issued (HS256 signed)
                        |
[ Operator ] ---> Authenticated API Requests (Authorization: Bearer <token>)
                        |
                        v
               Backend RBAC Privilege Evaluation
```

### 1.1 Password Security
- Passwords are encrypted using **bcrypt** with work factor `12`.
- Plaintext passwords are never logged, echoed, or stored in transient cache.

### 1.2 Access Tokens
- Signed with HMAC-SHA256 (`HS256`) using a cryptographically random secret key (`JWT_SECRET_KEY` >= 64 characters).
- Token payload contains operator subject (`sub`), role (`role`), issue timestamp (`iat`), and expiration timestamp (`exp`).
- Default expiration is 480 minutes (8 hours) corresponding to an operational shift.

---

## 2. Role-Based Access Control (RBAC)

Authorization is strictly enforced **server-side** at the FastAPI routing layer via dependency injection (`require_role`).

### 2.1 Role Hierarchy Matrix

| Role | Hierarchy Level | Capabilities | Allowed Actions |
|---|---|---|---|
| **VIEWER** | 10 | Read-only inspection | View dashboard, maps, timelines, and alerts. Cannot execute any state modifications. |
| **ANALYST** | 20 | Scientific & Geospatial Intelligence | All Viewer rights + generate LLM SITREP reports, inspect raw evidence, compare historical trends. |
| **OPERATOR** | 30 | Active Tactical Surveillance | All Analyst rights + trigger manual monitoring runs, acknowledge alerts, mark alerts in review. |
| **SUPERVISOR** | 40 | Incident Command & Escalation | All Operator rights + resolve active alerts, update location surveillance frequencies, override operational states. |
| **ADMIN** | 50 | System Administration | All Supervisor rights + user provisioning, security auditing, configuration updates, emergency controls. |

---

## 3. Immutable Security Audit Logging

Every critical administrative and operational action is recorded immutably to the `audit_logs` table:
- **Captured Events:**
  - `LOGIN_SUCCESS`, `LOGIN_FAILURE`, `LOGOUT`
  - `ALERT_ACKNOWLEDGE`, `ALERT_REVIEW`, `ALERT_RESOLVE`
  - `MONITORING_RUN_TRIGGERED`
  - `USER_CREATED`, `CONFIG_CHANGE`
  - `SECURITY_BREACH_ATTEMPT` (e.g. rate limit exhaustion or unauthorized resource access)
- **Record Schema:**
  - `event_id`: Unique forensic correlation identifier (`aud-<uuid>`)
  - `timestamp`: UTC ISO timestamp
  - `actor`: Operator username
  - `role`: Role at time of action
  - `action`: Specific state change verb
  - `resource` & `resource_id`: Targeted location or alert ID
  - `result`: `SUCCESS` or `FAILURE`
  - `event_metadata`: Sanitized JSON payload (passwords, tokens, and private keys automatically redacted with `[REDACTED]`).

---

## 4. API & Network Hardening

### 4.1 CORS (Cross-Origin Resource Sharing)
- Permissive development wildcards (`allow_origins=["*"]`) are strictly prohibited in production.
- Production CORS origins are explicitly parsed from `CORS_ALLOWED_ORIGINS` (e.g. `https://satguard.gov.in,https://dashboard.satguard.gov.in`).
- Credentials are supported only across explicitly whitelisted domains.

### 4.2 HTTP Security Headers
Every HTTP response carries OWASP-recommended security headers:
- `X-Content-Type-Options: nosniff` (Prevents MIME-sniffing exploits)
- `X-Frame-Options: SAMEORIGIN` (Mitigates clickjacking attacks)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy`: Strictly limits allowed origins for scripts, styles, images, and fonts.
- `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` (Enforces HTTPS across all connections)

### 4.3 Rate Limiting & DoS Protection
- In-memory sliding window rate limiter protects against brute force attacks and denial-of-service.
- Default limit: `120 requests/minute` per IP address.
- Exceeding the rate limit yields `HTTP 429 Too Many Requests`.

### 4.4 Request Correlation
- Every incoming HTTP request is assigned or tagged with an `X-Request-ID` header.
- This ID is propagated across pipeline logs and monitoring runs to enable distributed forensic tracking.

---

## 5. Secret Management & Zero-Leakage Policy

1. **No Hardcoded Secrets:**
   - No API keys, passwords, or tokens are committed to source control.
   - Codebase is protected by `.gitignore` preventing `.env` and `*.db` commits.
2. **Template Sanitation:**
   - `.env.example` contains variable names and dummy place-holders only.
3. **Safe API Error Responses:**
   - Production error handlers catch internal exceptions and return generic error summaries without leaking stack traces, database schema details, or filesystem paths.
