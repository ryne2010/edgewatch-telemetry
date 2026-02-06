from __future__ import annotations

import hashlib

from fastapi import Header, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import settings
from .db import db_session
from .models import Device

# NOTE: Device tokens may exceed bcrypt's 72-byte input limit (e.g., long random strings or JWTs).
# Use PBKDF2 instead to avoid truncation and backend/version issues with bcrypt wheels.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    return pwd_context.hash(token)


def verify_token(token: str, token_hash: str) -> bool:
    try:
        return pwd_context.verify(token, token_hash)
    except Exception:
        return False


def require_admin(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> None:
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")


def require_device_auth(authorization: str | None = Header(default=None, alias="Authorization")) -> Device:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization must be Bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty bearer token")

    fp = token_fingerprint(token)
    with db_session() as session:
        device = session.query(Device).filter(Device.token_fingerprint == fp).one_or_none()
        if device is None or not verify_token(token, device.token_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device token")
        if not device.enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Device disabled")
        return device
