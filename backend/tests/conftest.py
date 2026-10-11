"""Test configuration.

Points the app at a throwaway SQLite file BEFORE any `app.*` import, because
the engine is created from settings at import time.
"""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="aml-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ.setdefault("ENVIRONMENT", "development")

import pytest  # noqa: E402

from app.db.base import Base, SessionLocal, engine  # noqa: E402
import app.models  # noqa: E402,F401  (registers every table)


@pytest.fixture()
def db():
    """A fresh, empty schema per test."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
