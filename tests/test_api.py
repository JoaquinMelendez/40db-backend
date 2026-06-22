import pytest
import jwt
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.api.deps import (
    current_user, current_user_municipal, current_user_admin,
    current_user_municipal_o_admin, current_user_municipal_de_comuna,
    _decode_jwt
)
from app.domain.entities import Usuario, Reporte, Sensor, EvidenciaIot
from app.domain.errors import (
    NotFoundError, ForbiddenError, ComunaMismatchError, InvalidTokenError, UnauthorizedError
)

client = TestClient(app)
client_no_raise = TestClient(app, raise_server_exceptions=False)


# ── 1. Test JWT y Dependencies (deps.py) ──────────────────────────────────────

def test_decode_jwt_hs256_success():
    payload = {"sub": "user-123", "aud": "authenticated", "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())}
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")
    
    decoded = _decode_jwt(token)
    assert decoded["sub"] == "user-123"


def test_decode_jwt_invalid_token():
    with pytest.raises(InvalidTokenError):
        _decode_jwt("invalid-token-header.payload.signature")


def test_decode_jwt_unsupported_alg():
    payload = {"sub": "user-123", "aud": "authenticated"}
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS512")
    with pytest.raises(InvalidTokenError) as exc:
        _decode_jwt(token)
    assert "Algoritmo de firma no soportado" in str(exc.value)


def test_decode_jwt_expired():
    payload = {"sub": "user-123", "aud": "authenticated", "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())}
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")
    with pytest.raises(InvalidTokenError) as exc:
        _decode_jwt(token)
    assert "Token expirado." in str(exc.value) or "Token inválido: Signature verification failed" in str(exc.value)


@patch("app.api.deps._decode_jwt")
@patch("app.api.deps.UsuarioRepository")
@pytest.mark.anyio
async def test_current_user_unauthorized_no_creds(mock_repo_cls, mock_decode):
    with pytest.raises(UnauthorizedError):
        await current_user(None)


@patch("app.api.deps._decode_jwt")
@patch("app.api.deps.UsuarioRepository")
@pytest.mark.anyio
async def test_current_user_unauthorized_no_sub(mock_repo_cls, mock_decode):
    mock_decode.return_value = {"aud": "authenticated"}
    creds = MagicMock(credentials="token")
    with pytest.raises(InvalidTokenError):
        await current_user(creds)


@patch("app.api.deps._decode_jwt")
@patch("app.api.deps.UsuarioRepository")
@pytest.mark.anyio
async def test_current_user_not_found(mock_repo_cls, mock_decode):
    mock_decode.return_value = {"sub": "u1"}
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo
    creds = MagicMock(credentials="token")
    
    with pytest.raises(UnauthorizedError):
        await current_user(creds)


@patch("app.api.deps._decode_jwt")
@patch("app.api.deps.UsuarioRepository")
@pytest.mark.anyio
async def test_current_user_inactive(mock_repo_cls, mock_decode):
    mock_decode.return_value = {"sub": "u1"}
    user = Usuario(id="u1", nombre="N", tipo="ciudadano", activo=False)
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = user
    mock_repo_cls.return_value = mock_repo
    creds = MagicMock(credentials="token")
    
    with pytest.raises(UnauthorizedError):
        await current_user(creds)


@patch("app.api.deps._decode_jwt")
@patch("app.api.deps.UsuarioRepository")
@pytest.mark.anyio
async def test_current_user_success(mock_repo_cls, mock_decode):
    mock_decode.return_value = {"sub": "u1"}
    user = Usuario(id="u1", nombre="N", tipo="ciudadano", activo=True)
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = user
    mock_repo_cls.return_value = mock_repo
    creds = MagicMock(credentials="token")
    
    res = await current_user(creds)
    assert res == user


@pytest.mark.anyio
async def test_role_dependencies():
    ciudadano = Usuario(id="u1", nombre="N", tipo="ciudadano", activo=True)
    muni = Usuario(id="u2", nombre="N", tipo="municipalidad", activo=True, comuna_id=1)
    admin = Usuario(id="u3", nombre="N", tipo="admin", activo=True)

    # current_user_municipal
    assert await current_user_municipal(muni) == muni
    with pytest.raises(ForbiddenError):
        await current_user_municipal(ciudadano)

    # current_user_admin
    assert await current_user_admin(admin) == admin
    with pytest.raises(ForbiddenError):
        await current_user_admin(muni)

    # current_user_municipal_o_admin
    assert await current_user_municipal_o_admin(muni) == muni
    assert await current_user_municipal_o_admin(admin) == admin
    with pytest.raises(ForbiddenError):
        await current_user_municipal_o_admin(ciudadano)

    # current_user_municipal_de_comuna
    dep_comuna_1 = current_user_municipal_de_comuna(1)
    assert await dep_comuna_1(muni) == muni
    with pytest.raises(ComunaMismatchError):
        await dep_comuna_1(Usuario(id="u4", nombre="N", tipo="municipalidad", activo=True, comuna_id=2))


# ── 2. Test Correlation ID Middleware ─────────────────────────────────────────

def test_correlation_id_middleware():
    response = client.get("/health/live", headers={"X-Correlation-Id": "my-custom-cid"})
    assert response.status_code == 200
    assert response.headers.get("X-Correlation-Id") == "my-custom-cid"

    # Auto generation test
    response_auto = client.get("/health/live")
    assert response_auto.status_code == 200
    assert "X-Correlation-Id" in response_auto.headers


# ── 3. Test Health y Catalogos Routes ─────────────────────────────────────────

@patch("app.core.supabase_client.get_supabase")
def test_health_ready_success(mock_get_sb):
    mock_sb = MagicMock()
    mock_sb.table().select().limit().execute.return_value = MagicMock(data=[{"id": 1}])
    mock_get_sb.return_value = mock_sb

    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@patch("app.core.supabase_client.get_supabase")
def test_health_ready_degraded(mock_get_sb):
    mock_get_sb.side_effect = Exception("Supabase is down")

    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


@patch("app.api.routes.catalogos.get_supabase")
def test_catalogos_comunas(mock_get_sb):
    mock_sb = MagicMock()
    mock_sb.table().select().order().execute.return_value = MagicMock(data=[{"id": 1, "nombre": "Santiago"}])
    mock_get_sb.return_value = mock_sb

    response = client.get("/api/v1/comunas")
    assert response.status_code == 200
    assert response.json() == [{"id": 1, "nombre": "Santiago"}]


@patch("app.api.routes.catalogos.get_supabase")
def test_catalogos_tipos_estado(mock_get_sb):
    mock_sb = MagicMock()
    mock_sb.table().select().order().execute.return_value = MagicMock(data=[{"id": 1, "nombre": "En espera"}])
    mock_get_sb.return_value = mock_sb

    response = client.get("/api/v1/tipos-estado")
    assert response.status_code == 200
    assert response.json() == [{"id": 1, "nombre": "En espera"}]


# ── 4. Setup Mocking Helper para FastAPI Routes ───────────────────────────────

class DependencyOverrides:
    def __init__(self, user: Usuario):
        self.user = user

    def mock_current_user(self):
        return self.user

    def mock_current_user_municipal(self):
        if self.user.tipo != "municipalidad":
            raise ForbiddenError("Forbidden")
        return self.user

    def mock_current_user_admin(self):
        if self.user.tipo != "admin":
            raise ForbiddenError("Forbidden")
        return self.user

    def mock_current_user_municipal_o_admin(self):
        if self.user.tipo not in ("municipalidad", "admin"):
            raise ForbiddenError("Forbidden")
        return self.user


def set_api_user(user: Usuario):
    overrides = DependencyOverrides(user)
    app.dependency_overrides[current_user] = overrides.mock_current_user
    app.dependency_overrides[current_user_municipal] = overrides.mock_current_user_municipal
    app.dependency_overrides[current_user_admin] = overrides.mock_current_user_admin
    app.dependency_overrides[current_user_municipal_o_admin] = overrides.mock_current_user_municipal_o_admin


def clear_api_user():
    app.dependency_overrides.clear()


# ── 5. Test Routes: Reportes ──────────────────────────────────────────────────

@patch("app.application.buscar_evidencia.buscar_evidencia")
def test_route_reportes_buscar_evidencia(mock_usecase):
    user = Usuario(id="u1", nombre="N", tipo="ciudadano", activo=True)
    set_api_user(user)
    
    mock_usecase.return_value = EvidenciaIot(
        lectura_id=1, sensor_id="s1", sensor_nombre="S", nivel_db=80.0, distancia_metros=10, timestamp_medicion=datetime.now()
    )

    response = client.get("/api/v1/reportes/buscar-evidencia?lat=-33.45&lng=-70.65")
    assert response.status_code == 200
    assert response.json()["evidencia"]["sensor_id"] == "s1"
    
    clear_api_user()


@patch("app.application.crear_reporte.crear_reporte")
def test_route_reportes_crear(mock_usecase):
    user = Usuario(id="u1", nombre="N", tipo="ciudadano", activo=True)
    set_api_user(user)

    mock_usecase.return_value = Reporte(
        id="rep-1", usuario_id="u1", comuna_id=1, titulo="Ruido", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En espera"
    )

    payload = {"titulo": "Ruido", "descripcion": "Descripcion de prueba con mas de 10 caracteres.", "latitud": -33.0, "longitud": -70.0}
    response = client.post("/api/v1/reportes", json=payload)
    assert response.status_code == 201
    assert response.json()["id"] == "rep-1"
    
    clear_api_user()


@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_route_reportes_mios(mock_repo_cls):
    user = Usuario(id="u1", nombre="N", tipo="ciudadano", activo=True)
    set_api_user(user)

    mock_repo = MagicMock()
    mock_repo.list_by_usuario.return_value = ([], None)
    mock_repo_cls.return_value = mock_repo

    response = client.get("/api/v1/reportes/mios")
    assert response.status_code == 200
    assert response.json() == {"data": [], "next_cursor": None}

    clear_api_user()


@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_route_reportes_comuna(mock_repo_cls):
    user = Usuario(id="f1", nombre="N", tipo="municipalidad", activo=True, comuna_id=1)
    set_api_user(user)

    app.dependency_overrides[current_user_municipal_de_comuna(1)] = lambda: user

    mock_repo = MagicMock()
    mock_repo.list_by_comuna.return_value = ([], None)
    mock_repo_cls.return_value = mock_repo

    response = client.get("/api/v1/reportes/comuna/1")
    assert response.status_code == 200
    assert response.json() == {"data": [], "next_cursor": None}

    clear_api_user()


@patch("app.application.reporte_comentarios.listar_comentarios")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_route_reportes_detalle(mock_repo_cls, mock_list_comments):
    user = Usuario(id="u1", nombre="N", tipo="ciudadano", activo=True)
    set_api_user(user)

    rep = Reporte(
        id="rep-1", usuario_id="u1", comuna_id=1, titulo="Ruido", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En espera"
    )
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = rep
    mock_repo_cls.return_value = mock_repo
    mock_list_comments.return_value = []

    response = client.get("/api/v1/reportes/rep-1")
    assert response.status_code == 200
    assert response.json()["id"] == "rep-1"

    # Test forbidden detailed fetch (non-owner ciudadano)
    user_other = Usuario(id="u2", nombre="N", tipo="ciudadano", activo=True)
    set_api_user(user_other)
    response_forbidden = client.get("/api/v1/reportes/rep-1")
    assert response_forbidden.status_code == 403

    clear_api_user()


@patch("app.application.reporte_comentarios.listar_comentarios")
@patch("app.application.cambiar_estado_reporte.cambiar_estado_reporte")
def test_route_reportes_cambiar_estado(mock_usecase, mock_list_comments):
    user = Usuario(id="f1", nombre="N", tipo="municipalidad", activo=True, comuna_id=1)
    set_api_user(user)

    mock_usecase.return_value = Reporte(
        id="rep-1", usuario_id="u1", comuna_id=1, titulo="Ruido", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En atencion"
    )
    mock_list_comments.return_value = []

    payload = {"nuevo_estado": "En atencion", "comentario": None}
    response = client.patch("/api/v1/reportes/rep-1/estado", json=payload)
    assert response.status_code == 200
    assert response.json()["estado_actual"] == "En atencion"

    clear_api_user()


# ── 6. Test Routes: Heatmaps ──────────────────────────────────────────────────

@patch("app.application.obtener_heatmap.obtener_heatmap")
def test_route_heatmap(mock_usecase):
    mock_usecase.return_value = ([
        {"lat_cell": -33.45, "lng_cell": -70.65, "nivel_db_avg": 75.0, "nivel_db_max": 90.0, "lectura_count": 5, "bucket_start": "2026-06-03T12:00:00Z"}
    ], "matview")

    response = client.get("/api/v1/heatmaps?bbox=-70.7,-33.5,-70.6,-33.4&time_start=2026-06-03T00:00:00Z&time_end=2026-06-03T12:00:00Z&bucket_minutes=5")
    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"
    assert response.json()["metadata"]["fuente"] == "matview"


# ── 7. Test Routes: Usuarios ──────────────────────────────────────────────────

@patch("app.core.supabase_client.get_supabase")
def test_route_usuarios_me_get(mock_get_sb):
    user = Usuario(id="u1", nombre="Ciudadano 1", tipo="ciudadano", activo=True, comuna_id=1, telefono="1234")
    set_api_user(user)

    # Mock comuna fetch in _comuna_nombre
    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"nombre": "Santiago"})
    mock_get_sb.return_value = mock_sb

    response = client.get("/api/v1/usuarios/me")
    assert response.status_code == 200
    assert response.json()["id"] == "u1"
    assert response.json()["comuna_nombre"] == "Santiago"
    
    clear_api_user()


