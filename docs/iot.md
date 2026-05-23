# IoT / MQTT — 40dB

Documento del **contrato MQTT** entre los sensores acústicos (firmware ESP32 + micrófono) y el backend FastAPI. Cubre topics, payload, QoS, autenticación con el broker, manejo backend y provisioning de sensores.

> ⚠️ **Importante.** El subsistema IoT (firmware del ESP32 + integración con HiveMQ) lo implementa **otro miembro del equipo**, no este backend. Este documento es el **contrato de integración**: define lo que el backend espera recibir. Los detalles internos del firmware (cómo se mide, cómo se promedia el dB, cómo se reconecta el sensor a WiFi) son **decisión del equipo IoT**, pero los campos que el backend lee están fijados acá.
>
> Las secciones marcadas con 🔒 son decisiones tomadas (no negociables sin coordinación). Las 🤝 son puntos abiertos con el equipo IoT.

> 🚧 **Estado actual del firmware (2026-05-22).** El `.ino` actual del prototipo (`../contexto/sensor_ruido_40db/sensor_ruido_40db.ino`) **diverge** del contrato definido acá. Las divergencias se documentan en §0 para que cuando se actualice el firmware quede claro qué tiene que cambiar. **El backend implementa este contrato, no lo que el firmware actual emite** — el alineamiento queda pendiente del lado firmware.

**Documentos relacionados:**
- [`backend.md`](./backend.md) §5.2 — flujo de ingesta a alto nivel.
- [`bbdd.md`](./bbdd.md) §3.4 / §3.5 — tablas `sensor` y `lectura` (particionada).
- [`errores.md`](./errores.md) §7.2 — política de fallo MQTT.
- [`api.md`](./api.md) — el backend no expone los datos crudos de MQTT vía HTTP; se sirven agregados (heatmap).

---

## 0. Divergencias firmware ↔ contrato (estado conocido)

Snapshot del `.ino` actual contra lo que este documento exige. Cada fila bloqueante (🔴) impide que un mensaje del firmware se ingeste correctamente; las 🟡 son aceptables temporalmente pero deben cerrarse antes de producción.

| Aspecto | Firmware actual (`.ino`) | Contrato (este doc) | Sev. |
|---|---|---|---|
| Topic | `40db/sensors/UE-MAI-0001/readings` | `40db/sensores/{sensor_id}/lectura` (§2.1) | 🔴 |
| `sensor_id` en el topic | slug humano `UE-MAI-0001` | UUID de `public.sensor.id` (§2.1, §3.1) | 🔴 |
| Campo dB en el payload | `db` | `nivel_db` (§3.1) | 🔴 |
| `timestamp_medicion` | `millis()` (uptime del MCU) | ISO 8601 UTC con NTP (§3.1, §6.2) | 🔴 |
| Campos extra en payload | `sensor_id`, `geo: {lat, lng}` | solo `nivel_db` + `timestamp_medicion` (§3.1) | 🟡 (backend ignora silencioso) |
| QoS | 0 (default `PubSubClient`) | 1 (§1, I5) | 🟡 (afecta idempotencia) |
| TLS | `setInsecure()` (sin verificación de cert) | TLS con verificación (§1, I9) | 🟡 |
| Frecuencia | 5s fijo | 10s base, ráfaga 2s al superar 80 dB (§4) | 🟢 (aceptable) |
| Auth MQTT | credencial compartida (`40db-sensor`) | per-sensor recomendado (§5.1) | 🟢 (§5.2 lo admite) |

**Decisión sobre `sensor_id` (cierra una 🤝).** El topic usa **el UUID de `public.sensor.id`** (canónico, lowercase, con guiones). No usamos slugs humanos como `UE-MAI-0001`: el slug es útil para humanos pero no es PK ni se garantiza único contra renombramientos. El UUID es estable y matchea la FK que `lectura.sensor_id` necesita. Si el equipo IoT prefiere un slug en el firmware por legibilidad de logs, lo agregamos como **columna extra `codigo` en `sensor`** y el firmware sigue usando UUID en el topic.

