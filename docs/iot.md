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

📋 **Plan ejecutable para cerrar estas divergencias y conectar el flujo E2E**: ver `§10` al final de este documento.

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
| I8 | **Autenticación HiveMQ híbrida MVP: backend dedicado + publisher compartido** | 🔒 (MVP) / 🤝 (escala) | El backend usa `backend-subscriber` con ACL `SUBSCRIBE 40db/#` (solo lee). Los sensores comparten un único user `40db-sensor` con ACL `PUBLISH 40db/sensores/+/lectura` mientras haya 1 sensor en MVP. Cuando entren más sensores, migrar a credenciales por-sensor (§5.1) — sigue 🤝 para esa fase. Cerrado para MVP en §10. |
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

---

## 10. Plan de implementación IoT (E2E)

Plan ejecutable que cierra todas las 🔴 de §0 y conecta el flujo completo **sensor → HiveMQ → backend → DB**. Asume estado actual (2026-05-23):
- Backend desplegado en Render free tier, validado en smoke test.
- Supabase online con el schema definitivo (partición + FK compuesta).
- Cluster HiveMQ Cloud activo, ya recibiendo mensajes del firmware actual (formato divergente).
- ESP32 + KY-038 físicamente disponibles, prestados por un compañero.
- Sin WiFi propio configurado todavía. Sin sensor provisionado en `public.sensor`.

### 10.1 Pre-requisitos

| Recurso | Estado | Acción si falta |
|---|---|---|
| Cluster HiveMQ Cloud | ✅ existe | – |
| Credenciales actuales `40db-sensor` (publisher) | ✅ funcionando | – |
| Acceso al panel HiveMQ Cloud | 🤔 verificar | Login a console.hivemq.cloud |
| Supabase online linked | ✅ aplicado en smoke | – |
| Backend desplegado en Render | ✅ smoke OK | – |
| Variables MQTT en Render | ❌ falta | §10.5 |
| Comuna "Maipú" en seed/DB | ❌ falta (seed tiene solo Santiago/Providencia/Las Condes) | §10.2 paso 1 |
| Sensor en `public.sensor` con UUID conocido | ❌ falta | §10.2 paso 2 |
| User `backend-subscriber` en HiveMQ | ❌ falta | §10.3 |
| ESP32 reconfigurado | ❌ está con creds/WiFi del compañero | §10.4 |
| Cert raíz CA de HiveMQ Cloud | ❌ pendiente descarga | §10.4 paso 4 |

### 10.2 Provisioning del sensor en Supabase

**Paso 1 — Asegurar la comuna en `comuna`.**

El seed actual solo tiene Santiago/Providencia/Las Condes. El sensor del .ino está en Villa El Abrazo, Maipú (-33.5180, -70.7580). Insertar Maipú:

```sql
INSERT INTO comuna (nombre, region, codigo)
VALUES ('Maipú', 'Metropolitana', '13119')
ON CONFLICT (codigo) DO NOTHING;
```

(Código `13119` es el oficial del INE chileno para Maipú; verificar si el seed cambia política de códigos.)

**Paso 2 — Crear el sensor y guardar el UUID.**

```sql
INSERT INTO sensor (comuna_id, nombre, latitud, longitud)
VALUES (
  (SELECT id FROM comuna WHERE codigo='13119'),
  'Villa El Abrazo - Maipu',
  -33.5180,
  -70.7580
)
RETURNING id;
```

