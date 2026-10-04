# SATGUARD Data Sources Specification & Discovery Matrix

## Document Overview
This document specifies the authoritative, production-grade external data sources, satellite constellations, geospatial feeds, and AI inference APIs required for **SATGUARD** (Government Critical Location Earth Observation Platform).

Every data provider listed has been validated against official 2025/2026 documentation for endpoint availability, authentication requirements, rate limits, latency, spatial/temporal resolution, and legal licensing terms.

---

## 1. Master Data Sources Discovery Table

| Field | Source 1: Copernicus Sentinel-1 | Source 2: Copernicus Sentinel-2 | Source 3: Copernicus DEM (GLO-30) | Source 4: NASA GPM / IMERG |
| :--- | :--- | :--- | :--- | :--- |
| **SOURCE** | **Copernicus Data Space Ecosystem (CDSE) - Sentinel-1** | **Copernicus Data Space Ecosystem (CDSE) - Sentinel-2** | **Copernicus DEM (GLO-30 / GLO-90)** | **NASA Earthdata / GES DISC - GPM IMERG** |
| **PURPOSE** | Synthetic Aperture Radar (SAR) all-weather, day/night surface deformation, water extent, and structural coherence | Multispectral Optical Imagery (VNIR/SWIR) for vegetation indices, water bodies, glacial lakes, and land cover change | High-resolution elevation, slope, aspect, and hydrological drainage modeling for critical infrastructure and terrain | Near real-time and calibrated precipitation accumulation for flood risk, landslide triggering, and dam catchment stress |
| **OFFICIAL URL** | https://dataspace.copernicus.eu/ | https://dataspace.copernicus.eu/ | https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model | https://gpm.nasa.gov/data/imerg |
| **API / SDK** | • STAC API: `https://stac.dataspace.copernicus.eu/v1/`<br>• OData API: `https://catalogue.dataspace.copernicus.eu/odata/v1/`<br>• S3 API: `https://eodata.dataspace.copernicus.eu/`<br>• Sentinel Hub Process/Statistical API: `https://sh.dataspace.copernicus.eu/api/v1/`<br>• Python: `sentinelhub-py`, `pystac-client`, `boto3` | • STAC API: `https://stac.dataspace.copernicus.eu/v1/`<br>• OData API: `https://catalogue.dataspace.copernicus.eu/odata/v1/`<br>• S3 API: `https://eodata.dataspace.copernicus.eu/`<br>• Sentinel Hub Process/Statistical API: `https://sh.dataspace.copernicus.eu/api/v1/`<br>• Python: `sentinelhub-py`, `pystac-client`, `rioxarray` | • AWS Open Data S3: `s3://copernicus-dem-30m/`<br>• CDSE STAC / OData API<br>• OpenTopography REST API<br>• Python: `boto3` (no-sign-request), `rasterio`, `pystac-client` | • Earthdata Login + OPeNDAP: `https://gpm1.gesdisc.eosdis.nasa.gov/opendap/`<br>• GES DISC HTTPS REST Endpoint<br>• NASA CMR Search API: `https://cmr.earthdata.nasa.gov/search/granules.json`<br>• Python: `earthaccess`, `xarray` |
| **AUTH REQUIRED** | **Yes.** OAuth2 Client Credentials flow via Keycloak:<br>`https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`<br>Requires `CDSE_CLIENT_ID` and `CDSE_CLIENT_SECRET`. S3 requires Access Key/Secret Key generated from user dashboard. | **Yes.** Same OAuth2 Keycloak credentials and S3 credentials as Sentinel-1. | **No for AWS S3** (`--no-sign-request`).<br>**Yes for CDSE portal/STAC** (uses CDSE OAuth2 credentials). | **Yes.** NASA Earthdata Login (URS) account. Authentication via HTTP Basic / Bearer token or `_netrc` / `.netrc`. Must approve "NASA GES DISC DATA ARCHIVE" application. |
| **FREE?** | **Yes.** Public open data under European Union Copernicus Access Policy. | **Yes.** Public open data under European Union Copernicus Access Policy. | **Yes.** Free open public access for GLO-30 Public. | **Yes.** Free open public data under NASA Earth Science Data Policy. |
| **RATE LIMIT** | Standard CDSE quotas:<br>• OData/STAC: ~100 requests/minute<br>• S3 EODATA: High concurrency (up to 4-8 parallel download streams per IP/user)<br>• Sentinel Hub Process API: 300 processing units (PU) / minute on CDSE free tier | Standard CDSE quotas:<br>• STAC/OData: ~100 requests/min<br>• Process API: 300 PU/min<br>• S3 EODATA: Concurrent streaming allowed | AWS S3: High cloud-scale throughput (standard S3 multi-part limits, virtually unlimited for read-only access). | • CMR API: 2,000 req/min.<br>• GES DISC Web services: Nominal 10-20 concurrent connections; excessive crawling subject to temporary IP throttle. |
| **DATA LATENCY** | • Fast Delivery (NRT): 1 to 3 hours after satellite pass.<br>• Standard Level-1 GRD: 3 to 12 hours. | • Fast Delivery (NRT L1C): 2 to 4 hours.<br>• Refined L2A (Surface Reflectance): 4 to 12 hours. | Static / Semi-static benchmark dataset (Version 2021/2022 baseline, occasional tile maintenance). Instant S3 retrieval. | • IMERG Early Run (uncalibrated): ~4 hours.<br>• IMERG Late Run (adjusted): ~14 hours.<br>• IMERG Final Run (gauge-calibrated climatological): ~3.5 months. |
| **SPATIAL RESOLUTION** | 10 m (High Resolution Ground Range Detected - GRD in IW mode), 20 m (Medium Resolution). | 10 m (B2, B3, B4, B8 visible/NIR), 20 m (B5, B6, B7, B8A, B11, B12 RedEdge/SWIR), 60 m (atmospheric bands B1, B9, B10). | 30 meters (GLO-30 1 arc-second) global coverage; 90 meters (GLO-90 3 arc-second). | 0.1° x 0.1° (~10 km x 10 km grid). |
| **TEMPORAL RESOLUTION** | 6 days over Europe, 6-12 days globally (Sentinel-1A + Sentinel-1C following commissioning, with repeat orbit geometries). | 5 days at equator (combining Sentinel-2A + Sentinel-2B under constant viewing angles). | Static terrain model (referenced to WGS84 EGM2008 geoid). | Half-hourly (every 30 minutes) and aggregated daily accumulations. |
| **LICENSE / USAGE NOTES** | Open and free access for any purpose (commercial, academic, governmental) pursuant to EU Regulation (EU) No 377/2014 and Copernicus terms. Requires attribution: "Contains modified Copernicus Sentinel data [year]". | Open and free access under Copernicus Legal Notice. Requires attribution: "Contains modified Copernicus Sentinel data [year]". | Open access under Copernicus DEM Data Policy. Public GLO-30 worldwide (minor restricted territories covered by GLO-90). Attribution required. | Open access under NASA Open Data Policy (CC0 equivalent). Attribution to NASA Earth Science Data Systems required. |
| **WHAT SATGUARD WILL USE IT FOR** | **All-weather monitoring:** Radar backscatter ($\sigma_0$ VV/VH) change detection, floodwater inundation beneath clouds/smoke, glacial lake surface boundary changes, structural displacement/coherence loss at dams and bridges. | **Optical spectral monitoring:** Normalized Difference Water Index (NDWI) for lake/reservoir volume monitoring, NDVI for deforestation/land clearing, MNDWI for turbidity/siltation, and True Color (TCI) visual verification of construction/mining. | **Topographic baseline:** Slope, aspect, elevation profiles, watershed flow routing, SAR terrain radiometric and geometric terrain correction (orthorectification), and landslide slope-instability modeling. | **Hazard triggering and contextual correlation:** 24h, 48h, and 72h antecedent rainfall accumulation metrics linked directly to dam catchment inflows, landslide thresholds, and flash flood precursors. |