**Decisión sobre el timestamp (cierra una 🤝).** El firmware **debe sincronizar NTP** (suficiente con `configTime()` apuntando a `pool.ntp.org`) y mandar ISO 8601 UTC. La opción "backend setea `now()` si el timestamp es sospechoso" se descarta para el MVP porque mete una rama de comportamiento poco testeable en el ingestor; preferimos el invariante simple "el timestamp del payload manda".

**Mientras el firmware no se actualice**, el backend no recibirá lecturas válidas — la tabla `lectura` se llenará con seed para desarrollo (`bbdd.md` §8) y las RPCs de validación retornarán vacío en producción real.

---

## 1. Decisiones del contrato

| # | Decisión | Tipo | Justificación |
|---|---|---|---|
| I1 | **Broker MQTT administrado: HiveMQ Cloud (tier gratuito)** | 🔒 | Decisión de arquitectura (ADR 03 en `backend.md`). |
| I2 | **El backend es subscriber, los sensores son publishers** | 🔒 | Patrón pub/sub estándar; backend no inicia conexión a sensores. |
| I3 | **Cada sensor publica en su propio topic**: `40db/sensores/{sensor_id}/lectura` | 🔒 | `{sensor_id}` = UUID de `public.sensor.id` (canónico, lowercase, con guiones). Topic per-sensor permite suscripciones granulares en debug y ACLs por wildcard. Cerrado en §0. |
| I4 | **Payload JSON** con campos: `nivel_db` (numeric), `timestamp_medicion` (ISO 8601 UTC) | 🔒 | JSON > binario para prototipo (debuggable). Si el volumen escala (ver §4 y `bbdd.md` §3.5), evaluar MessagePack o Protobuf. Cerrado en §0. |
| I5 | **QoS 1 (at-least-once)** | 🔒 | Para sensores ambientales, perder lecturas ocasionales es tolerable, pero QoS 1 con idempotencia (I7) da una garantía razonable sin la complejidad de QoS 2. El firmware actual usa QoS 0 — debe subir a 1. |
| I6 | **No retain** flag en mensajes | 🔒 | Lecturas son time-series, no estado. Un suscriptor nuevo no debería recibir la "última lectura" como si fuera actual. |
| I7 | **Idempotencia: `(sensor_id, timestamp_medicion)` es UNIQUE en `lectura`** | 🔒 | QoS 1 puede duplicar. La UNIQUE constraint absorbe duplicados sin error. Sigue siendo válida tras particionamiento (`bbdd.md` §3.5). |
| I8 | **Autenticación: usuario/password por sensor en HiveMQ** | 🤝 | Cada sensor tiene credenciales propias para que la pérdida de una no comprometa la red. Alternativa más simple: un user compartido (ver §5.2). El firmware actual usa shared — aceptable mientras no haya promoción a producción. |
| I9 | **TLS obligatorio** (puerto 8883) con verificación de certificado | 🔒 | HiveMQ Cloud lo exige; además, las lecturas pueden derivar PII (ubicación + tiempo). El `setInsecure()` del firmware actual debe reemplazarse por verificación del cert raíz de HiveMQ. |
| I10 | **`lectura` es tabla particionada por mes** (Postgres native) | 🔒 | Diseño para 30 sensores a 5–10s sin TimescaleDB (no disponible en Supabase). Implicaciones del lado backend: ninguna — el INSERT `ON CONFLICT` ignora la partición. Ver `bbdd.md` §3.5 / D8. |

---

## 2. Topics

### 2.1 Lecturas (sensor → backend)

```
40db/sensores/{sensor_id}/lectura
```

- `{sensor_id}` es el `UUID` de `public.sensor.id`, en formato canónico con guiones (lowercase).
- Ejemplo: `40db/sensores/1e2c8b3f-...-9a/lectura`
- El backend se suscribe con wildcard: `40db/sensores/+/lectura`.

### 2.2 Topics futuros (roadmap, no implementados en MVP)

