"""HTTP Basic Auth for the whole app (single shared account).

Passwords are stored hashed with PBKDF2-HMAC-SHA256 (stdlib only) in the format
``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``. Enforcement is coarse: a
single ASGI middleware gates every HTTP and WebSocket request when enabled. The
``require_auth`` dependency stays as a no-op hook for future per-route needs.
"""

import base64
import hashlib
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 200_000
# Field separator. Deliberately ":" not "$": the hash is stored in the .env, and
# "$" would be treated as variable interpolation by the dotenv parser, mangling
# the value. Algorithm name and hex fields never contain ":".
_SEP = ":"


async def require_auth() -> None:
    """Per-route auth hook. Coarse enforcement lives in BasicAuthMiddleware."""
    return None


def hash_password(
    password: str, *, iterations: int = _ITERATIONS, salt: bytes | None = None
) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return _SEP.join((_ALGO, str(iterations), salt.hex(), digest.hex()))


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_str, salt_hex, hash_hex = stored.split(_SEP)
        if algo != _ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iter_str)
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(digest.hex(), hash_hex)


class BasicAuthMiddleware:
    """Reject any HTTP/WebSocket request lacking valid Basic credentials."""

    def __init__(self, app, *, username: str, password_hash: str, realm: str = "Raumzaehler"):
        self.app = app
        self._username = username
        self._password_hash = password_hash
        self._realm = realm

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        if self._authorized(headers.get(b"authorization", b"")):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            # Sending close before accept rejects the handshake.
            await send({"type": "websocket.close", "code": 1008})
            return
        body = b"Unauthorized"
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"www-authenticate", f'Basic realm="{self._realm}"'.encode()),
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    def _authorized(self, header: bytes) -> bool:
        if not header.startswith(b"Basic "):
            return False
        try:
            user, _, password = base64.b64decode(header[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        # Evaluate both sides regardless of the username result to avoid leaking
        # which half was wrong via timing.
        user_ok = secrets.compare_digest(user, self._username)
        password_ok = verify_password(password, self._password_hash)
        return user_ok and password_ok
