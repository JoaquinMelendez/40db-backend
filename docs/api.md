# API HTTP — 40dB

Documento autoritativo del **contrato HTTP** del backend 40dB. Define endpoints, métodos, autenticación requerida, shapes de request/response y status codes. Si un snippet en otro doc difiere, este gana (ver [`README.md`](./README.md) — Reglas de precedencia).

**Documentos relacionados:**
- [`backend.md`](./backend.md) §5 — flujos de alto nivel (la *intención* de cada endpoint).
- [`auth.md`](./auth.md) §6 — matriz de roles que el endpoint impone.
- [`errores.md`](./errores.md) — shape uniforme de error, status codes.
- [`bbdd.md`](./bbdd.md) — modelo de datos referenciado en los shapes.

---

## 1. Decisiones de API

| # | Decisión | Justificación |
|---|---|---|
| API1 | **Prefijo `/api/v1/`** en todos los endpoints de negocio | Versionado explícito desde día 1. Si rompemos contrato, `/api/v2/`. |
| API2 | **Health checks fuera del prefijo versionado**: `/health/live`, `/health/ready` | Los usa el orquestador, no clientes de negocio. No tienen contrato de cliente. |
| API3 | **JSON sobre HTTPS**. `Content-Type: application/json`. Charset UTF-8 implícito | Estándar; sin sorpresas. |
| API4 | **JWT en header `Authorization: Bearer <token>`** | Compatible con Supabase Auth, con curl, y con cualquier cliente HTTP. |
| API5 | **Paginación: cursor-based** para listas potencialmente largas (reportes, lecturas) | Cursor evita problemas de offset con insertions concurrentes. `?limit=…&cursor=…`. |
| API6 | **Errores con shape uniforme** (ver `errores.md` §4) | Frontend siempre parsea igual. |
| API7 | **Sin paginación en heatmap** — se acotan por `bbox` + ventana temporal + `bucket_minutes` | El heatmap es agregado; si el response es grande, se ajustan los parámetros, no se pagina. |
| API8 | **Idempotencia opcional en `POST /reportes`** vía header `Idempotency-Key` | Si el cliente reintenta por timeout, no se crean reportes duplicados. Roadmap para MVP+1. |
| API9 | **CORS**: el backend habilita explícitamente el origen del frontend (configurable vía env `CORS_ORIGINS`) | Sin `*`; lista blanca. |

---

## 2. Convenciones generales

### Headers de request

| Header | Obligatorio | Notas |
|---|---|---|
| `Authorization` | Solo en endpoints autenticados | `Bearer <jwt>`. JWT emitido por Supabase Auth. |
| `Content-Type` | En requests con body | `application/json`. |
| `X-Correlation-Id` | No | Si lo manda el cliente, el backend lo respeta y devuelve en la respuesta. Si no, lo genera. |
| `Idempotency-Key` | No (roadmap) | Para `POST /reportes`. UUID generado por el cliente. |

### Headers de response

| Header | Cuándo | Notas |
|---|---|---|
| `Content-Type` | Siempre | `application/json`. |
| `X-Correlation-Id` | Siempre | Eco del de request o uno generado. Útil para soporte. |

### Códigos comunes

| Code | Cuándo |
|---|---|
| 200 | OK |
| 201 | Created (POST que crea recursos) |
| 204 | No Content (PATCH/DELETE sin body de respuesta — no se usa en MVP, todos retornan algo) |
| 400 | JSON sintácticamente inválido |
| 401 | Auth ausente o inválida |
| 403 | Auth válida pero rol/comuna insuficiente |
| 404 | Recurso inexistente |
| 409 | Conflicto de negocio (transición inválida, duplicado) |
| 422 | Body parseable pero falla validación Pydantic |
| 500 | Error no manejado |
| 503 | Dependencia externa caída |

Mapeo completo y subtipos en [`errores.md`](./errores.md) §3 y §10.

---

## 3. Tabla maestra de endpoints

