# Backend — 40dB

Documento maestro de **arquitectura del backend** de la Plataforma de Inteligencia Acústica Municipal (40dB). Define el problema, las decisiones de alto nivel (ADRs), la estructura del proyecto y los puntos de entrada al resto de la documentación.

**Documentos hermanos** (ver [`README.md`](./README.md) para orden de lectura):
- [`bbdd.md`](./bbdd.md) — DDL, índices, triggers, RPC, RLS, máquina de estados.
- [`auth.md`](./auth.md) — autenticación, perfiles, OAuth, JWT.
- [`api.md`](./api.md) — contrato HTTP autoritativo (endpoints, shapes, status codes).
- [`errores.md`](./errores.md) — jerarquía de excepciones, mapeo HTTP, health checks.
- [`iot.md`](./iot.md) — contrato MQTT con el subsistema IoT.
- [`PLAN.md`](./PLAN.md) — orden de implementación al MVP.

---

## 1. Contexto del problema y objetivos

El backend de 40dB resuelve un sistema **híbrido transaccional + telemetría en tiempo real**: gestión de reportes ciudadanos de ruido molesto **+** ingesta continua de mediciones de sensores IoT, con el fin de **validar denuncias** con evidencia objetiva y **generar heatmaps acústicos** por zona y tiempo.

### Desafíos clave

1. **Asimetría de tráfico.** El flujo HTTP (reportes desde Vue 3) es esporádico; el flujo MQTT (sensores) es constante y de alta frecuencia. Una sola app FastAPI debe manejar ambos sin que el IoT bloquee al HTTP.
2. **Cruce geo-temporal.** Cuando un ciudadano envía un reporte, hay que cruzarlo con sensores cercanos (radio en metros) en una ventana temporal corta (minutos). Eso vive en Postgres con PostGIS, no en Python.
3. **Agregación para heatmap.** El volumen de `lectura` crece rápido; el frontend no puede recibir millones de puntos. Backend agrega/promedia por área y bucket temporal antes de enviar.
4. **Múltiples actores de entrada/salida.** HTTP (cliente web), MQTT (sensores), Postgres (persistencia + RPC). El acoplamiento entre ellos debe ser explícito y testeable.

---

## 2. Decisiones de arquitectura (ADR)

### ADR 01 — Framework: FastAPI
**Decisión.** FastAPI como único proceso orquestador del backend.
**Por qué.** Soporta HTTP asíncrono para el frontend y permite arrancar un loop MQTT de fondo via su manejador de `lifespan`. No introducir Celery/RQ para esto: agregaría infra para un caso que un async loop resuelve.
**Consecuencia.** Un solo deploy, un solo proceso. Si el loop MQTT crashea, el ciclo de vida lo reinicia.

### ADR 02 — Persistencia y auth: Supabase (Postgres + Auth)
**Decisión.** Supabase administrado como base de datos y proveedor de autenticación.
**Por qué.** Minimiza boilerplate (auth, migraciones, panel admin gratis). Postgres permite habilitar **PostGIS** para queries geo. La integración auth ↔ tabla de perfiles se resuelve con un trigger en `auth.users`.
**Consecuencia.** El backend habla con Supabase via cliente oficial Python. La `service_role_key` es secreta y vive solo en backend (ver ADR 07).
**Detalle de modelo:** [`bbdd.md`](./bbdd.md). Detalle de auth: [`auth.md`](./auth.md).

### ADR 03 — Ingesta IoT: MQTT vía HiveMQ Cloud
**Decisión.** Patrón publicador/suscriptor sobre un broker MQTT administrado (HiveMQ Cloud, tier gratuito).
**Por qué.** Evita complejidad de redes (puertos, DNS, NAT) para el prototipo y garantiza alta disponibilidad durante evaluación. El backend es **suscriptor**; los sensores publican.
**Consecuencia.** El backend necesita credenciales del broker en `.env`. Si HiveMQ se cae, los sensores idealmente bufferizan localmente (decisión de firmware, fuera de este doc).
**Detalle de topics, payload y lifecycle:** [`iot.md`](./iot.md).

### ADR 04 — Validación geo-temporal: RPC en Postgres
**Decisión.** La función `validar_reporte_ruido` vive en Postgres (PL/pgSQL + PostGIS). FastAPI la invoca durante `POST /reportes`.
**Por qué.** El cruce espacial-temporal es esencialmente SQL con `ST_DWithin` + índices GIST. Hacerlo en Python implicaría bajar datos a memoria, traduciendo lo que la DB hace en milisegundos a un loop ineficiente.
**Consecuencia.** La lógica de validación está **mitad en SQL** (matching) y **mitad en Python** (decisión de qué hacer con el resultado). Esto se documenta como pattern Strategy del lado Python (ver [`patterns.md`](./patterns.md)).
**SQL completo:** [`bbdd.md` §5](./bbdd.md).