@patch("app.core.supabase_client.get_supabase")
@patch("app.infrastructure.db.usuario_repo.UsuarioRepository")
def test_route_usuarios_me_patch(mock_repo_cls, mock_get_sb):
    user = Usuario(id="u1", nombre="Ciudadano 1", tipo="ciudadano", activo=True, comuna_id=1)
    set_api_user(user)

    # Mock comuna exists check + name resolution
    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.side_effect = [
        MagicMock(data={"id": 2}),  # check existence
        MagicMock(data={"nombre": "Santiago"})  # _comuna_nombre
    ]
    mock_get_sb.return_value = mock_sb

    mock_repo = MagicMock()
    mock_repo.update_me.return_value = Usuario(id="u1", nombre="Ciudadano 1", tipo="ciudadano", activo=True, comuna_id=2, telefono="+56912345678")
    mock_repo_cls.return_value = mock_repo

    payload = {"telefono": "+56912345678", "comuna_id": 2}
    response = client.patch("/api/v1/usuarios/me", json=payload)
    assert response.status_code == 200
    assert response.json()["comuna_id"] == 2
    assert response.json()["telefono"] == "+56912345678"

    clear_api_user()


@patch("app.core.supabase_client.get_supabase")
@patch("app.application.listar_usuarios.listar_usuarios")
def test_route_usuarios_listar(mock_usecase, mock_get_sb):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    mock_usecase.return_value = ([], None, {})

    response = client.get("/api/v1/usuarios")
    assert response.status_code == 200
    assert response.json() == {"data": [], "next_cursor": None}

    clear_api_user()


