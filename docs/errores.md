# Errores y salud — 40dB

Documento autoritativo de **manejo de errores** del backend 40dB. Define la jerarquía de excepciones de dominio, su mapeo a HTTP, el shape uniforme de la respuesta de error, la política frente a dependencias externas caídas y los health checks. Cualquier endpoint nuevo debe respetar lo definido acá.

**Documentos relacionados:**
- [`api.md`](./api.md) — qué status code lanza cada endpoint.
- [`backend.md`](./backend.md) §6 — patrones (Strategy / Observer) que pueden generar errores específicos.
- [`auth.md`](./auth.md) §11 — resumen del mapeo de auth, expandido acá.

---

## 1. Principios

| # | Decisión | Justificación |
|---|---|---|
| E1 | **Excepciones de dominio en `app/domain/errors.py`**, no en cada use case | Centralizadas, importables sin ciclos, fáciles de mapear en un solo lugar. |
| E2 | **Mapeo a HTTP en un único exception handler** registrado en `app/main.py` | Un solo lugar que sabe traducir excepciones a respuestas. Los use cases lanzan, no se preocupan del HTTP. |
| E3 | **Shape uniforme de respuesta de error** (sección 4) | Frontend siempre sabe cómo parsear el error. Sin sorpresas. |
| E4 | **Fallar fuerte ante dependencias críticas caídas** (Supabase, JWT secret) en startup | Mejor crash en boot que servir un proceso roto. Health checks lo reflejan. |
| E5 | **MQTT caído NO es fatal** para el proceso HTTP | El ingestor IoT corre en task aparte; si crashea, FastAPI sigue sirviendo HTTP. El lifespan lo reintenta con backoff. |
| E6 | **Logs estructurados (JSON)** con `correlation_id` por request | Trazabilidad sin necesidad de stack traces en producción. |

---

## 2. Jerarquía de excepciones de dominio

Definidas en `app/domain/errors.py`. Todas heredan de `DomainError`. **Ningún use case lanza `HTTPException` directamente** — eso es responsabilidad del handler.

```python
class DomainError(Exception):
    """Base. Toda excepción de dominio hereda de acá."""
    code: str           # identificador estable para el frontend, ej. "reporte_not_found"
    http_status: int    # status code default; el handler lo respeta salvo override

class NotFoundError(DomainError):
    http_status = 404
    code = "not_found"

class UnauthorizedError(DomainError):
    """Falta auth o el usuario no existe."""
    http_status = 401
    code = "unauthorized"

class ForbiddenError(DomainError):
    """Auth válida pero el rol/comuna no permite la acción."""
    http_status = 403
    code = "forbidden"

class ValidationError(DomainError):
    """Datos de entrada inconsistentes con reglas de negocio
    (no con el schema Pydantic — esas las maneja FastAPI con 422)."""
    http_status = 409
    code = "validation_error"

class InvalidStateTransitionError(ValidationError):
    """Intento de pasar un reporte por una transición no permitida."""
    code = "invalid_state_transition"

class ExternalServiceError(DomainError):
    """Supabase / MQTT / cualquier dependencia externa falló."""
    http_status = 503
    code = "external_service_error"

class ConflictError(DomainError):
    """Recurso ya existe / violación de UNIQUE."""
    http_status = 409
    code = "conflict"
```

**Subtipos específicos** se crean cuando el frontend necesita distinguirlos. Ejemplos:

```python
class ReporteNotFoundError(NotFoundError):
    code = "reporte_not_found"

class UsuarioNotFoundError(NotFoundError):
    code = "usuario_not_found"

class ComunaMismatchError(ForbiddenError):
    """Funcionario intenta actuar sobre reporte de otra comuna."""
    code = "comuna_mismatch"

class InvalidTokenError(UnauthorizedError):
    code = "invalid_token"
```

Si el código en el frontend hace `if (err.code === 'comuna_mismatch')`, vale la pena un subtipo. Si no, alcanza con el padre.

---

## 3. Mapeo HTTP

