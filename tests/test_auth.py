import base64

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.auth import hash_password, verify_password
from api.main import create_app
from config import Settings


def _auth_settings(tmp_path, **overrides):
    kwargs = {
        "auth_enabled": True,
        "auth_username": "admin",
        "auth_password_hash": hash_password("secret"),
        **overrides,
    }
    return Settings(
        _env_file=None,
        counter_source="none",
        db_path=str(tmp_path / "test.db"),
        **kwargs,
    )


def _basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_hash_roundtrip_and_rejects_wrong():
    stored = hash_password("hunter2")
    assert verify_password("hunter2", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("hunter2", "garbage")


def test_hash_is_salted_and_not_plaintext():
    a, b = hash_password("same"), hash_password("same")
    assert a != b  # random salt
    assert "same" not in a


def test_requests_require_credentials_when_enabled(tmp_path):
    with TestClient(create_app(_auth_settings(tmp_path))) as client:
        resp = client.get("/api/status")
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"].startswith("Basic")
        # static dashboard is gated too
        assert client.get("/").status_code == 401


def test_valid_and_invalid_credentials(tmp_path):
    with TestClient(create_app(_auth_settings(tmp_path))) as client:
        assert client.get("/api/status", headers=_basic("admin", "secret")).status_code == 200
        assert client.get("/api/status", headers=_basic("admin", "nope")).status_code == 401
        assert client.get("/api/status", headers=_basic("eve", "secret")).status_code == 401


def test_websocket_rejected_without_credentials(tmp_path):
    with TestClient(create_app(_auth_settings(tmp_path))) as client:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
            pass


def test_websocket_accepts_with_credentials(tmp_path):
    with TestClient(create_app(_auth_settings(tmp_path))) as client:
        with client.websocket_connect("/ws", headers=_basic("admin", "secret")):
            pass  # handshake succeeds


def test_password_hash_survives_env_file_roundtrip(tmp_path):
    # Regression: the dotenv parser must not interpolate the hash. The ":"
    # separator avoids "$" being treated as a variable reference.
    stored = hash_password("s3cr3t")
    env = tmp_path / ".env"
    env.write_text(f"AUTH_ENABLED=true\nAUTH_USERNAME=admin\nAUTH_PASSWORD_HASH={stored}\n")
    settings = Settings(_env_file=str(env))
    assert settings.auth_password_hash == stored
    assert verify_password("s3cr3t", settings.auth_password_hash)


def test_disabled_without_password_hash(tmp_path):
    # auth_enabled but no hash configured -> middleware not installed (open)
    settings = _auth_settings(tmp_path, auth_password_hash="")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/status").status_code == 200
