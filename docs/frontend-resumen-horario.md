# Frontend — Integración del resumen horario + heatmap optimizado

Instrucciones para que el frontend Vue 3 consuma la **capa OLAP** del backend (rollup horario + matview de heatmap). Esto materializa el componente de big data del proyecto en algo visible para la defensa.

**Endpoints relevantes:**
- `GET /api/v1/lecturas/resumen` — **nuevo**. Serie horaria pre-agregada por sensor (avg/min/max/p95). Spec: [`api.md`](./api.md) §4.27.
- `GET /api/v1/heatmaps` — **existente, contrato compatible**. Solo agrega `metadata.fuente ∈ {"matview","rpc"}` para que el cliente sepa si lo sirvió la matview.

**Contexto técnico**: [`bbdd.md`](./bbdd.md) §13, [`backend.md`](./backend.md) ADR 09.

---

## 1. ¿Dónde ponerlo en la UI?

### 1.1 Pantalla principal: detalle de sensor (panel municipalidad/admin)

El sensor detail ya existe (consume `GET /api/v1/sensores/{id}` → `estado_salud`, coords, etc.). Agregar una **sección/tab "Histórico de ruido"** con:

- **Gráfico de línea** con `avg_db` (línea principal) + `p95_db` (línea secundaria atenuada) + `min/max` como banda sombreada de fondo.
- **Selector de ventana**: chips "24h", "7 días", "30 días", "90 días". El default sugerido es 7 días (suele ser lo más informativo y entra en el matview del heatmap si el usuario navega a esa vista después).
- **Tooltip** al hover sobre un punto: `hora`, `avg_db`, `p95_db`, `n_lecturas`.
- **Indicador de frescura**: "Actualizado: hace 12 minutos" derivado de `refrescado_at`.
- **Empty state**: "Sin lecturas en este período" si `horas` está vacío.

### 1.2 Mockup ASCII

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Plaza Italia - Norte               estado: online   última: hace 1 min  │
│                                                                          │
│ Histórico de ruido    [ 24h ] [ 7d ✓ ] [ 30d ] [ 90d ]                  │
│                                       Actualizado: hace 12 min  ⓘ        │
│                                                                          │
│   80 dB ┤                            ╭╮                                  │
│   70 dB ┤  ╭───╮       ╭──╮       ╭──╯╰─╮      ────  promedio (avg)     │
│   60 dB ┤──╯   ╰──╮ ╭──╯  ╰──╮ ╭──╯     ╰───── ····  p95               │
│   50 dB ┤         ╰─╯         ╰─╯               ░░░  banda min–max     │
│   40 dB ┤                                                                │
│         └────────────────────────────────────────                        │
│         Lun        Mar        Mie         Jue                            │
│                                                                          │
│ Total lecturas en período: 1.247                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 Pantalla secundaria: vista por comuna (opcional, alto valor)

Una vista "resumen comuna" que muestra **mini-cards** con el avg_db de las últimas 24h por sensor, ordenadas de más ruidoso a menos. Cada card linkea al detalle. Implementación = N llamadas a `/lecturas/resumen` (una por sensor de la comuna) o un endpoint nuevo si crece molesto. **No urgente** — la pantalla 1.1 es la prioridad.

---

## 2. Cliente HTTP

### 2.1 Service para `/lecturas/resumen`

`src/services/lecturas.ts` (o `.js`):

```ts
import { http } from "./http";  // axios/fetch wrapper con baseURL y Bearer

export interface ResumenHorarioItem {
  hora: string;          // ISO 8601
  avg_db: number;
  min_db: number;
  max_db: number;
  p95_db: number;
  n_lecturas: number;
}

export interface ResumenHorarioResponse {
  sensor_id: string;
  sensor_nombre: string;
  desde: string;
  hasta: string;
  horas: ResumenHorarioItem[];
  fuente: "lectura_resumen_horaria";
  refrescado_at: string | null;
}

export async function getResumenHorario(
  sensorId: string,
  desde: Date,
  hasta: Date,
): Promise<ResumenHorarioResponse> {
  const { data } = await http.get<ResumenHorarioResponse>("/lecturas/resumen", {
    params: {
      sensor_id: sensorId,
      desde: desde.toISOString(),
      hasta: hasta.toISOString(),
    },
  });
  return data;
}
```

**Errores a manejar** (mismos códigos que el resto de la API — ver [`errores.md`](./errores.md) §4):

| Status | `code` típico | UX sugerida |
|---|---|---|
| 401 | `invalid_token` | Forzar re-login (el interceptor global ya lo hace). |
| 403 | `comuna_mismatch` | "No tenés permiso para ver datos de sensores de otra comuna." |
| 404 | `sensor_not_found` | "El sensor solicitado ya no existe." |
| 422 | `validation_error` | "La ventana solicitada supera 90 días." (o similar según `message`). |
| 503 | `external_service_error` | "Servicio temporalmente no disponible. Reintentá en unos segundos." |

---

## 3. Componente Vue 3 sugerido

