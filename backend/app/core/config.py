"""Application configuration.

All tunable values are sourced from environment variables (see `.env.example`)
so that no secret or deployment-specific value is ever hard-coded or shipped to
the frontend.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


def _default_sqlite_url() -> str:
    # Defaults are not validated, so normalise here too (creates the folder)
    return _normalise_sqlite_url(
        f"sqlite:///{(PROJECT_ROOT / 'database' / 'aml.db').as_posix()}"
    )


def _normalise_sqlite_url(url: str) -> str:
    """Anchor a relative SQLite path to `backend/` and make sure its folder exists.

    A relative `sqlite:///../database/aml.db` would otherwise resolve against
    whatever directory uvicorn or the seed was launched from, silently creating
    (or failing to open) a different database each time.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw = url[len(prefix):]
    if not raw or raw == ":memory:" or raw.startswith("file:"):
        return url
    path = Path(raw)
    if not path.is_absolute():
        path = (BACKEND_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path.as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ------------------------------------------------------
    app_name: str = "AML Surveillance Platform"
    environment: str = "demo"
    debug: bool = True
    api_v1_prefix: str = "/api"

    # --- Database ---------------------------------------------------------
    database_url: str = Field(default_factory=_default_sqlite_url)

    # --- Security ---------------------------------------------------------
    secret_key: str = "CHANGE_ME_dev_only_secret_key_do_not_use_in_production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    bcrypt_rounds: int = 12

    # --- CORS -------------------------------------------------------------
    # Kept as a plain comma-separated string: a List[str] field makes
    # pydantic-settings JSON-decode the env value before any validator runs,
    # which crashes on the comma-separated form documented in .env.example.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Risk thresholds (0-100) -----------------------------------------
    risk_threshold_medium: int = 35
    risk_threshold_high: int = 60
    risk_threshold_critical: int = 85

    # --- Model artifacts --------------------------------------------------
    ml_model_path: str = "app/ml/artifacts/proactive_rf.joblib"
    gnn_model_path: str = "app/gnn/artifacts/aml_gnn.pt"
    gnn_engine: str = "auto"

    @field_validator("database_url", mode="after")
    @classmethod
    def _anchor_sqlite_path(cls, value: str) -> str:
        return _normalise_sqlite_url(value)

    @property
    def cors_origin_list(self) -> List[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def ml_model_abspath(self) -> Path:
        return (BACKEND_ROOT / self.ml_model_path).resolve()

    @property
    def gnn_model_abspath(self) -> Path:
        return (BACKEND_ROOT / self.gnn_model_path).resolve()

    def risk_level_for(self, score: float) -> str:
        """Map a 0-100 risk score onto the configurable AML risk bands."""
        if score >= self.risk_threshold_critical:
            return "CRITICAL"
        if score >= self.risk_threshold_high:
            return "HIGH"
        if score >= self.risk_threshold_medium:
            return "MEDIUM"
        return "LOW"

    def decision_for(self, level: str) -> str:
        return {
            "LOW": "ALLOW",
            "MEDIUM": "MONITOR",
            "HIGH": "REVIEW",
            "CRITICAL": "BLOCK",
        }.get(level, "REVIEW")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

if settings.is_production and "CHANGE_ME" in settings.secret_key:
    raise RuntimeError(
        "SECRET_KEY must be set to a strong random value when ENVIRONMENT=production"
    )

os.environ.setdefault("PYTHONHASHSEED", "0")
