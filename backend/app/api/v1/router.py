"""Aggregates every v1 route module under the /api prefix."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    auth,
    customers,
    investigations,
    networks,
    rules,
    system,
    transactions,
)

api_router = APIRouter()

for module in (
    auth,
    customers,
    transactions,
    alerts,
    networks,
    investigations,
    rules,
    system,
):
    api_router.include_router(module.router)