---

| Field | Source 5: NASA FIRMS | Source 6: USGS Earthquake API | Source 7: OpenStreetMap (OSM) | Source 8: Groq API |
| :--- | :--- | :--- | :--- | :--- |
| **SOURCE** | **NASA FIRMS (Fire Information for Resource Management System)** | **USGS Earthquake Hazards Program** | **OpenStreetMap (Overpass & Nominatim)** | **Groq LPU Inference API** |
| **PURPOSE** | Active wildfire detection, thermal anomalies, industrial flaring, and agricultural burning near critical assets | Real-time global seismic monitoring, epicenter location, depth, magnitude, and shake intensity | Vector baseline infrastructure, roads, rail, dams, settlements, waterways, and administrative boundaries | High-throughput, low-latency LLM synthesis of physical geospatial evidence into structured government intelligence briefings |
| **OFFICIAL URL** | https://firms.modaps.eosdis.nasa.gov/ | https://earthquake.usgs.gov/ | https://www.openstreetmap.org/ | https://groq.com/ |
| **API / SDK** | • REST API: `https://firms.modaps.eosdis.nasa.gov/api/`<br>• Area endpoint: `/api/area/csv/{MAP_KEY}/{SOURCE}/{BBOX}/{DAYS}`<br>• Python: `requests`, `pandas` | • FDSN Event Web Service: `https://earthquake.usgs.gov/fdsnws/event/1/query`<br>• Real-time GeoJSON Feeds: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/`<br>• Python: `requests` | • Overpass API: `https://overpass-api.de/api/interpreter`<br>• Nominatim Geocoding: `https://nominatim.openstreetmap.org/search`<br>• Python: `overpy`, `osmnx`, `geopandas` | • OpenAI-compatible REST API: `https://api.groq.com/openai/v1/chat/completions`<br>• Python SDK: `groq` (`from groq import Groq`) |
| **AUTH REQUIRED** | **Yes.** Requires free `MAP_KEY` obtained via email submission at `https://firms.modaps.eosdis.nasa.gov/api/`. | **No.** Completely open public API without any key or registration required. | **No API key required** for public Overpass/Nominatim endpoints. Requires valid identifiable `User-Agent` HTTP header. Self-hosted instances require internal URL. | **Yes.** Requires `GROQ_API_KEY` obtained from Groq Console (`https://console.groq.com/keys`). Bearer token auth. |
| **FREE?** | **Yes.** Free for scientific, operational, and public interest applications. | **Yes.** 100% free open public service. | **Yes.** Free community and public foundation infrastructure. | **Yes (Free Developer Tier Available):** Free tier provides high token limits per minute/day for models like `llama-3.3-70b-versatile`. Paid tiers available for high enterprise throughput. |
| **RATE LIMIT** | Nominal limit: ~10 requests per minute. Automated scripts should cache responses and query once per hour per monitored region. | FDSN Service: ~20 requests per second. Real-time GeoJSON static files can be polled every 60 seconds without throttling. | Public Overpass: Max 2 concurrent queries per IP, max query execution time 180s. Nominatim: Strict 1 request/second policy. | Free Tier Limits (model-dependent, e.g. `llama-3.3-70b`):<br>• 30 Requests Per Minute (RPM)<br>• 1,000 Requests Per Day (RPD)<br>• 6,000 Tokens Per Minute (TPM) |
| **DATA LATENCY** | • Ultra Real-Time (URT): < 60 seconds (US/Canada).<br>• Near Real-Time (NRT): 1 to 3 hours globally from satellite overpass (MODIS + VIIRS). | • Instantaneous: Feeds updated every 1 minute as seismic networks detect, locate, and refine event magnitudes. | Real-time vector data reflecting global crowd-sourced database updates. OSM extracts updated minutely/hourly. | Real-time streaming response latency: 200–500 tokens/second on Groq LPU hardware. |
| **SPATIAL RESOLUTION** | • VIIRS (S-NPP, NOAA-20, NOAA-21): 375 m pixel resolution.<br>• MODIS (Terra/Aqua): 1 km pixel resolution. | Point epicenter coordinates ($\pm 1-5\text{ km}$ horizontal accuracy depending on local sensor network density); focal depth in km. | Vector geometries (sub-meter geometric accuracy depending on survey source and satellite trace quality). | Not applicable (Natural language / structured JSON schema output). |
| **TEMPORAL RESOLUTION** | Multiple daily passes per sensor (approx. 4-6 satellite views per 24-hour cycle combining Terra, Aqua, S-NPP, NOAA-20, NOAA-21). | Continuous event stream triggered automatically on event occurrence ($M \ge 1.0$ local, $M \ge 4.5$ global). | Continuous live edits to database; static vector snapshots updated on demand. | On-demand sub-second inference calls. |
| **LICENSE / USAGE NOTES** | NASA Open Data Policy (public domain). Attribution: "NASA FIRMS data courtesy of NASA EOSDIS". | Public Domain (USGS data released without copyright restrictions under US Federal Law). | Open Data Commons Open Database License (ODbL) 1.0. Attribution required: "© OpenStreetMap contributors". Derived vector data must maintain ODbL compatibility. | Groq Terms of Service. Enterprise data privacy guarantees that user prompt inputs are not used for model training. |
| **WHAT SATGUARD WILL USE IT FOR** | **Thermal risk overlay:** Identifying wildland fires encroaching on power corridors, gas pipelines, dams, and municipal watersheds; detecting illegal clearing fires in protected reserves. | **Seismic hazard correlation:** Triggering automatic emergency satellite re-tasking/query pipelines when an earthquake ($M \ge 4.5$ or within 50 km) affects dam structures, bridges, or landslide slopes. | **Geographic feature extraction:** Building footprints, road evacuation corridors, bridge vectors, river centerlines, dam barrier footprints, and administrative risk boundaries for clipping satellite AOIs. | **Government intelligence briefing generator:** Synthesizing multi-modal metrics (SAR amplitude delta, NDWI delta, DEM slope, antecedent rainfall, seismic peak acceleration) into executive reports. **LLM never fabricates science; it interprets computed statistical vectors.** |

