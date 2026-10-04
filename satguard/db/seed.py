"""
satguard/db/seed.py
Seeds the 10 initial sovereign critical locations from config/data_sources.yaml into the database.
Enforces the rule: Never hardcode locations in Python business logic.
"""

import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from satguard.config import settings
from satguard.db.session import init_db, get_db_session
from satguard.models.entities import CriticalLocation
from satguard.geospatial.aoi import create_circular_aoi, polygon_to_wkt


def seed_critical_locations(db: Session) -> int:
    """
    Parses critical locations from config/data_sources.yaml and upserts them into the database.
    """
    locations_data = settings.get_critical_locations()
    if not locations_data:
        raise ValueError("No critical locations found in config/data_sources.yaml")

    count = 0
    now = datetime.now(timezone.utc)

    for loc in locations_data:
        loc_id = loc["id"]
        lat = float(loc["latitude"])
        lon = float(loc["longitude"])
        radius_m = int(loc["radius_meters"])

        # Generate spatial boundary polygon from coordinates and radius
        boundary_poly = create_circular_aoi(latitude=lat, longitude=lon, radius_m=radius_m)
        wkt_geom = polygon_to_wkt(boundary_poly)

        existing = db.query(CriticalLocation).filter(CriticalLocation.id == loc_id).first()
        if existing:
            existing.name = loc["name"]
            existing.location_type = loc["location_type"]
            existing.latitude = lat
            existing.longitude = lon
            existing.radius_m = radius_m
            existing.geometry = wkt_geom
            existing.priority = loc.get("priority", "routine")
            existing.risk_category = loc.get("risk_category", "general_monitoring")
            existing.monitoring_frequency = loc.get("monitoring_frequency", "continuous_pass")
            existing.monitoring_enabled = loc.get("monitoring_enabled", True)
            existing.description = loc.get("description", "")
            existing.updated_at = now
        else:
            new_loc = CriticalLocation(
                id=loc_id,
                name=loc["name"],
                location_type=loc["location_type"],
                latitude=lat,
                longitude=lon,
                radius_m=radius_m,
                geometry=wkt_geom,
                priority=loc.get("priority", "routine"),
                risk_category=loc.get("risk_category", "general_monitoring"),
                monitoring_frequency=loc.get("monitoring_frequency", "continuous_pass"),
                monitoring_enabled=loc.get("monitoring_enabled", True),
                description=loc.get("description", ""),
                created_at=now,
                updated_at=now,
            )
            db.add(new_loc)
        count += 1

    db.commit()
    return count


if __name__ == "__main__":
    init_db()
    session = get_db_session()
    try:
        seeded = seed_critical_locations(session)
        print(f"Successfully seeded {seeded} critical locations from config/data_sources.yaml.")
    finally:
        session.close()
