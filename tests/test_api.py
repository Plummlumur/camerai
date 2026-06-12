from fastapi.testclient import TestClient

from api.main import create_app
from config import Settings


def make_client(tmp_path) -> TestClient:
    settings = Settings(_env_file=None, counter_source="none", db_path=str(tmp_path / "test.db"))
    return TestClient(create_app(settings))


def test_status_starts_empty(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["occupancy"] == 0
    assert body["today_in"] == 0
    assert body["today_out"] == 0
    assert body["sensor_id"] == "raum-1"


def test_status_restores_occupancy_from_events(tmp_path):
    settings = Settings(_env_file=None, counter_source="none", db_path=str(tmp_path / "test.db"))
    from storage.events import EventStore
    from timeutils import utc_now_iso

    store = EventStore(settings.db_path)
    store.add_event(utc_now_iso(), "in", "raum-1")
    store.add_event(utc_now_iso(), "in", "raum-1")
    store.close()
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/status").json()
    assert body["occupancy"] == 2
    assert body["today_in"] == 2


def test_dashboard_is_served(tmp_path):
    with make_client(tmp_path) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Raumzähler" in response.text
