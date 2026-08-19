"""Authentication and user management endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_actor, get_current_user, require_admin
from app.core.security import hash_password, permissions_for, verify_password
from app.core.security import create_access_token
from app.db.base import get_db
from app.models import User
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserPublic,
    UserUpdate,
)
from app.schemas.common import MessageResponse
from app.services import audit_service
from app.services.audit_service import Actor

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Exchange credentials for a JWT.

    The same generic message is returned for an unknown user and a wrong
    password, so the endpoint cannot be used to enumerate accounts.
    """
    user = db.scalar(select(User).where(User.username == payload.username))
    client_ip = request.client.host if request.client else "unknown"

    if user is None or not verify_password(payload.password, user.password_hash):
        # Log the failure without revealing which half was wrong
        audit_service.record(
            db,
            Actor(username=payload.username, role="UNKNOWN", ip_address=client_ip),
            action="LOGIN_FAILED",
            resource_type="USER",
            resource_ref=payload.username,
            new_state="DENIED",
            detail="Authentication failed.",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Invalid username or password."},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "account_disabled", "message": "This account is disabled."},
        )

    token, expires_at = create_access_token(subject=user.username, role=user.role)
    user.last_login_at = datetime.utcnow()

    audit_service.record(
        db,
        Actor.from_user(user, ip_address=client_ip),
        action="LOGIN_SUCCEEDED",
        resource_type="USER",
        resource_ref=user.username,
        new_state="AUTHENTICATED",
        detail=f"{user.full_name} signed in as {user.role}.",
    )
    db.commit()

    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserPublic.model_validate(user),
        permissions=permissions_for(user.role),
    )


@router.get("/me", response_model=TokenResponse)
def whoami(user: User = Depends(get_current_user)):
    """Re-issue a token for the current session (used to restore state on reload)."""
    token, expires_at = create_access_token(subject=user.username, role=user.role)
    return TokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=UserPublic.model_validate(user),
        permissions=permissions_for(user.role),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
):
    """Record the sign-out.

    Tokens are stateless and simply expire; the client discards it. The audit
    entry is what matters for compliance.
    """
    audit_service.record(
        db,
        actor,
        action="LOGOUT",
        resource_type="USER",
        resource_ref=actor.username,
        new_state="SIGNED_OUT",
        detail="Session ended by the user.",
    )
    db.commit()
    return MessageResponse(message="Signed out.")


# ---------------------------------------------------------------------------
# User administration (ADMIN only)
# ---------------------------------------------------------------------------


@router.get("/users", response_model=List[UserPublic])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    rows = db.scalars(select(User).order_by(User.username)).all()
    return [UserPublic.model_validate(u) for u in rows]


@router.post("/users", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _: User = Depends(require_admin),
):
    existing = db.scalar(
        select(User).where(
            (User.username == payload.username) | (User.email == payload.email)
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "user_exists",
                "message": "A user with that username or email already exists.",
            },
        )

    user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        team=payload.team,
        is_active=True,
    )
    db.add(user)
    db.flush()

    audit_service.record(
        db,
        actor,
        action="USER_CREATED",
        resource_type="USER",
        resource_ref=user.username,
        new_state=user.role,
        detail=f"Created {user.role} account for {user.full_name}.",
    )
    db.commit()
    return UserPublic.model_validate(user)


@router.patch("/users/{username}", response_model=UserPublic)
def update_user(
    username: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    admin: User = Depends(require_admin),
):
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": f"No user named {username}."},
        )

    if user.id == admin.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "self_disable",
                "message": "You cannot disable your own account.",
            },
        )

    previous_role = user.role
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.flush()

    audit_service.record(
        db,
        actor,
        action="USER_UPDATED",
        resource_type="USER",
        resource_ref=user.username,
        previous_state=previous_role,
        new_state=user.role,
        detail=f"Updated account for {user.full_name}.",
    )
    db.commit()
    return UserPublic.model_validate(user)
