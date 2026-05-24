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
| `GET` | `/api/v1/sensores` | ✅ | municipalidad (su comuna) o admin (todas) | Listar sensores con `estado_salud` derivado |
| `GET` | `/api/v1/sensores/{id}` | ✅ | municipalidad (de la comuna) o admin | Detalle de un sensor con `estado_salud` |
| `GET` | `/api/v1/sensores/resumen` | ✅ | municipalidad (su comuna) o admin | KPIs de salud (`online`/`intermitente`/`offline`/`sin_lecturas`) |
| `POST` | `/api/v1/sensores` | ✅ | admin | Crear sensor (provisioning) |
| `PATCH` | `/api/v1/sensores/{id}` | ✅ | admin | Editar nombre/coordenadas |
| `DELETE` | `/api/v1/sensores/{id}` | ✅ | admin | Soft-delete (`activo = false`) |
| `GET` | `/api/v1/usuarios` | ✅ | admin | Listar usuarios (filtrable por tipo, comuna) |
| `PATCH` | `/api/v1/usuarios/{id}/activo` | ✅ | admin | Activar/desactivar usuario |
| `PATCH` | `/api/v1/usuarios/{id}/promover` | ✅ | admin | Cambiar `tipo` (y `comuna_id` si aplica) |
| `POST` | `/api/v1/reportes-admin/archivos` | ✅ | admin | Subir PDF/CSV/imagen generado en el panel admin |
| `GET` | `/api/v1/reportes-admin/archivos` | ✅ | admin | Listar archivos (filtrable por `tipo`, `generado_por_id`) |
| `GET` | `/api/v1/reportes-admin/archivos/{id}/descarga` | ✅ | admin | Signed URL temporal para descargar el archivo |
| `DELETE` | `/api/v1/reportes-admin/archivos/{id}` | ✅ | admin | Eliminar archivo (blob + metadata) |

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
  "comuna_id": 13,
  "lectura_evidencia_id": 4821
}
```

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `titulo` | `string` (3–120) | ✅ | — |
| `descripcion` | `string` (10–2000) | ✅ | — |
| `latitud` | `float` (-90..90) | ✅ | — |
| `longitud` | `float` (-180..180) | ✅ | — |
| `comuna_id` | `int` | — | Si viene, debe existir en `comuna`. Si se omite, el server usa `usuario.comuna_id` como fallback. Ver §4.5.1 para el contrato cliente-side de resolución. |
| `lectura_evidencia_id` | `int` | — | Si vino del preview (`/buscar-evidencia`). Si se omite, el server intenta auto-adjuntar como fallback. |

**Lógica del server:** invoca la RPC compuesta `crear_reporte_con_validacion`. Detalle en [`backend.md`](./backend.md) §5.1 y [`bbdd.md`](./bbdd.md) §5.2.

#### 4.5.1 Resolución de `comuna_id` del lado cliente (contrato esperado)

El backend no carga polígonos comunales (sería ~3 horas de data work + riesgo de bugs geo). En su lugar, **delega al cliente** la responsabilidad de resolver `comuna_id` desde lat/lng. Esto es viable porque el frontend ya integra Leaflet + reverse-geocode (decisión F4 en `40db-frontend/docs/integracion-backend/README.md`).

**Pipeline esperado del cliente (frontend Vue 3):**

1. Usuario marca punto en el map picker → obtiene `lat, lng`.
2. Frontend llama a Nominatim (API pública de OpenStreetMap):
   ```
   GET https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}&format=jsonv2&accept-language=es
   ```
   Headers recomendados: `User-Agent: 40db-frontend/1.0 (contact@example.com)` (Nominatim exige UA identificable; rate limit 1 req/s — alcanza para reportes esporádicos).
3. Del response, extraer el nombre de comuna probando claves en este orden:
   - `address.county` (Chile suele venir acá: "Maipú", "Providencia").
   - `address.city_district` (fallback).
   - `address.suburb` o `address.town` (último recurso).
4. Normalizar (lowercase, sin tildes) y matchear contra `GET /api/v1/comunas` (catálogo cacheado en el front al boot).
5. Si match → enviar `comuna_id` resuelto en el body del `POST /reportes`.
6. Si no match (comuna no existe en el catálogo, o Nominatim no devuelve nada, o falla la red) → **no enviar `comuna_id`** y dejar que el backend use el fallback (`usuario.comuna_id`).

**Comportamiento del backend según viene o no `comuna_id`:**

| Caso | Acción del backend |
|---|---|
| `comuna_id` viene y existe en `comuna` | Se usa ese. Caso normal. |
| `comuna_id` viene pero no existe | 422 `validation_error` con mensaje "comuna_id no existe". |
| `comuna_id` omitido y `usuario.comuna_id` no es null | Se usa el del usuario. Comportamiento legacy. |
| `comuna_id` omitido y `usuario.comuna_id` es null (sin onboarding) | 422 `validation_error` con mensaje "Falta completar onboarding (comuna_id) o enviar comuna_id en el body". |

**Por qué no validamos `comuna_id` contra `(lat, lng)`:** sería redundante con la responsabilidad del cliente y obligaría a cargar polígonos en el backend. Si el cliente envía un `comuna_id` que no corresponde geográficamente, se acepta — el modelo de confianza es que el frontend ya hizo el match correcto.

**Riesgos asumidos:**

- **Nominatim down o lento** → fallback funciona (usa `usuario.comuna_id`), pero pierde precisión cross-comuna.
- **Rate limit de Nominatim** (1 req/s, sin key) → para reportes individuales no es problema. Si en el futuro hay flujos batch, considerar hostear Nominatim propio o pasar a Mapbox/Google.
- **Comuna inexistente en catálogo** → ej. usuario reporta desde una comuna no seedeada. El front no enviará `comuna_id`, fallback a `usuario.comuna_id`. Documentar: el catálogo `comuna` debe mantenerse al día.

**Roadmap:** si el modelo cliente-side genera friction (UX confusa, errores de matching), evaluar opción 2 del análisis original (polígonos del INE cargados en Postgres con función `comuna_by_point(lat, lng)`).

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

### 4.14 `GET /api/v1/sensores`

Listar sensores con `estado_salud` derivado on-demand (D10 en `bbdd.md`). Para `municipalidad`, filtra automáticamente por `usuario.comuna_id`. Para `admin`, lista todos o por `comuna_id` query.

```http
GET /api/v1/sensores?comuna_id=13&estado_salud=online&activo=true&limit=20&cursor=
Authorization: Bearer <jwt>
```

**Query params:**

| Param | Tipo | Notas |
|---|---|---|
| `comuna_id` | `int` | Solo aplicable para `admin` (`municipalidad` lo ignora y usa el suyo). Si no viene y el caller es admin → todas las comunas. |
| `estado_salud` | `string` | Filtra por `online` / `intermitente` / `offline` / `sin_lecturas`. |
| `activo` | `bool` | Filtro adicional sobre `sensor.activo`. Default: sin filtrar. |
| `limit`, `cursor` | — | Paginación cursor (mismo encoding que `/reportes/mios`). |

**Auth:** `current_user_municipal_o_admin`. Si caller no es ninguno → 403. Si caller es `municipalidad` y manda `comuna_id` distinto al suyo → se ignora (no se devuelve 403; el filtro de su comuna manda).

**Response 200:**
```json
{
  "data": [
    {
      "id": "d26bc4d1-3684-4fef-9953-00596b7d9ee8",
      "nombre": "Villa El Abrazo - Maipu",
      "comuna_id": 4,
      "comuna_nombre": "Maipú",
      "latitud": -33.5180,
      "longitud": -70.7580,
      "activo": true,
      "estado_salud": "online",
      "ultima_lectura_at": "2026-05-23T02:36:14Z",
      "ultima_lectura_db": 55.7
    }
  ],
  "next_cursor": null
}
```

Si un sensor nunca recibió lecturas: `ultima_lectura_at` y `ultima_lectura_db` son `null`, `estado_salud` es `sin_lecturas`.

**Errores:** 401, 403.

---

### 4.15 `GET /api/v1/sensores/{id}`

Detalle de un sensor individual con `estado_salud`.

```http
GET /api/v1/sensores/d26bc4d1-3684-4fef-9953-00596b7d9ee8
Authorization: Bearer <jwt>
```

**Auth:** `current_user_municipal_o_admin`. Si el caller es `municipalidad` y el sensor pertenece a otra comuna → 403 `comuna_mismatch`.

**Response 200:** mismo shape de un item de §4.14 pero envuelto sin `data`:

```json
{
  "id": "d26bc4d1-...",
  "nombre": "Villa El Abrazo - Maipu",
  "comuna_id": 4,
  "comuna_nombre": "Maipú",
  "latitud": -33.5180,
  "longitud": -70.7580,
  "activo": true,
  "estado_salud": "online",
  "ultima_lectura_at": "2026-05-23T02:36:14Z",
  "ultima_lectura_db": 55.7,
  "created_at": "2026-05-23T01:15:00Z"
}
```

**Errores:** 401, 403, 404 (`sensor_not_found`).

---

### 4.16 `GET /api/v1/sensores/resumen`

KPIs de salud agregados. Para municipalidad: contadores de su comuna. Para admin: globales (o por `comuna_id` si viene).

```http
GET /api/v1/sensores/resumen?comuna_id=4
Authorization: Bearer <jwt>
```

**Auth:** `current_user_municipal_o_admin`.

**Response 200:**
```json
{
  "total": 12,
  "online": 8,
  "intermitente": 2,
  "offline": 1,
  "sin_lecturas": 1,
  "calculado_at": "2026-05-23T02:38:00Z"
}
```

`calculado_at` es el `now()` del servidor — el front lo puede mostrar como "datos actualizados hace X segundos".

**Errores:** 401, 403.

---

### 4.17 `POST /api/v1/sensores`

Crear un sensor (provisioning). Reemplaza el flow manual de SQL editor.

```http
POST /api/v1/sensores
Authorization: Bearer <jwt-admin>
Content-Type: application/json
```

**Body:**
```json
{
  "nombre": "Plaza Italia - Norte",
  "comuna_id": 2,
  "latitud": -33.4372,
  "longitud": -70.6483
}
```

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nombre` | `string` (3–120) | ✅ | Único — UNIQUE en DB. |
| `comuna_id` | `int` | ✅ | Debe existir en `comuna`. |
| `latitud` | `float` (-90..90) | ✅ | — |
| `longitud` | `float` (-180..180) | ✅ | — |

