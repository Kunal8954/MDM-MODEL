"""
satguard/providers/usgs.py
Authoritative real-time USGS Earthquake Hazards FDSN Web Service provider.
Requires NO API key. Provides real global seismic event data.
"""

from typing import List, Optional
from datetime import datetime, timezone
import math
import requests
from satguard.providers.base import EarthquakeProvider, SeismicEvent


class USGSEarthquakeProvider(EarthquakeProvider):
    """
    USGS FDSN Event Web Service integration for structural and landslide seismic correlation.
    API Docs: https://earthquake.usgs.gov/fdsnws/event/1/
    """

    def __init__(self, endpoint: str = "https://earthquake.usgs.gov/fdsnws/event/1/query"):
        self.endpoint = endpoint

    def _haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0  # Earth's radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2.0) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c

    def get_seismic_events(
        self,
        latitude: float,
        longitude: float,
        radius_km: float = 100.0,
        min_magnitude: float = 3.5,
        start_time: Optional[datetime] = None,
    ) -> List[SeismicEvent]:
        params = {
            "format": "geojson",
            "latitude": latitude,
            "longitude": longitude,
            "maxradiuskm": radius_km,
            "minmagnitude": min_magnitude,
            "orderby": "time",
        }

        if start_time:
            params["starttime"] = start_time.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            response = requests.get(self.endpoint, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            raise ConnectionError(f"USGS Earthquake API request failed: {e}")

        events: List[SeismicEvent] = []
        features = data.get("features", [])

        for feat in features:
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [0, 0, 0])

            eq_lon = coords[0]
            eq_lat = coords[1]
            eq_depth = coords[2] if len(coords) > 2 else 0.0

            # Compute accurate surface distance from target
            dist_km = self._haversine_km(latitude, longitude, eq_lat, eq_lon)

            # Parse epoch timestamp in milliseconds
            epoch_ms = props.get("time", 0)
            dt = datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)

            event = SeismicEvent(
                id=feat.get("id", "unknown"),
                magnitude=float(props.get("mag") or 0.0),
                place=props.get("place", "Unknown Location"),
                timestamp=dt,
                latitude=eq_lat,
                longitude=eq_lon,
                depth_km=float(eq_depth),
                distance_km=round(dist_km, 2),
                mmi=props.get("mmi"),
                alert=props.get("alert"),
            )
            events.append(event)

        return events
