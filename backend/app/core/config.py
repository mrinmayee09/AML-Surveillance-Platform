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
    db_dir = PROJECT_ROOT / "database"
    db_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(db_dir / 'aml.db').as_posix()}"


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
    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Risk thresholds (0-100) -----------------------------------------
    risk_threshold_medium: int = 35
    risk_threshold_high: int = 60
    risk_threshold_critical: int = 85

    # --- Model artifacts --------------------------------------------------
    ml_model_path: str = "app/ml/artifacts/proactive_rf.joblib"
    gnn_model_path: str = "app/gnn/artifacts/aml_gnn.pt"
    gnn_engine: str = "auto"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
