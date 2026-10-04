# SATGUARD API Requirements, Authentication & Integration Protocols

## Document Overview
This document specifies the technical integration requirements, OAuth2 flows, query parameters, rate-limiting policies, error handling mechanisms, and the temporal observation retrieval algorithm for all external services connected to **SATGUARD**.

---

## 1. Authentication Architecture & Credential Management

All external API interactions must strictly adhere to the **Server-Side Isolation Principle**:
*   Credentials, tokens, and secrets must reside exclusively in backend environment configurations (`.env`) or secure secrets managers (e.g., HashiCorp Vault, AWS Secrets Manager).
*   **Zero Client Exposure:** No API keys or tokens are ever exposed to the web frontend, mobile interfaces, or browser runtime environments.
*   **Token Lifecycle Management:** OAuth2 access tokens must be managed in-memory with proactive expiration tracking (refreshing at $t_{\text{expire}} - 60\text{ seconds}$).

```
+---------------------------------------------------------------------------------------+
| SATGUARD Secure Backend Core                                                          |
|                                                                                       |
|   +---------------------+        +--------------------+        +--------------------+ |
|   | CDSE OAuth2 Manager |        | NASA Earthdata URS |        | Groq / FIRMS Auth  | |
|   | Token Cache & Auto- |        | Session Management |        | Key Vault Manager  | |
|   | Refresh Controller  |        | & Header Generator |        | (Static Keys)      | |
|   +----------+----------+        +---------+----------+        +---------+----------+ |
+--------------|-----------------------------|-----------------------------|------------+
               |                             |                             |             
       Bearer Token (600s)           Session Cookies / NetRC        Header / Param Auth  
               |                             |                             |             
               v                             v                             v             
+---------------------------+  +---------------------------+  +-------------------------+
| Copernicus Data Space     |  | NASA GES DISC / CMR       |  | NASA FIRMS / Groq Cloud |
| STAC, OData, S3, SH APIs  |  | GPM IMERG Rainfall API    |  | Fire & LPU Inference    |
+---------------------------+  +---------------------------+  +-------------------------+
```

---

## 2. Service-by-Service API Specifications

### 2.1 Copernicus Data Space Ecosystem (CDSE)

#### A. OAuth2 Token Acquisition
*   **Method:** `POST`
*   **Endpoint:** `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
*   **Headers:**
    ```http
    Content-Type: application/x-www-form-urlencoded
    ```
*   **Body Parameters:**
    ```text
    client_id=<CDSE_CLIENT_ID>
    client_secret=<CDSE_CLIENT_SECRET>
    grant_type=client_credentials
    ```
*   **Response Structure (200 OK):**
    ```json
    {
      "access_token": "eyJhbGciOiJSUzI1NiIsIn...",
      "expires_in": 600,
      "refresh_expires_in": 1800,
      "token_type": "Bearer",
      "not-before-policy": 0,
      "scope": "email profile"
    }
    ```

#### B. STAC Catalog Search (Satellite Discovery)
*   **Method:** `POST`
*   **Endpoint:** `https://stac.dataspace.copernicus.eu/v1/search`
*   **Headers:**
    ```http
    Authorization: Bearer <access_token>
    Content-Type: application/json
    Accept: application/geo+json
    ```
*   **Request Body (Sentinel-2 L2A Example):**
    ```json
    {
      "collections": ["sentinel-2-l2a"],
      "intersects": {
        "type": "Polygon",
        "coordinates": [
          [
            [78.50, 30.35],
            [78.55, 30.35],
            [78.55, 30.40],
            [78.50, 30.40],
            [78.50, 30.35]
          ]
        ]
      },
      "datetime": "2026-09-01T00:00:00Z/2026-10-04T00:00:00Z",
      "query": {
        "eo:cloud_cover": {
          "lt": 25.0
        }
      },
      "limit": 50,
      "sortby": [
        {
          "field": "properties.datetime",
          "direction": "asc"
        }
      ]
    }
    ```