### ADR 05 — Heatmap: on-demand fetching (no WebSockets)
**Decisión.** El frontend solicita datos del heatmap bajo demanda por área + ventana temporal. **No** se mantiene conexión persistente.
**Por qué.** El heatmap es histórico/agregado, no requiere actualización por segundo. WebSockets agregarían estado, complejidad y consumo de memoria sin beneficio real. Si se necesita "vivo" más adelante, se puede agregar SSE para una capa delgada de updates incrementales.
**Flujo.** `GET /api/v1/heatmaps?bbox=...&time_start=...&time_end=...&bucket_minutes=5` → backend agrega con PostGIS + buckets temporales → retorna GeoJSON ligero.

### ADR 06 — Arquitectura: hexagonal *lite*
**Decisión.** Aplicar **Ports & Adapters solo en los bordes I/O** (Supabase, MQTT, HTTP). El núcleo se organiza en capas pragmáticas (`domain` / `application` / `infrastructure` / `api`) sin mappers ni DTOs internos innecesarios.
**Por qué.** Hexagonal puro paga su costo en sistemas con dominio rico. En 40dB **gran parte de la lógica vive en Postgres** (RPC, triggers, índices); el dominio Python es orquestación delgada. Hexagonal estricto generaría boilerplate (entidades + mappers + DTOs) que duplica lo que `supabase-py` ya devuelve como dicts.
**Beneficio retenido.** Los puntos donde hexagonal **paga** sí los modelamos: puertos para `ReporteRepository`, `LecturaRepository`, etc., con adaptadores Supabase. Esto permite tests sin red y swapear Supabase → Postgres directo el día que convenga.
**Consecuencia.** El layout de carpetas (sección 3) refleja esta decisión. No se introducen frameworks de DI externos: `FastAPI.Depends()` basta.

### ADR 07 — RLS habilitada sin políticas; backend único cliente
**Decisión.** Todas las tablas tienen RLS activada **sin políticas explícitas**. El backend usa `service_role_key` que bypassa RLS por diseño.
**Por qué.** Garantiza que **ningún cliente del frontend** puede tocar Supabase directo. Toda autorización vive en FastAPI (use cases), centralizada y testeable. Diseñar políticas RLS granulares para un cliente que no existe sería trabajo perdido.
**Consecuencia.**
- La `service_role_key` **nunca** se expone al cliente.
- Si en el futuro algún flujo necesita cliente → Supabase directo (ej. real-time subscriptions), se diseñan políticas en ese momento. Ver [`bbdd.md` §6](./bbdd.md) y [`bbdd.md` §10.2](./bbdd.md).

---

## 3. Estructura del proyecto

Layout objetivo (alineado con hexagonal lite — ADR 06):

```text
40db-backend/
├── app/
│   ├── main.py                  # FastAPI app + lifespan (arranca MQTT)
│   ├── core/
│   │   ├── config.py            # Pydantic Settings (env vars)
│   │   └── supabase_client.py   # Cliente singleton de Supabase
│   ├── domain/                  # Núcleo: entidades + puertos
│   │   ├── entities.py          # Reporte, Sensor, Lectura, Usuario (dataclasses)
│   │   └── ports.py             # Protocols: ReporteRepository, LecturaRepository, …
│   ├── application/             # Casos de uso (orquestación pura)
│   │   ├── crear_reporte.py
│   │   ├── registrar_lectura.py
│   │   └── obtener_heatmap.py
│   ├── infrastructure/          # Adapters concretos (driven)
│   │   ├── db/
│   │   │   ├── reporte_repo.py  # SupabaseReporteRepository : ReporteRepository
│   │   │   ├── lectura_repo.py
│   │   │   └── rpc.py           # Wrapper de validar_reporte_ruido
│   │   └── mqtt/
│   │       └── ingestor.py      # Suscriptor MQTT (driving adapter)
│   ├── api/                     # Driving adapter HTTP (FastAPI)
│   │   ├── routes/
│   │   │   ├── reportes.py
│   │   │   └── heatmaps.py
│   │   ├── schemas/             # Pydantic request/response DTOs
│   │   │   ├── reporte.py
│   │   │   └── heatmap.py
│   │   └── deps.py              # Dependency Injection (Depends)
│   └── patterns/                # Composición interna: Strategy, Observer, …
│       ├── strategies/          # Algoritmos de validación intercambiables
│       ├── observers/           # Reactores al evento "lectura recibida"
│       └── validators/          # Reglas de negocio reusables
├── supabase/                    # Migraciones SQL + seed
│   ├── migrations/
│   └── seed.sql
├── docs/                        # Este conjunto de documentos
├── tests/
├── main.py                      # Atajo dev (puede llamar a app/main.py)
└── requirements.txt
```

