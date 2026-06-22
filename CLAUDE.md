# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo state vs. docs

**The MVP backend is implemented; the docs remain the spec.** `app/` holds the full hexagonal-lite layout (domain, application, infrastructure, api, core) with the 29 endpoints of `api.md`, the MQTT ingestor, and a test suite of **251 tests at 96% coverage** (see `docs/testing.md`). The root `main.py` is still a hola-mundo stub kept only as a dev shortcut; **`app/main.py` is the real entrypoint**. The docs in `docs/` are still authoritative: when code and a doc disagree, fix the authoritative doc and the code together (see precedence rules in `docs/README.md`).

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
| `docs/testing.md` | Test suite: layout, how to run, coverage, CI (`pytest` + `ruff`) |

Docs are in Spanish; so are domain identifiers (`reporte`, `lectura`, `sensor`, `usuario`, `comuna`, `tipo_estado`, `historial_estado`). Keep this convention when adding code.

**Folder layout** (from `backend.md` §3) is hexagonal lite and already in place: `app/api/`, `app/application/`, `app/domain/`, `app/infrastructure/{db,mqtt,storage}/`, `app/core/`, `app/patterns/`. The old scaffold names (`routes/`, `services/`, `repositories/`, …) have been migrated; the old → new mapping in `backend.md` §3 is now historical reference.

## Migration state warning

The committed migration `supabase/migrations/20260519000000_initial_schema.sql` is **out of sync** with `bbdd.md` in several ways: missing PostGIS, missing RPCs, still has the discarded `validacion_iot` N:M, `lectura` is not partitioned (D8 / ADR 08), `reporte` lacks the composite-FK columns to a partitioned `lectura`, etc. It must be regenerated **before** implementing `POST /reportes`. Full regen plan in `bbdd.md` §12; that's paso 1 of `PLAN.md`.

## Firmware ↔ contract state warning

The ESP32 firmware at `../../contexto/sensor_ruido_40db/sensor_ruido_40db.ino` **diverges** from the MQTT contract in `docs/iot.md` on four blocking points: topic name (`sensors/readings` vs `sensores/lectura`), `sensor_id` format (human slug vs UUID), payload field (`db` vs `nivel_db`), and timestamp (`millis()` uptime vs ISO 8601 UTC). The backend implements the contract as written in `iot.md`; the firmware will be updated to match (under the same team's control). Full diff and pending changes in `iot.md` §0 and §9.

## Architectural invariants (non-obvious)

These are decisions that touch multiple files and are easy to violate accidentally:

- **The backend is the *only* client of Supabase.** All tables have RLS enabled **with no policies**; the backend uses `service_role_key` which bypasses RLS by design. The frontend (Vue 3) never instantiates the Supabase JS client against business tables. The one exception: the frontend uses Supabase Auth's JS SDK with `anon_key` for signup/login only (see `auth.md` §9).
- **JWTs are verified locally in FastAPI** with `SUPABASE_JWT_SECRET` (HS256, audience `"authenticated"`) — no roundtrip to Supabase. See the `current_user` dependency sketch in `auth.md` §5.
- **Validation of reports against IoT readings is pull-based, not reactive.** Either the user clicks "Verificar evidencia" (preview endpoint `GET /reportes/buscar-evidencia`) or the server runs validation as a last-chance fallback during `POST /reportes`. The backend does **not** scan pending reports when new readings arrive — that was explicitly rejected (`backend.md` §5.2, §9). Atomicity of insert + evidence attach lives in the **RPC `crear_reporte_con_validacion`** (`bbdd.md` §5.3), not in Python. The use case is a thin wrapper that calls the RPC.
- **Single process, dual entrypoint.** FastAPI's `lifespan` starts an async MQTT ingestor alongside the HTTP server (paho-mqtt → HiveMQ Cloud). No Celery/RQ. If you add background work, prefer extending the lifespan over introducing new infra.
- **Geo-temporal matching lives in Postgres**, not Python. `ST_DWithin` over a GIST index on `geography(Point, 4326)` is the canonical query (RPC `validar_reporte_ruido`). Don't reimplement haversine in Python.
- **`lectura` is range-partitioned by month on `timestamp_medicion`** (Postgres native, not TimescaleDB — Supabase doesn't support it). Designed for ~30 sensors at 5–10s cadence (≈100M rows/year). Consequences that ripple into the schema: `lectura.PRIMARY KEY` is composite `(id, timestamp_medicion)`, and `reporte` references evidence via the composite FK `(lectura_evidencia_id, lectura_evidencia_timestamp)` because Postgres requires the partition key inside any unique/PK that an FK targets. The use case layer doesn't see this — adapter-level concern. See `backend.md` ADR 08 and `bbdd.md` §3.5 / D8.
- **`tipo='municipalidad'` promotion is manual SQL** (Supabase SQL editor with `service_role`). No endpoint exists for this in MVP (`auth.md` §8).

## Commands

```bash
# Dev server (FastAPI). app/main.py is the real entrypoint (routers + MQTT lifespan).
uvicorn app.main:app --reload            # real app
uvicorn main:app --reload                # root main.py: hola-mundo stub, dev shortcut only

# Python deps (runtime + dev/test, see requirements.txt)
pip install -r requirements.txt

# Tests + lint (full details in docs/testing.md)
pytest                                   # full suite with coverage (config in pytest.ini)
pytest -q                                # quiet, same as CI
ruff check app/ tests/                   # lint (config in ruff.toml)

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
- **Tests live under `tests/`** — `pytest` (config in `pytest.ini`), one file per layer, currently 251 tests at 96% coverage. Add new tests in the matching layer file and keep coverage from dropping. Lint with `ruff` (`ruff.toml`). CI runs both on every PR/push to `dev`/`main`. Full details in `docs/testing.md`.