El UUID retornado (formato `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) es lo que va al firmware como `SENSOR_ID`. **Guardalo en un lugar seguro** (1Password, nota local) — lo vas a usar dos veces (firmware + HiveMQ ACL si más adelante se mueve a per-sensor).

**Paso 3 — Verificación.**

```sql
SELECT id, nombre, latitud, longitud, ST_AsText(ubicacion) AS geo
FROM sensor WHERE nombre='Villa El Abrazo - Maipu';
```

Debe mostrar `POINT(-70.758 -33.518)` (longitud primero, latitud segundo — convención PostGIS).

### 10.3 HiveMQ: crear `backend-subscriber`

En el panel de HiveMQ Cloud → Access Management → Credentials:

1. **Crear nuevo credential:**
   - Username: `backend-subscriber`
   - Password: generar uno fuerte (32+ chars), guardar en password manager
2. **ACL para ese credential:**
   - Topic filter: `40db/#`
   - Permission: **Subscribe** únicamente (no Publish)
3. **Verificar que el credential del publisher (`40db-sensor`) sigue activo** y solo tiene permiso de **Publish** sobre `40db/sensores/+/lectura`. Si tenía ACL abierta (`#` con publish+subscribe), restringirla ahora — principio de mínimo privilegio.

Anotar: `MQTT_BROKER_URL`, `MQTT_USER=backend-subscriber`, `MQTT_PASSWORD=<generado>`.

### 10.4 Cambios al firmware ESP32

Diff contra `sensor_ruido_40db.ino` actual. Mantener la estructura de archivos pero modificar las siguientes secciones:

**1. Identidad del sensor (líneas 7-9):**

```c
// ANTES
const char* SENSOR_ID = "UE-MAI-0001";
const float LAT = -33.5180;
const float LNG = -70.7580;

// DESPUÉS — UUID provisionado en §10.2 paso 2. LAT/LNG ya no se publican
// (el backend los lee de public.sensor); solo se mantienen como referencia humana.
const char* SENSOR_ID = "PEGAR_UUID_DE_10.2_PASO_2";
```

**2. WiFi (líneas 12-13):**

```c
// ANTES (red del compañero)
const char* WIFI_SSID = "Saavedra";
const char* WIFI_PASS = "Matias200300400";

// DESPUÉS — tu red
const char* WIFI_SSID = "TU_SSID";
const char* WIFI_PASS = "TU_PASSWORD";
```

**3. MQTT (líneas 15-20):**

```c
// ANTES
const char* MQTT_TOPIC = "40db/sensors/UE-MAI-0001/readings";

// DESPUÉS — usa el UUID. Topic format del contrato (§2.1)
// Construir el topic con String para evitar errores de typo:
String mqttTopic = String("40db/sensores/") + SENSOR_ID + "/lectura";
// O hardcoded con el UUID concatenado a mano:
const char* MQTT_TOPIC = "40db/sensores/<UUID>/lectura";
```

Las credenciales `40db-sensor` / `2qcMJmByQm3yUQz3` actuales **se mantienen** porque cubren el rol publisher (§10.3 confirma que ese credential sigue activo).

**4. NTP + TLS — agregar al `setup()` antes del `connectMqtt()`:**

```c
#include <time.h>

void syncTime() {
  Serial.print("Sincronizando NTP");
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC
  time_t now = 0;
  while (now < 1700000000) {  // ~nov 2023, suficiente como "ya sincronizó"
    delay(500);
    Serial.print(".");
    time(&now);
  }
  Serial.printf("\nNTP OK. Epoch=%ld\n", now);
}

// En setup(), entre connectWifi() y connectMqtt():
syncTime();
```

**5. TLS con verificación de cert (reemplazar `setInsecure()`):**

```c
// ANTES (línea 102)
wifiClient.setInsecure();

// DESPUÉS — usar el cert raíz que HiveMQ Cloud publica (ISRG Root X1 de Let's Encrypt).
// Descargar de https://letsencrypt.org/certs/isrgrootx1.pem y embeber:
const char* HIVEMQ_CA_CERT = R"EOF(
-----BEGIN CERTIFICATE-----
MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw
... (pegar el contenido completo del .pem)
-----END CERTIFICATE-----
)EOF";

wifiClient.setCACert(HIVEMQ_CA_CERT);
```

**6. Publicación con QoS 1 (reemplazar `publishReading`):**

`PubSubClient` (la librería actual) **no soporta QoS 1 en publish** — `mqtt.publish()` siempre es QoS 0. Opciones:

- **Opción A (mínimo cambio):** dejar QoS 0 en MVP. La idempotencia por `(sensor_id, timestamp_medicion)` UNIQUE en `lectura` cubre duplicados; lo que perdemos con QoS 0 son lecturas que el cliente cree haber publicado pero el broker no recibió. Aceptable para 1 sensor de testing.
- **Opción B (correcto):** migrar a `AsyncMqttClient` o `PicoMQTT` que sí soportan QoS 1. Más trabajo, mejor garantía. Recomendado para producción real, no obligatorio para MVP.

**Decisión MVP: Opción A**. Se documenta como deuda técnica. Si en algún momento se ven huecos sospechosos en `lectura`, migrar a Opción B.

**Reescritura del `publishReading()`:**

```c
void publishReading(float db) {
  // Timestamp ISO 8601 UTC
  time_t now;
  time(&now);
  struct tm timeinfo;
  gmtime_r(&now, &timeinfo);
  char ts[32];
  strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);

  // Payload del contrato (§3.1): solo nivel_db + timestamp_medicion
  StaticJsonDocument<128> doc;
  doc["nivel_db"]           = db;
  doc["timestamp_medicion"] = ts;

  char buf[128];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(MQTT_TOPIC, buf, false);  // retain=false (§1 I6)

  Serial.print("PUB → ");
  Serial.println(buf);
}
```

**7. Frecuencia.** Para 1 sensor de testing, **dejar `delay(5000)`** como está. Cuando se sume un segundo sensor, subir a 10s base (§4).

### 10.5 Backend: env vars en Render

En el panel de Render → Service → Environment → Add Environment Variable:

```
MQTT_BROKER_URL=ssl://<TU_CLUSTER>.s1.eu.hivemq.cloud:8883
MQTT_USER=backend-subscriber
MQTT_PASSWORD=<el que generaste en §10.3>
MQTT_CLIENT_ID=40db-backend-prod
```

`MQTT_BROKER_URL` toma el formato `ssl://<host>:<port>` que ya espera el `MqttIngestor` (ver `app/infrastructure/mqtt/ingestor.py:35`).

Guardar disparará un redeploy. Cuando termine, verificar:

```bash
curl https://four0db-backend.onrender.com/health/ready
# Esperado: {"checks": {... "mqtt": "ok"}} (ya no "disabled")
```

Si `mqtt` viene como `"reconnecting"` o `"error"`, revisar logs en Render — el host del broker o las creds están mal.

### 10.6 Workflow de testing manual

Por el patrón "ESP32 apagado, encendido solo para probar" + Render free dormido:

1. **Despertar el backend** (1ª request HTTP demora ~30-50s en free tier):
   ```bash
   curl https://four0db-backend.onrender.com/health/live
   ```
2. **Esperar ~30 s** y confirmar que el ingestor MQTT conectó:
   ```bash
   curl https://four0db-backend.onrender.com/health/ready
   # esperar a ver "mqtt": "ok"
   ```
3. **Encender el ESP32.** Mirar el Serial Monitor: `WiFi OK → NTP OK → MQTT OK → PUB →`.
4. **En Render logs** (panel del servicio → Logs) debería aparecer línea con el INSERT en `lectura`.
5. **Verificar en Supabase**:
   ```sql
   SELECT tableoid::regclass, nivel_db, timestamp_medicion
   FROM lectura
   WHERE sensor_id='<UUID del sensor>'
   ORDER BY timestamp_medicion DESC LIMIT 5;
   ```
   La fila más nueva debe caer en `lectura_2026_05` (o el mes que corresponda) — confirma que la partición funciona en producción real.
6. **Apagar el ESP32** cuando termines de probar.

### 10.7 Consideraciones operativas

**Render free tier — dormido.** El servicio HTTP duerme tras 15 min sin requests. Cuando duerme, el proceso muere, y con él el subscriber MQTT. Implicaciones para este MVP:

- ✅ **No afecta el testing intencional** porque siempre despertás manualmente con curl antes de encender el sensor (§10.6 paso 1).
- ⚠️ **Afecta si el sensor publica mientras Render duerme** — esas lecturas se pierden, HiveMQ las descarta tras N segundos sin suscriptores (TTL de la sesión). Mientras el ESP32 esté apagado entre pruebas, no es problema.
- 🛡️ **Para el día de la presentación**: upgradar a Render paid el día anterior, hacer una corrida de prueba, dejar todo on. Costo: ~7 USD/mes prorrateado a un día = ~$0.25/día (Render permite downgrade después).

**HiveMQ Cloud free tier — límites.** 100 conexiones concurrentes, 10 GB/mes de tráfico. Con 1 sensor a 5s + backend, estás muy por debajo del límite — no hay que preocuparse hasta que se sumen >50 sensores activos.

**Buffer en el ESP32.** El `.ino` actual no buffer-ea cuando MQTT/WiFi cae. Para MVP es aceptable; si se necesita resiliencia, agregar buffer circular en RAM (~1000 lecturas) o en SPIFFS. Queda como roadmap.

### 10.8 Checklist de cierre

Cuando se completen todos los pasos, actualizar §0 y §1:

- [ ] §10.2 ejecutado, UUID del sensor guardado.
- [ ] §10.3 ejecutado, `backend-subscriber` activo en HiveMQ.
- [ ] §10.4 aplicado en firmware (cambios 1-6).
- [ ] §10.5 vars en Render, `/health/ready` reporta `mqtt: ok`.
- [ ] §10.6 workflow ejecutado: una lectura llegó del ESP32 al backend al `lectura_2026_XX`.
- [ ] §0 tabla de divergencias: las 🔴 pasan a ✅ (puede comentarse "cerrado en §10.X").
- [ ] §1 I5 (QoS 1) sigue como 🔒 nominal pero anotar que el firmware MVP corre Opción A (QoS 0). Si se migra a Opción B, esto se resuelve definitivamente.