### 3.1 `HistoricoRuidoSensor.vue`

```vue
<script setup lang="ts">
import { ref, computed, watch, onMounted } from "vue";
import { getResumenHorario, type ResumenHorarioItem } from "@/services/lecturas";

const props = defineProps<{ sensorId: string; sensorNombre: string }>();

type Ventana = "24h" | "7d" | "30d" | "90d";
const VENTANAS: Record<Ventana, number> = { "24h": 1, "7d": 7, "30d": 30, "90d": 90 };

const ventana = ref<Ventana>("7d");
const horas = ref<ResumenHorarioItem[]>([]);
const refrescadoAt = ref<string | null>(null);
const cargando = ref(false);
const error = ref<string | null>(null);

const totalLecturas = computed(() =>
  horas.value.reduce((acc, h) => acc + h.n_lecturas, 0),
);

const refrescadoHaceMin = computed(() => {
  if (!refrescadoAt.value) return null;
  const ms = Date.now() - new Date(refrescadoAt.value).getTime();
  return Math.round(ms / 60000);
});

async function cargar() {
  cargando.value = true;
  error.value = null;
  try {
    const hasta = new Date();
    const desde = new Date(hasta.getTime() - VENTANAS[ventana.value] * 24 * 3600 * 1000);
    const r = await getResumenHorario(props.sensorId, desde, hasta);
    horas.value = r.horas;
    refrescadoAt.value = r.refrescado_at;
  } catch (e: any) {
    error.value = e?.response?.data?.message ?? "Error al cargar el histórico.";
  } finally {
    cargando.value = false;
  }
}

watch(() => [props.sensorId, ventana.value], cargar);
onMounted(cargar);
</script>

<template>
  <section class="historico-ruido">
    <header>
      <h3>Histórico de ruido</h3>
      <div class="chips">
        <button
          v-for="v in Object.keys(VENTANAS) as Ventana[]"
          :key="v"
          :class="{ activo: ventana === v }"
          @click="ventana = v"
        >
          {{ v }}
        </button>
      </div>
      <p v-if="refrescadoHaceMin !== null" class="frescura">
        Actualizado: hace {{ refrescadoHaceMin }} min
      </p>
    </header>

    <div v-if="cargando" class="estado">Cargando…</div>
    <div v-else-if="error" class="estado error">{{ error }}</div>
    <div v-else-if="horas.length === 0" class="estado">
      Sin lecturas en este período.
    </div>
    <div v-else>
      <!-- TU LIBRERIA DE GRAFICOS aqui (ver §4) -->
      <GraficoRuido :horas="horas" />
      <p class="total">Total lecturas en período: {{ totalLecturas.toLocaleString() }}</p>
    </div>
  </section>
</template>
```

### 3.2 `GraficoRuido.vue` (ejemplo con vue-chartjs)

```bash
npm i chart.js vue-chartjs chartjs-adapter-date-fns date-fns
```

```vue
<script setup lang="ts">
import { computed } from "vue";
import { Line } from "vue-chartjs";
import {
  Chart, LineElement, PointElement, LinearScale, TimeScale, Tooltip, Legend, Filler, CategoryScale,
} from "chart.js";
import "chartjs-adapter-date-fns";
import type { ResumenHorarioItem } from "@/services/lecturas";

Chart.register(LineElement, PointElement, LinearScale, TimeScale, Tooltip, Legend, Filler, CategoryScale);

const props = defineProps<{ horas: ResumenHorarioItem[] }>();

const data = computed(() => ({
  datasets: [
    {
      label: "Promedio (dB)",
      data: props.horas.map(h => ({ x: h.hora, y: h.avg_db })),
      borderColor: "#3b82f6",
      backgroundColor: "transparent",
      tension: 0.2,
      pointRadius: 0,
      borderWidth: 2,
    },
    {
      label: "P95 (dB)",
      data: props.horas.map(h => ({ x: h.hora, y: h.p95_db })),
      borderColor: "#f97316",
      backgroundColor: "transparent",
      borderDash: [4, 4],
      tension: 0.2,
      pointRadius: 0,
      borderWidth: 1.5,
    },
    {
      label: "Max",
      data: props.horas.map(h => ({ x: h.hora, y: h.max_db })),
      borderColor: "transparent",
      backgroundColor: "rgba(148, 163, 184, 0.15)",
      fill: "+1",   // rellena hasta el siguiente dataset (min)
      tension: 0.2,
      pointRadius: 0,
    },
    {
      label: "Min",
      data: props.horas.map(h => ({ x: h.hora, y: h.min_db })),
      borderColor: "transparent",
      backgroundColor: "transparent",
      tension: 0.2,
      pointRadius: 0,
    },
  ],
}));

const options = {
  responsive: true,
  maintainAspectRatio: false,
  scales: {
    x: { type: "time" as const, time: { tooltipFormat: "dd MMM HH:mm" } },
    y: { title: { display: true, text: "dB" }, suggestedMin: 30, suggestedMax: 90 },
  },
  plugins: {
    legend: { position: "bottom" as const },
    tooltip: {
      callbacks: {
        afterBody: (ctx: any) => {
          const i = ctx[0].dataIndex;
          const h = props.horas[i];
          return `Lecturas: ${h.n_lecturas}`;
        },
      },
    },
  },
};
</script>

<template>
  <div style="height: 320px">
    <Line :data="data" :options="options" />
  </div>
</template>
```

