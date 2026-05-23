# Plan de implementación — MVP 40dB

Orden ejecutable de tareas para llegar de "scaffold vacío" a "MVP funcional". Cada paso tiene **dependencias**, **doc autoritativo**, y **done when** explícito.

> **Cómo usar este doc.** Una IA o un dev puede pedir "implementá paso N" y tener toda la info para hacerlo. Si algo no está claro en este plan, el doc autoritativo del paso (columna "Spec") manda. Si el spec tampoco lo cubre, **pregunta antes de inventar**.

---

## Pre-requisitos

Antes de empezar cualquier paso:

- [ ] Tener `supabase` CLI instalado y proyecto local funcionando (`supabase start` levanta sin errores).
- [ ] `.env` con `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `CORS_ORIGINS`. (Ver `backend.md` §8.)
- [ ] Python 3.11+ y `pip install -r requirements.txt`. **Atención:** `requirements.txt` está incompleto (solo `fastapi` y `uvicorn`). El paso 0 lo arregla.

---

## Paso 0 — Bootstrap del entorno

**Dependencias:** ninguna.

**Tareas:**
- Completar `requirements.txt` con todas las dependencias necesarias:
  ```
  fastapi
  uvicorn[standard]
  supabase                  # cliente Python oficial
  paho-mqtt                 # cliente MQTT
  pydantic-settings         # config desde env
  pyjwt[crypto]             # verificación JWT local
  python-ulid               # correlation_id
  ```
- Crear `.env.example` en la raíz, con todas las variables de `backend.md` §8 (valores placeholder, sin secretos).
- Agregar `.env`, `__pycache__/`, `.DS_Store` al `.gitignore` si faltan.
- Verificar que `uvicorn main:app --reload` levanta sin error (sigue siendo hola-mundo).

**Done when:**
- `pip install -r requirements.txt` corre sin errores.
- `.env.example` existe y `.env` está gitignoreado.
- `uvicorn main:app --reload` responde 200 en `GET /`.

---

## Paso 1 — Regenerar migración SQL

**Dependencias:** paso 0.

**Spec:** [`bbdd.md`](./bbdd.md) §12 (plan completo de regeneración, paso a paso).

**Tareas resumidas:**
- Eliminar `supabase/migrations/20260519000000_initial_schema.sql` (versión previa desalineada) y `supabase/seed.sql`.
- Crear migración nueva con `supabase migration new initial_schema`.
- Poblarla siguiendo `bbdd.md` §3, §4, §5.1–5.4, §6 en orden. **Atención específica:**
  - `lectura` con `PARTITION BY RANGE (timestamp_medicion)` + PK compuesta `(id, timestamp_medicion)` (D8 en `bbdd.md` §1, detalle en §3.5).
  - Crear las 8 particiones mensuales (`lectura_2026_05` … `lectura_2026_12`) + `lectura_default` (§3.5.1).
  - `reporte` con `lectura_evidencia_id` + `lectura_evidencia_timestamp` + FK compuesta + `chk_evidencia_pair` (§3.6).
  - RPCs `validar_reporte_ruido_top_n` y `crear_reporte_con_validacion` deben devolver el par id+timestamp (§5.2, §5.3).
- Reescribir `supabase/seed.sql` (`bbdd.md` §8 + §12.1 paso 4). Las lecturas mock deben tener `timestamp_medicion` dentro del rango de alguna partición creada.
- Aplicar local con `supabase db reset` y verificar (`bbdd.md` §12.1 paso 6).

**Done when:**
- `supabase db reset` corre sin errores.
- `\dx` en psql muestra `postgis`.
- `\d+ lectura` muestra `Partition key: RANGE (timestamp_medicion)` y lista las particiones.
- `SELECT tableoid::regclass FROM lectura LIMIT 1` confirma que las filas del seed caen en una partición concreta (no en `lectura_default`).
- `SELECT * FROM validar_reporte_ruido(...)` y `SELECT * FROM crear_reporte_con_validacion(...)` existen y devuelven datos (incluyendo el par id+timestamp).
- `INSERT` duplicado en `lectura` con mismo `(sensor_id, timestamp_medicion)` falla con UNIQUE violation.
- `INSERT INTO reporte` con `lectura_evidencia_id` sin `lectura_evidencia_timestamp` falla por `chk_evidencia_pair`; con par válido funciona.

---

## Paso 2 — Estructura de carpetas (hexagonal lite)

**Dependencias:** paso 0.

**Spec:** [`backend.md`](./backend.md) §3.

**Tareas:**
- Crear las carpetas del layout objetivo bajo `app/`: `api/routes/`, `api/schemas/`, `api/middleware/`, `application/`, `domain/`, `infrastructure/db/`, `infrastructure/mqtt/`, `core/`, `patterns/`.
- Mover/renombrar las carpetas scaffold existentes según la tabla de migración en `backend.md` §3.
- Crear `app/__init__.py` vacíos donde haga falta.
- Crear `app/core/config.py` con `pydantic-settings` cargando todas las vars de `backend.md` §8.
- Crear `app/core/supabase_client.py` singleton inicializado con `service_role_key`.
- Reescribir `app/main.py` con: instancia FastAPI, registro de middleware (correlation_id), registro de exception handlers, `lifespan` que arranque MQTT condicionalmente (paso 6).

**Done when:**
- `uvicorn app.main:app --reload` levanta sin errores.
- `app/core/config.py` falla con mensaje claro si falta una env obligatoria.

---

## Paso 3 — Capa de errores y health checks

**Dependencias:** paso 2.

**Spec:** [`errores.md`](./errores.md) (entero) + [`api.md`](./api.md) §4.1, §4.2.

**Tareas:**
- Crear `app/domain/errors.py` con la jerarquía de `errores.md` §2.
- Crear `app/api/error_handlers.py` con los handlers de `errores.md` §5 (registrarlos en `app/main.py`).
- Crear `app/api/middleware/correlation.py` (`errores.md` §6) y registrarlo.
- Crear `app/api/routes/health.py` con `/health/live` y `/health/ready` (`errores.md` §8).
- Implementar los checks de `/health/ready`: ping Supabase con `SELECT 1`, estado MQTT desde el ingestor, presencia de `JWT_SECRET`.

**Done when:**
- `GET /health/live` responde 200.
- `GET /health/ready` responde 200 si Supabase está vivo, 503 si está caído.
- Lanzar `raise NotFoundError("test")` en un endpoint produce el shape uniforme de `errores.md` §4 con HTTP 404.

---

## Paso 4 — Auth: dependency `current_user`

**Dependencias:** paso 3.

**Spec:** [`auth.md`](./auth.md) §5 + [`errores.md`](./errores.md) §10.

**Tareas:**
- Crear `app/domain/entities.py` con dataclass `Usuario` (campos de `bbdd.md` §3.3).
- Crear `app/domain/ports.py` con `Protocol UsuarioRepository`.
- Crear `app/infrastructure/db/usuario_repo.py` con `SupabaseUsuarioRepository: UsuarioRepository`.
- Crear `app/api/deps.py` con:
  - `bearer = HTTPBearer()`.
  - `current_user(...)` que valida JWT con HS256 + `SUPABASE_JWT_SECRET`, audience `"authenticated"`, carga `usuario` por `sub`, verifica `activo=true`.
  - `current_user_municipal(...)` que requiere `tipo='municipalidad'`.
  - `current_user_municipal_de_comuna(comuna_id)` factory.

**Done when:**
- Un endpoint protegido con `Depends(current_user)` responde 401 sin JWT, 401 con JWT inválido, 200 con JWT válido de un usuario activo.
- 401 con JWT válido pero `usuario.activo = false`.

---

## Paso 5 — Endpoints de reportes (CORE)

**Dependencias:** paso 4.

**Spec:** [`api.md`](./api.md) §4.4–§4.9 + [`backend.md`](./backend.md) §5.1.

**Sub-pasos:**

### 5a. `GET /api/v1/reportes/buscar-evidencia`
- Crear `app/application/buscar_evidencia.py`.
- Crear `app/infrastructure/db/rpc.py` con wrapper para `validar_reporte_ruido`.
- Crear route en `app/api/routes/reportes.py` que invoca el use case.
- Schemas en `app/api/schemas/reporte.py`.

### 5b. `POST /api/v1/reportes`
- Crear `app/application/crear_reporte.py`.
- Wrapper RPC para `crear_reporte_con_validacion` (`bbdd.md` §5.3).
- El use case **solo invoca la RPC y mapea el resultado**. La atomicidad vive en SQL.
- Validar en el use case: `usuario.comuna_id` está seteado (si no, derivar de lat/lng o rechazar — decidir al implementar).

### 5c. `GET /api/v1/reportes/mios` (paginado)
- Use case `listar_reportes_propios` con cursor `(created_at, id)`.
- Encoding del cursor: base64 de JSON con esos dos campos.

### 5d. `GET /api/v1/reportes/comuna/{id}` (paginado, municipal)
- Mismo shape que 5c pero con `current_user_municipal_de_comuna(id)`.

### 5e. `GET /api/v1/reportes/{id}` (detalle)
- Use case `obtener_reporte` con permisos: dueño o municipal de la comuna del reporte.

### 5f. `PATCH /api/v1/reportes/{id}/estado`
- Use case `cambiar_estado_reporte`.
- Validar máquina de estados (`bbdd.md` §7) y comentario obligatorio para `Descartado`.
- Si transición es `En espera → En atencion`, setear `atendido_por_id = current_user.id`.

**Done when:**
- Los 6 endpoints responden los shapes de `api.md` §4.4–§4.9.
- Test manual con `curl` + JWT genuino de Supabase:
  - Crear reporte → 201 con `lectura_evidencia` poblada si hay sensor con lectura alta cerca.
  - Cambiar estado saltando "En atencion" → 409.
  - Funcionario de otra comuna → 403.

---

## Paso 6 — Ingestor MQTT

**Dependencias:** paso 2 (estructura) + paso 1 (DB lista).

**Spec:** [`iot.md`](./iot.md) (entero) + [`backend.md`](./backend.md) §5.2.

**Tareas:**
- Crear `app/infrastructure/mqtt/ingestor.py` con clase `MqttIngestor`:
  - Conexión con TLS (puerto 8883), reconexión con backoff (paho-mqtt nativo).
  - Subscribe a `40db/sensores/+/lectura` con QoS 1.
  - `on_message`: extraer `sensor_id` del topic, parsear JSON, validar payload (`iot.md` §3.2), verificar que `sensor_id` existe (con cache), invocar `registrar_lectura`.
- Crear `app/application/registrar_lectura.py`.
- Crear `app/infrastructure/db/lectura_repo.py` con `INSERT ... ON CONFLICT DO NOTHING`.
- En `app/main.py` `lifespan`: arrancar `MqttIngestor` en `asyncio.create_task(...)` si las vars MQTT existen; logear "MQTT deshabilitado" si no.
- Exponer estado del ingestor para `/health/ready` (paso 3).

**Done when:**
- Si MQTT no configurado, FastAPI levanta y `/health/ready` reporta `mqtt: "disabled"`.
- Con MQTT configurado, publicar un mensaje válido en `40db/sensores/<id-existente>/lectura` resulta en un row en `lectura`.
- Publicar el mismo mensaje 2 veces: solo 1 row (UNIQUE absorbe).
- Publicar payload malformado: `WARNING` en logs, ingestor sigue procesando.

---

## Paso 7 — Heatmap

**Dependencias:** paso 1 + paso 2.

**Spec:** [`api.md`](./api.md) §4.3 + [`bbdd.md`](./bbdd.md) §5.4 + [`backend.md`](./backend.md) §5.3.

**Tareas:**
- Agregar `heatmap()` a `LecturaRepository` que ejecuta la SQL de `bbdd.md` §5.4.
- Crear `app/application/obtener_heatmap.py`.
- Crear route en `app/api/routes/heatmaps.py` con validación de bbox + ventana + bucket.
- Serializar a `FeatureCollection` GeoJSON (`api.md` §4.3).
- Endpoint público (sin `Depends(current_user)`).

**Done when:**
- `GET /api/v1/heatmaps?bbox=...&time_start=...&time_end=...&bucket_minutes=5` devuelve GeoJSON válido.
- Validaciones: 422 con ventana > 7 días, bucket no permitido, bbox malformado.

---

## Paso 8 — Endpoints auxiliares y onboarding

**Dependencias:** paso 4.

**Spec:** [`api.md`](./api.md) §4.10–§4.13.

**Tareas:**
- `GET /api/v1/usuarios/me`.
- `PATCH /api/v1/usuarios/me` (telefono + comuna_id). Validar que `comuna_id` existe.
- `GET /api/v1/comunas` (público).
- `GET /api/v1/tipos-estado` (público).

**Done when:** los 4 endpoints responden el shape de `api.md`.

---

## Paso 9 — Tests mínimos

**Dependencias:** pasos previos según qué se teste.

**Tareas:**
- Setup de `pytest` + `httpx` + `pytest-asyncio`.
- Tests de happy path para `POST /reportes`, `PATCH /reportes/{id}/estado`, `GET /heatmaps`.
- Test de auth: 401 sin token, 403 cross-comuna.
- Test de máquina de estados: salto prohibido → 409.
- Tests de RPCs con `pgTAP` o queries directas (opcional pero recomendado).

**Done when:** `pytest` corre verde con cobertura de happy paths.

---

## Resumen visual de dependencias

```
0. Bootstrap
   │
   ├──▶ 1. Migración SQL ────────┐
   │                              │
   └──▶ 2. Estructura carpetas ───┤
                │                  │
                ▼                  │
         3. Errores + health       │
                │                  │
                ▼                  │
         4. Auth (current_user)    │
                │                  │
                ├──▶ 5. Reportes ◀─┤
                │                  │
                ├──▶ 6. MQTT  ◀────┤
                │                  │
                ├──▶ 7. Heatmap ◀──┘
                │
                └──▶ 8. Auxiliares
                       │
                       ▼
                  9. Tests
```

Pasos 5, 6, 7, 8 son **paralelizables** entre sí una vez completados 1–4.

---

## Excluido del MVP (no implementar)

Aunque aparezcan en roadmap de otros docs, **no** son parte de este plan:

- `validacion_iot` N:M (`bbdd.md` §10.1).
- Vistas materializadas (`bbdd.md` §10.4).
- **Automatización** de creación de particiones con `pg_partman` (`bbdd.md` §10.3). El particionamiento en sí **sí** está en el MVP (paso 1).
- SSE / WebSockets para heatmap "vivo" (`backend.md` §9).
- Endpoint admin de promoción de roles (`auth.md` §12).
- Topics MQTT `status`, `config`, `comandos` (`iot.md` §2.2).
- Rate limiting / Idempotency-Key (`api.md` §1 — API8).
- Observers reactivos que revaliden reportes al llegar lecturas altas (`backend.md` §9, explícitamente rechazado).
- Google OAuth / Magic links / MFA (`auth.md` §12).

Cuando alguno de estos surja como necesidad real, **primero actualizar el doc autoritativo**, después agregar al plan.