| Método | Path | Auth | Rol | Para qué |
|---|---|---|---|---|
| `GET` | `/health/live` | ❌ | — | Liveness probe |
| `GET` | `/health/ready` | ❌ | — | Readiness probe |
| `GET` | `/api/v1/heatmaps` | ❌ | público | Agregado acústico geo-temporal |
| `GET` | `/api/v1/reportes/buscar-evidencia` | ✅ | ciudadano+ | Preview de evidencia disponible |
| `POST` | `/api/v1/reportes` | ✅ | ciudadano+ | Crear reporte (con evidencia opcional) |
| `GET` | `/api/v1/reportes/mios` | ✅ | ciudadano+ | "Mis reportes" del usuario autenticado |
| `GET` | `/api/v1/reportes/comuna/{comuna_id}` | ✅ | municipalidad de esa comuna | Panel funcionario |
| `GET` | `/api/v1/reportes/{id}` | ✅ | dueño o municipalidad de la comuna | Detalle |
| `PATCH` | `/api/v1/reportes/{id}/estado` | ✅ | municipalidad de la comuna | Cambio de estado |
| `PATCH` | `/api/v1/usuarios/me` | ✅ | el propio | Onboarding (`telefono`, `comuna_id`) |
| `GET` | `/api/v1/usuarios/me` | ✅ | el propio | Perfil propio |
| `GET` | `/api/v1/comunas` | ❌ | público | Catálogo de comunas (dropdown del frontend) |
| `GET` | `/api/v1/tipos-estado` | ❌ | público | Catálogo de estados (dropdown) |

> **Auth flow (signup/login)** vive en Supabase Auth, **no en este backend**. Ver [`auth.md`](./auth.md) §4.

---

## 4. Especificación detallada

### 4.1 `GET /health/live`

```http
GET /health/live
```

**Response 200:**
```json
{ "status": "alive" }
```

No falla nunca salvo que el proceso esté caído.

---

### 4.2 `GET /health/ready`

```http
GET /health/ready
```

**Response 200 (todo OK):**
```json
{
  "status": "ready",
  "checks": { "supabase": "ok", "mqtt": "ok", "jwt_secret": "ok" }
}
```

**Response 503 (algo falla):**
```json
{
  "status": "degraded",
  "checks": { "supabase": "ok", "mqtt": "reconnecting", "jwt_secret": "ok" }
}
```

Detalle en [`errores.md`](./errores.md) §8.

---

### 4.3 `GET /api/v1/heatmaps`

```http
GET /api/v1/heatmaps
  ?bbox=-70.65,-33.45,-70.55,-33.40
  &time_start=2026-05-19T00:00:00Z
  &time_end=2026-05-19T23:59:59Z
  &bucket_minutes=5
```

**Query params:**

| Param | Tipo | Obligatorio | Default | Notas |
|---|---|---|---|---|
| `bbox` | `string` (4 floats CSV: `minLng,minLat,maxLng,maxLat`) | ✅ | — | Acota área. WGS84. |
| `time_start` | ISO 8601 | ✅ | — | Inicio de ventana. |
| `time_end` | ISO 8601 | ✅ | — | Fin de ventana. Max 7 días desde `time_start`. |
| `bucket_minutes` | `int` | — | 5 | Tamaño de bucket temporal. Permitidos: 1, 5, 15, 60. |

**Response 200:** GeoJSON `FeatureCollection` con un `Feature` por celda + bucket que tenga lecturas:

```json
{
  "type": "FeatureCollection",
  "metadata": {
    "bucket_minutes": 5,
    "grid_size_deg": 0.001,
    "total_cells": 234
  },
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [-70.6483, -33.4372]
      },
      "properties": {
        "nivel_db_avg": 62.3,
        "nivel_db_max": 71.8,
        "lectura_count": 12,
        "bucket_start": "2026-05-19T18:30:00Z"
      }
    }
  ]
}
```

**Detalle de agregación:** lat/lng se redondean a una grilla de `0.001°` (~100 m) por celda. Cada feature representa una celda en un bucket. La SQL exacta en [`bbdd.md`](./bbdd.md) §5.3.

**Errores:**
- 422 si `bbox` inválido, ventana negativa, o `bucket_minutes` no permitido.
- 422 si `time_end - time_start > 7 días`.

---

### 4.4 `GET /api/v1/reportes/buscar-evidencia`

```http
GET /api/v1/reportes/buscar-evidencia?lat=-33.4372&lng=-70.6483
Authorization: Bearer <jwt>
```

**Query params:**

| Param | Tipo | Obligatorio |
|---|---|---|
| `lat` | `float` | ✅ |
| `lng` | `float` | ✅ |

**Response 200 (con match):**
```json
{
  "evidencia": {
    "lectura_id": 4821,
    "sensor_id": "1e2c...",
    "sensor_nombre": "Plaza Italia - Norte",
    "nivel_db": 72.4,
    "distancia_metros": 84.2,
    "timestamp_medicion": "2026-05-19T22:14:33Z"
  }
}
```

**Response 200 (sin match):**
```json
{ "evidencia": null }
```

**Auth:** requerida (rol mínimo `ciudadano`). Razón: el endpoint expone presencia/ubicación de sensores; mejor mantenerlo scoped.