**Auth:** `current_user_admin`.

**Response 201:** el sensor recién creado, mismo shape que §4.15. `activo=true`, `estado_salud='sin_lecturas'`, `ultima_lectura_at=null`.

**Side effects:**
- `id` se genera (UUID v4 vía `gen_random_uuid()`).
- `ubicacion` (geography) se genera automáticamente por el `GENERATED ALWAYS AS`.
- El UUID generado **debe** copiarse al firmware del ESP32 que va a publicar a `40db/sensores/{id}/lectura` (ver `iot.md` §10.4).

**Errores:**
- 401, 403.
- 422 si `nombre` duplicado (`sensor_nombre_already_exists`), `comuna_id` no existe, o coords fuera de rango.

---

### 4.18 `PATCH /api/v1/sensores/{id}`

Editar nombre o coordenadas. **No se puede cambiar `comuna_id`** (un sensor pertenece a la comuna donde fue instalado físicamente; mover sensor = darlo de baja y crear uno nuevo).

```http
PATCH /api/v1/sensores/d26bc4d1-...
Authorization: Bearer <jwt-admin>
Content-Type: application/json
```

**Body (todos opcionales, al menos uno requerido):**
```json
{
  "nombre": "Villa El Abrazo - Maipú (recalibrado)",
  "latitud": -33.5181,
  "longitud": -70.7581,
  "activo": false
}
```

