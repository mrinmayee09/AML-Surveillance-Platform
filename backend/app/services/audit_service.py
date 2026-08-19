"""Append-only audit logging.

Every state change in the platform routes through `record()`. Audit rows are
never updated or deleted, and the writer never trusts a client-supplied actor -
the actor always comes from the verified JWT subject.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog, User


class Actor:
    """Resolved identity of whoever caused an auditable change."""

    def __init__(
        self,
        username: str = "system",
        role: str = "SYSTEM",
        user_id: Optional[int] = None,
        ip_address: str = "127.0.0.1",
        session_id: str = "",
    ):
        self.username = username
        self.role = role
        self.user_id = user_id
        self.ip_address = ip_address
        self.session_id = session_id

    @classmethod
    def from_user(
        cls, user: User, ip_address: str = "127.0.0.1", session_id: str = ""
    ) -> "Actor":
        return cls(
            username=user.username,
            role=user.role,
            user_id=user.id,
            ip_address=ip_address,
            session_id=session_id,
        )

    @classmethod
    def system(cls, name: str = "aml-engine") -> "Actor":
        return cls(username=name, role="SYSTEM", ip_address="internal")


def record(
    db: Session,
    actor: Actor,
    action: str,
    resource_type: str,
    resource_ref: str,
    previous_state: Optional[str] = None,
    new_state: Optional[str] = None,
    detail: str = "",
    context: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[datetime] = None,
) -> AuditLog:
    """Append one audit entry. Caller commits."""
    entry = AuditLog(
        occurred_at=occurred_at or datetime.utcnow(),
        user_id=actor.user_id,
        actor=actor.username,
        actor_role=actor.role,
        action=action,
        resource_type=resource_type,
        resource_ref=resource_ref,
        previous_state=previous_state,
        new_state=new_state,
        detail=detail,
        context=context or {},
        ip_address=actor.ip_address,
        session_id=actor.session_id,
    )
    db.add(entry)
    return entry