*   **Response Validation:**
    *   Extract STAC Feature items: `id`, `properties.datetime`, `properties.eo:cloud_cover`, `assets`, `properties.platform`.
    *   Filter out invalid geometric intersections or degraded quality flags.

#### C. OData v4.0 Query (Alternative Catalog & Direct Product Stream)
*   **Method:** `GET`
*   **Endpoint:** `https://catalogue.dataspace.copernicus.eu/odata/v1/Products`
*   **Query String:**
    ```text
    $filter=Collection/Name eq 'SENTINEL-1' and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'GRD') and ContentDate/Start ge 2026-09-01T00:00:00.000Z and OData.CSC.Intersects(area=geography'SRID=4326;POLYGON((78.50 30.35, 78.55 30.35, 78.55 30.40, 78.50 30.40, 78.50 30.35))')&$orderby=ContentDate/Start asc&$top=20
    ```
*   **Download Endpoint:**
    ```http
    GET https://catalogue.dataspace.copernicus.eu/odata/v1/Products({Product_ID})/$value
    Authorization: Bearer <access_token>
    ```

#### D. S3 Direct Stream Access (High Performance)
*   **Host Endpoint:** `https://eodata.dataspace.copernicus.eu/`
*   **Client Configuration:** Standard S3 client (AWS SDK / Boto3 / GDAL VSI)
*   **Parameters:**
    *   `endpoint_url`: `https://eodata.dataspace.copernicus.eu`
    *   `aws_access_key_id`: `<CDSE_S3_ACCESS_KEY>`
    *   `aws_secret_access_key`: `<CDSE_S3_SECRET_KEY>`
    *   `region_name`: `default`
    *   `addressing_style`: `path`

---

### 2.2 NASA GPM / IMERG Precipitation API

#### A. NASA CMR Granule Search
*   **Method:** `GET`
*   **Endpoint:** `https://cmr.earthdata.nasa.gov/search/granules.json`
*   **Query Parameters:**
    *   `short_name`: `GPM_3IMERGHH` (Half-Hourly) or `GPM_3IMERGDF` (Daily)
    *   `bounding_box`: `min_lon,min_lat,max_lon,max_lat`
    *   `temporal`: `2026-09-20T00:00:00Z,2026-10-04T00:00:00Z`
*   **Output:** List of downloadable HDF5/NetCDF granule URLs hosted on GES DISC.

#### B. GES DISC OPeNDAP Spatial Subset Stream
*   **Method:** `GET`
*   **Endpoint:** `https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGHH.07/{YYYY}/{DOY}/3B-HHR.MS.MRG.3IMERG.{TIMESTAMP}.V07B.HDF5.nc4`
*   **Query Slicing:** `?precipitationCal[time_idx][lat_min:lat_max][lon_min:lon_max]`
*   **Headers:**
    ```http
    Authorization: Bearer <EARTHDATA_TOKEN>
    ```

---

### 2.3 NASA FIRMS Active Fire API

*   **Method:** `GET`
*   **Endpoint:** `https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SENSOR}/{BBOX}/{DAYS}`
*   **Parameters:**
    *   `MAP_KEY`: Hex string from `.env`
    *   `SENSOR`: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `MODIS_NRT`
    *   `BBOX`: `west,south,east,north` (e.g., `78.4,30.2,78.6,30.5`)
    *   `DAYS`: `1` to `10`
*   **Sample Response (CSV Stream):**
    ```csv
    latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight
    30.3812,78.5234,342.1,0.39,0.36,2026-10-03,0742,N,VIIRS,nominal,2.0NRT,291.4,14.8,D
    ```

---

### 2.4 USGS Earthquake Hazards FDSN Web Service

*   **Method:** `GET`
*   **Endpoint:** `https://earthquake.usgs.gov/fdsnws/event/1/query`
*   **Query Parameters:**
    ```text
    format=geojson
    latitude=30.38
    longitude=78.48
    maxradiuskm=100
    minmagnitude=3.5
    starttime=2026-09-04T00:00:00
    endtime=2026-10-04T23:59:59
    orderby=time
    ```
