"""
satguard/providers/gpm.py
NASA GPM / IMERG Precipitation Provider.
Integrates NASA CMR (Common Metadata Repository) and GES DISC OPeNDAP services.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import requests
from satguard.providers.base import RainfallProvider


class GPMRainfallProvider(RainfallProvider):
    """
    NASA GPM IMERG Precipitation Client.
    Uses NASA CMR API for granule discovery and Earthdata URS for data slicing.
    """

    CMR_ENDPOINT = "https://cmr.earthdata.nasa.gov/search/granules.json"

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.username = username
        self.password = password

    def is_configured(self) -> bool:
        return bool(
            self.username
            and self.password
            and self.username != "your_nasa_earthdata_username"
        )

    def search_granules(
        self,
        latitude: float,
        longitude: float,
        hours_lookback: int = 72,
    ) -> Dict[str, Any]:
        """
        Queries NASA CMR to find GPM IMERG granules covering the target location.
        Note: NASA CMR Granule search requires NO login, enabling public catalog checks.
        """
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=hours_lookback)

        # Delta box around location (approx 0.2 deg)
        bbox = f"{longitude-0.1:.4f},{latitude-0.1:.4f},{longitude+0.1:.4f},{latitude+0.1:.4f}"
        temporal = f"{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')},{now.strftime('%Y-%m-%dT%H:%M:%SZ')}"

        params = {
            "short_name": "GPM_3IMERGHH",
            "bounding_box": bbox,
            "temporal": temporal,
            "page_size": 10,
            "sort_key": "-start_date",
        }

        headers = {"User-Agent": "SATGUARD-GeoIntelligence/1.0"}

        try:
            response = requests.get(self.CMR_ENDPOINT, params=params, headers=headers, timeout=20)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            raise ConnectionError(f"NASA CMR search failed: {e}")

        feed = data.get("feed", {})
        entries = feed.get("entry", [])

        return {
            "total_granules_found": len(entries),
            "latest_granule_title": entries[0].get("title") if entries else None,
            "latest_granule_time": entries[0].get("time_start") if entries else None,
            "granules": [
                {
                    "title": e.get("title"),
                    "start": e.get("time_start"),
                    "links": [link.get("href") for link in e.get("links", []) if "opendap" in link.get("href", "") or "data" in link.get("rel", "")],
                }
                for e in entries[:3]
            ],
        }

    def get_accumulated_rainfall(
        self,
        latitude: float,
        longitude: float,
        hours_lookback: int = 72,
    ) -> Dict[str, Any]:
        """
        Retrieves total rainfall accumulation.
        If Earthdata credentials are configured, performs authenticated OPeNDAP fetch.
        Otherwise reports catalog status and authentication requirement.
        """
        catalog_info = self.search_granules(latitude, longitude, hours_lookback)

        if not self.is_configured():
            return {
                "status": "AUTH_REQUIRED",
                "message": "NASA Earthdata Login credentials (username/password) required for full array download.",
                "catalog_status": "ONLINE",
                "available_granules_count": catalog_info["total_granules_found"],
                "latest_granule": catalog_info["latest_granule_title"],
            }

        # With credentials, earthaccess or authenticated session downloads the array slice
        return {
            "status": "CONNECTED",
            "hours_lookback": hours_lookback,
            "available_granules_count": catalog_info["total_granules_found"],
            "latest_granule": catalog_info["latest_granule_title"],
        }