| Topic | Dirección | Para qué |
|---|---|---|
| `40db/sensores/{id}/status` | sensor → backend | Heartbeat / estado (online, batería, RSSI). Retain=true. |
| `40db/sensores/{id}/config` | backend → sensor | Push de configuración remota (intervalo de muestreo, umbral). Retain=true. |
| `40db/sensores/{id}/comandos` | backend → sensor | Comandos puntuales (reboot, recalibrar). QoS 1, no retain. |

Por ahora **el contrato MVP es solo `/lectura`**.

---

## 3. Payload

### 3.1 Schema (JSON)

```json
{
  "nivel_db": 67.3,
  "timestamp_medicion": "2026-05-19T22:14:33.421Z"
}
```

| Campo | Tipo | Obligatorio | Reglas |
|---|---|---|---|
| `nivel_db` | `number` | ✅ | Rango razonable: 20 a 130. Precisión: 2 decimales. |
| `timestamp_medicion` | `string` | ✅ | ISO 8601, **UTC** (terminado en `Z` o `+00:00`). Si el sensor no tiene NTP confiable, ver §6.2. |

### 3.2 Campos rechazados o ignorados

El backend **descarta** mensajes que:
- No sean JSON parseable.
- Falten campos requeridos.
- Tengan `nivel_db` fuera del rango sano (negativo, > 200).
- Tengan `timestamp_medicion` > 5 minutos en el futuro (skew de reloj sospechoso).
- Tengan `timestamp_medicion` > 24 h en el pasado (lectura demasiado vieja; probablemente bug del sensor).

En todos los casos: log `WARNING` con el payload truncado + `sensor_id` extraído del topic, y se continúa procesando los siguientes mensajes.

### 3.3 Tamaño esperado

Payload típico < 100 bytes. Si el equipo IoT decide agregar campos (`bateria`, `rssi`, `temperatura`), confirmar acá antes de codear el parser del backend.

---

## 4. Frecuencia de muestreo y volumen

**Política de muestreo:**
- Una lectura cada **10 segundos** por sensor en operación normal.
- Si `nivel_db > 80`, subir a una cada **2 segundos** durante 1 minuto, después volver al ritmo normal.
- Si la conexión MQTT cae, **buffer local** en el ESP32 (filesystem o RAM circular) y reenvío al reconectar (decisión del firmware, fuera de este doc).

**Proyección de volumen** (alimenta la decisión de particionamiento, D8 en `bbdd.md`):

| Escenario | Lecturas/sensor/día | Total/día | Total/mes (1 partición) | Total/año |
|---|---|---|---|---|
| 1 sensor @ 10 s | 8.640 | 8.640 | ~260k | ~3.2M |
| 10 sensores @ 10 s | 8.640 | 86.400 | ~2.6M | ~32M |
| 30 sensores @ 10 s (objetivo) | 8.640 | 259.200 | ~7.9M | ~95M |
| 30 sensores @ 5 s (firmware actual) | 17.280 | 518.400 | ~15.5M | ~189M |

Con particiones mensuales, cada `lectura_YYYY_MM` se mantiene entre 8M y 16M rows en el escenario objetivo — tamaño cómodo para los índices btree/GIST. Sin particionamiento, la tabla monolítica llegaría a ~100M+ rows en un año y el `VACUUM`/`ANALYZE` empezaría a doler.

**Cuándo revisar:** si la cadencia base baja de 10s a 5s **en producción** (no solo en el prototipo de un solo sensor), recalcular y considerar adoptar `pg_partman` para automatizar (ver `bbdd.md` §10.3).

---

## 5. Autenticación al broker

### 5.1 Propuesta (recomendada): credenciales por sensor 🤝

Cada sensor tiene su propio `mqtt_user` / `mqtt_password` configurados en HiveMQ con ACL restrictiva:

```
ACL: user=sensor-1e2c..., puede PUBLISH a 40db/sensores/1e2c.../+
```