*   **Sample Response Payload:**
    ```json
    {
      "type": "FeatureCollection",
      "metadata": {
        "generated": 1791114629000,
        "title": "USGS Earthquakes",
        "status": 200,
        "count": 1
      },
      "features": [
        {
          "type": "Feature",
          "properties": {
            "mag": 4.8,
            "place": "18 km NNE of Tehri, India",
            "time": 1791054000000,
            "updated": 1791057600000,
            "mmi": 5.2,
            "alert": "green",
            "status": "reviewed",
            "type": "earthquake"
          },
          "geometry": {
            "type": "Point",
            "coordinates": [78.51, 30.52, 12.4]
          },
          "id": "us7000xxxx"
        }
      ]
    }
    ```

---

### 2.5 OpenStreetMap (OSM) Overpass API

*   **Method:** `POST`
*   **Endpoint:** `https://overpass-api.de/api/interpreter`
*   **Headers:**
    ```http
    Content-Type: application/x-www-form-urlencoded
    User-Agent: SATGUARD-GeoIntelligence/1.0 (satguard-monitoring@domain.gov)
    ```
*   **Body (Overpass QL):**
    ```text
    data=[out:json][timeout:60];
    (
      node["waterway"="dam"](30.30,78.40,30.50,78.60);
      way["waterway"="dam"](30.30,78.40,30.50,78.60);
      relation["waterway"="dam"](30.30,78.40,30.50,78.60);
      way["water"="reservoir"](30.30,78.40,30.50,78.60);
      way["bridge"="yes"](30.30,78.40,30.50,78.60);
    );
    out body;
    >;
    out skel qt;
    ```

---

### 2.6 Groq Inference API (Evidence Synthesis)

*   **Method:** `POST`
*   **Endpoint:** `https://api.groq.com/openai/v1/chat/completions`
*   **Headers:**
    ```http
    Authorization: Bearer <GROQ_API_KEY>
    Content-Type: application/json
    ```
*   **Payload Specification:**
    ```json
    {
      "model": "llama-3.3-70b-versatile",
      "temperature": 0.1,
      "max_tokens": 1500,
      "response_format": { "type": "json_object" },
      "messages": [
        {
          "role": "system",
          "content": "You are SATGUARD-Analyst, a rigorous evidence synthesizer for government critical location surveillance. You NEVER fabricate numbers or invent hazards. You receive computed physical sensor changes and output a structured intelligence briefing according to schema."
        },
        {
          "role": "user",
          "content": "Location: Tehri Dam. Coordinates: (30.378, 78.480). Baseline: T1 (2026-09-15), Current: T2 (2026-10-01). Metrics: Delta-NDWI=+0.18 (lake surface expansion +12.4%), SAR VV backscatter delta=-3.2dB (surface water saturation increase), 72h Rainfall=142mm (GPM IMERG), Seismic events=None (USGS, M>3.0 within 50km), Thermal anomalies=0 (FIRMS). Generate structured intelligence report."
        }
      ]
    }
    ```

---

## 3. Temporal Monitoring Pipeline & Zero-Wasted-Bandwidth Engine

To satisfy the non-negotiable operational constraint:
> **DO NOT download satellite imagery continuously if there is no new observation.**

SATGUARD implements a multi-tier polling and state-transition model:

