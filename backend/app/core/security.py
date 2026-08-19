"""Password hashing, JWT issuance/verification and role helpers.

Passwords are hashed with bcrypt (per-password random salt). Plaintext
passwords are never stored, logged or returned by the API.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

ROLE_ANALYST = "ANALYST"
ROLE_ADMIN = "ADMIN"
ROLES = (ROLE_ANALYST, ROLE_ADMIN)

# Capability matrix - kept server-side. The frontend receives the resolved
# permission list only so it can hide controls; every endpoint re-checks.
ROLE_PERMISSIONS: Dict[str, list[str]] = {
    ROLE_ANALYST: [
        "transactions:read",
        "customers:read",
        "alerts:read",
        "alerts:update",
        "networks:read",
        "investigations:read",
        "investigations:write",
        "rules:read",
        "models:read",
        "gateway:simulate",
    ],
    ROLE_ADMIN: [
        "transactions:read",
        "customers:read",
        "alerts:read",
        "alerts:update",
        "networks:read",
        "investigations:read",
        "investigations:write",
        "rules:read",
        "rules:write",
        "models:read",
        "gateway:simulate",
        "users:manage",
        "audit:read",
        "settings:write",
    ],
}


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str, role: str, expires_delta: Optional[timedelta] = None
) -> tuple[str, datetime]:
    expire_at = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": expire_at,
        "iss": settings.app_name,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expire_at


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require_sub": True},
        )
    except JWTError:
        return None


def permissions_for(role: str) -> list[str]:
    return list(ROLE_PERMISSIONS.get(role.upper(), []))


def role_has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role.upper(), [])