**Migración desde el scaffold actual.** El repo ya tiene carpetas `routes/`, `services/`, `repositories/`, `iot/`, `middleware/`, `models/`, `schemas/`. Se mapean así al layout objetivo:

| Scaffold actual | Layout objetivo |
|---|---|
| `app/routes/` | `app/api/routes/` |
| `app/services/` | `app/application/` |
| `app/repositories/` | `app/infrastructure/db/` |
| `app/iot/` | `app/infrastructure/mqtt/` |
| `app/models/` | `app/domain/entities.py` (+ `domain/ports.py`) |
| `app/schemas/` | `app/api/schemas/` |
| `app/middleware/` | `app/api/middleware/` |
| `app/patterns/` | `app/patterns/` (se mantiene) |
| `app/core/` | `app/core/` (se mantiene) |

La migración no es prioritaria; puede hacerse al implementar el primer endpoint para no romper nada antes.

---

## 4. Composición en runtime

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI process                           │
│                                                                  │
│   lifespan startup:                                              │
│     1. cargar Settings desde .env                                │
│     2. inicializar supabase_client (singleton)                   │
│     3. arrancar MqttIngestor en async task                       │
│                                                                  │
│   ┌─────────────┐                       ┌──────────────────┐    │
│   │  HTTP API   │                       │  MQTT Ingestor   │    │
│   │  (uvicorn)  │                       │  (paho-mqtt)     │    │
│   └──────┬──────┘                       └─────────┬────────┘    │
│          │                                        │             │
│          ▼                                        ▼             │
│   ┌──────────────────────────────────────────────────────┐     │
│   │            application/  (use cases)                  │     │
│   │  crear_reporte · registrar_lectura · obtener_heatmap  │     │
│   └────────────────────────┬─────────────────────────────┘     │
│                            │                                    │
│                            ▼                                    │
│   ┌──────────────────────────────────────────────────────┐     │
│   │       domain/ports.py   (Protocols / interfaces)      │     │
│   └────────────────────────┬─────────────────────────────┘     │
│                            │ implementado por                   │
│                            ▼                                    │
│   ┌──────────────────────────────────────────────────────┐     │
│   │   infrastructure/db/   (Supabase adapters + RPC)      │     │
│   └────────────────────────┬─────────────────────────────┘     │
└────────────────────────────┼────────────────────────────────────┘
                             ▼
                      ┌─────────────┐
                      │  Supabase   │   (Postgres + Auth + RLS)
                      └─────────────┘
