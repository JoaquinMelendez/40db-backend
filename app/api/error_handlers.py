import logging
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

log = logging.getLogger(__name__)


def _cid(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


def register_handlers(app: FastAPI) -> None:
    from app.domain.errors import DomainError, ExternalServiceError

    @app.exception_handler(httpx.HTTPError)
    async def supabase_http_handler(request: Request, exc: httpx.HTTPError):
        """Errores de red contra Supabase/PostgREST se mapean a 503."""
        cid = _cid(request)
        log.warning("supabase_http_error path=%s cid=%s err=%s",
                    request.url.path, cid, exc.__class__.__name__)
        return JSONResponse(
            status_code=503,
            content={"error": {
                "code": "external_service_error",
                "message": "Servicio externo no disponible.",
                "details": None,
                "correlation_id": cid,
            }},
        )

    @app.exception_handler(DomainError)
    async def domain_handler(request: Request, exc: DomainError):
        cid = _cid(request)
        log.warning("domain_error code=%s path=%s cid=%s", exc.code, request.url.path, cid)
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {
                "code": exc.code,
                "message": str(exc) or "Error de dominio.",
                "details": getattr(exc, "details", None),
                "correlation_id": cid,
            }},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        cid = _cid(request)
        return JSONResponse(
            status_code=422,
            content={"error": {
                "code": "validation_error",
                "message": "Los datos enviados no son válidos.",
                "details": {"fields": exc.errors()},
                "correlation_id": cid,
            }},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        cid = _cid(request)
        log.exception("unhandled_exception path=%s cid=%s", request.url.path, cid)
        return JSONResponse(
            status_code=500,
            content={"error": {
                "code": "internal_error",
                "message": "Error interno del servidor.",
                "details": None,
                "correlation_id": cid,
            }},
        )
