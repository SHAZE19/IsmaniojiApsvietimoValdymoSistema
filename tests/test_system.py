import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from backend.main import create_app

PASSWORD = "Test-admin-password-2026"
KEY = "test-device-key-" + "a" * 32
BROWSER = {"X-Requested-With": "LightingApp"}
DEVICE = {"X-Device-Key": KEY}


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv("LIGHTING_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("LIGHTING_DEVICE_KEY", KEY)
    with TestClient(create_app(tmp_path)) as client:
        yield client, tmp_path


def login(client, username="admin", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=BROWSER)


def register(client, uid="A1B2C3D4", owner=1):
    return client.post("/api/cards", json={"card_id": uid, "label": "Darbo kortelė", "user_id": owner}, headers=BROWSER)


def scan(client, uid="A1B2C3D4"):
    return client.post("/api/nfc/authorize", json={"card_id": uid}, headers=DEVICE)


def idle(path, seconds):
    with sqlite3.connect(path / "lighting.sqlite3") as conn:
        conn.execute("UPDATE lighting SET last_activity=? WHERE id=1", (time.time() - seconds,))


def test_home_and_private_routes(system):
    client, _ = system
    home = client.get("/")
    assert home.status_code == 200 and 'lang="lt"' in home.text
    assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
    for route in ["/api/lighting", "/api/cards", "/api/users", "/api/events", "/api/settings"]:
        assert client.get(route).status_code == 401
    assert client.get("/static/../backend/data/device-secret.txt").status_code == 404


def test_auth_session_logout_and_csrf(system):
    client, _ = system
    assert client.post("/api/auth/login", json={"username":"admin", "password":PASSWORD}).status_code == 403
    result = login(client)
    assert result.status_code == 200
    cookie = result.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert client.get("/api/auth/me").json()["role"] == "admin"
    assert client.put("/api/lighting", json={"mode":"on"}).status_code == 403
    assert client.post("/api/auth/logout", headers=BROWSER).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_login_rate_limit_and_audit(system):
    client, path = system
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    assert login(client).status_code == 429
    with sqlite3.connect(path / "lighting.sqlite3") as conn:
        assert conn.execute("SELECT COUNT(*) FROM events WHERE kind='login_denied'").fetchone()[0] == 5


def test_device_requires_separate_secret(system):
    client, _ = system
    login(client)
    assert client.post("/api/nfc/authorize", json={"card_id":"A1B2C3D4"}).status_code == 401
    assert client.get("/api/device/state").status_code == 401
    assert client.post("/api/device/telemetry", json={"motion":True,"actual_brightness":100}).status_code == 401
    assert client.get("/api/device/state", headers=DEVICE).status_code == 200


def test_nfc_and_automatic_dimming_off(system):
    client, path = system
    login(client)
    assert register(client).status_code == 201
    assert scan(client, "99999999").json()["authorized"] is False
    granted = scan(client, " a1b2c3d4 ").json()
    assert granted["authorized"] and granted["desired_brightness"] == 100
    assert client.get("/api/lighting").json()["actual_brightness"] is None
    idle(path, 65)
    assert client.get("/api/lighting").json()["stage"] == "dimmed"
    assert client.get("/api/device/state", headers=DEVICE).json()["desired_brightness"] == 25
    idle(path, 125)
    assert client.get("/api/lighting").json()["desired_brightness"] == 0
    # PIR alone cannot grant a new session after the lights turn off.
    result = client.post("/api/device/telemetry", headers=DEVICE, json={"motion":True,"actual_brightness":0}).json()
    assert result["desired_brightness"] == 0


def test_motion_extends_active_session_and_tracks_confirmed_state(system):
    client, path = system
    login(client); register(client); scan(client)
    idle(path, 80)
    result = client.post("/api/device/telemetry", headers=DEVICE, json={"motion":True,"actual_brightness":25}).json()
    assert result["desired_brightness"] == 100
    current = client.get("/api/lighting").json()
    assert current["online"] and current["motion"] and current["actual_brightness"] == 25
    for _ in range(3):
        client.post("/api/device/telemetry", headers=DEVICE, json={"motion":True,"actual_brightness":100})
    events = client.get("/api/events?kind=motion").json()
    assert len(events) == 1


def test_manual_commands_and_nfc_override(system):
    client, path = system
    login(client); register(client)
    result = client.put("/api/lighting", headers=BROWSER, json={"mode":"on","brightness":70}).json()
    assert result["desired_brightness"] == 70 and result["remaining_seconds"] is None
    idle(path, 1000)
    assert client.get("/api/lighting").json()["desired_brightness"] == 70
    client.put("/api/lighting", headers=BROWSER, json={"mode":"off"})
    assert client.get("/api/lighting").json()["desired_brightness"] == 0
    assert scan(client).json()["mode"] == "auto"
    client.put("/api/lighting", headers=BROWSER, json={"mode":"auto"})
    assert client.get("/api/lighting").json()["desired_brightness"] == 0


def test_card_lifecycle_and_duplicate_validation(system):
    client, _ = system
    login(client)
    assert register(client).status_code == 201
    assert register(client).status_code == 409
    assert register(client, "not-a-card").status_code == 422
    assert register(client, "11223344", 999).status_code == 400
    scan(client)
    assert client.patch("/api/cards/A1B2C3D4", headers=BROWSER, json={"enabled":False}).status_code == 200
    assert scan(client).json()["authorized"] is False
    assert client.get("/api/lighting").json()["desired_brightness"] == 0
    client.patch("/api/cards/A1B2C3D4", headers=BROWSER, json={"enabled":True})
    assert scan(client).json()["authorized"] is True
    client.delete("/api/cards/A1B2C3D4", headers=BROWSER)
    assert scan(client).json()["authorized"] is False
    assert client.delete("/api/cards/A1B2C3D4", headers=BROWSER).status_code == 404


def test_user_role_and_disabling_revokes_sessions_and_cards(system):
    client, _ = system
    login(client)
    result = client.post("/api/users", headers=BROWSER, json={"username":"jonas","display_name":"Jonas","password":"User-password-1234"})
    assert result.status_code == 201
    uid = result.json()["id"]
    register(client, owner=uid)
    admin_token = client.cookies.get("lighting_session")
    login(client, "jonas", "User-password-1234")
    user_token = client.cookies.get("lighting_session")
    for path in ["/api/users", "/api/cards", "/api/events", "/api/settings"]:
        assert client.get(path).status_code == 403
    assert client.put("/api/lighting", headers=BROWSER, json={"mode":"on"}).status_code == 200
    scan(client)
    client.cookies.set("lighting_session", admin_token)
    assert client.patch(f"/api/users/{uid}", headers=BROWSER, json={"enabled":False}).status_code == 200
    assert scan(client).json()["authorized"] is False
    client.cookies.set("lighting_session", user_token)
    assert client.get("/api/lighting").status_code == 401


def test_settings_and_input_bounds(system):
    client, _ = system
    login(client)
    assert client.put("/api/settings", headers=BROWSER, json={"dim_after_seconds":20,"off_after_seconds":10,"dim_brightness":25}).status_code == 422
    assert client.put("/api/settings", headers=BROWSER, json={"dim_after_seconds":10,"off_after_seconds":30,"dim_brightness":15}).status_code == 200
    assert client.get("/api/device/state", headers=DEVICE).json()["dim_after_seconds"] == 10
    assert client.put("/api/lighting", headers=BROWSER, json={"mode":"on","brightness":101}).status_code == 422
    assert client.post("/api/device/telemetry", headers=DEVICE, json={"motion":"yes","actual_brightness":10}).status_code == 422
    assert client.patch("/api/users/1", headers=BROWSER, json={"enabled":False}).status_code == 400
    assert client.get("/api/events?limit=10000").status_code == 422


def test_increasing_timeout_does_not_revive_expired_session(system):
    client, path = system
    login(client); register(client); scan(client)
    idle(path, 130)
    result = client.put("/api/settings", headers=BROWSER, json={"dim_after_seconds":200,"off_after_seconds":300,"dim_brightness":25})
    assert result.status_code == 200
    assert client.get("/api/lighting").json()["desired_brightness"] == 0


def test_data_persists_after_restart(system):
    client, path = system
    login(client); register(client)
    with TestClient(create_app(path)) as restarted:
        login(restarted)
        assert restarted.get("/api/cards").json()[0]["card_id"] == "A1B2C3D4"
        assert scan(restarted).json()["authorized"]
    with sqlite3.connect(path / "lighting.sqlite3") as conn:
        encoded = conn.execute("SELECT password_hash FROM users WHERE id=1").fetchone()[0]
        assert PASSWORD not in encoded


def test_event_pagination_and_stale_device(system):
    client, path = system
    login(client)
    for _ in range(4): scan(client, "99999999")
    page1 = client.get("/api/events?limit=2&kind=nfc_denied").json()
    page2 = client.get(f"/api/events?limit=2&kind=nfc_denied&before_id={page1[-1]['id']}").json()
    assert len({r["id"] for r in page1+page2}) == 4
    client.post("/api/device/telemetry", headers=DEVICE, json={"motion":True,"actual_brightness":0})
    with sqlite3.connect(path / "lighting.sqlite3") as conn:
        conn.execute("UPDATE lighting SET last_seen=? WHERE id=1", (time.time()-20,))
    current = client.get("/api/lighting").json()
    assert not current["online"] and not current["motion"]