---

## 2. In-Depth Provider Specifications & Access Models

### 2.1 Copernicus Data Space Ecosystem (CDSE)
*   **Significance:** Replaced the legacy Copernicus Open Access Hub (SciHub) as of 2023/2024. CDSE is the single sovereign source for ESA Sentinel missions.
*   **Protocols Supported:**
    1.  **SpatioTemporal Asset Catalog (STAC) API:** RFC-compliant STAC v1.0.0 endpoint at `https://stac.dataspace.copernicus.eu/v1/`. Allows search by GeoJSON polygon, bounding box, date range, cloud coverage, and collection (`sentinel-1-grd`, `sentinel-2-l2a`).
    2.  **OData v4.0 API:** Full catalogue query interface at `https://catalogue.dataspace.copernicus.eu/odata/v1/`. Offers filtering via `$filter=OData.CSC.Intersects(...)` and direct zip/TAR product download via `/Products({Id})/$value`.
    3.  **S3 Object Storage Interface:** High-throughput streaming endpoint at `https://eodata.dataspace.copernicus.eu/`. Products are structured hierarchically under the `eodata` bucket (e.g., `s3://eodata/Sentinel-2/MSI/L2A/...`). This allows reading individual Cloud-Optimized GeoTIFFs (COGs) or band rasters without downloading entire 1 GB zip files.
    4.  **Sentinel Hub on CDSE:** Managed raster analytics engine (Process API, Statistical API) deployed on CDSE infrastructure (`https://sh.dataspace.copernicus.eu`). Executes on-the-fly evalscripts (JavaScript) for rapid cloud masking, NDVI, NDWI, and SAR backscatter orthorectification.