```

**Punto clave:** las flechas siempre apuntan hacia adentro. `api/` y `mqtt/` dependen de `application/`, que depende de `domain/ports.py`, que **no depende de nada**. `infrastructure/db/` también depende del `domain` (implementa sus puertos). Esto es lo que mantiene el dominio testeable.

---

## 5. Flujos clave (resumen)

### 5.1 Crear reporte con validación

El flujo combina **preview opcional iniciado por el usuario** (UX) y **validación server-side autoritativa** (seguridad). La RPC `validar_reporte_ruido` corre como mucho dos veces: una en el preview (a pedido del usuario) y otra en el insert (como red de seguridad o para verificar lo que el cliente declara).

**UX en el formulario del frontend:**

1. El ciudadano llena `titulo`, `descripcion`, `latitud`, `longitud`.
2. Opcionalmente clickea **"Verificar evidencia de micrófonos cercanos"**:
   - Frontend → `GET /api/v1/reportes/buscar-evidencia?lat=…&lng=…`.
   - Si hay match → la UI muestra "Encontramos una validación disponible (sensor *X* a *Y* m, *Z* dB)" + botón **"Añadir evidencia al reporte"**.
   - Si no hay match → diálogo "No se encontró evidencia" (no bloquea el envío).
3. Si el ciudadano clickea "Añadir evidencia", el frontend guarda el `lectura_evidencia_id` recibido en el estado local del form. Si no clickea, el form sigue sin id.
4. En el submit → `POST /api/v1/reportes` con el body completo, incluyendo `lectura_evidencia_id` solo si el usuario lo agregó en el paso 3.

**Endpoints involucrados:**

`GET /api/v1/reportes/buscar-evidencia?lat=…&lng=…`
- Stateless, no escribe nada.
- Invoca `validar_reporte_ruido(lat, lng, now())`.
- Response: `{ evidencia: { lectura_id, sensor_id, sensor_nombre, nivel_db, distancia_metros, timestamp_medicion } | null }`.

`POST /api/v1/reportes`
- Body: `{ titulo, descripcion, latitud, longitud, lectura_evidencia_id?: number }`.
- El use case `crear_reporte` **delega la atomicidad a una RPC compuesta**: `crear_reporte_con_validacion(p_usuario_id, p_comuna_id, p_titulo, p_descripcion, p_lat, p_lng, p_lectura_evidencia_id)`. La RPC corre en una sola transacción de Postgres y devuelve el reporte ya construido (con `lectura_evidencia_id` resuelto). Lógica interna de la RPC:
  1. INSERT en `reporte` (sin evidencia todavía). El trigger `set_initial_estado` agrega "En espera" automáticamente.
  2. **Si el body trajo `p_lectura_evidencia_id`** → re-correr la variante top-N de `validar_reporte_ruido` con `now()` y confirmar que ese id está en el resultado. Si pasa → adjuntar. Si no pasa → descartar silenciosamente y caer al paso 3.
  3. **Si no se adjuntó nada en el paso 2** → última corrida de `validar_reporte_ruido(lat, lng, now())` como red de seguridad ("apareció evidencia mientras el ciudadano llenaba el form"). Si retorna match → adjuntar; si no → queda sin evidencia (caso normal).
- Response 201 con el reporte completo. Si falla la transacción interna, la RPC hace `RAISE EXCEPTION` y el backend mapea a HTTP 5xx vía `errores.md`.
- Definición SQL de la RPC en [`bbdd.md` §5.2](./bbdd.md).

**Anti-forgery (paso 3).** El `lectura_evidencia_id` viene del cliente y por tanto no se confía. Sin verificación, un usuario podría inyectar el id de cualquier lectura alta de otra zona. La validación re-ejecuta `validar_reporte_ruido` (variante top-N) con `lat/lng/now()` del reporte y confirma que el id está en el resultado. Si no está → se descarta y se aplica el fallback del paso 4 (no se devuelve error al cliente).

**Staleness temporal.** La RPC usa ventana retrospectiva (10 min default). Si entre el preview y el submit el ciudadano demoró, la lectura previewada puede haber salido de la ventana. El paso 3 corre con `now()` del submit, no del preview — si la lectura ya no califica, se descarta sin error y se aplica el fallback. Transparente al usuario.

### 5.2 Ingesta de lectura IoT
1. Sensor publica en topic MQTT (ver [`iot.md`](./iot.md)).
2. `MqttIngestor.on_message` parsea payload.
3. Invoca use case `registrar_lectura`.
4. Use case usa `LecturaRepository.insert(...)`.

> **Nota.** El backend **no** revalida reactivamente reportes "En espera" cercanos al llegar una lectura alta. La validación es pull (paso 4 de §5.1 corre en el submit) o explícita (preview iniciado por el usuario en §5.1 paso 2). Si en el futuro se requiere matching reactivo, ver §8.

### 5.3 Heatmap on-demand

`GET /api/v1/heatmaps?bbox=…&time_start=…&time_end=…&bucket_minutes=5` (contrato completo en [`api.md`](./api.md) §4.3).

**Estrategia de agregación.** Lat/lng se redondean a una **grilla raw de 0.001°** (~100 m por celda). Cada celda + bucket temporal produce un punto del heatmap con métricas agregadas. Sin H3 ni geohash extension — para volumen MVP, redondear + `GROUP BY` es suficiente y no requiere extensiones extra.

**Pipeline:**
1. FastAPI parsea bbox + ventana + `bucket_minutes`.
2. Validaciones: ventana ≤ 7 días, `bucket_minutes ∈ {1, 5, 15, 60}`, bbox válido.
3. Use case `obtener_heatmap` invoca `LecturaRepository.heatmap(...)` que ejecuta la query de agregación en Postgres (SQL en [`bbdd.md`](./bbdd.md) §5.3).
4. Cada row del resultado se serializa a un `Feature` GeoJSON con `Point` en el centro de la celda + properties (`nivel_db_avg`, `nivel_db_max`, `lectura_count`, `bucket_start`).
5. Response: `FeatureCollection` con metadata (`bucket_minutes`, `grid_size_deg`, `total_cells`).

**Performance.** Con índice `idx_lectura_timestamp` + `idx_sensor_ubicacion` (GIST), un bbox urbano sobre 24 h se resuelve en O(100 ms). Si crece volumen y se nota lentitud, primero subir el `bucket_minutes` mínimo permitido; si aún no alcanza, ir a vista materializada (`bbdd.md` §10.4) o particionamiento (`bbdd.md` §10.3).

**Caching.** Sin cache en MVP. Si se vuelve hotspot, agregar `Cache-Control: public, max-age=60` y/o un cache en memoria por hash de query.

---

## 6. Patrones de diseño aplicados (resumen)

Detalle completo en [`patterns.md`](./patterns.md). Resumen:

| Patrón | Uso |
|---|---|
| Repository | `domain/ports.py` define interfaces; `infrastructure/db/` las implementa contra Supabase. |
| Adapter | `MqttIngestor` y `SupabaseClient` envuelven librerías externas detrás de APIs propias. |
| Strategy | Algoritmos de validación intercambiables (`patterns/strategies/`). |
| Observer | Reactores al evento "nueva lectura" — desacopla pipeline IoT. |
| Factory | Selección de Strategy según parámetros del reporte. |
| Dependency Injection | `FastAPI.Depends()` inyecta repos en use cases, use cases en routes. |
| DTO | Pydantic schemas en `api/schemas/` separan contrato HTTP del dominio. |

---

## 7. Stack y versiones

- **Python** 3.11+
- **FastAPI** + **uvicorn[standard]**
- **supabase-py** (cliente oficial)
- **paho-mqtt** (cliente MQTT)
- **pydantic-settings** para configuración
- **PostgreSQL 15+** con **PostGIS** (provisto por Supabase)

`requirements.txt` se irá poblando a medida que se implementen capas.

---

## 8. Configuración (variables de entorno)

Todas las variables se cargan via `pydantic-settings` en `app/core/config.py` y se exponen como `settings`. Si una variable obligatoria falta en boot, el proceso crashea con mensaje claro (ver [`errores.md`](./errores.md) §7).

### 8.1 Obligatorias

| Variable | Para qué | Ejemplo |
|---|---|---|
| `SUPABASE_URL` | URL del proyecto Supabase | `https://abc123.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Acceso al backend (bypassa RLS) | `eyJhbGciOi...` |
| `SUPABASE_JWT_SECRET` | Verificación local de JWT del cliente | string 32+ caracteres |
| `CORS_ORIGINS` | Origenes permitidos (CSV) | `http://localhost:5173,https://40db.cl` |