**Errores:**
- 401 si JWT inválido.
- 422 si `lat`/`lng` fuera de rango (-90/90, -180/180).

---

### 4.5 `POST /api/v1/reportes`

```http
POST /api/v1/reportes
Authorization: Bearer <jwt>
Content-Type: application/json
```

**Body:**
```json
{
  "titulo": "Fiesta con parlantes a la calle",
  "descripcion": "Música muy alta desde las 23:00",
  "latitud": -33.4372,
  "longitud": -70.6483,
  "lectura_evidencia_id": 4821
}
```

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `titulo` | `string` (3–120) | ✅ | — |
| `descripcion` | `string` (10–2000) | ✅ | — |
| `latitud` | `float` (-90..90) | ✅ | — |
| `longitud` | `float` (-180..180) | ✅ | — |
| `lectura_evidencia_id` | `int` | — | Si vino del preview (`/buscar-evidencia`). Si se omite, el server intenta auto-adjuntar como fallback. |

**Lógica del server:** invoca la RPC compuesta `crear_reporte_con_validacion`. Detalle en [`backend.md`](./backend.md) §5.1 y [`bbdd.md`](./bbdd.md) §5.2.

**Response 201:**
```json
{
  "id": "0f8c...",
  "usuario_id": "user-uuid",
  "comuna_id": 13,
  "titulo": "Fiesta con parlantes a la calle",
  "descripcion": "Música muy alta desde las 23:00",
  "latitud": -33.4372,
  "longitud": -70.6483,
  "estado_actual": "En espera",
  "lectura_evidencia": {
    "lectura_id": 4821,
    "sensor_id": "1e2c...",
    "sensor_nombre": "Plaza Italia - Norte",
    "nivel_db": 72.4,
    "timestamp_medicion": "2026-05-19T22:14:33Z"
  },
  "created_at": "2026-05-19T22:15:01Z"
}
```

Si no hay evidencia adjuntada (ni del cliente ni del fallback), `lectura_evidencia` es `null`.

**Errores:**
- 401, 422 (Pydantic), 503 (Supabase).
- **No 4xx por lectura_evidencia_id inválido** — se descarta silenciosamente y se cae al fallback (anti-forgery transparente, ver `backend.md` §5.1).

---

### 4.6 `GET /api/v1/reportes/mios`

```http
GET /api/v1/reportes/mios?limit=20&cursor=<opaque>
Authorization: Bearer <jwt>
```

**Query params:**

| Param | Tipo | Default | Notas |
|---|---|---|---|
| `limit` | `int` (1–100) | 20 | — |
| `cursor` | `string` | — | Opaco; viene del response anterior. |
| `estado` | `string` | — | Filtra por nombre de estado (`En espera`, etc.). |

**Response 200:**
```json
{
  "data": [
    { "id": "...", "titulo": "...", "estado_actual": "En espera", "created_at": "..." }
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0Ijo..." 
}
```

`next_cursor` es `null` cuando no hay más resultados. El cursor encodea `(created_at, id)` del último elemento — el cliente lo trata como opaco.

**Errores:** 401.

---

### 4.7 `GET /api/v1/reportes/comuna/{comuna_id}`

```http
GET /api/v1/reportes/comuna/13?limit=20&cursor=<opaque>&estado=En%20espera
Authorization: Bearer <jwt>
```

**Auth:** solo `tipo='municipalidad'` Y `usuario.comuna_id == comuna_id`. Caso contrario → 403 `comuna_mismatch`.

**Response 200:** mismo shape que `/reportes/mios`.

**Errores:** 401, 403 (`forbidden` si no es funcionario; `comuna_mismatch` si lo es pero de otra comuna), 404 (comuna inexistente).

---

### 4.8 `GET /api/v1/reportes/{id}`

```http
GET /api/v1/reportes/0f8c...
Authorization: Bearer <jwt>
```

**Auth:** el dueño del reporte (`usuario_id == auth.uid`), o funcionario `municipalidad` de la misma comuna.

**Response 200:**
```json
{
  "id": "0f8c...",
  "usuario": { "id": "...", "nombre": "..." },
  "atendido_por": { "id": "...", "nombre": "..." },
  "comuna_id": 13,
  "titulo": "...",
  "descripcion": "...",
  "latitud": -33.4372,
  "longitud": -70.6483,
  "estado_actual": "En atencion",
  "historial": [
    { "estado": "En espera", "comentario": null, "created_at": "...", "usuario": null },
    { "estado": "En atencion", "comentario": "Tomando el caso", "created_at": "...", "usuario": { "id": "...", "nombre": "..." } }
  ],
  "lectura_evidencia": { /* mismo shape que en POST response */ } 
}
```

