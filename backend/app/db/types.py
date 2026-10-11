"""Timezone handling shared by the ORM and the services.

Rule: every datetime inside the application is timezone-aware UTC.

The database stores naive UTC (portable across SQLite, which has no timezone
support, and PostgreSQL `timestamp without time zone`). `UTCDateTime` is the
boundary: it converts on the way in and re-attaches UTC on the way out, so the
API always emits an explicit offset and clients never have to guess which zone a
timestamp is in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    """Current time as an aware UTC datetime."""
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalise to aware UTC. A naive value is taken to already be UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Naive-UTC storage, aware-UTC in Python."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return as_utc(value).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):  # defensive: raw SQLite text
            value = datetime.fromisoformat(value)
        return as_utc(value)