@patch("app.core.supabase_client.get_supabase")
@patch("app.application.promover_usuario.promover_usuario")
def test_route_usuarios_promover(mock_usecase, mock_get_sb):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    promovido = Usuario(id="u2", nombre="Muni", tipo="municipalidad", activo=True, comuna_id=1)
    mock_usecase.return_value = promovido

    # Mock _comuna_nombre
    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"nombre": "Santiago"})
    mock_get_sb.return_value = mock_sb

    payload = {"nuevo_tipo": "municipalidad", "comuna_id": 1}
    response = client.patch("/api/v1/usuarios/u2/promover", json=payload)
    assert response.status_code == 200
    assert response.json()["tipo"] == "municipalidad"

    clear_api_user()


@patch("app.core.supabase_client.get_supabase")
@patch("app.application.cambiar_activo_usuario.cambiar_activo_usuario")
def test_route_usuarios_activo(mock_usecase, mock_get_sb):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    target = Usuario(id="u2", nombre="U", tipo="ciudadano", activo=False)
    mock_usecase.return_value = target

    # Mock _comuna_nombre
    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data=None)
    mock_get_sb.return_value = mock_sb

    payload = {"activo": False}
    response = client.patch("/api/v1/usuarios/u2/activo", json=payload)
    assert response.status_code == 200
    assert response.json()["activo"] is False

    clear_api_user()


