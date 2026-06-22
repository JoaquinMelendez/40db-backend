"""
Tests de Integración
====================
Validan flujos completos API → Servicio → Repositorio, mockeando SOLO
la capa de Supabase (get_supabase). Todas las capas intermedias
(use cases, repos, schemas) ejecutan código real.

Diferencia con smoke tests:
  - Smoke: mockea use cases, verifica status codes.
  - Integración: mockea solo Supabase, verifica lógica de negocio cruzando capas.
"""

import contextlib

import pytest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import (
    current_user, current_user_municipal, current_user_admin,
    current_user_municipal_o_admin,
)
from app.domain.entities import Usuario

client = TestClient(app, raise_server_exceptions=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

CIUDADANO = Usuario(id="int-c1", nombre="Ciudadano Int", tipo="ciudadano", activo=True, comuna_id=1)
MUNICIPAL = Usuario(id="int-m1", nombre="Municipal Int", tipo="municipalidad", activo=True, comuna_id=1)
MUNICIPAL_OTRA = Usuario(id="int-m2", nombre="Municipal Otra", tipo="municipalidad", activo=True, comuna_id=2)
ADMIN = Usuario(id="int-a1", nombre="Admin Int", tipo="admin", activo=True)


def _override_user(user: Usuario):
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_user_municipal] = lambda: user
    app.dependency_overrides[current_user_admin] = lambda: user
    app.dependency_overrides[current_user_municipal_o_admin] = lambda: user


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()


def _sequenced_mock(responses: list):
    """Crea un MagicMock de Supabase que devuelve respuestas distintas
    en cada llamada a .execute() a lo largo de una cadena PostgREST.

    Todas las llamadas de cadena (.table, .select, .eq, etc.) devuelven
    el mismo mock, y .execute() itera sobre `responses`.
    """
    mock = MagicMock()
    call_idx = {"n": 0}

    def _execute():
        idx = call_idx["n"]
        call_idx["n"] += 1
        if idx < len(responses):
            return MagicMock(data=responses[idx])
        return MagicMock(data=None)

    # Hacer que todos los métodos de cadena retornen el propio mock
    for method in ("table", "select", "insert", "update", "delete",
                   "eq", "neq", "lt", "gt", "gte", "lte", "ilike",
                   "order", "limit", "maybe_single", "single",
                   "in_", "rpc", "upsert"):
        getattr(mock, method).return_value = mock

    mock.execute = _execute
    return mock


# Módulos que hacen `from app.core.supabase_client import get_supabase` a nivel
# de módulo: el nombre queda bindeado en el namespace de cada uno al importar,
# así que parchear solo el módulo origen NO alcanza a esos nombres ya importados.
# Hay que parchear cada sitio. (Los imports lazy —usuarios, health,
# cambiar_estado_reporte— sí se resuelven desde el origen en tiempo de llamada.)
_SUPABASE_TARGETS = (
    "app.core.supabase_client.get_supabase",
    "app.api.routes.catalogos.get_supabase",
    "app.application.listar_usuarios.get_supabase",
    "app.application.sensores.get_supabase",
    "app.application.crear_reporte.get_supabase",
    "app.application.promover_usuario.get_supabase",
    "app.infrastructure.storage.reportes_admin_storage.get_supabase",
    "app.infrastructure.db.usuario_repo.get_supabase",
    "app.infrastructure.db.rpc.get_supabase",
    "app.infrastructure.db.resumen_horario_repo.get_supabase",
    "app.infrastructure.db.sensor_repo.get_supabase",
    "app.infrastructure.db.lectura_repo.get_supabase",
    "app.infrastructure.db.reporte_comentario_repo.get_supabase",
    "app.infrastructure.db.reporte_repo.get_supabase",
    "app.infrastructure.db.reporte_archivo_admin_repo.get_supabase",
)


