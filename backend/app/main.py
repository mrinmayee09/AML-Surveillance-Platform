"""FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.db.base import engine, init_db

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("aml")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables and report which engines are actually loaded."""
    init_db()

    from app.gnn.registry import get_gnn_engine
    from app.ml.registry import get_proactive_model

    model = get_proactive_model()
    gnn = get_gnn_engine()

    logger.info("%s v%s starting (%s)", settings.app_name, __version__, settings.environment)
    logger.info("Database: %s", engine.dialect.name)
    logger.info(
        "Proactive model: %s v%s | trained=%s", model.name, model.version, model.trained
    )
    logger.info("Graph engine:    %s v%s | trained=%s", gnn.name, gnn.version, gnn.trained)
    if not model.trained or not gnn.trained:
        logger.warning(
            "One or more models are UNTRAINED and the API reports them as such. "
            "Run `python -m seed.seed` to train them."
        )
    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
    description=(
        "Intelligent AML and financial transaction surveillance platform.\n\n"
        "Three distinct layers: **transaction integrity** (was the request "
        "tampered with?), **proactive AML** (is this customer becoming risky?) and "
        "**reactive AML + GNN** (do settled transactions form a suspicious network?).\n\n"
        "All risk scores are model-generated indicators for human triage. They are "
        "not evidence and do not establish that any offence occurred."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id and timing to every response."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    request.state.request_id = request_id

    response = await call_next(request)

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


# ---------------------------------------------------------------------------
# Error handling: one consistent envelope for every failure
# ---------------------------------------------------------------------------


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", [])[1:]) or None
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "validation_error",
                "message": first.get("msg", "The request payload failed validation."),
                "field": location,
            },
            "request_id": _request_id(request),
            "details": [
                {
                    "field": ".".join(str(p) for p in e.get("loc", [])[1:]),
                    "message": e.get("msg", ""),
                }
                for e in exc.errors()[:10]
            ],
        },
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "database_error",
                "message": "A database error occurred while processing the request.",
            },
            "request_id": _request_id(request),
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    # Internal details are logged, never returned
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred. The incident has been logged.",
            },
            "request_id": _request_id(request),
        },
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/api/health", tags=["system"])
def health():
    """Liveness plus an honest statement of which engines are loaded."""
    from app.gnn.registry import get_gnn_engine
    from app.ml.registry import get_proactive_model

    model = get_proactive_model()
    gnn = get_gnn_engine()
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
        "database": engine.dialect.name,
        "engines": {
            "proactive_model": {
                "name": model.name,
                "type": model.model_type,
                "trained": model.trained,
            },
            "graph_engine": {
                "name": gnn.name,
                "architecture": gnn.architecture,
                "trained": gnn.trained,
            },
        },
    }


@app.get("/", include_in_schema=False)
def root():
    return {
        "app": settings.app_name,
        "version": __version__,
        "docs": "/api/docs",
        "health": "/api/health",
    }
