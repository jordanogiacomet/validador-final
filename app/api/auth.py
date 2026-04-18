from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.core.tenant_loader import resolve_tenant_api_key
from app.services.auth_service import AuthService, IssuedAPIKeyStatus

API_KEY_HEADER = "X-API-Key"
_AUTH_STATE_KEY = "tenant_auth"
_PUBLIC_EXACT_PATHS = {"/", "/health", "/login", "/metrics", "/openapi.json"}
_PUBLIC_PREFIXES = ("/docs", "/redoc")


def _build_auth_service() -> AuthService:
    storage_path = os.getenv("VALIDATOR_API_KEY_STORE_PATH")
    return AuthService(storage_path=Path(storage_path) if storage_path else None)


auth_service = _build_auth_service()


@dataclass(frozen=True)
class AuthenticatedTenant:
    tenant_id: str
    api_key_id: str
    operator_id: str | None = None


def _normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


def _is_public_request(request: Request) -> bool:
    if request.method.upper() == "OPTIONS":
        return True

    normalized_path = _normalize_path(request.url.path)
    if normalized_path in _PUBLIC_EXACT_PATHS:
        return True

    return any(normalized_path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def _auth_error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


async def api_key_auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if _is_public_request(request):
        return await call_next(request)

    api_key = request.headers.get(API_KEY_HEADER, "").strip()
    if not api_key:
        return _auth_error(401, f"Missing {API_KEY_HEADER} header")

    try:
        issued_key = auth_service.inspect_issued_api_key(api_key)
        if issued_key.status is IssuedAPIKeyStatus.MISSING:
            match = resolve_tenant_api_key(api_key)
        else:
            match = None
    except ValueError as exc:
        return _auth_error(500, str(exc))

    if issued_key.status is IssuedAPIKeyStatus.REVOKED:
        return _auth_error(401, issued_key.detail)

    if issued_key.status is IssuedAPIKeyStatus.EXPIRED:
        return _auth_error(401, issued_key.detail)

    if issued_key.status is IssuedAPIKeyStatus.MISSING and match is None:
        return _auth_error(401, "Invalid API key")

    if issued_key.resolved_api_key is not None:
        authenticated_tenant = AuthenticatedTenant(
            tenant_id=issued_key.resolved_api_key.tenant_id,
            api_key_id=issued_key.resolved_api_key.api_key_id,
            operator_id=issued_key.resolved_api_key.operator_id,
        )
    else:
        authenticated_tenant = AuthenticatedTenant(
            tenant_id=match.tenant.tenant_id,
            api_key_id=match.api_key.key_id,
        )

    setattr(
        request.state,
        _AUTH_STATE_KEY,
        authenticated_tenant,
    )
    return await call_next(request)


def get_authenticated_tenant(request: Request) -> AuthenticatedTenant:
    auth = getattr(request.state, _AUTH_STATE_KEY, None)
    if not isinstance(auth, AuthenticatedTenant):
        raise HTTPException(
            status_code=500,
            detail="Authenticated tenant missing from request state",
        )
    return auth


def resolve_request_tenant_id(request: Request, requested_tenant_id: str | None) -> str:
    auth = get_authenticated_tenant(request)
    if requested_tenant_id is not None and requested_tenant_id != auth.tenant_id:
        raise HTTPException(
            status_code=403,
            detail=f"API key does not grant access to tenant '{requested_tenant_id}'",
        )
    return auth.tenant_id
