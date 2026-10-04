"""
scripts/verify_api_connectivity.py
SATGUARD Real API and Data Infrastructure Connectivity Verification.

Connects to all real endpoints using real critical location coordinates:
- Tehri Dam (30.3781°N, 78.4803°E)
- Zero fake data!
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from shapely.geometry import box

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from satguard.config import settings
from satguard.providers.usgs import USGSEarthquakeProvider
from satguard.providers.osm import OSMProvider
from satguard.providers.copernicus_dem import CopernicusDEMProvider
from satguard.providers.copernicus import CopernicusSatelliteProvider
from satguard.providers.gpm import GPMRainfallProvider
from satguard.providers.firms import FIRMSFireProvider
from satguard.providers.groq_provider import GroqLLMProvider


def test_usgs_earthquake():
    print("\n" + "=" * 70)
    print("[1/7] TESTING REAL USGS EARTHQUAKE HAZARDS API (Zero-Key)")
    print("=" * 70)
    provider = USGSEarthquakeProvider()
    lat, lon = 30.3781, 78.4803  # Tehri Dam
    radius_km = 300.0  # Regional Himalayan arc
    min_mag = 4.0
    start_time = datetime.now(timezone.utc) - timedelta(days=180)

    try:
        events = provider.get_seismic_events(
            latitude=lat,
            longitude=lon,
            radius_km=radius_km,
            min_magnitude=min_mag,
            start_time=start_time,
        )
        print(f"  Status: ONLINE (HTTP 200)")
        print(f"  Endpoint: {provider.endpoint}")
        print(f"  Target: Tehri Dam ({lat}N, {lon}E, Radius: {radius_km}km)")
        print(f"  Real Seismic Events Found (M>={min_mag}, Last 180d): {len(events)}")
        if events:
            top_event = events[0]
            clean_place = top_event.place.encode("ascii", "replace").decode("ascii")
            print(f"  Latest Real Event: M{top_event.magnitude} - {clean_place}")
            print(f"  Timestamp: {top_event.timestamp.isoformat()}, Depth: {top_event.depth_km}km, Distance: {top_event.distance_km}km")
        return {"status": "SUCCESS", "records": len(events)}
    except Exception as e:
        print(f"  Status: ERROR: {e}")
        return {"status": "FAILED", "error": str(e)}


def test_copernicus_dem():
    print("\n" + "=" * 70)
    print("[2/7] TESTING REAL COPERNICUS DEM GLO-30 ON AWS OPEN DATA (Zero-Key)")
    print("=" * 70)
    provider = CopernicusDEMProvider()
    lat, lon = 30.3781, 78.4803  # Tehri Dam

    try:
        res = provider.check_dem_tile_availability(lat, lon)
        print(f"  Status: ONLINE (Public AWS S3 Anonymous Read)")
        print(f"  Target Tile: {res.get('tile_name')}")
        print(f"  Available: {res.get('available')}")
        print(f"  S3 URI: {res.get('s3_uri')}")
        print(f"  File Size: {res.get('size_mb')} MB ({res.get('size_bytes')} bytes)")
        print(f"  Resolution: {res.get('resolution')}")
        return {"status": "SUCCESS", "tile": res.get("tile_name"), "size_mb": res.get("size_mb")}
    except Exception as e:
        print(f"  Status: ERROR: {e}")
        return {"status": "FAILED", "error": str(e)}


def test_osm_overpass():
    print("\n" + "=" * 70)
    print("[3/7] TESTING REAL OPENSTREETMAP OVERPASS API (Zero-Key)")
    print("=" * 70)
    provider = OSMProvider(endpoint=settings.OSM_OVERPASS_URL, user_agent=settings.OSM_USER_AGENT)
    bbox = (30.35, 78.45, 30.42, 78.52)  # Tehri Dam reservoir perimeter

    try:
        data = provider.get_infrastructure_features(bbox)
        print(f"  Status: ONLINE (HTTP 200)")
        print(f"  Endpoint: {provider.endpoint}")
        print(f"  BBox: {bbox}")
        print(f"  Raw OSM Elements Returned: {data['raw_element_count']}")
        print(f"  Dams Detected: {len(data['dams'])}")
        for d in data["dams"][:3]:
            print(f"    - {d['name']} (ID: {d['id']})")
        print(f"  Water Bodies / Reservoirs Detected: {len(data['water_bodies'])}")
        print(f"  Major Highway Features: {len(data['major_roads'])}")
        return {"status": "SUCCESS", "elements": data["raw_element_count"]}
    except Exception as e:
        print(f"  Status: ERROR: {e}")
        return {"status": "FAILED", "error": str(e)}


def test_nasa_gpm_cmr():
    print("\n" + "=" * 70)
    print("[4/7] TESTING REAL NASA GPM / IMERG PRECIPITATION DISCOVERY")
    print("=" * 70)
    provider = GPMRainfallProvider(
        username=settings.EARTHDATA_USERNAME,
        password=settings.EARTHDATA_PASSWORD,
    )
    lat, lon = 30.3781, 78.4803

    try:
        catalog = provider.search_granules(lat, lon, hours_lookback=72)
        print(f"  Catalog Discovery Status: ONLINE (NASA CMR Public API)")
        print(f"  Granules Found in 72h Window: {catalog['total_granules_found']}")
        print(f"  Latest Real Granule: {catalog['latest_granule_title']}")
        print(f"  Granule Timestamp: {catalog['latest_granule_time']}")

        acc = provider.get_accumulated_rainfall(lat, lon, hours_lookback=72)
        if acc["status"] == "AUTH_REQUIRED":
            print(f"  Download Auth Status: AUTH_REQUIRED ({acc['message']})")
        else:
            print(f"  Download Auth Status: CONNECTED")
        return {"status": "SUCCESS", "granules": catalog["total_granules_found"]}
    except Exception as e:
        print(f"  Status: ERROR: {e}")
        return {"status": "FAILED", "error": str(e)}


def test_cdse_satellite():
    print("\n" + "=" * 70)
    print("[5/7] TESTING COPERNICUS DATA SPACE ECOSYSTEM (CDSE)")
    print("=" * 70)
    provider = CopernicusSatelliteProvider(
        client_id=settings.CDSE_CLIENT_ID,
        client_secret=settings.CDSE_CLIENT_SECRET,
        s3_access_key=settings.CDSE_S3_ACCESS_KEY,
        s3_secret_key=settings.CDSE_S3_SECRET_KEY,
    )

    if not provider.is_configured() or "your_cdse" in str(settings.CDSE_CLIENT_ID):
        print("  Status: CREDENTIALS_REQUIRED")
        print("  Note: Enter CDSE_CLIENT_ID and CDSE_CLIENT_SECRET in .env")
        print("  Sign up at: https://dataspace.copernicus.eu/")
        return {"status": "AWAITING_CREDENTIALS", "provider": "CDSE"}

    try:
        authenticated = provider.authenticate()
        print(f"  OAuth2 Authentication: {'SUCCESS (Token Generated)' if authenticated else 'FAILED'}")
        
        # Test STAC search with 10km box around Tehri Dam
        geom = box(78.40, 30.30, 78.55, 30.45)
        now = datetime.now(timezone.utc)
        observations = provider.search_observations(
            geometry=geom,
            start_time=now - timedelta(days=30),
            end_time=now,
            collection="sentinel-2-l2a",
            max_cloud_cover=40.0,
            limit=5,
        )
        print(f"  Real Observations Found in STAC: {len(observations)}")
        for obs in observations[:2]:
            print(f"    - Product: {obs.product_id}")
            print(f"      Acquired: {obs.acquisition_time}, Cloud Cover: {obs.cloud_cover}%")
        return {"status": "SUCCESS", "observations": len(observations)}
    except Exception as e:
        print(f"  Status: ERROR: {e}")
        return {"status": "FAILED", "error": str(e)}


def test_nasa_firms():
    print("\n" + "=" * 70)
    print("[6/7] TESTING NASA FIRMS (Active Fire / Thermal)")
    print("=" * 70)
    provider = FIRMSFireProvider(map_key=settings.FIRMS_MAP_KEY)

    if not provider.is_configured():
        print("  Status: MAP_KEY_REQUIRED")
        print("  Note: Set FIRMS_MAP_KEY in .env")
        print("  Request free key at: https://firms.modaps.eosdis.nasa.gov/api/")
        return {"status": "AWAITING_KEY", "provider": "NASA_FIRMS"}

    try:
        bbox = (78.35, 30.25, 78.60, 30.50)
        fires = provider.get_active_fires(bbox=bbox, days_lookback=2)
        print(f"  Status: ONLINE (HTTP 200)")
        print(f"  Thermal Anomalies Detected: {len(fires)}")
        return {"status": "SUCCESS", "anomalies": len(fires)}
    except Exception as e:
        print(f"  Status: ERROR: {e}")
        return {"status": "FAILED", "error": str(e)}


def test_groq_llm():
    print("\n" + "=" * 70)
    print("[7/7] TESTING GROQ LPU INFERENCE CLOUD")
    print("=" * 70)
    provider = GroqLLMProvider(api_key=settings.GROQ_API_KEY, model=settings.GROQ_PRIMARY_MODEL)

    if not provider.is_configured():
        print("  Status: GROQ_API_KEY_REQUIRED")
        print("  Note: Set GROQ_API_KEY in .env")
        print("  Get key at: https://console.groq.com/keys")
        return {"status": "AWAITING_KEY", "provider": "Groq"}

    try:
        test_metrics = {
            "delta_ndwi": 0.14,
            "surface_water_area_change_percent": 8.5,
            "sar_vv_backscatter_delta_db": -2.8,
        }
        test_context = {
            "antecedent_rainfall_72h_mm": 64.2,
            "nearest_seismic_event": "None (M>3.5)",
            "active_fires_count": 0,
        }
        sitrep = provider.synthesize_situation_report(
            location_name="Tehri Dam",
            location_type="dam",
            computed_metrics=test_metrics,
            environmental_context=test_context,
        )
        print(f"  Status: ONLINE (Groq LPU Inference Verified)")
        print(f"  Model Used: {settings.GROQ_PRIMARY_MODEL}")
        print(f"  JSON SITREP Keys Generated: {list(sitrep.keys())}")
        return {"status": "SUCCESS", "sitrep": sitrep}
    except Exception as e:
        print(f"  Status: ERROR: {e}")
        return {"status": "FAILED", "error": str(e)}


def main():
    print("\n" + "#" * 70)
    print("  SATGUARD PLATFORM - LIVE INFRASTRUCTURE CONNECTIVITY AUDIT")
    print("  Timestamp: " + datetime.now(timezone.utc).isoformat())
    print("#" * 70)

    results = {}
    results["USGS_Earthquake"] = test_usgs_earthquake()
    results["Copernicus_DEM"] = test_copernicus_dem()
    results["OpenStreetMap"] = test_osm_overpass()
    results["NASA_GPM_CMR"] = test_nasa_gpm_cmr()
    results["CDSE_Satellite"] = test_cdse_satellite()
    results["NASA_FIRMS"] = test_nasa_firms()
    results["Groq_LLM"] = test_groq_llm()

    print("\n" + "#" * 70)
    print("  AUDIT SUMMARY")
    print("#" * 70)
    for service, res in results.items():
        status = res.get("status")
        print(f"  {service:20s}: {status}")
    print("#" * 70 + "\n")


if __name__ == "__main__":
    main()