**Auth:** `current_user_admin`.

**Response 200:** sensor actualizado.

**Errores:** 401, 403, 404, 422.

---

### 4.19 `DELETE /api/v1/sensores/{id}`

Soft-delete. Setea `activo=false` y mantiene las lecturas históricas (alimentan heatmap).

```http
DELETE /api/v1/sensores/d26bc4d1-...
Authorization: Bearer <jwt-admin>
```

**Auth:** `current_user_admin`.

**Response 200:**
```json
{
  "id": "d26bc4d1-...",
  "activo": false,
  "estado_salud": "offline"
}
```

**Side effects:**
- `validar_reporte_ruido` (`bbdd.md` §5.1) filtra por `sensor.activo = true`, así que un sensor con `activo=false` deja de generar evidencia para reportes nuevos.
- Las lecturas existentes siguen apareciendo en el heatmap.

**No hay hard-delete** en API. Si por alguna razón se requiere borrar físicamente (caso GDPR, falla de aprovisionamiento), hacerlo via SQL editor con cuidado de la FK compuesta `reporte.lectura_evidencia_*` → `lectura(id, timestamp_medicion)`.

**Errores:** 401, 403, 404.

---

### 4.20 `GET /api/v1/usuarios`

Listar usuarios. Solo admin.

```http
GET /api/v1/usuarios?tipo=municipalidad&comuna_id=13&activo=true&limit=20&cursor=
Authorization: Bearer <jwt-admin>
```