# ── 8. Test Routes: Sensores ──────────────────────────────────────────────────

@patch("app.application.sensores.listar_sensores")
def test_route_sensores_listar(mock_usecase):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    mock_usecase.return_value = ([], None)

    response = client.get("/api/v1/sensores")
    assert response.status_code == 200
    assert response.json() == {"data": [], "next_cursor": None}

    clear_api_user()


@patch("app.application.sensores.obtener_sensor")
def test_route_sensores_detalle(mock_usecase):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    sensor = Sensor(id="s1", comuna_id=1, nombre="Sensor", latitud=0, longitud=0, activo=True)
    mock_usecase.return_value = sensor

    response = client.get("/api/v1/sensores/s1")
    assert response.status_code == 200
    assert response.json()["id"] == "s1"

    clear_api_user()


@patch("app.application.sensores.obtener_resumen_sensores")
def test_route_sensores_resumen(mock_usecase):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    mock_usecase.return_value = {"total": 10, "online": 5, "intermitente": 2, "offline": 2, "sin_lecturas": 1}

    response = client.get("/api/v1/sensores/resumen")
    assert response.status_code == 200
    assert response.json() == {"total": 10, "online": 5, "intermitente": 2, "offline": 2, "sin_lecturas": 1, "calculado_at": None}

    clear_api_user()


