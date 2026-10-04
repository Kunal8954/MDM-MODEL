"""
scripts/verify_phase3.py
End-to-End Real Integration Verification Script for Phase 3: Multi-Sensor Evidence Fusion.
Fuses Sentinel-1, Sentinel-2, NASA GPM, NASA FIRMS, USGS Earthquake, and Copernicus DEM
evidence for Tehri Dam into an auditable EvidenceSnapshot.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from satguard.db.session import get_db_session, init_db
from satguard.models.entities import CriticalLocation, EvidenceSnapshot
from satguard.fusion.engine import EvidenceFusionEngine


def run_phase3_verification():
    print("=" * 65)
    print("SATGUARD — PHASE 3 MULTI-SENSOR EVIDENCE FUSION VERIFICATION")
    print("=" * 65)

    init_db()
    db = get_db_session()

    try:
        location_id = "loc-001-tehri-dam"
        engine = EvidenceFusionEngine()

        print("[*] Fusing multi-sensor evidence for critical location: Tehri Dam...")
        evidence = engine.fuse_location_evidence(
            db=db,
            location_id=location_id,
            window_days=40,
            force_recompute=True,
        )

        print("\n" + "=" * 65)
        print("PHASE 3 STATUS: PASS")
        print("=" * 65)

        print(f"SNAPSHOT ID         : {evidence.id}")
        print(f"LOCATION            : {evidence.location_name} ({evidence.location_id})")
        print(f"REFERENCE TIME      : {evidence.reference_time.isoformat()}")
        print(f"EVIDENCE WINDOW     : {evidence.evidence_window_start.strftime('%Y-%m-%d')} to {evidence.evidence_window_end.strftime('%Y-%m-%d')}")

        print("\n" + "-" * 65)
        print("ALIGNED EVIDENCE STREAMS")
        print("-" * 65)

        # 1. Sentinel-1
        s1 = evidence.sentinel1
        print(f"1. SENTINEL-1 SAR   : {'AVAILABLE' if s1.available else 'UNAVAILABLE'}")
        if s1.available:
            print(f"   - T1 / T2 IDs    : {s1.t1_observation_id} -> {s1.t2_observation_id}")
            print(f"   - Orbit Geometry : {s1.orbit_direction} (rel orbit {s1.relative_orbit})")
            print(f"   - Mean Delta VV  : {s1.mean_delta_vv_db} dB | Mean Delta VH: {s1.mean_delta_vh_db} dB")
            print(f"   - Changed Pixels : {s1.changed_percentage}% (VV: {s1.vv_changed_percent}%, VH: {s1.vh_changed_percent}%, Joint: {s1.joint_changed_percent}%)")
            print(f"   - Change Regions : {s1.significant_region_count} contiguous clusters")
            print(f"   - Temporal Align : {s1.temporal_alignment.status} (distance: {s1.temporal_alignment.temporal_distance_hours} hrs)")
            print(f"   - Spatial Align  : {s1.spatial_alignment.spatial_relation} (distance: {s1.spatial_alignment.distance_km} km)")

        # 2. Sentinel-2
        s2 = evidence.sentinel2
        print(f"2. SENTINEL-2 OPT   : {'AVAILABLE' if s2.available else 'UNAVAILABLE'}")
        if s2.available:
            print(f"   - Observation ID : {s2.observation_id} (Cloud cover: {s2.cloud_cover}%)")
            print(f"   - Water Extent   : {s2.water_area_m2:,.1f} m2 (Delta: {s2.water_change_percentage}%)")
            print(f"   - Status         : {s2.optical_change_status}")
            print(f"   - Temporal Align : {s2.temporal_alignment.status} (gap: {s2.temporal_alignment.temporal_distance_hours} hrs)")
            print(f"   - Spatial Align  : {s2.spatial_alignment.spatial_relation}")

        # 3. Rainfall
        rain = evidence.rainfall
        print(f"3. NASA GPM PRECIP  : {'AVAILABLE' if rain.available else 'UNAVAILABLE'}")
        if rain.available:
            print(f"   - Source         : {rain.source}")
            print(f"   - Granules Found : {rain.total_granules_found}")
            print(f"   - Est. Rain (mm) : {rain.estimated_rainfall_mm} mm")
            print(f"   - Temporal Align : {rain.temporal_alignment.status}")

        # 4. Fire
        fire = evidence.fire
        print(f"4. NASA FIRMS FIRE  : {'AVAILABLE' if fire.available else 'NO_ACTIVE_FIRE'}")
        if fire.available:
            print(f"   - Active Fires   : {fire.fire_count} (Max FRP: {fire.max_frp_mw} MW)")
        else:
            print(f"   - Note           : {fire.provenance.get('note', 'No active thermal anomalies detected in window')}")

        # 5. Earthquake
        quake = evidence.earthquake
        print(f"5. USGS SEISMIC     : {'AVAILABLE' if quake.available else 'UNAVAILABLE'}")
        if quake.available:
            print(f"   - Events Found   : {quake.events_found_count} within 150 km")
            if quake.events_found_count > 0:
                print(f"   - Nearest Event  : ID {quake.nearest_event_id} (M{quake.nearest_magnitude}, depth {quake.nearest_depth_km} km at {quake.distance_km} km)")

        # 6. Terrain
        dem = evidence.terrain
        print(f"6. COPERNICUS DEM   : {'AVAILABLE' if dem.available else 'UNAVAILABLE'}")
        if dem.available:
            print(f"   - Tile / Source  : {dem.tile_name} ({dem.source})")
            print(f"   - Elevation / Slp: {dem.elevation_m} m | Slope: {dem.slope_degrees} deg")

        print("\n" + "-" * 65)
        print("DETERMINISTIC EVIDENCE CORRELATIONS")
        print("-" * 65)
        print(f"Total Correlations Identified: {len(evidence.correlations)}")
        for idx, c in enumerate(evidence.correlations, start=1):
            print(f"\n[{idx}] {c.correlation_type} (Confidence: {c.confidence_score})")
            print(f"    - Sources     : {', '.join(c.source_evidence_ids)}")
            print(f"    - Values      : {c.supporting_values}")
            print(f"    - Scientific  : {c.scientific_note}")

        print("\n" + "-" * 65)
        print("DATABASE PERSISTENCE AUDIT")
        print("-" * 65)
        persisted = db.query(EvidenceSnapshot).filter(EvidenceSnapshot.id == evidence.id).first()
        assert persisted is not None
        print(f"Snapshot persisted in 'evidence_snapshots' table: ID={persisted.id}")
        print(f"Active Summary Designations: {evidence.summary_designations}")

        print("\n" + "=" * 65)
        print("PHASE 3 COMPLETE: EVIDENCE FUSION READY FOR STAGE 4 MONITORING")
        print("=" * 65)

    finally:
        db.close()


if __name__ == "__main__":
    run_phase3_verification()