**Query params:**

| Param | Tipo | Notas |
|---|---|---|
| `tipo` | `string` | Filtra por `ciudadano` / `municipalidad` / `admin`. |
| `comuna_id` | `int` | Filtra por comuna del usuario. |
| `activo` | `bool` | Filtra por `usuario.activo`. |
| `q` | `string` | Búsqueda por `nombre` o `email` (ILIKE). Opcional. |
| `limit`, `cursor` | — | Paginación cursor. |

**Auth:** `current_user_admin`.

**Response 200:**
```json
{
  "data": [
    {
      "id": "uuid",
      "nombre": "Joaquín Meléndez",
      "email": "joaquin@example.com",
      "telefono": "+56912345678",
      "tipo": "ciudadano",
      "comuna_id": 4,
      "comuna_nombre": "Maipú",
      "activo": true,
      "created_at": "2026-05-15T18:30:00Z"
    }
  ],
  "next_cursor": null
}
```

**Nota sobre `email`:** vive en `auth.users.email` (no en `public.usuario`). El backend hace JOIN al armar la respuesta para que el panel admin lo muestre.

**Errores:** 401, 403.

---

### 4.21 `PATCH /api/v1/usuarios/{id}/activo`

Activar o desactivar un usuario (soft-disable). Un usuario inactivo no puede autenticarse (401 en `current_user`).

```http
PATCH /api/v1/usuarios/c1b8a700-.../activo
Authorization: Bearer <jwt-admin>
Content-Type: application/json
```

**Body:**
```json
{ "activo": false }
```

**Auth:** `current_user_admin`. **El admin no puede desactivarse a sí mismo** (`id == current_user.id`) → 422.

**Response 200:** usuario completo (mismo shape que `GET /usuarios/{id}.data[]`).

**Errores:** 401, 403, 404, 422.

---

### 4.22 `PATCH /api/v1/usuarios/{id}/promover`

Cambiar el rol y/o comuna de un usuario. Reglas detalladas en [`auth.md`](./auth.md) §8.2.

```http
PATCH /api/v1/usuarios/c1b8a700-.../promover
Authorization: Bearer <jwt-admin>
Content-Type: application/json
```

**Body:**
```json
{
  "nuevo_tipo": "municipalidad",
  "comuna_id": 13
}
```

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `nuevo_tipo` | `string` | ✅ | `ciudadano` / `municipalidad` / `admin`. |
| `comuna_id` | `int` | Obligatorio si `nuevo_tipo='municipalidad'` | Debe existir. Para `admin` es opcional (afinidad informativa). Para `ciudadano` se ignora (preserva la actual). |

**Auth:** `current_user_admin`. **El admin no puede degradarse a sí mismo** (`id == current_user.id`) → 422 `cannot_demote_self`.

**Response 200:** usuario actualizado.

**Errores:**
- 401, 403, 404.
- 422 `comuna_id_required` si `nuevo_tipo='municipalidad'` y no viene `comuna_id`.
- 422 `comuna_not_found` si el `comuna_id` no existe.
- 422 `cannot_demote_self` si `id == current_user.id`.

---

### 4.23 `POST /api/v1/reportes-admin/archivos`

Subir un archivo (PDF, CSV o imagen) generado desde la vista `/admin-dashboard/reportes`. El backend guarda el blob en el bucket privado `reportes-admin` de Supabase Storage y registra la metadata en `reporte_archivo_admin`.

```http
POST /api/v1/reportes-admin/archivos
Authorization: Bearer <jwt-admin>
Content-Type: multipart/form-data
```

**Body (multipart):**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `archivo` | file | ✅ | El binario. `Content-Type` debe coincidir con `tipo`. |
| `nombre` | `string` | ✅ | Nombre legible para mostrar al usuario (1–200 chars). |
| `tipo` | `string` | ✅ | `pdf` / `csv` / `imagen`. |
| `rango_desde` | ISO 8601 | — | Inicio del período cubierto por el reporte. |
| `rango_hasta` | ISO 8601 | — | Fin del período. Debe ser ≥ `rango_desde`. |

**MIME types aceptados:**

- `tipo=pdf`: `application/pdf`
- `tipo=csv`: `text/csv`, `application/csv`, `application/vnd.ms-excel`
- `tipo=imagen`: `image/png`, `image/jpeg`, `image/webp`

