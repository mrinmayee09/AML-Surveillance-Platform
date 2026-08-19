"""Shared response envelopes and primitives."""

from __future__ import annotations

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    """Standard paginated collection envelope."""

    items: List[T]
    total: int = Field(description="Total rows matching the filter, ignoring pagination")
    page: int = 1
    page_size: int = 50
    pages: int = 1


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: Optional[str] = None


class MessageResponse(BaseModel):
    message: str


class RiskFactor(BaseModel):
    """One additive contribution to an explainable risk score."""

    code: str
    label: str
    contribution: float = Field(description="Points added to the 0-100 score")
    detail: str = ""
    # Which family the signal came from: BEHAVIOURAL, VELOCITY, NETWORK, GEO, KYC
    category: str = "BEHAVIOURAL"


class ModelProvenance(BaseModel):
    """Honest description of what produced a score."""

    model_name: str
    model_version: str
    model_type: str
    trained: bool = Field(
        description="True only when a real fitted artifact produced this output"
    )
    training_data: str = Field(
        description="What the model was fitted on, in plain language"
    )
    notes: str = ""


class TimePoint(BaseModel):
    label: str
    value: float


class Bucket(BaseModel):
    key: str
    label: str
    count: int
    value: float = 0.0
