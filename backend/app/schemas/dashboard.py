"""Dashboard, rules, model-insight and demo schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ModelProvenance, ORMModel


class Kpi(BaseModel):
    key: str
    label: str
    value: float
    display: str
    delta_pct: Optional[float] = None
    # up | down | flat  (direction of change, not a judgement)
    direction: str = "flat"
    # good | bad | neutral - whether the direction is desirable
    sentiment: str = "neutral"
    hint: str = ""


class SeriesPoint(BaseModel):
    bucket: str
    label: str
    total: float = 0.0
    low: float = 0.0
    medium: float = 0.0
    high: float = 0.0
    critical: float = 0.0
    alerts: float = 0.0
    volume: float = 0.0
    suspicious_pct: float = 0.0
    avg_risk: float = 0.0


class GeoRisk(BaseModel):
    region: str
    country: str
    transactions: int
    volume: float
    high_risk_count: int
    avg_risk: float
    risk_level: str


class DashboardOverview(BaseModel):
    window: str
    generated_at: datetime
    kpis: List[Kpi]
    risk_distribution: List[Dict[str, Any]]
    series: List[SeriesPoint]
    geo_risk: List[GeoRisk]
    channel_breakdown: List[Dict[str, Any]]
    top_alerts: List[Dict[str, Any]]
    suspicious_networks: List[Dict[str, Any]]
    pipeline_health: List[Dict[str, Any]]
    advisory: str


# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------


class RuleOut(ORMModel):
    id: int
    code: str
    name: str
    description: str
    category: str
    severity: str
    layer: str
    enabled: bool
    threshold: float
    operator: str
    threshold_unit: str
    score_weight: float
    params: Dict[str, Any] = {}
    triggered_count: int


class RuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    threshold: Optional[float] = Field(default=None, ge=0)
    score_weight: Optional[float] = Field(default=None, ge=0, le=100)
    severity: Optional[str] = Field(default=None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")


class RuleCreate(BaseModel):
    code: str = Field(min_length=3, max_length=48, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=3, max_length=128)
    description: str = Field(default="", max_length=1000)
    category: str = Field(default="BEHAVIOURAL", max_length=32)
    severity: str = Field(default="MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")
    layer: str = Field(default="REACTIVE", pattern="^(PROACTIVE|REACTIVE|NETWORK|INTEGRITY)$")
    threshold: float = Field(default=0.0, ge=0)
    operator: str = Field(default="GTE", pattern="^(GT|GTE|LT|LTE|EQ)$")
    threshold_unit: str = Field(default="", max_length=24)
    score_weight: float = Field(default=10.0, ge=0, le=100)
    params: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Model insights
# ---------------------------------------------------------------------------


class ClassificationMetrics(BaseModel):
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: Optional[float] = None
    support: int
    confusion_matrix: List[List[int]]
    labels: List[str]


class FeatureImportance(BaseModel):
    feature: str
    label: str
    importance: float
    description: str = ""


class ProactiveModelCard(BaseModel):
    provenance: ModelProvenance
    purpose: str
    algorithm: str
    hyperparameters: Dict[str, Any]
    feature_count: int
    features: List[FeatureImportance]
    metrics: Optional[ClassificationMetrics] = None
    trained_at: Optional[datetime] = None
    training_rows: int = 0
    class_balance: Dict[str, int] = {}
    caveats: List[str] = []


class GnnModelCard(BaseModel):
    provenance: ModelProvenance
    purpose: str
    architecture: str
    graph_summary: Dict[str, Any]
    tasks: List[Dict[str, str]]
    hyperparameters: Dict[str, Any] = {}
    metrics: Optional[Dict[str, Any]] = None
    trained_at: Optional[datetime] = None
    signal_vocabulary: List[Dict[str, str]] = []
    caveats: List[str] = []


class ModelInsightsResponse(BaseModel):
    proactive: ProactiveModelCard
    gnn: GnnModelCard
    honesty_statement: str


# ---------------------------------------------------------------------------
# Demo orchestration
# ---------------------------------------------------------------------------


class DemoRunRequest(BaseModel):
    scenario: str = Field(default="LAYERED_RING", max_length=48)
    claimed_amount: Optional[float] = Field(default=None, gt=0)


class DemoStep(BaseModel):
    index: int
    key: str
    title: str
    layer: str
    status: str
    summary: str
    detail: Dict[str, Any] = {}
    # Where in the UI the investigator can go to see this for themselves
    route: Optional[str] = None
    duration_ms: float = 0.0


class DemoRunResponse(BaseModel):
    run_ref: str
    scenario: str
    started_at: datetime
    finished_at: datetime
    steps: List[DemoStep]
    outcome: Dict[str, Any]
    advisory: str


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class ThresholdSettings(BaseModel):
    medium: int = Field(ge=1, le=99)
    high: int = Field(ge=2, le=99)
    critical: int = Field(ge=3, le=100)


class SystemSettings(BaseModel):
    app_name: str
    environment: str
    thresholds: ThresholdSettings
    database_engine: str
    ml_engine: Dict[str, Any]
    gnn_engine: Dict[str, Any]
    roles: Dict[str, List[str]]
    version: str