**Errores:** 401, 403, 404 (`reporte_not_found`).

---

### 4.9 `PATCH /api/v1/reportes/{id}/estado`

```http
PATCH /api/v1/reportes/0f8c.../estado
Authorization: Bearer <jwt>
Content-Type: application/json
```

**Body:**
```json
{
  "nuevo_estado": "En atencion",
  "comentario": "Tomando el caso"
}
```

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nuevo_estado` | `string` | ✅ | Uno de los nombres de `tipo_estado`. |
| `comentario` | `string` (max 500) | Solo obligatorio para `Descartado` | — |

**Auth:** `tipo='municipalidad'` Y `usuario.comuna_id == reporte.comuna_id`.

**Reglas (validadas en use case):**
- No se puede saltar `En espera` → `Atendido` sin pasar por `En atencion`.
- `Descartado` requiere `comentario` no vacío.
- No se puede transicionar desde un estado terminal (`Atendido`, `Descartado`).
- Detalle de máquina en [`bbdd.md`](./bbdd.md) §7.

**Response 200:** reporte completo (mismo shape que `GET /reportes/{id}`).

**Side effect:** si la transición es `En espera` → `En atencion`, se setea `reporte.atendido_por_id = auth.uid` en el mismo update.

**Errores:**
- 401, 403, 404.
- 409 `invalid_state_transition` para saltos prohibidos.
- 422 si `comentario` falta en `Descartado` (validación de schema o de dominio).

---

### 4.10 `GET /api/v1/usuarios/me`

```http
GET /api/v1/usuarios/me
Authorization: Bearer <jwt>
```

**Response 200:**
```json
{
  "id": "user-uuid",
  "nombre": "Joaquín Meléndez",
  "telefono": "+56912345678",
  "tipo": "ciudadano",
  "comuna_id": 13,
  "comuna_nombre": "Providencia",
  "activo": true,
  "created_at": "..."
}
```

Si `comuna_id` es `null` (sin onboarding), `comuna_nombre` también es `null`.

**Errores:** 401.

---

### 4.11 `PATCH /api/v1/usuarios/me`

```http
PATCH /api/v1/usuarios/me
Authorization: Bearer <jwt>
Content-Type: application/json
```

**Body (todos opcionales, pero al menos uno):**
```json
{
  "telefono": "+56912345678",
  "comuna_id": 13
}
```

**Campos no editables:** `id`, `tipo`, `nombre` (se setea en signup), `activo`.

**Response 200:** perfil completo (mismo shape que GET).

**Errores:**
- 401.
- 422 si `comuna_id` no existe o `telefono` no matchea regex de E.164.

---

### 4.12 `GET /api/v1/comunas`

```http
GET /api/v1/comunas
```

**Response 200:**
```json
[
  { "id": 13, "nombre": "Providencia", "region": "Metropolitana", "codigo": "13123" },
  { "id": 14, "nombre": "Santiago", "region": "Metropolitana", "codigo": "13101" }
]
```

Catálogo público; sin paginación (es chico).

---

### 4.13 `GET /api/v1/tipos-estado`

```http
GET /api/v1/tipos-estado
```

**Response 200:**
```json
[
  { "id": 1, "nombre": "En espera", "descripcion": "Reporte creado, sin asignar", "orden": 1 },
  { "id": 2, "nombre": "En atencion", "descripcion": "Funcionario asignado trabajando", "orden": 2 },
  { "id": 3, "nombre": "Atendido", "descripcion": "Reporte resuelto", "orden": 3 },
  { "id": 4, "nombre": "Descartado", "descripcion": "Reporte invalido o duplicado", "orden": 4 }
]
```

---

## 5. CORS

- **Origenes permitidos:** lista blanca configurable vía env `CORS_ORIGINS` (CSV de URLs). En dev, suele incluir `http://localhost:5173` (Vite del frontend Vue).
- **Métodos permitidos:** `GET`, `POST`, `PATCH`, `OPTIONS`.
- **Headers permitidos:** `Authorization`, `Content-Type`, `X-Correlation-Id`, `Idempotency-Key`.
- **Credentials:** `false`. Los JWT se envían explícitamente, no en cookies.

---

## 6. Versionado

- Prefijo `/api/v1/`. Cambios **rompedores** (remover campo, cambiar tipo, agregar required) bumpean a `/api/v2/` y `/api/v1/` queda deprecated 3 meses con header `Deprecation: …`.
- Cambios **aditivos** (nuevo endpoint, nuevo campo opcional, nuevo status code) no bumpean.