@patch("app.application.sensores.crear_sensor")
def test_route_sensores_crear(mock_usecase):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    sensor = Sensor(id="s1", comuna_id=1, nombre="Sensor", latitud=0.0, longitud=0.0, activo=True)
    mock_usecase.return_value = sensor

    payload = {"nombre": "Sensor", "comuna_id": 1, "latitud": 0.0, "longitud": 0.0}
    response = client.post("/api/v1/sensores", json=payload)
    assert response.status_code == 201
    assert response.json()["id"] == "s1"

    clear_api_user()


@patch("app.application.sensores.actualizar_sensor")
def test_route_sensores_actualizar(mock_usecase):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    sensor = Sensor(id="s1", comuna_id=1, nombre="Nuevo Nombre", latitud=0.0, longitud=0.0, activo=True)
    mock_usecase.return_value = sensor

    payload = {"nombre": "Nuevo Nombre", "latitud": None, "longitud": None, "activo": None}
    response = client.patch("/api/v1/sensores/s1", json=payload)
    assert response.status_code == 200
    assert response.json()["nombre"] == "Nuevo Nombre"

    clear_api_user()


@patch("app.application.sensores.desactivar_sensor")
def test_route_sensores_desactivar(mock_usecase):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    sensor = Sensor(id="s1", comuna_id=1, nombre="S", latitud=0.0, longitud=0.0, activo=False)
    mock_usecase.return_value = sensor

    response = client.delete("/api/v1/sensores/s1")
    assert response.status_code == 200
    assert response.json()["activo"] is False

    clear_api_user()


# ── 9. Test Routes: Lecturas Resumen ──────────────────────────────────────────

@patch("app.api.routes.lecturas.obtener_resumen_horario")
def test_route_lecturas_resumen(mock_usecase):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    set_api_user(user)

    mock_usecase.return_value = {
        "sensor_id": "s1",
        "sensor_nombre": "S",
        "desde": "2026-06-03T00:00:00",
        "hasta": "2026-06-03T12:00:00",
        "horas": [],
        "fuente": "lectura_resumen_horaria",
        "refrescado_at": "2026-06-03T12:00:00"
    }

    response = client.get("/api/v1/lecturas/resumen?sensor_id=s1&desde=2026-06-03T00:00:00&hasta=2026-06-03T12:00:00")
    assert response.status_code == 200
    assert response.json()["sensor_id"] == "s1"

    clear_api_user()


# ── 10. Test Domain Exception Mappings (error_handlers.py) ───────────────────

def test_exception_handler_not_found():
    user = Usuario(id="u1", nombre="N", tipo="ciudadano", activo=True)
    set_api_user(user)

    with patch("app.infrastructure.db.reporte_repo.ReporteRepository") as mock_repo_cls:
        mock_repo = MagicMock()
        mock_repo.get_by_id.side_effect = NotFoundError("No existe el reporte")
        mock_repo_cls.return_value = mock_repo

        response = client.get("/api/v1/reportes/rep-nonexistent")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    clear_api_user()


def test_exception_handler_unhandled():
    with patch("app.api.routes.catalogos.get_supabase") as mock_get_sb:
        mock_get_sb.side_effect = RuntimeError("Crash")
        response = client_no_raise.get("/api/v1/comunas")
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
