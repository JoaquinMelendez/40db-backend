# Testing — 40dB Backend

Documento autoritativo sobre la **suite de pruebas** del backend: qué hay, cómo correrla, cómo se mide la cobertura y cómo corre en CI.

> **Estado actual:** 251 tests en verde, **96 % de cobertura** sobre `app/`
> (1624 statements, 68 sin cubrir). Última corrida: `pytest -q`.

---

## 1. Filosofía: cobertura > cantidad

La métrica que se sigue es **cobertura de líneas y de casos relevantes**, no el
número absoluto de tests. Un total de tests alto no implica calidad: es fácil de
inflar con pruebas triviales o redundantes que no suben cobertura ni atrapan
bugs. Para un MVP de ~1600 statements, 251 tests bien distribuidos con 96 % de
cobertura cubren happy paths, errores de dominio, auth/autorización y flujos
end-to-end.

Si se agregan tests, que sea para **cubrir comportamiento no cubierto** (casos
borde de la máquina de estados, fallos de RPC, particionamiento de `lectura`,
reintentos del ingestor MQTT), no para alcanzar un número.

---

## 2. Layout de la suite

Toda la suite vive bajo `tests/`. Un archivo por capa/preocupación:

| Archivo | Capa / foco | Tests |
|---|---|---:|
| `tests/test_domain.py` | Entidades y errores de dominio (`app/domain/`) | 13 |
| `tests/test_application.py` | Casos de uso (`app/application/`) con repos mockeados | 69 |
| `tests/test_infrastructure.py` | Adapters DB/MQTT/storage (`app/infrastructure/`) | 11 |
| `tests/test_api.py` | Routes HTTP (`app/api/`): shapes, status codes, validación | 36 |
| `tests/test_smoke.py` | Humo sobre los 29 endpoints de la API | 43 |
| `tests/test_integration.py` | Flujos completos API → use case → repo | 32 |
| `tests/test_security.py` | Autenticación y autorización (401/403, cross-comuna, roles) | 47 |
| **Total** | | **251** |

Las pruebas de **carga (k6)** viven aparte en `tests/load/` — ver §6.

---

## 3. Cómo correr los tests

```bash
# Suite completa con cobertura (config en pytest.ini)
pytest

# Modo silencioso (lo que corre CI)
pytest -q

# Un archivo / un test
pytest tests/test_security.py
pytest tests/test_application.py::test_crear_reporte_happy_path

# Ver el reporte HTML de cobertura tras correr
open htmlcov/index.html
```

Config de pytest (`pytest.ini` en la raíz):

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
addopts = --cov=app --cov-report=term-missing --cov-report=html
```

- `asyncio_mode = auto`: no hace falta marcar cada test async con `@pytest.mark.asyncio`.
- `--cov=app`: la cobertura se mide solo sobre el paquete `app/`.
- `--cov-report=term-missing`: muestra las líneas sin cubrir en la terminal.
- `--cov-report=html`: genera `htmlcov/` (gitignored).

> **Variables de entorno:** `pydantic-settings` exige `SUPABASE_URL`,
> `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` y `CORS_ORIGINS` al importar
> la app. En local se toman del `.env`; en CI se inyectan con valores dummy
> (ver §5). El `SUPABASE_JWT_SECRET` debe ser el mismo con el que los tests
> firman y verifican los JWT.

---

## 4. Estrategia por capa

- **Dominio** (`test_domain.py`): puro, sin I/O. Valida invariantes de las
  entidades y la jerarquía de excepciones de `app/domain/errors.py`
  (ver [`errores.md`](./errores.md)).
- **Aplicación** (`test_application.py`): cada use case con sus repos/puertos
  mockeados. Verifica reglas de negocio y orquestación, no SQL.
- **Infraestructura** (`test_infrastructure.py`): adapters PostgREST/RPC,
  storage y el ingestor MQTT. Mockea el cliente Supabase y el cliente MQTT.
- **API** (`test_api.py`): usa `TestClient`/`httpx` contra la app FastAPI con
  dependencias sobreescritas. Verifica shapes y status codes de
  [`api.md`](./api.md).
- **Smoke** (`test_smoke.py`): un toque rápido a los 29 endpoints — detecta
  rutas rotas o que no levantan.
- **Integración** (`test_integration.py`): flujo real API → use case → repo
  (mockeando solo el borde Supabase), para validar el cableado completo.
- **Seguridad** (`test_security.py`): 401 sin token, 403 por rol, aislamiento
  por comuna, JWT inválido/expirado. Refleja la matriz de [`auth.md`](./auth.md).

---

## 5. CI (GitHub Actions)

Workflow en `.github/workflows/ci.yml`. Corre en cada **PR hacia `dev`/`main`** y
en cada **push** a esas ramas. Dos jobs:

1. **Lint (`ruff`)** — `ruff check app/ tests/`. Config en `ruff.toml`
   (reglas por defecto E4/E7/E9 + F; `E501` desactivado a propósito).
2. **Regresión (`pytest`)** — instala `requirements.txt` y corre `pytest -q`.
   Inyecta las env vars de Supabase con valores dummy (no hay `.env` en CI).

Si lint o la suite rompen, el PR queda en rojo.

---

## 6. Pruebas de carga (k6)

Aparte de la suite unitaria, hay una prueba de carga con [k6](https://k6.io) en
`tests/load/load_test.js` (ver `tests/load/README.md`). **No corre en CI**:
necesita el servidor levantado, así que se ejecuta a mano contra un entorno
desplegado.

```bash
k6 run tests/load/load_test.js
```

---

## 7. Dependencias de test

En `requirements.txt`, bloque "Dev / test":

- `pytest`, `pytest-asyncio` — runner + soporte async.
- `pytest-cov` — cobertura.
- `httpx` — cliente para tests de API.
- `ruff==0.15.18` — linter (pin exacto para igualar CI).