Esto requiere:
- Generar credenciales al provisionar cada sensor.
- Almacenarlas en HiveMQ Cloud (panel admin o API).
- Flashearlas en el firmware del sensor.

**Pro:** comprometer un sensor solo permite publicar como ese sensor.
**Contra:** overhead operacional (un set de credenciales por dispositivo).

### 5.2 Alternativa: credenciales compartidas 🤝

Un solo `mqtt_user` compartido por todos los sensores, con ACL `40db/sensores/+/+`.

**Pro:** mínimo overhead.
**Contra:** si las credenciales se filtran de un sensor, cualquiera puede publicar como cualquier sensor.

**Recomendación del backend:** ir con **5.1** desde el inicio. El backend confía en que el `sensor_id` del topic es legítimo (validado por ACL del broker). Si se va con 5.2, el backend debería verificar que el `sensor_id` existe en la tabla `sensor` y rechazar topics con id desconocido — lo cual de hecho ya hacemos (sección 6.1), así que el extra de 5.1 es la garantía de que un sensor no puede falsificar identidad de otro.

### 5.3 Backend → broker

El backend se conecta como **subscriber** con credenciales propias (env vars `MQTT_USER`, `MQTT_PASSWORD`), con ACL solo para `SUBSCRIBE 40db/#`.

---

## 6. Manejo en el backend

### 6.1 Pipeline de procesamiento

```
mensaje MQTT en 40db/sensores/{id}/lectura
   │
   ▼
MqttIngestor.on_message
   │
   ├── 1. Extraer sensor_id del topic
   ├── 2. Parsear payload JSON
   ├── 3. Validar payload (schema + rangos)
   ├── 4. Verificar que sensor_id existe en public.sensor (cache TTL ~5 min)
   │       └── si no existe → log WARNING, descartar
   ├── 5. Invocar use case registrar_lectura(sensor_id, nivel_db, timestamp_medicion)
   │       └── INSERT INTO lectura ... ON CONFLICT (sensor_id, timestamp_medicion) DO NOTHING
   └── 6. Log INFO con (sensor_id, nivel_db, timestamp_medicion)
```

**Implementación:** `app/infrastructure/mqtt/ingestor.py` (driving adapter). El use case `registrar_lectura` vive en `app/application/` y depende del puerto `LecturaRepository`.

### 6.2 Skew de reloj

Si el ESP32 no tiene NTP confiable y manda timestamps incorrectos, el heatmap se distorsiona. Mitigaciones:
- **Validación:** ver §3.2 (rechazo de timestamps > 5 min futuros o > 24 h pasados).
- **Roadmap:** que el backend setee `timestamp_medicion = now()` si el del payload es `null` o sospechoso. Por ahora confiamos en el sensor.

### 6.3 Idempotencia

```sql
ALTER TABLE lectura ADD CONSTRAINT uq_lectura_sensor_timestamp
  UNIQUE (sensor_id, timestamp_medicion);

INSERT INTO lectura (sensor_id, nivel_db, timestamp_medicion)
VALUES ($1, $2, $3)
ON CONFLICT (sensor_id, timestamp_medicion) DO NOTHING;
```

Con esto, QoS 1 puede entregar duplicados sin generar errores ni rows duplicados. **Pendiente:** agregar esta UNIQUE en la migración (ver `bbdd.md` §3.5).

### 6.4 Lifecycle del cliente MQTT

```
FastAPI lifespan startup:
  1. Si MQTT_BROKER_URL / MQTT_USER / MQTT_PASSWORD existen → arrancar MqttIngestor
  2. Si no → log "MQTT deshabilitado", FastAPI sigue (modo HTTP-only)

MqttIngestor:
  - Conexión con TLS (puerto 8883)
  - Subscribe a 40db/sensores/+/lectura con QoS 1
  - on_disconnect → backoff exponencial (1s → 2s → 4s → … → max 60s), reintentar
  - on_message → procesar (ver §6.1). Si throw, log ERROR y continuar.

FastAPI lifespan shutdown:
  - Llamar a MqttIngestor.disconnect() limpiamente.
```

