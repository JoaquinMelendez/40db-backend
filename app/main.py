import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    if settings.mqtt_enabled:
        from app.infrastructure.mqtt.ingestor import MqttIngestor
        ingestor = MqttIngestor()
        app.state.mqtt_ingestor = ingestor
        ingestor.start()
        log.info("MQTT ingestor arrancado")
    else:
        app.state.mqtt_ingestor = None
        log.info("MQTT deshabilitado (vars no configuradas)")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    if app.state.mqtt_ingestor:
        app.state.mqtt_ingestor.stop()
        log.info("MQTT ingestor detenido")


app = FastAPI(title="40dB API", version="1.0.0", lifespan=lifespan)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-Id", "Idempotency-Key"],
    allow_credentials=False,
)

# ── Middleware y handlers (se registran en los pasos siguientes) ───────────────
# Los imports se hacen aquí para que el arranque falle explícitamente si algo falta.
from app.api.middleware.correlation import CorrelationMiddleware
from app.api.error_handlers import register_handlers
from app.api.routes import health
from app.api.routes import reportes, heatmaps, usuarios, catalogos, sensores, reportes_admin_archivos

app.add_middleware(CorrelationMiddleware)
register_handlers(app)

app.include_router(health.router)
app.include_router(reportes.router, prefix=settings.api_prefix)
app.include_router(heatmaps.router, prefix=settings.api_prefix)
app.include_router(usuarios.router, prefix=settings.api_prefix)
app.include_router(catalogos.router, prefix=settings.api_prefix)
app.include_router(sensores.router, prefix=settings.api_prefix)
app.include_router(reportes_admin_archivos.router, prefix=settings.api_prefix)
