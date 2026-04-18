import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import api_key_auth_middleware, auth_service
from app.api.middleware import request_id_middleware
from app.api.routes import router
from app.core.health import HealthReport, build_health_report, get_health_status_code
from app.core.logging import configure_logging
from app.core.metrics import (
    get_metrics_content_type,
    metrics_enabled,
    render_metrics,
)
from app.services.auth_service import AuthServiceError

configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        auth_service.bootstrap_admin_from_env()
    except (AuthServiceError, ValueError) as exc:
        raise RuntimeError("Failed to bootstrap the initial administrative operator") from exc
    yield


app = FastAPI(title="Multi-Tenant Inventory Validator", lifespan=lifespan)

app.middleware("http")(request_id_middleware)
app.middleware("http")(api_key_auth_middleware)


def _get_cors_origins() -> list[str]:
    configured_origins = os.getenv(
        "VALIDATOR_FRONTEND_ORIGINS",
        "http://127.0.0.1:3000,http://localhost:3000",
    )
    return [origin.strip() for origin in configured_origins.split(",") if origin.strip()]


def _get_cors_origin_regex() -> str | None:
    configured_regex = os.getenv("VALIDATOR_FRONTEND_ORIGIN_REGEX", "").strip()
    return configured_regex or None


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_origin_regex=_get_cors_origin_regex(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", response_model=HealthReport)
async def health(response: Response) -> HealthReport:
    from app.api import routes as api_routes
    from app.services import validation_service

    report = build_health_report(
        uploads_dir=validation_service.UPLOADS_DIR,
        results_dir=validation_service.RESULTS_DIR,
        job_store_path=api_routes.job_service.storage_path,
    )
    response.status_code = get_health_status_code(report)
    return report


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    if not metrics_enabled():
        raise HTTPException(status_code=404, detail="Metrics endpoint disabled")

    return Response(
        content=render_metrics(),
        headers={"Content-Type": get_metrics_content_type()},
    )
