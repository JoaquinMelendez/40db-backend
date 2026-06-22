# Pruebas de Carga (k6)

Miden latencia y tasa de error del backend FastAPI bajo concurrencia creciente.
La herramienta es [k6](https://k6.io) (script en `load_test.js`).

## Por qué k6 y no pytest

Las pruebas de carga necesitan un servidor **corriendo de verdad** y un cliente
que genere concurrencia real (no mocks). pytest cubre las otras capas (unitaria,
humo, integración, seguridad) mockeando Supabase; carga es el único tipo que
ejercita el proceso ASGI real end-to-end.

## Escenarios

| Escenario | Endpoints | Requiere |
|---|---|---|
| **Humo de carga** (siempre) | `GET /health/live`, `GET /openapi.json` | Solo el backend corriendo. No tocan Supabase: miden el techo del stack ASGI (routing, middleware, serialización). |
| **API autenticada** (opcional) | `GET /usuarios/me`, `GET /sensores`, `GET /reportes/mios` | Backend + Supabase real + un `TOKEN` (JWT válido). Se activa solo si se pasa `TOKEN`. |

## Cómo correrlo

```bash
# 1. Levantar el backend (otra terminal). MQTT se deshabilita dejando sus vars vacías.
MQTT_BROKER_URL="" MQTT_USER="" MQTT_PASSWORD="" uvicorn app.main:app --port 8000

# 2. Carga básica (sin DB):
k6 run tests/load/load_test.js

# 3. Parametrizada (más VUs, más tiempo, otro host):
BASE_URL=http://localhost:8000 VUS=50 DURATION=1m k6 run tests/load/load_test.js

# 4. Incluyendo endpoints autenticados (Supabase real + JWT):
TOKEN="eyJhbGci..." k6 run tests/load/load_test.js
```

### Parámetros (variables de entorno)

| Var | Default | Descripción |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Host del backend a golpear |
| `VUS` | `20` | Usuarios virtuales concurrentes (pico) |
| `DURATION` | `30s` | Duración del tramo en régimen (además hay 10s de rampa de subida y 5s de bajada) |
| `TOKEN` | _(vacío)_ | JWT válido; si está, activa el escenario autenticado |

## Umbrales (el run falla si no se cumplen)

- `http_req_failed` **< 1%** — tasa de requests con error.
- `http_req_duration` **p95 < 500ms** — latencia del percentil 95.
- `check_success_rate` **> 99%** — asserts de status code correctos.

## Baseline de referencia

Medición local (macOS, backend en `localhost`, solo escenario sin DB,
`VUS=20 DURATION=20s`):

```
http_req_duration  p(95)=17.54ms   avg=7.1ms   max=68.54ms
http_req_failed    0.00%  (0 de 2164)
check_success_rate 100.00%
throughput         ~61 req/s        (2164 requests)
```

Todos los umbrales en verde. Sirve como punto de comparación para detectar
regresiones de rendimiento. Contra Supabase real (escenario autenticado) la
latencia será mayor: ajustar el umbral p95 según el entorno objetivo.
