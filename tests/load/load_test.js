// ============================================================================
// 40dB — Prueba de Carga (k6)
// ============================================================================
// Mide latencia y tasa de error del backend FastAPI bajo concurrencia creciente.
//
// Escenarios:
//   - "humo de carga" (siempre): GET /health/live y GET /openapi.json. No tocan
//     Supabase, así que ejercitan el stack ASGI completo (routing, middleware
//     de correlación, serialización) y sirven para medir el techo de throughput
//     del servidor en sí. Corre sin infraestructura externa.
//   - "API autenticada" (opcional): si se entrega un TOKEN (JWT válido) y el
//     backend apunta a una Supabase real, además golpea endpoints de lectura
//     reales (sensores, reportes propios, perfil).
//
// Uso:
//   # 1. Levantar el backend (en otra terminal):
//   uvicorn app.main:app --port 8000
//
//   # 2. Carga básica (solo endpoints sin DB):
//   k6 run tests/load/load_test.js
//
//   # 3. Parametrizado (más carga, contra otro host):
//   BASE_URL=http://localhost:8000 VUS=50 DURATION=1m k6 run tests/load/load_test.js
//
//   # 4. Incluir endpoints autenticados (requiere Supabase real + JWT):
//   TOKEN="eyJhbGci..." k6 run tests/load/load_test.js
//
// Umbrales (el run FALLA si no se cumplen):
//   - http_req_failed  < 1%      (tasa de requests con error)
//   - http_req_duration p95 < 500ms
//   - check_success_rate > 99%   (asserts de status code correctos)
// ============================================================================

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Rate } from "k6/metrics";

// ── Parámetros (configurables por variables de entorno) ──────────────────────
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN || "";
const VUS = parseInt(__ENV.VUS || "20", 10);
const DURATION = __ENV.DURATION || "30s";

// Métrica propia: proporción de checks (asserts) que pasaron.
const checkSuccess = new Rate("check_success_rate");

export const options = {
  // Rampa: sube de 0 a VUS, se mantiene, y baja. Permite ver cómo se degrada
  // la latencia a medida que entra carga, no solo el promedio en régimen.
  stages: [
    { duration: "10s", target: VUS },
    { duration: DURATION, target: VUS },
    { duration: "5s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
    check_success_rate: ["rate>0.99"],
  },
};

// Helper: registra el resultado de un check en la métrica propia.
function assert(res, name, expectedStatus) {
  const ok = check(res, {
    [`${name}: status ${expectedStatus}`]: (r) => r.status === expectedStatus,
  });
  checkSuccess.add(ok);
  return ok;
}

export default function () {
  // ── Escenario 1: endpoints sin DB (siempre) ────────────────────────────────
  group("salud y metadatos (sin DB)", () => {
    const live = http.get(`${BASE_URL}/health/live`);
    assert(live, "GET /health/live", 200);

    const openapi = http.get(`${BASE_URL}/openapi.json`);
    assert(openapi, "GET /openapi.json", 200);
  });

  // ── Escenario 2: API autenticada (solo si hay TOKEN + Supabase real) ────────
  if (TOKEN) {
    group("API de lectura autenticada", () => {
      const headers = { Authorization: `Bearer ${TOKEN}` };

      const me = http.get(`${BASE_URL}/api/v1/usuarios/me`, { headers });
      assert(me, "GET /usuarios/me", 200);

      const sensores = http.get(`${BASE_URL}/api/v1/sensores`, { headers });
      assert(sensores, "GET /sensores", 200);

      const mios = http.get(`${BASE_URL}/api/v1/reportes/mios`, { headers });
      assert(mios, "GET /reportes/mios", 200);
    });
  }

  // Pausa breve entre iteraciones para modelar usuarios reales (no martillar).
  sleep(0.5);
}
