from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live():
    return {"status": "alive"}


@router.get("/health/ready")
async def ready(request: Request):
    checks = {}

    # JWT secret
    from app.core.config import settings
    checks["jwt_secret"] = "ok" if settings.supabase_jwt_secret else "missing"

    # Supabase ping
    try:
        from app.core.supabase_client import get_supabase
        client = get_supabase()
        client.table("tipo_estado").select("id").limit(1).execute()
        checks["supabase"] = "ok"
    except Exception:
        checks["supabase"] = "error"

    # MQTT
    ingestor = getattr(request.app.state, "mqtt_ingestor", None)
    if ingestor is None:
        checks["mqtt"] = "disabled"
    else:
        checks["mqtt"] = ingestor.status()

    all_ok = all(v in ("ok", "disabled") for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if all_ok else "degraded", "checks": checks},
    )
