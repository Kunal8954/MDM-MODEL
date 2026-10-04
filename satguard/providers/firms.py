"""
satguard/providers/firms.py
NASA FIRMS Active Fire Provider.
Queries near real-time thermal anomalies from VIIRS and MODIS sensors.
"""

from typing import List, Tuple, Optional
import csv
import io
import requests
from satguard.providers.base import FireProvider, ThermalAnomaly


class FIRMSFireProvider(FireProvider):
    """
    Retrieves active fire and thermal anomaly observations from NASA FIRMS.
    API Docs: https://firms.modaps.eosdis.nasa.gov/api/
    """

    def __init__(
        self,
        map_key: Optional[str] = None,
        endpoint: str = "https://firms.modaps.eosdis.nasa.gov/api/area/csv",
    ):
        self.map_key = map_key
        self.endpoint = endpoint

    def is_configured(self) -> bool:
        return bool(self.map_key and self.map_key != "your_32_char_firms_map_key_here")

    def get_active_fires(
        self,
        bbox: Tuple[float, float, float, float],
        days_lookback: int = 2,
        sensor: str = "VIIRS_SNPP_NRT",
    ) -> List[ThermalAnomaly]:
        """
        Query FIRMS within bbox (west, south, east, north).
        """
        if not self.is_configured():
            raise ValueError(
                "FIRMS_MAP_KEY is not configured in .env. "
                "Get a free key at: https://firms.modaps.eosdis.nasa.gov/api/"
            )

        west, south, east, north = bbox
        bbox_str = f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"
        url = f"{self.endpoint}/{self.map_key}/{sensor}/{bbox_str}/{days_lookback}"

        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
        except requests.RequestException as e:
            raise ConnectionError(f"NASA FIRMS API request failed: {e}")

        # Check for error string returned in plain text
        if "Invalid MAP_KEY" in response.text or "Error" in response.text:
            raise PermissionError(f"NASA FIRMS authentication error: {response.text.strip()}")

        anomalies: List[ThermalAnomaly] = []
        reader = csv.DictReader(io.StringIO(response.text))

        for row in reader:
            try:
                anomaly = ThermalAnomaly(
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    brightness=float(row.get("bright_ti4") or row.get("brightness") or 0.0),
                    confidence=row.get("confidence", "nominal"),
                    acq_date=row.get("acq_date", ""),
                    acq_time=row.get("acq_time", ""),
                    frp_mw=float(row.get("frp") or 0.0),
                    sensor=sensor,
                )
                anomalies.append(anomaly)
            except (ValueError, KeyError):
                continue

        return anomalies