### 6.5 Concurrencia

`paho-mqtt` callback corre en su propio thread. El use case `registrar_lectura` invoca al `LecturaRepository` (que usa `supabase-py`, sincrónico). Si el volumen escala, evaluar `aiomqtt` (async) y un repo async. Por ahora **sync está bien para el volumen MVP**.

---

## 7. Provisioning de sensores

### 7.1 Alta de un sensor nuevo

Manual en MVP (no hay endpoint admin):

1. Insertar row en `public.sensor` vía SQL editor de Supabase:
   ```sql
   INSERT INTO sensor (comuna_id, nombre, latitud, longitud)
   VALUES (13, 'Plaza Italia - Norte', -33.4372, -70.6483)
   RETURNING id;
   ```
2. Crear credenciales en HiveMQ Cloud para `sensor-{id}` (ver §5.1).
3. Flashear el ESP32 con: WiFi creds, MQTT broker URL, sensor_id, mqtt_user, mqtt_password.
4. (Recomendado) Verificar conectividad publicando una lectura de prueba y chequeando que aparece en `lectura`.

**Roadmap:** endpoint admin protegido para provisioning, una vez que haya rol `admin` (ver `auth.md` §12).

### 7.2 Baja / desactivación

Para "apagar" un sensor sin borrar histórico:
```sql
UPDATE sensor SET activo = false WHERE id = '...';
```
La RPC `validar_reporte_ruido` filtra por `sensor.activo = true`, así que las lecturas de un sensor desactivado no validan reportes nuevos. Las lecturas históricas siguen apareciendo en el heatmap (decisión: las queremos para el record).

---

## 8. Variables de entorno (backend)

```bash
# .env (sección MQTT)
MQTT_BROKER_URL=ssl://abc123.s1.eu.hivemq.cloud:8883
MQTT_USER=backend-subscriber
MQTT_PASSWORD=<secret>
MQTT_CLIENT_ID=40db-backend-prod   # opcional; si no, paho genera uno
```

Si alguna está ausente, el ingestor no arranca pero el resto del backend sí (ver `errores.md` §7.2).

---

## 9. Cambios pendientes en el firmware

El firmware está bajo control de este equipo (no de un externo). La lista de cambios necesarios para cerrar las 🔴 de §0:

1. **Topic:** cambiar `40db/sensors/{slug}/readings` → `40db/sensores/{uuid}/lectura`. El `{uuid}` debe ser el UUID provisionado al crear la fila en `public.sensor`.
2. **Payload:**
   - Renombrar `db` → `nivel_db`.
   - Reemplazar `timestamp: millis()` por ISO 8601 UTC (`configTime(0, 0, "pool.ntp.org")` + `strftime("%Y-%m-%dT%H:%M:%SZ", …)`).
   - Eliminar `sensor_id` y `geo` del body (el backend los obtiene del topic y de la tabla `sensor`).
3. **QoS:** el segundo argumento de `mqtt.publish(topic, payload, retained=false, qos=1)` — la API de `PubSubClient` requiere reemplazo por una versión que soporte QoS 1, o migrar a `AsyncMqttClient`/`PicoMQTT`. **Decisión de firmware**.
4. **TLS:** reemplazar `wifiClient.setInsecure()` por carga del cert raíz de HiveMQ Cloud (Let's Encrypt R3 o el que corresponda) con `wifiClient.setCACert(...)`.
5. **Frecuencia:** el `delay(5000)` puede quedarse en 5s para el prototipo de 1 sensor, pero al escalar a varios sensores **subir a 10s base** (§4).

**Puntos abiertos (🤝) que persisten:**
- I8 (credenciales por sensor vs compartidas) — decisión queda postergada hasta que haya >1 sensor real desplegado.
- Si se agregan campos al payload (batería, RSSI, temperatura), confirmar antes para que el parser del backend los acepte.

Cuando un punto se cierra, actualizar la columna "Tipo" en §1 de 🤝 a 🔒 y la tabla de §0 (si aplica).