def patch_supabase(fn):
    """Decorador que reemplaza a @patch("app.core.supabase_client.get_supabase").

    Parchea get_supabase en TODOS los módulos que lo importaron y comparte un
    único MagicMock, inyectado como primer argumento (mock_get_sb). Así el test
    sigue escribiendo `mock_get_sb.return_value = mock_db` sin cambios.
    """
    def wrapper(self, *args, **kwargs):
        shared = MagicMock()
        with contextlib.ExitStack() as stack:
            for target in _SUPABASE_TARGETS:
                stack.enter_context(patch(target, shared))
            return fn(self, shared, *args, **kwargs)
    # No usamos functools.wraps a propósito: copiar la firma de `fn` haría que
    # pytest interprete `mock_get_sb` como un fixture inexistente. Copiamos solo
    # el nombre para que el reporte de tests muestre el nombre real.
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# 1. FLUJO: Crear Reporte (API → crear_reporte → RPC + ReporteRepository)
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationCrearReporte:

    @patch_supabase
    def test_crear_reporte_flujo_completo(self, mock_get_sb):
        _override_user(CIUDADANO)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. RPC crear_reporte_con_validacion
            [{"reporte_id": "rep-int-1", "lectura_evidencia_id": None}],
            # 2. repo.get_by_id → reporte row
            {"id": "rep-int-1", "usuario_id": "int-c1", "comuna_id": 1,
             "titulo": "Ruido nocturno", "descripcion": "Mucho ruido",
             "latitud": -33.45, "longitud": -70.65,
             "lectura_evidencia_id": None, "atendido_por_id": None,
             "created_at": now, "updated_at": now},
            # 3. _get_estado_actual
            [{"tipo_estado": {"nombre": "En espera"}}],
            # 4. _get_historial
            [{"tipo_estado": {"nombre": "En espera"}, "comentario": None,
              "created_at": now, "usuario": {"id": "sys", "nombre": "Sistema"}}],
        ])
        mock_get_sb.return_value = mock_db

        payload = {
            "titulo": "Ruido nocturno",
            "descripcion": "Mucho ruido en la calle a las 3am todos los dias",
            "latitud": -33.45,
            "longitud": -70.65,
        }
        r = client.post("/api/v1/reportes", json=payload)
        assert r.status_code == 201
        body = r.json()
        assert body["id"] == "rep-int-1"
        assert body["titulo"] == "Ruido nocturno"
        assert body["estado_actual"] == "En espera"

    @patch_supabase
    def test_crear_reporte_comuna_invalida(self, mock_get_sb):
        _override_user(Usuario(id="int-c2", nombre="Sin comuna", tipo="ciudadano", activo=True))
        mock_db = _sequenced_mock([None])  # comuna lookup returns nothing
        mock_get_sb.return_value = mock_db

        payload = {
            "titulo": "Ruido nocturno",
            "descripcion": "Mucho ruido en la calle a las 3am todos los dias",
            "latitud": -33.45, "longitud": -70.65, "comuna_id": 9999,
        }
        r = client.post("/api/v1/reportes", json=payload)
        assert r.status_code == 422

    def test_crear_reporte_payload_invalido(self):
        _override_user(CIUDADANO)
        r = client.post("/api/v1/reportes", json={"titulo": "", "latitud": -33.0, "longitud": -70.0})
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 2. FLUJO: Cambiar Estado Reporte
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationCambiarEstado:

    @patch_supabase
    def test_transicion_valida_en_espera_a_en_atencion(self, mock_get_sb):
        _override_user(MUNICIPAL)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. repo.get_by_id → reporte
            {"id": "rep-1", "usuario_id": "u1", "comuna_id": 1,
             "titulo": "T", "descripcion": "D", "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": None,
             "created_at": now, "updated_at": now},
            # 2. _get_estado_actual
            [{"tipo_estado": {"nombre": "En espera"}}],
            # 3. _get_historial
            [],
            # 4. tipo_estado lookup
            {"id": 2},
            # 5. historial_estado.insert
            [{"id": 1}],
            # 6. reporte.update(atendido_por_id)
            [{"id": "rep-1"}],
            # 7. repo.get_by_id final
            {"id": "rep-1", "usuario_id": "u1", "comuna_id": 1,
             "titulo": "T", "descripcion": "D", "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": "int-m1",
             "created_at": now, "updated_at": now},
            # 8. _get_estado_actual final
            [{"tipo_estado": {"nombre": "En atencion"}}],
            # 9. _get_historial final
            [{"tipo_estado": {"nombre": "En atencion"}, "comentario": None,
              "created_at": now, "usuario": {"id": "int-m1", "nombre": "Municipal Int"}}],
            # 10-12. listar_comentarios internals
            {"id": "rep-1", "usuario_id": "u1", "comuna_id": 1,
             "titulo": "T", "descripcion": "D", "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": "int-m1",
             "created_at": now, "updated_at": now},
            [{"tipo_estado": {"nombre": "En atencion"}}],
            [],
            # 13. comentarios query
            [],
        ])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/reportes/rep-1/estado",
                         json={"nuevo_estado": "En atencion", "comentario": None})
        assert r.status_code == 200
        assert r.json()["estado_actual"] == "En atencion"

    @patch_supabase
    def test_transicion_invalida_rechazada(self, mock_get_sb):
        _override_user(MUNICIPAL)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            {"id": "rep-1", "usuario_id": "u1", "comuna_id": 1,
             "titulo": "T", "descripcion": "D", "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": None,
             "created_at": now, "updated_at": now},
            [{"tipo_estado": {"nombre": "Atendido"}}],
            [],
        ])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/reportes/rep-1/estado",
                         json={"nuevo_estado": "En espera", "comentario": None})
        # InvalidStateTransitionError has http_status=409
        assert r.status_code in (409, 422)

    @patch_supabase
    def test_comuna_mismatch_rechazado(self, mock_get_sb):
        _override_user(MUNICIPAL_OTRA)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            {"id": "rep-1", "usuario_id": "u1", "comuna_id": 1,
             "titulo": "T", "descripcion": "D", "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": None,
             "created_at": now, "updated_at": now},
            [{"tipo_estado": {"nombre": "En espera"}}],
            [],
        ])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/reportes/rep-1/estado",
                         json={"nuevo_estado": "En atencion", "comentario": None})
        assert r.status_code == 403

    @patch_supabase
    def test_descartar_sin_comentario_rechazado(self, mock_get_sb):
        _override_user(MUNICIPAL)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            {"id": "rep-1", "usuario_id": "u1", "comuna_id": 1,
             "titulo": "T", "descripcion": "D", "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": None,
             "created_at": now, "updated_at": now},
            [{"tipo_estado": {"nombre": "En espera"}}],
            [],
        ])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/reportes/rep-1/estado",
                         json={"nuevo_estado": "Descartado", "comentario": None})
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 3. FLUJO: Promover Usuario
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationPromoverUsuario:

    @patch("app.api.routes.usuarios._comuna_nombre", return_value="Santiago")
    @patch_supabase
    def test_promover_ciudadano_a_municipal(self, mock_get_sb, mock_comuna):
        _override_user(ADMIN)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. _validar_comuna
            {"id": 1},
            # 2. repo.get_by_id(target)
            {"id": "u-target", "nombre": "Target", "tipo": "ciudadano",
             "activo": True, "comuna_id": None, "created_at": now},
            # 3. repo.promover → update
            [{"id": "u-target", "nombre": "Target", "tipo": "municipalidad",
              "activo": True, "comuna_id": 1, "created_at": now}],
        ])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/usuarios/u-target/promover",
                         json={"nuevo_tipo": "municipalidad", "comuna_id": 1})
        assert r.status_code == 200
        assert r.json()["tipo"] == "municipalidad"
        assert r.json()["comuna_id"] == 1

    @patch_supabase
    def test_promover_sin_comuna_para_municipal_rechazado(self, mock_get_sb):
        _override_user(ADMIN)
        mock_get_sb.return_value = _sequenced_mock([])

        r = client.patch("/api/v1/usuarios/u-target/promover",
                         json={"nuevo_tipo": "municipalidad", "comuna_id": None})
        assert r.status_code == 422

    @patch_supabase
    def test_admin_no_puede_degradarse(self, mock_get_sb):
        _override_user(ADMIN)
        mock_get_sb.return_value = _sequenced_mock([])

        r = client.patch("/api/v1/usuarios/int-a1/promover",
                         json={"nuevo_tipo": "ciudadano", "comuna_id": None})
        assert r.status_code == 422

    @patch_supabase
    def test_promover_comuna_inexistente_rechazado(self, mock_get_sb):
        _override_user(ADMIN)
        mock_db = _sequenced_mock([None])  # comuna not found
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/usuarios/u-target/promover",
                         json={"nuevo_tipo": "municipalidad", "comuna_id": 9999})
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 4. FLUJO: CRUD Sensores
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationSensores:

    @patch_supabase
    def test_crear_sensor(self, mock_get_sb):
        _override_user(ADMIN)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. _validar_comuna
            {"id": 1},
            # 2. sensor.insert
            [{"id": "sensor-new", "comuna_id": 1, "nombre": "Sensor Plaza",
              "latitud": -33.45, "longitud": -70.65, "activo": True, "created_at": now}],
            # 3. get_by_id (RPC sensores_con_salud) post-insert
            [{"id": "sensor-new", "comuna_id": 1, "nombre": "Sensor Plaza",
              "latitud": -33.45, "longitud": -70.65, "activo": True,
              "created_at": now, "estado_salud": "sin_lecturas", "ultima_lectura_at": None}],
            # 4. comuna name lookup
            [{"id": 1, "nombre": "Santiago"}],
        ])
        mock_get_sb.return_value = mock_db

        r = client.post("/api/v1/sensores",
                        json={"nombre": "Sensor Plaza", "comuna_id": 1,
                              "latitud": -33.45, "longitud": -70.65})
        assert r.status_code == 201
        assert r.json()["nombre"] == "Sensor Plaza"

    @patch_supabase
    def test_crear_sensor_comuna_invalida(self, mock_get_sb):
        _override_user(ADMIN)
        mock_db = _sequenced_mock([None])
        mock_get_sb.return_value = mock_db

        r = client.post("/api/v1/sensores",
                        json={"nombre": "S", "comuna_id": 9999,
                              "latitud": 0.0, "longitud": 0.0})
        assert r.status_code == 422

    @patch_supabase
    def test_obtener_sensor_no_existente(self, mock_get_sb):
        _override_user(ADMIN)
        # sensores_con_salud RPC returns empty → sensor not found
        mock_db = _sequenced_mock([[]])
        mock_get_sb.return_value = mock_db

        r = client.get("/api/v1/sensores/no-existe")
        assert r.status_code == 404

    @patch_supabase
    def test_municipal_no_ve_sensor_otra_comuna(self, mock_get_sb):
        _override_user(MUNICIPAL)  # comuna_id=1
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. RPC sensores_con_salud
            [{"id": "s-otra", "comuna_id": 2, "nombre": "Sensor Otra",
              "latitud": 0.0, "longitud": 0.0, "activo": True,
              "created_at": now, "estado_salud": None, "ultima_lectura_at": None}],
            # 2. comuna lookup
            [{"id": 2, "nombre": "Otra Comuna"}],
        ])
        mock_get_sb.return_value = mock_db

        r = client.get("/api/v1/sensores/s-otra")
        assert r.status_code == 403

    @patch_supabase
    def test_desactivar_sensor(self, mock_get_sb):
        _override_user(ADMIN)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. get_by_id check (RPC)
            [{"id": "s1", "comuna_id": 1, "nombre": "S", "latitud": 0.0, "longitud": 0.0,
              "activo": True, "created_at": now, "estado_salud": None, "ultima_lectura_at": None}],
            # 2. comuna lookup for get_by_id
            [{"id": 1, "nombre": "Santiago"}],
            # 3. actualizar → update
            [{"id": "s1", "comuna_id": 1, "nombre": "S", "latitud": 0.0, "longitud": 0.0,
              "activo": False, "created_at": now}],
            # 4. get_by_id post-update (RPC)
            [{"id": "s1", "comuna_id": 1, "nombre": "S", "latitud": 0.0, "longitud": 0.0,
              "activo": False, "created_at": now, "estado_salud": "offline", "ultima_lectura_at": None}],
            # 5. comuna lookup
            [{"id": 1, "nombre": "Santiago"}],
        ])
        mock_get_sb.return_value = mock_db

        r = client.delete("/api/v1/sensores/s1")
        assert r.status_code == 200
        assert r.json()["activo"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. FLUJO: Detalle Reporte + Permisos
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationDetalleReporte:

    @patch_supabase
    def test_dueno_puede_ver_su_reporte(self, mock_get_sb):
        _override_user(CIUDADANO)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. repo.get_by_id
            {"id": "rep-1", "usuario_id": "int-c1", "comuna_id": 1,
             "titulo": "Mi reporte", "descripcion": "Desc",
             "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": None,
             "created_at": now, "updated_at": now},
            # 2. _get_estado_actual
            [{"tipo_estado": {"nombre": "En espera"}}],
            # 3. _get_historial
            [],
            # 4-6. listar_comentarios → _cargar_reporte
            {"id": "rep-1", "usuario_id": "int-c1", "comuna_id": 1,
             "titulo": "Mi reporte", "descripcion": "Desc",
             "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": None,
             "created_at": now, "updated_at": now},
            [{"tipo_estado": {"nombre": "En espera"}}],
            [],
            # 7. comentarios query
            [],
        ])
        mock_get_sb.return_value = mock_db

        r = client.get("/api/v1/reportes/rep-1")
        assert r.status_code == 200
        assert r.json()["id"] == "rep-1"
        assert r.json()["titulo"] == "Mi reporte"

    @patch_supabase
    def test_ciudadano_no_dueno_rechazado(self, mock_get_sb):
        _override_user(CIUDADANO)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            {"id": "rep-1", "usuario_id": "otro-usuario", "comuna_id": 1,
             "titulo": "T", "descripcion": "D",
             "latitud": -33.0, "longitud": -70.0,
             "lectura_evidencia_id": None, "atendido_por_id": None,
             "created_at": now, "updated_at": now},
            [{"tipo_estado": {"nombre": "En espera"}}],
            [],
        ])
        mock_get_sb.return_value = mock_db

        r = client.get("/api/v1/reportes/rep-1")
        assert r.status_code == 403

    @patch_supabase
    def test_reporte_no_existente_404(self, mock_get_sb):
        mock_db = _sequenced_mock([None])
        mock_get_sb.return_value = mock_db
        _override_user(CIUDADANO)

        r = client.get("/api/v1/reportes/no-existe")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 6. FLUJO: Actualizar Perfil (PATCH /usuarios/me)
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationActualizarPerfil:

    @patch("app.api.routes.usuarios._comuna_nombre", return_value="Providencia")
    @patch_supabase
    def test_actualizar_telefono_y_comuna(self, mock_get_sb, mock_comuna):
        _override_user(CIUDADANO)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. comuna exists check
            {"id": 2},
            # 2. repo.update_me
            [{"id": "int-c1", "nombre": "Ciudadano Int", "tipo": "ciudadano",
              "activo": True, "comuna_id": 2, "telefono": "+56912345678",
              "created_at": now}],
        ])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/usuarios/me",
                         json={"telefono": "+56912345678", "comuna_id": 2})
        assert r.status_code == 200
        assert r.json()["telefono"] == "+56912345678"
        assert r.json()["comuna_id"] == 2

    def test_actualizar_sin_campos_rechazado(self):
        _override_user(CIUDADANO)
        r = client.patch("/api/v1/usuarios/me", json={})
        assert r.status_code == 422

    @patch_supabase
    def test_actualizar_comuna_invalida(self, mock_get_sb):
        _override_user(CIUDADANO)
        mock_db = _sequenced_mock([None])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/usuarios/me", json={"comuna_id": 9999})
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 7. FLUJO: Buscar Evidencia IoT
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationBuscarEvidencia:

    @patch_supabase
    def test_evidencia_encontrada(self, mock_get_sb):
        _override_user(CIUDADANO)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. RPC validar_reporte_ruido
            [{"lectura_id": 42, "sensor_id": "s1", "nivel_db": 85.0,
              "distancia_metros": 15.0, "timestamp_medicion": now}],
            # 2. sensor nombre lookup
            {"nombre": "Sensor Plaza"},
        ])
        mock_get_sb.return_value = mock_db

        r = client.get("/api/v1/reportes/buscar-evidencia?lat=-33.45&lng=-70.65")
        assert r.status_code == 200
        body = r.json()
        assert body["evidencia"]["sensor_id"] == "s1"
        assert body["evidencia"]["sensor_nombre"] == "Sensor Plaza"
        assert body["evidencia"]["nivel_db"] == 85.0

    @patch_supabase
    def test_sin_evidencia(self, mock_get_sb):
        _override_user(CIUDADANO)
        mock_db = _sequenced_mock([[]])  # RPC returns empty
        mock_get_sb.return_value = mock_db

        r = client.get("/api/v1/reportes/buscar-evidencia?lat=-33.45&lng=-70.65")
        assert r.status_code == 200
        assert r.json()["evidencia"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 8. FLUJO: Listar Reportes con Paginación
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationListarReportes:

    @patch_supabase
    def test_listar_mis_reportes_con_datos(self, mock_get_sb):
        _override_user(CIUDADANO)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. list_by_usuario query
            [{"id": "r1", "titulo": "Reporte 1", "created_at": now,
              "comuna_id": 1, "lectura_evidencia_id": None},
             {"id": "r2", "titulo": "Reporte 2", "created_at": now,
              "comuna_id": 1, "lectura_evidencia_id": None}],
            # 2-3. _get_estado_actual for each
            [{"tipo_estado": {"nombre": "En espera"}}],
            [{"tipo_estado": {"nombre": "Atendido"}}],
        ])
        mock_get_sb.return_value = mock_db

        r = client.get("/api/v1/reportes/mios")
        assert r.status_code == 200
        body = r.json()
        assert len(body["data"]) == 2

    @patch_supabase
    def test_listar_reportes_vacio(self, mock_get_sb):
        _override_user(CIUDADANO)
        mock_db = _sequenced_mock([[]])
        mock_get_sb.return_value = mock_db

        r = client.get("/api/v1/reportes/mios")
        assert r.status_code == 200
        assert r.json() == {"data": [], "next_cursor": None}


