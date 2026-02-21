from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from fastapi import Header, HTTPException, status
from sqlalchemy.exc import MultipleResultsFound

from .config import settings
from .db import db_session
from .models import Device


# -----------------------------------------------------------------------------
# Device token hashing
#
# Why not bcrypt?
# - bcrypt has a 72-byte input limit (tokens/JWTs can exceed that).
# - We want deterministic, portable hashing without OS-specific crypto backends.
#
# We use PBKDF2-HMAC-SHA256 with an explicit iteration count.
# Format:
#   pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
# -----------------------------------------------------------------------------


def token_fingerprint(token: str) -> str:
    """Stable lookup key to avoid scanning hashes.

    WARNING: This is not a secret; it's for indexing only.
    """

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def hash_token(token: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = int(settings.token_pbkdf2_iterations)
    dk = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64url(salt)}${_b64url(dk)}"


def verify_token(token: str, token_hash: str) -> bool:
    try:
        parts = token_hash.split("$")
        if len(parts) != 4:
            return False
        scheme, iterations_s, salt_b64, dk_b64 = parts
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        salt = _b64url_decode(salt_b64)
        expected = _b64url_decode(dk_b64)
        got = hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Auth dependencies
# -----------------------------------------------------------------------------


def require_admin(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> None:
    """Admin authorization gate.

    Modes
    - ADMIN_AUTH_MODE=key  (default): require X-Admin-Key and compare with ADMIN_API_KEY
    - ADMIN_AUTH_MODE=none           : trust perimeter (Cloud Run IAM / IAP / VPN)

    NOTE: If ENABLE_ADMIN_ROUTES=false, the admin router is not mounted, so this
    dependency should never be invoked.
    """

    mode = getattr(settings, "admin_auth_mode", "key")
    if mode == "none":
        return

    # Default: shared admin key (local/dev).
    if (
        not x_admin_key
        or not settings.admin_api_key
        or not hmac.compare_digest(x_admin_key, settings.admin_api_key)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


def require_device_auth(authorization: str | None = Header(default=None, alias="Authorization")) -> Device:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization must be Bearer token"
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty bearer token")

    fp = token_fingerprint(token)
    with db_session() as session:
        try:
            device = session.query(Device).filter(Device.token_fingerprint == fp).one_or_none()
        except MultipleResultsFound:
            # A token fingerprint should be unique. If it's not, treat as auth failure.
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")

        if device is None or not verify_token(token, device.token_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")
        if not device.enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device disabled")
        return device