| HTTP | Cuándo | Excepción típica |
|---|---|---|
| **400 Bad Request** | Body inválido a nivel **sintáctico** (JSON mal formado) | FastAPI lo emite, no nosotros |
| **401 Unauthorized** | JWT ausente, inválido, expirado, o usuario inactivo | `UnauthorizedError`, `InvalidTokenError` |
| **403 Forbidden** | JWT válido pero rol/comuna insuficiente | `ForbiddenError`, `ComunaMismatchError` |
| **404 Not Found** | Recurso inexistente | `NotFoundError` y subtipos |
| **409 Conflict** | Estado inválido o duplicado | `ValidationError`, `ConflictError`, `InvalidStateTransitionError` |
| **422 Unprocessable Entity** | Body parseable pero falla validación Pydantic | FastAPI lo emite automáticamente |
| **429 Too Many Requests** | Rate limit (futuro, no implementado en MVP) | — |
| **500 Internal Server Error** | Excepción no manejada | Cualquier `Exception` no-`DomainError` |
| **503 Service Unavailable** | Dependencia externa caída (Supabase, MQTT) | `ExternalServiceError` |

**Regla:** ningún use case decide su status code mirando flags. Lanza la excepción semántica y el handler resuelve.

---

## 4. Shape uniforme de respuesta de error

```json
{
  "error": {
    "code": "reporte_not_found",
    "message": "El reporte solicitado no existe o fue eliminado.",
    "details": null,
    "correlation_id": "01HF8K..."
  }
}
```

Campos:

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `error.code` | `string` | ✅ | Identificador estable, snake_case, **no traducible**. Usado por el frontend para branching lógico. |
| `error.message` | `string` | ✅ | Mensaje en español, legible por humanos. Puede traducirse el día que haya i18n. |
| `error.details` | `object \| null` | — | Info extra estructurada cuando aplica (ej. lista de campos inválidos en un 422). |
| `error.correlation_id` | `string` | ✅ | ULID/UUID que matchea el log del backend. El cliente lo incluye al reportar bugs. |

**Para errores Pydantic (422)**, `details` lleva el formato estándar de FastAPI:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Los datos enviados no son válidos.",
    "details": {
      "fields": [
        { "loc": ["body", "latitud"], "msg": "value is not a valid float", "type": "type_error.float" }
      ]
    },
    "correlation_id": "01HF8K..."
  }
}
```

---

## 5. Exception handler

Registrado en `app/main.py`. Sketch:

```python
# app/api/error_handlers.py (esquemático)
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.domain.errors import DomainError
import logging, ulid

log = logging.getLogger(__name__)

async def domain_exception_handler(request: Request, exc: DomainError):
    cid = request.state.correlation_id
    log.warning("domain_error", extra={
        "code": exc.code, "message": str(exc),
        "correlation_id": cid, "path": request.url.path,
    })
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {
            "code": exc.code,
            "message": str(exc) or "Error de dominio.",
            "details": getattr(exc, "details", None),
            "correlation_id": cid,
        }},
    )

async def unhandled_exception_handler(request: Request, exc: Exception):
    cid = request.state.correlation_id
    log.exception("unhandled_exception", extra={
        "correlation_id": cid, "path": request.url.path,
    })
    return JSONResponse(
        status_code=500,
        content={"error": {
            "code": "internal_error",
            "message": "Error interno del servidor.",
            "details": None,
            "correlation_id": cid,
        }},
    )
```

El handler para `RequestValidationError` (Pydantic) reescribe el body default de FastAPI al shape uniforme.

---

## 6. Correlation ID middleware

Cada request entrante recibe un `correlation_id`. Si el cliente lo envía en header `X-Correlation-Id`, se respeta; si no, se genera (ULID).

```python
# app/api/middleware/correlation.py (esquemático)
class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cid = request.headers.get("X-Correlation-Id") or str(ulid.new())
        request.state.correlation_id = cid
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = cid
        return response