```
+-----------------------------------------------------------------------------------+
| Scheduled Orchestrator (Temporal Job)                                             |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
                  [Fetch Active Critical Locations from DB]
                                          |
                                          v
                For each location: Query CDSE STAC / OData Catalog
                   Filter: Bounding Box / Polygon + Date Window
                                          |
                                          v
                        [Retrieve Catalog Observations]
                                          |
                                          v
               Compare Latest STAC `datetime` with `last_observation_time`
                                          |
                 +------------------------+------------------------+
                 |                                                 |
         [No Newer Item Found]                             [New Granule Found]
                 |                                                 |
                 v                                                 v
   Set Status: NO_NEW_OBSERVATION                   Set Status: NEW_OBSERVATION_AVAILABLE
   Update `last_catalog_check`                       Record Observation Header in DB
   Log zero bandwidth consumed                                     |
                                                                   v
                                                      [Quality Validation Gate]
                                                    Cloud Cover <= Threshold?
                                                    Data Geometry Complete?
                                                                   |
                                                  +----------------+----------------+
                                                  |                                 |
                                             [Passed]                           [Failed]
                                                  |                                 |
                                                  v                                 v
                                     Set Status: PROCESSING             Set Status: QUALITY_REJECTED
                                     Stream Required Bands via S3       Record rejection reason
                                                  |
                                                  v
                                     [Compute Differential Metrics]
                                     Compare with T_{n-1} Baseline
                                                  |
                                                  v
                                     Set Status: ANALYSIS_COMPLETE
                                     Generate Alerts & Risk Assessment
```

### Observation State Machine

| State | Definition | Next Permitted Transition |
| :--- | :--- | :--- |
| `NO_NEW_OBSERVATION` | STAC catalog returned no observations newer than the most recent recorded acquisition timestamp. | `NEW_OBSERVATION_AVAILABLE` on subsequent catalog check. |
| `NEW_OBSERVATION_AVAILABLE`| A new valid granule was detected in the space agency catalog; product metadata parsed and queued. | `PROCESSING` or `QUALITY_REJECTED`. |
| `QUALITY_REJECTED` | The observation failed quality checks (e.g., optical cloud cover > threshold, corrupt tile, partial scan). No heavy raster downloaded. | `NO_NEW_OBSERVATION` or next granule check. |
| `PROCESSING` | S3 band streaming and radiometric/spectral change calculations are actively executing. | `ANALYSIS_COMPLETE` or `PROCESSING_FAILED`. |
| `PROCESSING_FAILED` | Internal computation error, network timeout during raster slice, or invalid matrix dimension. | Automatic retry (up to 3 times) then `FAILED`. |
| `ANALYSIS_COMPLETE` | Derived metrics computed, baseline delta calculated, alerts evaluated, and intelligence stored. | Stable terminal state for observation cycle. |
| `DATA_UNAVAILABLE` | External provider API returned HTTP 5xx, 429, or network drop. System logs failure without inventing data. | Retry on next scheduler tick. |

---

## 4. Error Handling, Rate Limiting & Resilience Matrix

| Provider | HTTP Code | Root Cause | System Action | Fallback State |
| :--- | :--- | :--- | :--- | :--- |
| **CDSE** | `401 Unauthorized` | Access token expired or client secret revoked | Purge in-memory token cache, trigger synchronous re-auth, retry request | `DATA_UNAVAILABLE` (if re-auth fails) |
| **CDSE** | `429 Too Many Requests` | Burst limit exceeded (>100 req/min) | Exponential backoff with jitter: $T_{\text{wait}} = 2^k \times (1 \pm 0.1)\text{ s}$ | Pause queue worker for 60 seconds |
| **NASA GPM** | `404 Not Found` | Granule not yet processed into archive (latency delay) | Log observation latency, skip current half-hour slot | Mark rainfall as `CALCULATING_PENDING` |
| **NASA FIRMS** | `403 Forbidden` | Invalid or exhausted `MAP_KEY` | Log high-severity system alert to administrator | `DATA_UNAVAILABLE` (Never fabricate 0 fires) |
| **USGS** | `503 Service Unavailable` | USGS upstream network maintenance | Retry after 30 seconds; fallback to secondary GeoJSON summary feed | `DATA_UNAVAILABLE` |
| **OSM Overpass** | `429 / 504 Gateway Timeout`| Server overloaded or query timeout (>180s) | Switch to secondary public Overpass mirror (e.g., `kumi-systems`, `openstreetmap.fr`) or use cached DB vectors | Use previously cached PostGIS infrastructure vectors |
| **Groq API** | `429 Rate Limit` | Token per minute (TPM) limit reached | Enqueue synthesis request into background Celery/Redis queue; retry after 15s | Defer executive summary generation while keeping raw numerical metrics intact |
