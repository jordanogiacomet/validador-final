import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(title="Multi-Tenant Inventory Validator")


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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
