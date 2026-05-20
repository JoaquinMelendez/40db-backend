# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo state vs. docs

**Important: the code is a near-empty scaffold; the architecture lives in `docs/`.** Both `main.py` (root) and `app/main.py` are stub FastAPI apps with a single hola-mundo endpoint. Every folder under `app/` is a `.gitkeep` placeholder. There are no tests, no models, no use cases yet.

**Start at `docs/README.md`** — it indexes the whole documentation set in reading order and defines precedence rules between docs.

Quick map (full index in `docs/README.md`):

| Doc | What for |
|---|---|
| `docs/PLAN.md` | **Implementation order.** "Implementá paso N de PLAN.md" — everything else is spec for the plan. |
| `docs/backend.md` | Architecture, ADRs, target layout (hexagonal lite), runtime composition, config |
| `docs/bbdd.md` | Canonical data model: DDL, triggers, RPCs, RLS, migration regen plan |
| `docs/api.md` | Authoritative HTTP contract: endpoints, shapes, status codes |
| `docs/auth.md` | Supabase Auth, JWT, role matrix, dependency sketches |
| `docs/errores.md` | Domain exception hierarchy, HTTP mapping, health checks |
| `docs/iot.md` | MQTT contract (IoT subsystem implemented by **another team member**) |

Docs are in Spanish; so are domain identifiers (`reporte`, `lectura`, `sensor`, `usuario`, `comuna`, `tipo_estado`, `historial_estado`). Keep this convention when adding code.

**Target folder layout** (from `backend.md` §3) is hexagonal lite: `app/api/`, `app/application/`, `app/domain/`, `app/infrastructure/{db,mqtt}/`, `app/core/`, `app/patterns/`. The current scaffold uses older names. The migration table in `backend.md` §3 maps old → new. Migrate to the target layout as endpoints are implemented (paso 2 of `PLAN.md`), not as a separate refactor.

## Migration state warning

The committed migration `supabase/migrations/20260502225141_initial_schema.sql` is **out of sync** with `bbdd.md` (missing PostGIS, missing RPCs, still has the discarded `validacion_iot` N:M, etc.). It must be regenerated **before** implementing `POST /reportes`. Full regen plan in `bbdd.md` §12; that's paso 1 of `PLAN.md`.

## Architectural invariants (non-obvious)

These are decisions that touch multiple files and are easy to violate accidentally:

- **The backend is the *only* client of Supabase.** All tables have RLS enabled **with no policies**; the backend uses `service_role_key` which bypasses RLS by design. The frontend (Vue 3) never instantiates the Supabase JS client against business tables. The one exception: the frontend uses Supabase Auth's JS SDK with `anon_key` for signup/login only (see `auth.md` §9).
- **JWTs are verified locally in FastAPI** with `SUPABASE_JWT_SECRET` (HS256, audience `"authenticated"`) — no roundtrip to Supabase. See the `current_user` dependency sketch in `auth.md` §5.
- **Validation of reports against IoT readings is pull-based, not reactive.** Either the user clicks "Verificar evidencia" (preview endpoint `GET /reportes/buscar-evidencia`) or the server runs validation as a last-chance fallback during `POST /reportes`. The backend does **not** scan pending reports when new readings arrive — that was explicitly rejected (`backend.md` §5.2, §9). Atomicity of insert + evidence attach lives in the **RPC `crear_reporte_con_validacion`** (`bbdd.md` §5.3), not in Python. The use case is a thin wrapper that calls the RPC.
- **Single process, dual entrypoint.** FastAPI's `lifespan` starts an async MQTT ingestor alongside the HTTP server (paho-mqtt → HiveMQ Cloud). No Celery/RQ. If you add background work, prefer extending the lifespan over introducing new infra.
- **Geo-temporal matching lives in Postgres**, not Python. `ST_DWithin` over a GIST index on `geography(Point, 4326)` is the canonical query (RPC `validar_reporte_ruido`). Don't reimplement haversine in Python.
- **`tipo='municipalidad'` promotion is manual SQL** (Supabase SQL editor with `service_role`). No endpoint exists for this in MVP (`auth.md` §8).

## Commands

```bash
# Dev server (FastAPI). Either entrypoint works — both are hola-mundo stubs today.
uvicorn main:app --reload                # root main.py (dev shortcut)
uvicorn app.main:app --reload            # app/main.py (will become the real entrypoint)

# Python deps
pip install -r requirements.txt          # currently: fastapi, uvicorn[standard]

# Supabase local stack (requires Supabase CLI)
supabase start                           # boot Postgres + Auth + Studio (ports in supabase/config.toml)
supabase db reset                        # apply migrations + run seed.sql
supabase migration new <name>            # scaffold a new timestamped migration
supabase db push                         # apply local migrations to the linked remote project
supabase db diff -f <name>               # generate a migration from local schema changes
```

Local Supabase ports (`supabase/config.toml`): API 54321, DB 54322, Studio 54323, Inbucket (mail) 54324.

## Conventions

- **Language: Spanish** for domain names, comments, doc strings, and commit messages. Code identifiers follow Python style (`snake_case` for vars/functions, `PascalCase` for classes), but the *words* are Spanish (`crear_reporte`, `ReporteRepository`, `LecturaRepository`).
- **Commit style** (from `git log`): `feat:`, `chore:`, `add:`, `fix:` prefixes, lowercase, Spanish.
- **Python version**: docs say 3.11+; actual runtime is **3.9.6** (system Python from macOS CommandLineTools, `pip3` installs to `~/Library/Python/3.9`). The `.pyc` artifact from 3.14 was a one-off; ignore it.
- **No tests yet** — when adding the first one, set up `pytest` and put it under `tests/`. There is no test runner configured.
