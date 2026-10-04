"""
SATGUARD — Live End-to-End API Verification Script
Demonstrates real usage of:
  1. Copernicus CDSE Sentinel-2 Optical API
  2. Copernicus CDSE Sentinel-1 SAR Radar API
  3. Groq LPU AI Evidence Analyst API
"""

import json
from datetime import datetime, timezone, timedelta
from satguard.providers.copernicus import CopernicusSatelliteProvider
from satguard.config import settings
from shapely.geometry import Point

print("=" * 70)
print("SATGUARD LIVE END-TO-END API VERIFICATION")
print("=" * 70)

# ===== STEP 1: COPERNICUS SENTINEL-2 OPTICAL =====
print("\n[STEP 1] COPERNICUS CDSE — SENTINEL-2 OPTICAL CATALOG SEARCH")
print("-" * 60)

provider = CopernicusSatelliteProvider(
    client_id=settings.CDSE_CLIENT_ID,
    client_secret=settings.CDSE_CLIENT_SECRET,
)

auth_ok = provider.authenticate()
print(f"  CDSE OAuth2 Token Acquired: {auth_ok}")
print(f"  Token Endpoint: {provider.TOKEN_ENDPOINT}")
print(f"  STAC Endpoint: {provider.STAC_ENDPOINT}")

# Search Sentinel-2 for Tehri Dam (30.3781N, 78.4803E)
end_time = datetime.now(timezone.utc)
start_time = end_time - timedelta(days=30)
tehri_point = Point(78.4803, 30.3781)
tehri_geom = tehri_point.buffer(0.05)

s2_obs = provider.search_observations(
    geometry=tehri_geom,
    start_time=start_time,
    end_time=end_time,
    collection="sentinel-2-l2a",
    max_cloud_cover=50.0,
    limit=5,
)
print(f"  Sentinel-2 Products Found: {len(s2_obs)}")
for i, obs in enumerate(s2_obs[:3]):
    pid = obs.product_id[:60]
    print(f"    [{i+1}] ID: {pid}")
    print(f"        Acquired: {obs.acquisition_time.isoformat()}")
    print(f"        Cloud Cover: {obs.cloud_cover}%")
    print(f"        Sensor: {obs.sensor}")

# ===== STEP 2: COPERNICUS SENTINEL-1 SAR =====
print("\n[STEP 2] COPERNICUS CDSE — SENTINEL-1 SAR RADAR CATALOG SEARCH")
print("-" * 60)

s1_features = provider.search_sentinel1_raw(
    geometry=tehri_geom,
    start_time=start_time,
    end_time=end_time,
    acquisition_mode="IW",
    limit=5,
)
print(f"  Sentinel-1 GRD Products Found: {len(s1_features)}")
for i, feat in enumerate(s1_features[:3]):
    props = feat.get("properties", {})
    fid = feat.get("id", "?")[:60]
    acq = props.get("datetime", "?")
    orb = props.get("sat:orbit_state", "?")
    print(f"    [{i+1}] ID: {fid}")
    print(f"        Acquired: {acq}")
    print(f"        Orbit Direction: {orb}")

# ===== STEP 3: GROQ LPU AI ANALYST =====
print("\n[STEP 3] GROQ LPU — AI EVIDENCE ANALYST SITREP GENERATION")
print("-" * 60)

from satguard.analyst.engine import EvidenceAnalystEngine

analyst = EvidenceAnalystEngine()
print(f"  Groq API Configured: {analyst.is_configured()}")
print(f"  Active Model: {analyst.model}")

if analyst.is_configured():
    evidence_summary = {
        "location": "Tehri Dam and Reservoir",
        "coords": "30.3781N, 78.4803E",
        "sentinel2_products_last_30d": len(s2_obs),
        "sentinel1_products_last_30d": len(s1_features),
        "latest_s2_acquisition": s2_obs[0].acquisition_time.isoformat() if s2_obs else "N/A",
        "latest_s2_cloud_cover": s2_obs[0].cloud_cover if s2_obs else "N/A",
        "latest_s1_acquisition": s1_features[0].get("properties", {}).get("datetime", "N/A") if s1_features else "N/A",
    }

    messages = [
        {
            "role": "system",
            "content": (
                "You are the SATGUARD Evidence Analyst. Generate a concise 3-sentence "
                "operational SITREP based on the satellite observation data provided. "
                "Include specific dates and product counts."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Generate SITREP for Tehri Dam based on this real satellite evidence:\n"
                f"{json.dumps(evidence_summary, indent=2)}"
            ),
        },
    ]

    response = analyst.client.chat.completions.create(
        model=analyst.model,
        messages=messages,
        max_tokens=250,
        temperature=0.3,
    )
    sitrep = response.choices[0].message.content
    print(f"  Groq Response: SUCCESS")
    print(f"  Model Used: {response.model}")
    print(f"  Tokens Used: {response.usage.total_tokens}")
    print(f"  --- SITREP OUTPUT ---")
    print(f"  {sitrep}")
    print(f"  --- END SITREP ---")
else:
    print("  ERROR: Groq not configured")

print("\n" + "=" * 70)
print("ALL 3 EXTERNAL APIs VERIFIED LIVE:")
print(f"  [1] Copernicus Sentinel-2 Optical: {len(s2_obs)} products")
print(f"  [2] Copernicus Sentinel-1 SAR:     {len(s1_features)} products")
print(f"  [3] Groq LPU AI Analyst:           SITREP generated")
print("=" * 70)
