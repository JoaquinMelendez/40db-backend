"""
Tests de Humo (Smoke Tests)
============================
Verifican que TODOS los endpoints de la API responden con el status code
esperado y no devuelven errores 500 inesperados.

Objetivo: confirmar que la API "está viva" tras cada deploy/merge.
No se valida lógica de negocio (eso es responsabilidad de los tests unitarios).
"""

import pytest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.api.deps import (
    current_user, current_user_municipal, current_user_admin,
    current_user_municipal_o_admin, current_user_municipal_de_comuna,
)
from app.domain.entities import (
    Usuario, Reporte, Sensor, ResumenHorario,
    EvidenciaIot, ReporteArchivoAdmin,
)

client = TestClient(app, raise_server_exceptions=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

CIUDADANO = Usuario(id="smoke-c1", nombre="Ciudadano Smoke", tipo="ciudadano", activo=True, comuna_id=1)
MUNICIPAL = Usuario(id="smoke-m1", nombre="Municipal Smoke", tipo="municipalidad", activo=True, comuna_id=1)
ADMIN = Usuario(id="smoke-a1", nombre="Admin Smoke", tipo="admin", activo=True)


def _override_user(user: Usuario):
    """Inyecta un usuario mock en todas las dependencias de autenticación."""
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[current_user_municipal] = lambda: user
    app.dependency_overrides[current_user_admin] = lambda: user
    app.dependency_overrides[current_user_municipal_o_admin] = lambda: user


@pytest.fixture(autouse=True)
def _cleanup():
    """Limpia overrides tras cada test."""
    yield
    app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════════════════════
# 1. HEALTH — Endpoints sin autenticación
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeHealth:
    """Smoke tests para /health/*"""

    def test_liveness_returns_200(self):
        r = client.get("/health/live")
        assert r.status_code == 200
        assert "status" in r.json()

    @patch("app.core.supabase_client.get_supabase")
    def test_readiness_returns_200_or_503(self, mock_sb):
        mock_sb.return_value = MagicMock()
        mock_sb.return_value.table().select().limit().execute.return_value = MagicMock(data=[{}])
        r = client.get("/health/ready")
        assert r.status_code in (200, 503)
        assert "status" in r.json()


# ══════════════════════════════════════════════════════════════════════════════
# 2. CATÁLOGOS — Endpoints públicos (solo requieren Supabase mock)
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeCatalogos:
    """Smoke tests para /api/v1/comunas y /api/v1/tipos-estado"""

    @patch("app.api.routes.catalogos.get_supabase")
    def test_comunas_returns_200(self, mock_sb):
        mock_sb.return_value = MagicMock()
        mock_sb.return_value.table().select().order().execute.return_value = MagicMock(data=[])
        r = client.get("/api/v1/comunas")
        assert r.status_code == 200

    @patch("app.api.routes.catalogos.get_supabase")
    def test_tipos_estado_returns_200(self, mock_sb):
        mock_sb.return_value = MagicMock()
        mock_sb.return_value.table().select().order().execute.return_value = MagicMock(data=[])
        r = client.get("/api/v1/tipos-estado")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 3. REPORTES — Endpoints autenticados
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeReportes:
    """Smoke tests para /api/v1/reportes/*"""

    @patch("app.application.buscar_evidencia.buscar_evidencia")
    def test_buscar_evidencia_returns_200(self, mock_uc):
        _override_user(CIUDADANO)
        mock_uc.return_value = None
        r = client.get("/api/v1/reportes/buscar-evidencia?lat=-33.45&lng=-70.65")
        assert r.status_code == 200

    @patch("app.application.crear_reporte.crear_reporte")
    def test_crear_reporte_returns_201(self, mock_uc):
        _override_user(CIUDADANO)
        mock_uc.return_value = Reporte(
            id="r1", usuario_id="smoke-c1", comuna_id=1,
            titulo="Test", descripcion="Smoke", latitud=-33.0, longitud=-70.0,
            estado_actual="En espera",
        )
        payload = {
            "titulo": "Test smoke",
            "descripcion": "Descripcion de prueba de humo con suficientes caracteres.",
            "latitud": -33.0,
            "longitud": -70.0,
        }
        r = client.post("/api/v1/reportes", json=payload)
        assert r.status_code == 201

    @patch("app.infrastructure.db.reporte_repo.ReporteRepository")
    def test_mis_reportes_returns_200(self, mock_repo_cls):
        _override_user(CIUDADANO)
        mock_repo_cls.return_value.list_by_usuario.return_value = ([], None)
        r = client.get("/api/v1/reportes/mios")
        assert r.status_code == 200

    @patch("app.infrastructure.db.reporte_repo.ReporteRepository")
    def test_reportes_comuna_returns_200(self, mock_repo_cls):
        _override_user(MUNICIPAL)
        app.dependency_overrides[current_user_municipal_de_comuna(1)] = lambda: MUNICIPAL
        mock_repo_cls.return_value.list_by_comuna.return_value = ([], None)
        r = client.get("/api/v1/reportes/comuna/1")
        assert r.status_code == 200

    @patch("app.application.reporte_comentarios.listar_comentarios")
    @patch("app.infrastructure.db.reporte_repo.ReporteRepository")
    def test_detalle_reporte_returns_200(self, mock_repo_cls, mock_comments):
        _override_user(CIUDADANO)
        mock_repo_cls.return_value.get_by_id.return_value = Reporte(
            id="r1", usuario_id="smoke-c1", comuna_id=1,
            titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0,
            estado_actual="En espera",
        )
        mock_comments.return_value = []
        r = client.get("/api/v1/reportes/r1")
        assert r.status_code == 200

    @patch("app.application.reporte_comentarios.listar_comentarios")
    @patch("app.application.cambiar_estado_reporte.cambiar_estado_reporte")
    def test_cambiar_estado_returns_200(self, mock_uc, mock_comments):
        _override_user(MUNICIPAL)
        mock_uc.return_value = Reporte(
            id="r1", usuario_id="u1", comuna_id=1,
            titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0,
            estado_actual="En atencion",
        )
        mock_comments.return_value = []
        r = client.patch("/api/v1/reportes/r1/estado", json={"nuevo_estado": "En atencion", "comentario": None})
        assert r.status_code == 200

    @patch("app.application.reporte_comentarios.agregar_comentario")
    def test_crear_comentario_returns_201(self, mock_uc):
        _override_user(CIUDADANO)
        mock_uc.return_value = {
            "id": 1, "visibilidad": "externo", "cuerpo": "Test",
            "autor": {"id": "smoke-c1", "nombre": "Ciudadano Smoke"},
            "delegado_a": None, "delegado_at": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        payload = {"visibilidad": "externo", "cuerpo": "Comentario de prueba smoke"}
        r = client.post("/api/v1/reportes/r1/comentarios", json=payload)
        assert r.status_code == 201

    @patch("app.application.reporte_comentarios.listar_comentarios")
    def test_listar_comentarios_returns_200(self, mock_uc):
        _override_user(CIUDADANO)
        mock_uc.return_value = []
        r = client.get("/api/v1/reportes/r1/comentarios")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 4. HEATMAPS
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeHeatmaps:
    """Smoke tests para /api/v1/heatmaps"""

    @patch("app.application.obtener_heatmap.obtener_heatmap")
    def test_heatmap_returns_200(self, mock_uc):
        mock_uc.return_value = ([], "matview")
        r = client.get(
            "/api/v1/heatmaps?bbox=-70.7,-33.5,-70.6,-33.4"
            "&time_start=2026-06-03T00:00:00Z"
            "&time_end=2026-06-03T12:00:00Z"
            "&bucket_minutes=5"
        )
        assert r.status_code == 200
        assert r.json()["type"] == "FeatureCollection"


# ══════════════════════════════════════════════════════════════════════════════
# 5. USUARIOS
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeUsuarios:
    """Smoke tests para /api/v1/usuarios/*"""

    @patch("app.core.supabase_client.get_supabase")
    def test_me_get_returns_200(self, mock_sb):
        _override_user(CIUDADANO)
        mock_sb.return_value = MagicMock()
        mock_sb.return_value.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"nombre": "Santiago"})
        r = client.get("/api/v1/usuarios/me")
        assert r.status_code == 200

    @patch("app.api.routes.usuarios._comuna_nombre", return_value="Santiago")
    @patch("app.core.supabase_client.get_supabase")
    @patch("app.infrastructure.db.usuario_repo.UsuarioRepository")
    def test_me_patch_returns_200(self, mock_repo_cls, mock_sb, mock_comuna):
        _override_user(CIUDADANO)
        # Mock comuna existence check in patch_me
        mock_sb.return_value = MagicMock()
        mock_sb.return_value.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"id": 1})
        mock_repo_cls.return_value.update_me.return_value = Usuario(
            id="smoke-c1", nombre="Ciudadano Smoke", tipo="ciudadano",
            activo=True, comuna_id=1, telefono="+56912345678",
        )
        r = client.patch("/api/v1/usuarios/me", json={"telefono": "+56912345678"})
        assert r.status_code == 200

    @patch("app.core.supabase_client.get_supabase")
    @patch("app.application.listar_usuarios.listar_usuarios")
    def test_listar_usuarios_returns_200(self, mock_uc, mock_sb):
        _override_user(ADMIN)
        mock_uc.return_value = ([], None, {})
        r = client.get("/api/v1/usuarios")
        assert r.status_code == 200

    @patch("app.core.supabase_client.get_supabase")
    @patch("app.application.promover_usuario.promover_usuario")
    def test_promover_usuario_returns_200(self, mock_uc, mock_sb):
        _override_user(ADMIN)
        mock_uc.return_value = Usuario(id="u2", nombre="Promo", tipo="municipalidad", activo=True, comuna_id=1)
        mock_sb.return_value = MagicMock()
        mock_sb.return_value.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"nombre": "Santiago"})
        r = client.patch("/api/v1/usuarios/u2/promover", json={"nuevo_tipo": "municipalidad", "comuna_id": 1})
        assert r.status_code == 200

    @patch("app.core.supabase_client.get_supabase")
    @patch("app.application.cambiar_activo_usuario.cambiar_activo_usuario")
    def test_cambiar_activo_returns_200(self, mock_uc, mock_sb):
        _override_user(ADMIN)
        mock_uc.return_value = Usuario(id="u2", nombre="U", tipo="ciudadano", activo=False)
        mock_sb.return_value = MagicMock()
        mock_sb.return_value.table().select().eq().maybe_single().execute.return_value = MagicMock(data=None)
        r = client.patch("/api/v1/usuarios/u2/activo", json={"activo": False})
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 6. SENSORES
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeSensores:
    """Smoke tests para /api/v1/sensores/*"""

    @patch("app.application.sensores.listar_sensores")
    def test_listar_sensores_returns_200(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = ([], None)
        r = client.get("/api/v1/sensores")
        assert r.status_code == 200

    @patch("app.application.sensores.obtener_sensor")
    def test_detalle_sensor_returns_200(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = Sensor(id="s1", comuna_id=1, nombre="S", latitud=0, longitud=0, activo=True)
        r = client.get("/api/v1/sensores/s1")
        assert r.status_code == 200

    @patch("app.application.sensores.obtener_resumen_sensores")
    def test_resumen_sensores_returns_200(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = {"total": 0, "online": 0, "intermitente": 0, "offline": 0, "sin_lecturas": 0}
        r = client.get("/api/v1/sensores/resumen")
        assert r.status_code == 200

    @patch("app.application.sensores.crear_sensor")
    def test_crear_sensor_returns_201(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = Sensor(id="s1", comuna_id=1, nombre="Nuevo", latitud=0.0, longitud=0.0, activo=True)
        r = client.post("/api/v1/sensores", json={"nombre": "Nuevo", "comuna_id": 1, "latitud": 0.0, "longitud": 0.0})
        assert r.status_code == 201

    @patch("app.application.sensores.actualizar_sensor")
    def test_actualizar_sensor_returns_200(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = Sensor(id="s1", comuna_id=1, nombre="Upd", latitud=0.0, longitud=0.0, activo=True)
        r = client.patch("/api/v1/sensores/s1", json={"nombre": "Upd", "latitud": None, "longitud": None, "activo": None})
        assert r.status_code == 200

    @patch("app.application.sensores.desactivar_sensor")
    def test_desactivar_sensor_returns_200(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = Sensor(id="s1", comuna_id=1, nombre="S", latitud=0.0, longitud=0.0, activo=False)
        r = client.delete("/api/v1/sensores/s1")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 7. LECTURAS
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeLecturas:
    """Smoke tests para /api/v1/lecturas/*"""

    @patch("app.api.routes.lecturas.obtener_resumen_horario")
    def test_resumen_horario_returns_200(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = {
            "sensor_id": "s1", "sensor_nombre": "S",
            "desde": "2026-06-03T00:00:00", "hasta": "2026-06-03T12:00:00",
            "horas": [], "fuente": "lectura_resumen_horaria", "refrescado_at": None,
        }
        r = client.get("/api/v1/lecturas/resumen?sensor_id=s1&desde=2026-06-03T00:00:00&hasta=2026-06-03T12:00:00")
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 8. REPORTES ADMIN ARCHIVOS
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeReportesAdminArchivos:
    """Smoke tests para /api/v1/reportes-admin/archivos/*"""

    @patch("app.application.reportes_admin_archivos.listar_archivos")
    def test_listar_archivos_returns_200(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = ([], None)
        r = client.get("/api/v1/reportes-admin/archivos")
        assert r.status_code == 200

    @patch("app.application.reportes_admin_archivos.subir_archivo")
    def test_subir_archivo_returns_201(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = ReporteArchivoAdmin(
            id="a1", nombre="test.pdf", tipo="pdf", mime_type="application/pdf",
            tamano_bytes=1024, generado_por_id="smoke-a1", generado_por_nombre="Admin Smoke",
            object_path="reportes-admin/a1/test.pdf",
            created_at=datetime.now(timezone.utc),
        )
        r = client.post(
            "/api/v1/reportes-admin/archivos",
            data={"nombre": "test.pdf", "tipo": "pdf"},
            files={"archivo": ("test.pdf", BytesIO(b"fake-pdf-content"), "application/pdf")},
        )
        assert r.status_code == 201

    @patch("app.application.reportes_admin_archivos.obtener_url_descarga")
    def test_descarga_archivo_returns_200(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = ("https://storage.example.com/signed-url", 3600)
        r = client.get("/api/v1/reportes-admin/archivos/a1/descarga")
        assert r.status_code == 200

    @patch("app.application.reportes_admin_archivos.eliminar_archivo")
    def test_eliminar_archivo_returns_204(self, mock_uc):
        _override_user(ADMIN)
        mock_uc.return_value = None
        r = client.delete("/api/v1/reportes-admin/archivos/a1")
        assert r.status_code == 204


# ══════════════════════════════════════════════════════════════════════════════
# 9. SMOKE: ENDPOINTS SIN AUTH DEVUELVEN 401/403
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeAuthRequired:
    """Verifica que endpoints protegidos rechazan requests sin token."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/v1/reportes/mios"),
        ("GET", "/api/v1/reportes/buscar-evidencia?lat=-33.45&lng=-70.65"),
        ("POST", "/api/v1/reportes"),
        ("GET", "/api/v1/usuarios/me"),
        ("GET", "/api/v1/usuarios"),
        ("GET", "/api/v1/sensores"),
        ("GET", "/api/v1/sensores/resumen"),
        ("GET", "/api/v1/lecturas/resumen?sensor_id=s1&desde=2026-06-03T00:00:00&hasta=2026-06-03T12:00:00"),
        ("GET", "/api/v1/reportes-admin/archivos"),
    ])
    def test_returns_401_or_403_without_token(self, method, path):
        """Sin token de autenticación, el endpoint debe rechazar la request."""
        r = client.request(method, path)
        assert r.status_code in (401, 403), (
            f"{method} {path} returned {r.status_code}, expected 401 or 403"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 10. SMOKE: CORRELATION ID PROPAGATION
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeCorrelationId:
    """Verifica que el middleware de correlation ID funciona en toda la API."""

    def test_custom_correlation_id_is_echoed(self):
        r = client.get("/health/live", headers={"X-Correlation-Id": "smoke-test-123"})
        assert r.headers.get("X-Correlation-Id") == "smoke-test-123"

    def test_auto_generated_correlation_id(self):
        r = client.get("/health/live")
        assert "X-Correlation-Id" in r.headers
        assert len(r.headers["X-Correlation-Id"]) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 11. SMOKE: ERROR FORMAT CONSISTENCY
# ══════════════════════════════════════════════════════════════════════════════

class TestSmokeErrorFormat:
    """Verifica que los errores siguen el formato estándar de la API."""

    def test_404_has_standard_error_format(self):
        _override_user(CIUDADANO)
        with patch("app.infrastructure.db.reporte_repo.ReporteRepository") as mock_cls:
            from app.domain.errors import NotFoundError
            mock_cls.return_value.get_by_id.side_effect = NotFoundError("No existe")
            r = client.get("/api/v1/reportes/nonexistent-id")
            assert r.status_code == 404
            body = r.json()
            assert "error" in body
            assert "code" in body["error"]
            assert "message" in body["error"]
            assert "correlation_id" in body["error"]

    def test_422_has_standard_error_format(self):
        _override_user(CIUDADANO)
        # Enviar payload inválido (sin campos requeridos)
        r = client.post("/api/v1/reportes", json={})
        assert r.status_code == 422
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "validation_error"

    @patch("app.api.routes.catalogos.get_supabase")
    def test_500_has_standard_error_format(self, mock_sb):
        mock_sb.side_effect = RuntimeError("Unhandled crash")
        r = client.get("/api/v1/comunas")
        assert r.status_code == 500
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "internal_error"
