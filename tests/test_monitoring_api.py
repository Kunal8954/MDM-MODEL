"""
Tests for the arbitrary-AOI monitoring API.

The properties that matter most here are that any geometry works, that DEMO and LIVE are
never confused, and that a reported anomaly carries its evidence.
"""

import pytest
from fastapi.testclient import TestClient

from satguard.api.main import app
from satguard.db.session import get_db_session
TEHRI_BBOX = [78.58, 30.28, 78.72, 30.40]
POINT = {"latitude": 30.30, "longitude": 78.60, "radius_m": 1500.0}
POLYGON = [[78.58, 30.28], [78.72, 30.28], [78.72, 30.40], [78.58, 30.40], [78.58, 30.28]]


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client bound to an isolated database, with no side effects on shared state."""
    from sqlalchemy.orm import sessionmaker
    import satguard.api.main as api_main
    from satguard.db.session import create_sqlite_engine
    from satguard.models.entities import Base

    engine = create_sqlite_engine(f"sqlite:///{tmp_path/'test.db'}")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    def _get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    # Entering the TestClient runs the app lifespan, which would otherwise seed the shared
    # database and start the background scheduler for the rest of the test session.
    monkeypatch.setattr(api_main, "init_db", lambda *a, **k: None, raising=False)
    monkeypatch.setattr("satguard.monitoring.scheduler.scheduler.start",
                        lambda *a, **k: None, raising=False)

    app.dependency_overrides[get_db_session] = _get_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


GEOMETRY_KEYS = ("geometry", "point", "bbox", "polygon", "geojson", "place_name")


def _create_area(client, **overrides):
    body = {"bbox": TEHRI_BBOX, "monitoring_mode": "infrastructure",
            "user_label": "Tehri test", "source": "DEMO"}
    body.update(overrides)
    # Supplying one geometry replaces the default rather than adding a second, because
    # build_aoi intentionally rejects ambiguous requests that carry two geometries.
    supplied = [key for key in GEOMETRY_KEYS if key in overrides]
    if supplied:
        for key in GEOMETRY_KEYS:
            if key not in supplied:
                body.pop(key, None)
    response = client.post("/api/aoi", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_any_geometry_type_is_accepted(client):
    """Point, bbox, polygon and GeoJSON must all work; nothing is hard-coded."""
    cases = {
        "point": {"point": POINT},
        "bbox": {"bbox": TEHRI_BBOX},
        "polygon": {"polygon": POLYGON},
        "geojson": {"geojson": {"type": "Polygon", "coordinates": [POLYGON]}},
    }
    for label, override in cases.items():
        area = _create_area(client, **override)
        assert area["id"], label
        assert area["geometry"]["type"] in ("Polygon", "MultiPolygon"), label
        assert area["area_km2"] > 0, label
        assert area["center"]["lon"] and area["center"]["lat"], label


def test_created_area_records_its_provenance(client):
    demo = _create_area(client, source="DEMO")
    assert demo["source"] == "DEMO"

    live = _create_area(client, point=POINT, source="LIVE")
    assert live["source"] == "LIVE"
    assert live["monitoring_mode"] == "infrastructure"


def test_unknown_monitoring_mode_is_rejected_with_the_valid_options(client):
    response = client.post("/api/aoi", json={"bbox": TEHRI_BBOX,
                                              "monitoring_mode": "volcano"})
    assert response.status_code == 422
    assert "glacier" in response.text


def test_area_without_any_geometry_is_rejected(client):
    response = client.post("/api/aoi", json={"monitoring_mode": "general"})
    assert response.status_code == 422
    assert "place_name" in response.text


def test_malformed_geometry_is_rejected_not_stored(client):
    response = client.post("/api/aoi", json={"bbox": [200.0, 0.0, -200.0, 10.0],
                                              "monitoring_mode": "general"})
    assert response.status_code in (422, 400)
    assert client.get("/api/aoi").json()["count"] == 0


def test_areas_can_be_listed_filtered_fetched_and_deleted(client):
    _create_area(client)
    _create_area(client, point={"latitude": 32.0, "longitude": 77.0, "radius_m": 2000.0},
                 monitoring_mode="glacier", source="LIVE")

    everything = client.get("/api/aoi").json()
    assert everything["count"] == 2

    assert client.get("/api/aoi", params={"monitoring_mode": "glacier"}).json()["count"] == 1
    assert client.get("/api/aoi", params={"source": "DEMO"}).json()["count"] == 1

    area_id = everything["areas"][0]["id"]
    assert client.get(f"/api/aoi/{area_id}").status_code == 200
    assert client.delete(f"/api/aoi/{area_id}").status_code == 204
    assert client.get(f"/api/aoi/{area_id}").status_code == 404


def test_monitoring_run_reports_anomalies_with_evidence(client):
    area = _create_area(client)
    response = client.post("/api/monitor", json={
        "area_id": area["id"], "source": "DEMO",
        "demo_scenario": "new_construction", "grid_size": 160,
    })
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["source"] == "DEMO"
    assert body["anomaly_count"] >= 1
    assert body["run_id"]
    assert 0.0 < body["run_confidence"]["detection_confidence"] <= 1.0

    anomaly = body["anomalies"][0]
    for field in ("detection_confidence", "anomaly_confidence", "severity",
                  "evidence", "caveats", "geometry", "area_km2"):
        assert field in anomaly, field
    assert anomaly["evidence"], "an anomaly must carry evidence"
    assert anomaly["geometry"]["type"] in ("Polygon", "MultiPolygon")

    # The DEMO run is scored against the ground truth it was built from.
    assert "demo_truth" in body["provenance"]
    assert body["provenance"]["demo_truth"]["intersection_over_union"] > 0.5


def test_live_run_without_credentials_fails_and_never_returns_demo(client):
    area = _create_area(client)
    response = client.post("/api/monitor", json={"area_id": area["id"], "source": "LIVE"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error_code"] == "LIVE_DATA_UNAVAILABLE"
    # Nothing synthetic may be persisted under a LIVE label.
    assert client.get("/api/anomalies").json()["count"] == 0


def test_unknown_source_is_rejected(client):
    area = _create_area(client)
    response = client.post("/api/monitor", json={"area_id": area["id"], "source": "GUESS"})
    assert response.status_code == 422


def test_monitoring_unknown_area_is_404(client):
    response = client.post("/api/monitor", json={"area_id": "aoi-missing", "source": "DEMO"})
    assert response.status_code == 404


def test_persisted_anomalies_are_retrievable_and_separate_the_confidences(client):
    area = _create_area(client)
    run = client.post("/api/monitor", json={"area_id": area["id"], "source": "DEMO",
                                            "demo_scenario": "new_construction",
                                            "grid_size": 160}).json()

    listing = client.get("/api/anomalies", params={"area_id": area["id"]}).json()
    assert listing["count"] == run["anomaly_count"]
    assert set(listing["summary_by_severity"]) == {
        "none", "low", "moderate", "high", "critical"
    }

    stored = listing["anomalies"][0]
    assert stored["area_id"] == area["id"]
    assert stored["run_id"] == run["run_id"]
    assert stored["source"] == "DEMO"
    # The three quantities are stored and returned separately, never merged.
    assert stored["detection_confidence"] != stored["anomaly_confidence"]
    assert stored["severity"] in ("none", "low", "moderate", "high", "critical")

    detail = client.get(f"/api/anomalies/{stored['id']}").json()
    assert detail["evidence"]
    assert detail["geometry"]["type"] in ("Polygon", "MultiPolygon")


def test_anomaly_filters_work(client):
    area = _create_area(client)
    client.post("/api/monitor", json={"area_id": area["id"], "source": "DEMO",
                                      "demo_scenario": "new_construction",
                                      "grid_size": 160})

    assert client.get("/api/anomalies", params={"severity": "critical"}).json()["count"] >= 0
    assert client.get("/api/anomalies", params={"min_confidence": 1.01}).status_code == 422
    assert client.get("/api/anomalies", params={"source": "LIVE"}).json()["count"] == 0
    assert client.get("/api/anomalies/nope").status_code == 404


def test_demo_site_and_scenario_catalogue_is_explicit_about_synthetic_data(client):
    sites = client.get("/api/demo/sites").json()
    assert sites["source"] == "DEMO"
    assert "not satellite observations" in sites["disclaimer"].lower()
    assert len(sites["sites"]) >= 5

    glacier = client.get("/api/demo/scenarios",
                         params={"monitoring_mode": "glacier"}).json()
    assert glacier["scenarios"] == ["glacier_retreat"]


def test_grid_size_is_bounded(client):
    area = _create_area(client)
    for size in (8, 5000):
        response = client.post("/api/monitor", json={
            "area_id": area["id"], "source": "DEMO", "grid_size": size})
        assert response.status_code == 422, size


def test_deleting_an_area_removes_its_anomalies(client):
    area = _create_area(client)
    client.post("/api/monitor", json={"area_id": area["id"], "source": "DEMO",
                                      "demo_scenario": "new_construction",
                                      "grid_size": 120})
    assert client.get("/api/anomalies", params={"area_id": area["id"]}).json()["count"] >= 1

    client.delete(f"/api/aoi/{area['id']}")
    assert client.get("/api/anomalies", params={"area_id": area["id"]}).json()["count"] == 0