### 8.2 Opcionales (con default)

| Variable | Default | Para qué |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `API_PREFIX` | `/api/v1` | Prefijo de rutas de negocio. No cambiar salvo bump de versión. |
| `VALIDACION_RADIO_METROS` | 100 | Override de la RPC `validar_reporte_ruido` |
| `VALIDACION_VENTANA_MINUTOS` | 10 | Override de la RPC |
| `VALIDACION_UMBRAL_DB` | 65 | Override de la RPC |
| `HEATMAP_GRID_SIZE_DEG` | 0.001 | Tamaño de celda del heatmap (~100 m) |
| `HEATMAP_MAX_WINDOW_DAYS` | 7 | Ventana temporal máxima del query |

### 8.3 MQTT (opcionales — si faltan, el ingestor no arranca pero HTTP sí)

| Variable | Para qué | Ejemplo |
|---|---|---|
| `MQTT_BROKER_URL` | URL del broker con TLS | `ssl://abc.s1.eu.hivemq.cloud:8883` |
| `MQTT_USER` | Usuario subscriber del backend | `backend-subscriber` |
| `MQTT_PASSWORD` | Password | `<secret>` |
| `MQTT_CLIENT_ID` | (opcional) ID del cliente paho | `40db-backend-prod` |

Detalle del subsistema MQTT en [`iot.md`](./iot.md).

### 8.4 Convención

- `.env.example` en la raíz lista todas las variables con valores placeholder (sin secretos reales).
- `.env` está en `.gitignore`.
- En CI/prod, las variables vienen del orquestador (no de archivos `.env`).

---

## 9. Roadmap arquitectónico

Cambios postergados pero documentados:

- **Validación IoT N:M** con score y método (auto/manual). Ver [`bbdd.md` §10.1](./bbdd.md). Requiere reintroducir tabla `validacion_iot`.
- **SSE para heatmap "vivo"** si surge requerimiento UX.
- **Matching reactivo de reportes en espera** al llegar lecturas altas (no implementado; el flujo actual es pull, ver §5.1 / §5.2).
- **Vista materializada** para heatmap si performance lo exige. Ver [`bbdd.md` §10.4](./bbdd.md).
- **Particionamiento de `lectura`** por mes cuando se acumule volumen. Ver [`bbdd.md` §10.3](./bbdd.md).
