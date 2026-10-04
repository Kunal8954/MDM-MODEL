"""
satguard/geospatial/aoi.py
Area of Interest (AOI) generation, projection, and geometry utilities for SATGUARD.
Converts latitude, longitude, and radius_m into authoritative geospatial polygons and bounding boxes.
"""

import math
from typing import Tuple, Dict, Any, List
from shapely.geometry import Polygon, box, mapping, shape
import shapely.wkt


def create_circular_aoi(latitude: float, longitude: float, radius_m: float, points: int = 32) -> Polygon:
    """
    Generates a geospatial polygon approximating a circle of radius_m around (lat, lon) on WGS84 ellipsoid.
    """
    R = 6378137.0  # WGS-84 Earth equatorial radius in meters
    coords: List[Tuple[float, float]] = []

    for i in range(points):
        angle = (2.0 * math.pi / points) * i
        # Offsets in meters
        dx = radius_m * math.cos(angle)
        dy = radius_m * math.sin(angle)

        # Coordinate offsets in degrees
        dlat = (dy / R) * (180.0 / math.pi)
        dlon = (dx / (R * math.cos(math.radians(latitude)))) * (180.0 / math.pi)

        coords.append((longitude + dlon, latitude + dlat))

    # Close the ring
    coords.append(coords[0])
    return Polygon(coords)


def create_bbox_from_point(latitude: float, longitude: float, radius_m: float) -> Tuple[float, float, float, float]:
    """
    Computes a bounding box (min_lon, min_lat, max_lon, max_lat) around a coordinate center.
    """
    R = 6378137.0
    dlat = (radius_m / R) * (180.0 / math.pi)
    dlon = (radius_m / (R * math.cos(math.radians(latitude)))) * (180.0 / math.pi)

    min_lon = longitude - dlon
    max_lon = longitude + dlon
    min_lat = latitude - dlat
    max_lat = latitude + dlat

    return (min_lon, min_lat, max_lon, max_lat)


def polygon_to_wkt(poly: Polygon) -> str:
    return poly.wkt


def wkt_to_polygon(wkt_str: str) -> Polygon:
    return shapely.wkt.loads(wkt_str)


def compute_bbox_area_m2(bbox: Tuple[float, float, float, float]) -> float:
    """
    Calculates geographic surface area in square meters for a bounding box (min_lon, min_lat, max_lon, max_lat).
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    mean_lat = (min_lat + max_lat) / 2.0
    R = 6378137.0

    width_m = (max_lon - min_lon) * (math.pi / 180.0) * R * math.cos(math.radians(mean_lat))
    height_m = (max_lat - min_lat) * (math.pi / 180.0) * R

    return abs(width_m * height_m)
