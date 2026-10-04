"""
satguard/providers/osm.py
OpenStreetMap Overpass API Provider for real vector infrastructure extraction.
Requires NO API key. Uses standard Overpass QL queries.
"""

from typing import Dict, Any, List, Tuple, Optional
import requests
from satguard.providers.base import MapDataProvider


class OSMProvider(MapDataProvider):
    """
    Queries OpenStreetMap Overpass API to fetch real water bodies, dams, bridges, and infrastructure.
    """

    def __init__(
        self,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        user_agent: str = "SATGUARD-GeoIntelligence/1.0 (satguard-monitoring@domain.gov)",
    ):
        self.endpoint = endpoint
        self.user_agent = user_agent

    def get_infrastructure_features(
        self,
        bbox: Tuple[float, float, float, float],
        feature_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Query Overpass API within bounding box (south, west, north, east).
        """
        south, west, north, east = bbox

        # Construct Overpass QL query
        overpass_ql = f"""
        [out:json][timeout:30];
        (
          node["waterway"="dam"]({south},{west},{north},{east});
          way["waterway"="dam"]({south},{west},{north},{east});
          relation["waterway"="dam"]({south},{west},{north},{east});
          way["water"="reservoir"]({south},{west},{north},{east});
          way["natural"="water"]({south},{west},{north},{east});
          way["bridge"="yes"]({south},{west},{north},{east});
          way["highway"~"primary|secondary|trunk|motorway"]({south},{west},{north},{east});
        );
        out body;
        >;
        out skel qt;
        """

        headers = {
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = requests.post(
                self.endpoint, data={"data": overpass_ql}, headers=headers, timeout=40
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            raise ConnectionError(f"OpenStreetMap Overpass API request failed: {e}")

        elements = data.get("elements", [])
        
        # Categorize features
        categorized = {
            "dams": [],
            "water_bodies": [],
            "bridges": [],
            "major_roads": [],
            "raw_element_count": len(elements),
        }

        for elem in elements:
            tags = elem.get("tags", {})
            name = tags.get("name", "Unnamed")
            
            if tags.get("waterway") == "dam":
                categorized["dams"].append({"id": elem.get("id"), "name": name, "tags": tags})
            elif tags.get("water") == "reservoir" or tags.get("natural") == "water":
                categorized["water_bodies"].append({"id": elem.get("id"), "name": name, "tags": tags})
            elif tags.get("bridge") == "yes":
                categorized["bridges"].append({"id": elem.get("id"), "name": name, "tags": tags})
            elif "highway" in tags:
                categorized["major_roads"].append({"id": elem.get("id"), "name": name, "highway": tags.get("highway")})

        return categorized
