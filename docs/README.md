# Documentación — 40dB Backend

Punto de entrada a la documentación del backend. Está pensada como **especificación accionable**: leyendo este folder en orden, una IA o desarrollador debe poder implementar el MVP sin información externa.

---

## Orden de lectura sugerido

| # | Doc | Para qué |
|---|---|---|
| 1 | [`backend.md`](./backend.md) | Contexto del problema, ADRs, layout objetivo, composición runtime, flujos clave a alto nivel. **Empezar acá.** |
| 2 | [`bbdd.md`](./bbdd.md) | Modelo de datos canónico: DDL, índices, triggers, RPCs, RLS, máquina de estados. |
| 3 | [`auth.md`](./auth.md) | Auth con Supabase, JWT, trigger de provisioning, matriz de roles, onboarding. |
| 4 | [`api.md`](./api.md) | Contrato HTTP autoritativo: endpoints, request/response, status codes, errores. |
| 5 | [`errores.md`](./errores.md) | Jerarquía de excepciones de dominio, mapeo HTTP, health checks, manejo de fallos externos. |
| 6 | [`iot.md`](./iot.md) | Contrato MQTT con el subsistema IoT (lo implementa otro miembro del equipo). |
| 7 | [`PLAN.md`](./PLAN.md) | **Orden de implementación con dependencias.** Esto es lo que se ejecuta. |

---

## Reglas de precedencia entre docs

Cuando dos docs digan cosas distintas, manda el más específico:

- **Modelo de datos** → `bbdd.md` gana sobre cualquier otro.
- **Contrato HTTP (shapes, status codes)** → `api.md` gana sobre snippets en `backend.md` o `auth.md`.
- **Códigos de error y excepciones** → `errores.md` gana.
- **Auth (JWT, roles, dependencies)** → `auth.md` gana.
- **Topics MQTT y payload** → `iot.md` gana.
- **Arquitectura general y ADRs** → `backend.md` gana sobre los demás *solo* si no hay un doc específico de la materia.

Si encontrás una contradicción, **corregí el doc menos específico** para que apunte al autoritativo. No dejes la inconsistencia.

---

## Convenciones

- **Idioma**: español para identificadores de dominio (`reporte`, `lectura`, `sensor`, `usuario`, `comuna`), comentarios, mensajes de error y docs. Conventions de estilo Python (`snake_case`, `PascalCase`) se respetan.
- **API**: prefijo `/api/v1/`. Si se rompe contrato, se bumpea a `/api/v2/`.
- **SQL**: identifiers en `snake_case`, tablas en singular (`reporte`, no `reportes`), índices con prefijo `idx_<tabla>_<col>`.
- **Bloques de código en docs**: si el snippet es **autoritativo** (DDL, RPC, response shape), tratarlo como source of truth. Si es **ilustrativo**, marcarlo con un comentario `// esquemático` o equivalente.

---

## Estado de cada doc

| Doc | Estado | Notas |
|---|---|---|
| `backend.md` | ✅ ratificado | Arquitectura, ADRs y flujos cerrados |
| `bbdd.md` | ✅ ratificado | Migración SQL pendiente de regeneración (ver `PLAN.md`) |
| `auth.md` | ✅ ratificado | — |
| `api.md` | ✅ ratificado | — |
| `errores.md` | ✅ ratificado | — |
| `iot.md` | 🟡 propuesta | Contrato sugerido al equipo IoT, sujeto a confirmación con compañero |
| `PLAN.md` | ✅ ratificado | Path crítico al MVP |
| `patterns.md` | ⏸ postergado | Patrones se concretarán al implementar; ver `backend.md` §6 |

---

## Cómo usar estos docs con Claude Code

El layout está pensado para que se pueda decir:

> "Claude, implementá lo que dice `docs/PLAN.md` paso 1." (o varios pasos)

Para esto:

1. **`PLAN.md` es el orquestador.** Cada paso del plan referencia los docs autoritativos que necesita y declara su "done when".
2. **Los demás docs son spec.** No describen "qué hacer ahora" sino "cómo debe quedar". Son cooperativos con el plan.
3. **`CLAUDE.md` (raíz del repo)** tiene invariantes arquitectónicos y comandos. No duplica la spec — apunta acá.

Si vas a modificar el comportamiento, modificá el doc autoritativo primero, después el código. Si codeás algo que el doc no contempla, **actualizá el doc en el mismo PR**.