# ══════════════════════════════════════════════════════════════════════════════
# 9. FLUJO: Cambiar Activo Usuario
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationCambiarActivo:

    @patch("app.api.routes.usuarios._comuna_nombre", return_value=None)
    @patch_supabase
    def test_desactivar_usuario(self, mock_get_sb, mock_comuna):
        _override_user(ADMIN)
        now = datetime.now(timezone.utc).isoformat()

        mock_db = _sequenced_mock([
            # 1. repo.get_by_id target
            {"id": "u-target", "nombre": "Target", "tipo": "ciudadano",
             "activo": True, "created_at": now},
            # 2. repo.set_activo
            [{"id": "u-target", "nombre": "Target", "tipo": "ciudadano",
              "activo": False, "created_at": now}],
        ])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/usuarios/u-target/activo", json={"activo": False})
        assert r.status_code == 200
        assert r.json()["activo"] is False

    @patch_supabase
    def test_desactivar_usuario_no_existente(self, mock_get_sb):
        _override_user(ADMIN)
        mock_db = _sequenced_mock([None])
        mock_get_sb.return_value = mock_db

        r = client.patch("/api/v1/usuarios/no-existe/activo", json={"activo": False})
        assert r.status_code == 404

    @patch_supabase
    def test_admin_no_puede_desactivarse(self, mock_get_sb):
        _override_user(ADMIN)
        mock_get_sb.return_value = _sequenced_mock([])

        r = client.patch("/api/v1/usuarios/int-a1/activo", json={"activo": False})
        assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# 10. FLUJO: Reportes Admin Archivos
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegrationReportesAdminArchivos:

    @patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
    @patch_supabase
    def test_subir_archivo(self, mock_get_sb, mock_storage_cls):
        _override_user(ADMIN)
        now = datetime.now(timezone.utc).isoformat()
        mock_storage_cls.return_value = MagicMock()

        mock_db = _sequenced_mock([
            [{"id": "arch-1", "generado_por_id": "int-a1", "nombre": "informe.pdf",
              "tipo": "pdf", "mime_type": "application/pdf", "tamano_bytes": 8,
              "object_path": "int-a1/ulid_informe.pdf",
              "rango_desde": None, "rango_hasta": None, "created_at": now,
              "usuario": {"nombre": "Admin Int"}}],
        ])
        mock_get_sb.return_value = mock_db

        r = client.post(
            "/api/v1/reportes-admin/archivos",
            data={"nombre": "informe.pdf", "tipo": "pdf"},
            files={"archivo": ("informe.pdf", BytesIO(b"fake-pdf"), "application/pdf")},
        )
        assert r.status_code == 201
        assert r.json()["nombre"] == "informe.pdf"
        mock_storage_cls.return_value.upload.assert_called_once()

    @patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
    @patch_supabase
    def test_eliminar_archivo(self, mock_get_sb, mock_storage_cls):
        _override_user(ADMIN)
        now = datetime.now(timezone.utc).isoformat()
        mock_storage_cls.return_value = MagicMock()

        mock_db = _sequenced_mock([
            # 1. repo.get_by_id
            {"id": "arch-1", "generado_por_id": "int-a1", "nombre": "informe.pdf",
             "tipo": "pdf", "mime_type": "application/pdf", "tamano_bytes": 1024,
             "object_path": "int-a1/ulid_informe.pdf",
             "rango_desde": None, "rango_hasta": None, "created_at": now,
             "usuario": {"nombre": "Admin Int"}},
            # 2. repo.delete
            None,
        ])
        mock_get_sb.return_value = mock_db

        r = client.delete("/api/v1/reportes-admin/archivos/arch-1")
        assert r.status_code == 204
        mock_storage_cls.return_value.remove.assert_called_once()

    @patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
    @patch_supabase
    def test_subir_archivo_mime_invalido(self, mock_get_sb, mock_storage_cls):
        _override_user(ADMIN)
        mock_get_sb.return_value = _sequenced_mock([])

        r = client.post(
            "/api/v1/reportes-admin/archivos",
            data={"nombre": "malware.exe", "tipo": "pdf"},
            files={"archivo": ("malware.exe", BytesIO(b"fake"), "application/x-msdownload")},
        )
        assert r.status_code == 422