*   **Authentication Flow:**
    *   OAuth2 Keycloak Token Endpoint: `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
    *   Grant type: `client_credentials`
    *   Credentials required: `client_id` and `client_secret` (generated inside the CDSE User Dashboard).
    *   Token lifespan: 600 seconds (10 minutes). Must be cached in server memory and refreshed asynchronously.
    *   S3 Credentials: Dedicated S3 Access Key and Secret Key generated via User Profile -> S3 Access.

### 2.2 Copernicus DEM (Digital Elevation Model)
*   **Dataset Identification:** `Copernicus_DSM_COG_10_N...` (GLO-30) and `Copernicus_DSM_COG_30_N...` (GLO-90).
*   **Storage Architecture:** Hosted on AWS Open Data as Cloud Optimized GeoTIFFs (COGs).
    *   Bucket: `s3://copernicus-dem-30m/`
    *   Access Mode: Anonymous (`--no-sign-request`).
    *   Coordinate System: WGS 84 (EPSG:4326) with orthometric heights above the EGM2008 geoid.
*   **Usage Pattern:** The system performs raster window reads via `rasterio` or `rioxarray` directly from S3 without storing multi-terabyte global elevation rasters locally.

### 2.3 NASA GPM / IMERG (Precipitation)
*   **Dataset:** GPM Level 3 IMERG Half-Hourly (GPM_3IMERGHH) and Daily (GPM_3IMERGDF).
*   **Access Protocols:**
    1.  **NASA CMR (Common Metadata Repository):** Fast discovery of NetCDF4/HDF5 granules matching location bounding box and time range.
    2.  **GES DISC OPeNDAP:** Subsets spatial boxes and variables (`precipitationCal`, `precipitationUncal`) on the server side so that only a few kilobytes of data are downloaded per query rather than full global grids.