Si ya usás otra librería (ECharts, vue3-apexcharts, Highcharts, etc.), la lógica de mapeo es la misma — lo único que importa es respetar el shape de `ResumenHorarioItem`.

---

## 4. Detalles de UX que importan defendiendo el proyecto

### 4.1 Mostrar `refrescado_at`

El gráfico no es "tiempo real" — los datos se actualizan **cada hora al minuto 5** (cron). Mostrar "Actualizado: hace X min" es transparencia con el usuario *y* sirve de evidencia visual de que existe una capa de batch processing.

### 4.2 Manejar huecos temporales

Las horas sin lecturas **no aparecen** en `horas`. El gráfico de línea va a conectar puntos saltándose ese hueco. Si querés que se vea un gap explícito, podés rellenar manualmente con `null` en el dataset:

```ts
function rellenarHuecos(horas: ResumenHorarioItem[], desde: Date, hasta: Date) {
  // Generar todas las horas del rango y emparejarlas con horas[].
  // Resultado: array con la misma longitud que la ventana, con nulls donde no hay data.
}
```

Chart.js dibuja `null` como un gap automáticamente (`spanGaps: false`). Útil para que un sensor offline 3 días sea visualmente obvio.

### 4.3 Zona horaria

El backend devuelve timestamps en UTC (sufijo `Z`). Chart.js + `chartjs-adapter-date-fns` los rendea en la zona local del navegador automáticamente. Para Chile (America/Santiago, UTC-3 o UTC-4 con DST) esto es lo correcto. No conviertas a mano.

### 4.4 Ventana 90 días

Es el máximo permitido (el backend devuelve 422 si pasás más). Un sensor con datos completos genera 90 × 24 = **2160 puntos** — Chart.js los renderea bien con `pointRadius: 0`. Si tu librería renderiza puntos visibles por defecto, ocultalos en este modo.

### 4.5 Cache cliente (opcional)

Si el usuario alterna entre ventanas (24h → 7d → 24h), reconsultar es barato (Postgres responde en <50ms). Pero si querés cachear, hacelo con TTL de 5 min (alineado con la cadencia del cron del heatmap) o de 1h (alineado con el rollup). Pinia + un store por sensor es suficiente.

---

## 5. `GET /heatmaps` — qué cambia para el front

**Nada rompedor.** El shape del response es idéntico al pre-existente; lo único nuevo es:

```jsonc
{
  "type": "FeatureCollection",
  "metadata": {
    "bucket_minutes": 5,
    "grid_size_deg": 0.001,
    "total_cells": 234,
    "fuente": "matview"        // ← NUEVO. Valores: "matview" | "rpc"
  },
  "features": [ … ]
}
```

**Decisión front opcional:** mostrar un pequeño badge en la esquina del mapa de calor:

- `fuente == "matview"` → ⚡ "Servido desde caché (5 min)" — el caso típico.
- `fuente == "rpc"` → 🔍 "Consulta en vivo" — pasa cuando el usuario pide `bucket_minutes ∈ {1, 15, 60}` o ventana > 7 días.

Si el panel del heatmap permite cambiar `bucket_minutes`, fijate que el de 5 min va a sentirse notablemente más rápido. Esa diferencia es exactamente el valor del componente big data — vale exponerla.

---

## 6. Checklist de implementación

- [ ] Service `getResumenHorario` con tipos.
- [ ] Componente `HistoricoRuidoSensor.vue` integrado al detalle de sensor.
- [ ] Selector de ventana (24h / 7d / 30d / 90d) con default 7d.
- [ ] Gráfico de línea con avg + p95 + banda min/max.
- [ ] Tooltip con `n_lecturas` por hora.
- [ ] Indicador "Actualizado: hace X min" desde `refrescado_at`.
- [ ] Empty state ("sin lecturas en este período").
- [ ] Loading + error states.
- [ ] (Opcional) Badge `fuente` en `/heatmaps`.
- [ ] Manejo de 401/403/404/422/503 con mensajes claros.

---

## 7. Auth recordatorio

Ambos endpoints viven bajo `/api/v1/`:
- `/heatmaps` → **público**, sin Bearer.
- `/lecturas/resumen` → requiere JWT de un usuario `municipalidad` (solo sensores de su comuna) o `admin` (cualquier sensor).

El interceptor global de axios ya debería estar adjuntando el `Authorization: Bearer <jwt>` cuando hay sesión activa de Supabase Auth. Si en algún momento ves 401 en `/lecturas/resumen` con sesión iniciada, verificá que el JWT no expiró (Supabase auto-refresca, pero un cliente viejo puede haber perdido el listener).