**Tamaño máximo:** `ARCHIVO_MAX_SIZE_MB` (default 20 MB).

**Auth:** `current_user_admin`.

**Response 201:**

```json
{
  "id": "uuid",
  "nombre": "reporte-mayo-2026.pdf",
  "tipo": "pdf",
  "mime_type": "application/pdf",
  "tamano_bytes": 184320,
  "generado_por_id": "uuid",
  "generado_por_nombre": "Admin Demo",
  "rango_desde": "2026-05-01T00:00:00Z",
  "rango_hasta": "2026-05-31T23:59:59Z",
  "created_at": "2026-05-24T18:00:00Z"
}
```

**Errores:** 401, 403, 422 (`validation_error` si mime no matchea `tipo`, archivo vacío, o tamaño > límite), 503 (`external_service_error` si Storage o la metadata fallan).

---

### 4.24 `GET /api/v1/reportes-admin/archivos`

Listar archivos previamente subidos. Paginación cursor (mismo esquema que `/usuarios`).

```http
GET /api/v1/reportes-admin/archivos
  ?tipo=pdf
  &generado_por_id=<uuid>
  &limit=20
  &cursor=
Authorization: Bearer <jwt-admin>
```

**Query params:**

| Param | Tipo | Default | Notas |
|---|---|---|---|
| `tipo` | `string` | — | Filtra por `pdf` / `csv` / `imagen`. |
| `generado_por_id` | `uuid` | — | Filtra por autor. |
| `limit` | `int` | 20 | 1–100. |
| `cursor` | `string` | — | Cursor opaco de la página anterior. |

**Response 200:**

```json
{
  "data": [
    {
      "id": "uuid",
      "nombre": "reporte-mayo-2026.pdf",
      "tipo": "pdf",
      "mime_type": "application/pdf",
      "tamano_bytes": 184320,
      "generado_por_id": "uuid",
      "generado_por_nombre": "Admin Demo",
      "rango_desde": "2026-05-01T00:00:00Z",
      "rango_hasta": "2026-05-31T23:59:59Z",
      "created_at": "2026-05-24T18:00:00Z"
    }
  ],
  "next_cursor": null
}
```

**Errores:** 401, 403.

---

### 4.25 `GET /api/v1/reportes-admin/archivos/{id}/descarga`

Devuelve una signed URL de corta duración apuntando directamente al objeto en Supabase Storage. El frontend hace `GET` (o `<a download>`) contra esa URL — el backend **no** hace proxy del binario.

```http
GET /api/v1/reportes-admin/archivos/{id}/descarga
Authorization: Bearer <jwt-admin>
```

**Response 200:**

```json
{
  "url": "https://<proj>.supabase.co/storage/v1/object/sign/reportes-admin/...?token=...",
  "expires_in_seconds": 300
}
```

`expires_in_seconds` se controla con el env `STORAGE_SIGNED_URL_TTL_SECONDS` (default 300).

**Errores:** 401, 403, 404 (`not_found`), 503 si Storage está caído.

---

### 4.26 `DELETE /api/v1/reportes-admin/archivos/{id}`

Borra el blob del bucket y luego la fila de metadata. Si el blob no existe el backend ignora el error (compensación). Si la metadata falla tras borrar el blob, queda un huérfano *en la base* — la operación inversa al upload.

```http
DELETE /api/v1/reportes-admin/archivos/{id}
Authorization: Bearer <jwt-admin>
```

**Response 204:** sin body.

**Errores:** 401, 403, 404, 503.

---

## 5. CORS

- **Origenes permitidos:** lista blanca configurable vía env `CORS_ORIGINS` (CSV de URLs). En dev, suele incluir `http://localhost:5173` (Vite del frontend Vue).
- **Métodos permitidos:** `GET`, `POST`, `PATCH`, `DELETE`, `OPTIONS`.
- **Headers permitidos:** `Authorization`, `Content-Type`, `X-Correlation-Id`, `Idempotency-Key`.
- **Credentials:** `false`. Los JWT se envían explícitamente, no en cookies.

---

## 6. Versionado

- Prefijo `/api/v1/`. Cambios **rompedores** (remover campo, cambiar tipo, agregar required) bumpean a `/api/v2/` y `/api/v1/` queda deprecated 3 meses con header `Deprecation: …`.
- Cambios **aditivos** (nuevo endpoint, nuevo campo opcional, nuevo status code) no bumpean.