*   **Authentication Flow:**
    *   NASA Earthdata Login (URS) username and password.
    *   Stored server-side in environment variables `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`.
    *   Automated via Python `earthaccess` library which handles cookie sessions and redirects.

### 2.4 NASA FIRMS (Active Fire Data)
*   **Sensors:** VIIRS (375 m resolution from Suomi-NPP, NOAA-20, NOAA-21) and MODIS (1 km from Terra, Aqua).
*   **Access Mechanism:** RESTful CSV/GeoJSON Area API:
    ```http
    GET https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SENSOR}/{WEST,SOUTH,EAST,NORTH}/{DAYS}
    ```
*   **Key Parameters:**
    *   `MAP_KEY`: 32-character hex key issued to user.
    *   `SENSOR`: `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT`.
    *   `DAYS`: Integer between 1 and 10.
*   **Data Fields Returned:** `latitude`, `longitude`, `brightness`, `scan`, `track`, `acq_date`, `acq_time`, `satellite`, `confidence`, `version`, `bright_t31`, `frp` (Fire Radiative Power in MW), `daynight`.

### 2.5 USGS Earthquake Hazards Program
*   **Endpoint:** FDSN Event Web Service (`https://earthquake.usgs.gov/fdsnws/event/1/query`) and Summary Feeds.
*   **Query Parameters:**
    *   `format=geojson`
    *   `latitude`, `longitude`, `maxradiuskm`
    *   `starttime`, `endtime`
    *   `minmagnitude` (typically 3.0 to 4.5 for infrastructure alert thresholds)
*   **Key Fields Returned:** `mag`, `place`, `time`, `updated`, `tz`, `url`, `detail`, `felt`, `cdi`, `mmi` (Modified Mercalli Intensity), `alert` (PAGER alert level: green, yellow, orange, red), `status`, `tsunami`, `sig`, `net`, `code`, `ids`, `sources`, `types`, `nst`, `dmin`, `rms`, `gap`, `magType`, `type`, `geometry` (coordinates: [lon, lat, depth_km]).

### 2.6 OpenStreetMap (OSM)
*   **Primary Interfaces:**
    1.  **Overpass API:** Executes Overpass QL queries to extract critical infrastructure features within the location polygon or buffer:
        *   Water bodies: `way["water"="reservoir"]`, `way["water"="lake"]`, `relation["natural"="water"]`
        *   Dam structures: `way["waterway"="dam"]`, `way["man_made"="dyke"]`
        *   Infrastructure: `way["bridge"="yes"]`, `way["highway"]`, `way["railway"]`
        *   Mining/Industry: `way["landuse"="quarry"]`, `way["landuse"="industrial"]`
    2.  **Nominatim Geocoding:** Reverse-geocoding of monitored coordinates to obtain national, regional, and district administrative names.
*   **Operational Safeguards:** SATGUARD caches all OSM vector footprints locally in the PostGIS database. Vector extraction is executed once during critical location onboarding and refreshed only on administrative request, respecting OSM public resource limits.

### 2.7 Groq LLM Inference Service
*   **Model Selection:** `llama-3.3-70b-versatile` (primary synthesis engine), `mixtral-8x7b-32768` (secondary fallback).
*   **Architectural Guardrail:**
    *   The LLM **never** estimates mathematical risk directly.
    *   The LLM receives a strictly validated JSON payload containing computed telemetry:
        *   Baseline vs Current Water Index ($\Delta\text{NDWI}$)
        *   Radar Backscatter Intensity Change ($\Delta\sigma_{VV}^0, \Delta\sigma_{VH}^0$)
        *   Antecedent 48-Hour Rainfall Accumulation ($mm$)
        *   DEM Slope Gradient ($\text{degrees}$)
        *   Seismic Event Proximity ($km$, Magnitude, MMI)
        *   Active Thermal Anomaly Count and Max Fire Radiative Power ($MW$)
    *   The LLM performs structured schema extraction (`response_format={"type": "json_object"}`) to produce a standard government SITREP (Situation Report) with citation of exact numerical indicators.
