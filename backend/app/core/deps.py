"""FastAPI dependencies: authentication, RBAC and the request actor."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token, role_has_permission
from app.db.base import get_db
from app.models import User
from app.services.audit_service import Actor

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

_UNAUTHORISED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"code": "not_authenticated", "message": "A valid access token is required."},
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve and validate the caller from the Authorization header."""
    if credentials is None or not credentials.credentials:
        raise _UNAUTHORISED

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_token",
                "message": "The access token is invalid or has expired.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    username = payload.get("sub")
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "user_inactive",
                "message": "The account for this token is inactive or no longer exists.",
            },
        )
    return user


def get_actor(
    request: Request,
    user: User = Depends(get_current_user),
) -> Actor:
    """Audit actor derived from the verified token - never from the request body."""
    client_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    session_id = request.headers.get("x-session-id", "")[:64]
    return Actor.from_user(user, ip_address=client_ip, session_id=session_id)


class RequirePermission:
    """Dependency factory enforcing a capability on the caller's role.

    Every protected endpoint re-checks server-side. The permission list the
    frontend receives is only used to hide controls, never to grant access.
    """

    def __init__(self, permission: str):
        self.permission = permission

    def __call__(self, user: User = Depends(get_current_user)) -> User:
        if not role_has_permission(user.role, self.permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "forbidden",
                    "message": (
                        f"Role {user.role} does not have the '{self.permission}' "
                        "capability required for this action."
                    ),
                },
            )
        return user


require_admin = RequirePermission("users:manage")
require_audit_read = RequirePermission("audit:read")
require_rules_write = RequirePermission("rules:write")
require_alerts_update = RequirePermission("alerts:update")
require_investigations_write = RequirePermission("investigations:write")
require_gateway = RequirePermission("gateway:simulate")
require_settings_write = RequirePermission("settings:write")