```

Todo log emitido durante el request incluye `correlation_id` en el extra.

---

## 7. Dependencias externas: política de fallo

### 7.1 Supabase / Postgres

- **Boot**: si `service_role_key` o `JWT_SECRET` faltan → crash en startup (no servir nada).
- **Runtime, dos capas de defensa:**
  1. Los repositories que envuelven calls a `supabase-py` atrapan excepciones esperadas y relanzan `ExternalServiceError` → HTTP 503.
  2. Como red de seguridad, hay un handler global para `httpx.HTTPError` (registrado en `app/api/error_handlers.py`) que captura cualquier error de red al PostgREST que se haya escapado de un repo. Cubre código que llama directo a `get_supabase()` (rutas de catálogos, helpers) sin tener que envolver cada call.
- **Reintentos**: **no se reintenta automáticamente** en MVP. Falla rápido y deja que el cliente reintente si quiere. Roadmap: backoff exponencial con `tenacity` para queries idempotentes (`GET`).

### 7.2 MQTT (HiveMQ)

- **Boot**: si las credenciales MQTT faltan, el ingestor se loguea como "deshabilitado" y FastAPI **sigue arrancando** (modo HTTP-only).
- **Runtime**: si la conexión MQTT se cae, el ingestor reintenta con backoff exponencial (`paho-mqtt` lo soporta nativo). Mientras tanto, se loguea cada fallo de reconexión y se expone en `/health/ready`.
- **Mensaje malformado**: se descarta (log a nivel WARNING con el payload truncado) y se continúa. No tumba el ingestor.
- Detalle del lifecycle en [`iot.md`](./iot.md).

### 7.3 Validación JWT

- JWT inválido / expirado → 401 `InvalidTokenError`. No se intenta refresh desde el backend (eso es del cliente).
- Si el secret está mal configurado, **todo request autenticado falla con 401** — health check `/health/ready` debe detectarlo.

---

## 8. Health checks

Dos endpoints, ambos públicos (sin auth):

### 8.1 `GET /health/live`
- **Qué verifica:** que el proceso responda. Nada más.
- **Response 200:** `{"status": "alive"}`.
- **Uso:** liveness probe del orquestador (k8s, Render, etc.). Si falla, reiniciar el proceso.

### 8.2 `GET /health/ready`
- **Qué verifica:** que las dependencias necesarias estén disponibles.
  - Ping a Supabase (`SELECT 1` con timeout corto, ~1s).
  - Estado del cliente MQTT (`connected | reconnecting | disabled`).
  - JWT secret cargado.
- **Response 200** si todo OK:
  ```json
  {
    "status": "ready",
    "checks": {
      "supabase": "ok",
      "mqtt": "ok",
      "jwt_secret": "ok"
    }
  }
  ```
- **Response 503** si algo falla, listando qué falló:
  ```json
  {
    "status": "degraded",
    "checks": {
      "supabase": "ok",
      "mqtt": "reconnecting",
      "jwt_secret": "ok"
    }
  }
  ```
- **Uso:** readiness probe. Si falla, el orquestador deja de mandar tráfico hasta que mejore.

> **Nota:** `mqtt: "disabled"` y `mqtt: "reconnecting"` no son fatales para el HTTP — el endpoint `/reportes` y `/heatmaps` funcionan igual. El check los reporta para visibilidad operativa.

---

## 9. Logging

- **Formato**: JSON. Una línea por evento. Sin colores en producción.
- **Niveles**:
  - `DEBUG`: solo en local.
  - `INFO`: requests recibidos, lecturas IoT procesadas, decisiones de negocio relevantes (ej. "reporte adjunto evidencia X").
  - `WARNING`: errores de dominio (4xx que el cliente puede corregir), payloads MQTT malformados.
  - `ERROR`: 5xx, excepciones no manejadas, fallos persistentes de dependencias.
- **Campos estándar**: `timestamp`, `level`, `event`, `correlation_id`, `path`, `method`, `user_id` (si autenticado).
- **PII**: nunca loguear tokens, passwords, ni `service_role_key`. El payload de `POST /reportes` (que tiene lat/lng del ciudadano) se puede loguear truncado o con precisión reducida si se vuelve un issue de privacidad.

---

## 10. Tabla resumen de excepciones más usadas

| Excepción | `code` | HTTP | Cuándo |
|---|---|---|---|
| `InvalidTokenError` | `invalid_token` | 401 | JWT mal formado, firma inválida, expirado |
| `UnauthorizedError` | `unauthorized` | 401 | JWT válido pero `usuario` no existe o `activo=false` |
| `ForbiddenError` | `forbidden` | 403 | Rol insuficiente |
| `ComunaMismatchError` | `comuna_mismatch` | 403 | Funcionario actúa sobre otra comuna |
| `ReporteNotFoundError` | `reporte_not_found` | 404 | Reporte no existe |
| `UsuarioNotFoundError` | `usuario_not_found` | 404 | Usuario no existe |
| `InvalidStateTransitionError` | `invalid_state_transition` | 409 | Salto de estado no permitido (ej. "En espera" → "Atendido") |
| `ConflictError` | `conflict` | 409 | Violación UNIQUE u operación duplicada |
| `ExternalServiceError` | `external_service_error` | 503 | Supabase / MQTT caído |
