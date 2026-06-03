import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.domain.entities import (
    Usuario, Sensor, Lectura, ResumenHorario, EvidenciaIot,
    ReporteArchivoAdmin, Reporte
)
from app.domain.errors import (
    NotFoundError, ValidationError, ForbiddenError, ComunaMismatchError,
    InvalidStateTransitionError, ExternalServiceError
)

# Use cases to test
from app.application.buscar_evidencia import buscar_evidencia
from app.application.registrar_lectura import registrar_lectura
from app.application.cambiar_activo_usuario import cambiar_activo_usuario, CannotDeactivateSelfError
from app.application.cambiar_estado_reporte import cambiar_estado_reporte
from app.application.crear_reporte import crear_reporte
from app.application.obtener_heatmap import obtener_heatmap
from app.application.obtener_resumen_horario import obtener_resumen_horario, SensorNotFoundError
from app.application.promover_usuario import promover_usuario, CannotDemoteSelfError, ComunaIdRequiredError, ComunaNotFoundError, TipoInvalidoError
from app.application.listar_usuarios import listar_usuarios
from app.application.reporte_comentarios import agregar_comentario, listar_comentarios
from app.application.reportes_admin_archivos import subir_archivo, listar_archivos, obtener_url_descarga, eliminar_archivo
from app.application.sensores import (
    listar_sensores, obtener_sensor, obtener_resumen_sensores,
    crear_sensor, actualizar_sensor, desactivar_sensor,
    SensorNotFoundError as SensorNotFoundAppError, ComunaNotFoundError as ComunaNotFoundAppError
)


# ── 1. Buscar Evidencia ───────────────────────────────────────────────────────

@patch("app.infrastructure.db.rpc.buscar_evidencia")
def test_buscar_evidencia(mock_rpc):
    evidencia = EvidenciaIot(
        lectura_id=123,
        sensor_id="sensor-1",
        sensor_nombre="Sensor 1",
        nivel_db=85.5,
        distancia_metros=12.0,
        timestamp_medicion=datetime.now(timezone.utc)
    )
    mock_rpc.return_value = evidencia

    result = buscar_evidencia(-33.45, -70.65)
    assert result == evidencia
    mock_rpc.assert_called_once()


# ── 2. Registrar Lectura ──────────────────────────────────────────────────────

@patch("app.application.registrar_lectura.LecturaRepository")
def test_registrar_lectura(mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo_cls.return_value = mock_repo

    registrar_lectura("sensor-1", 72.4, "2026-06-03T12:00:00Z")
    mock_repo.insert.assert_called_once_with(
        sensor_id="sensor-1",
        nivel_db=72.4,
        timestamp_medicion="2026-06-03T12:00:00Z"
    )


# ── 3. Cambiar Activo Usuario ─────────────────────────────────────────────────

@patch("app.application.cambiar_activo_usuario.UsuarioRepository")
def test_cambiar_activo_usuario_self_deactivate(mock_repo_cls):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    with pytest.raises(CannotDeactivateSelfError):
        cambiar_activo_usuario(actor=actor, target_id="admin-1", activo=False)


@patch("app.application.cambiar_activo_usuario.UsuarioRepository")
def test_cambiar_activo_usuario_not_found(mock_repo_cls):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo

    from app.domain.errors import UsuarioNotFoundError
    with pytest.raises(UsuarioNotFoundError):
        cambiar_activo_usuario(actor=actor, target_id="user-2", activo=False)


@patch("app.application.cambiar_activo_usuario.UsuarioRepository")
def test_cambiar_activo_usuario_success(mock_repo_cls):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    target = Usuario(id="user-2", nombre="User", tipo="ciudadano", activo=True)
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = target
    mock_repo.set_activo.return_value = Usuario(id="user-2", nombre="User", tipo="ciudadano", activo=False)
    mock_repo_cls.return_value = mock_repo

    result = cambiar_activo_usuario(actor=actor, target_id="user-2", activo=False)
    assert result.activo is False
    mock_repo.set_activo.assert_called_once_with("user-2", False)


@patch("app.application.cambiar_activo_usuario.UsuarioRepository")
def test_cambiar_activo_usuario_set_activo_returns_none(mock_repo_cls):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    target = Usuario(id="user-2", nombre="User", tipo="ciudadano", activo=True)
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = target
    mock_repo.set_activo.return_value = None
    mock_repo_cls.return_value = mock_repo

    from app.domain.errors import UsuarioNotFoundError
    with pytest.raises(UsuarioNotFoundError):
        cambiar_activo_usuario(actor=actor, target_id="user-2", activo=False)


# ── 4. Cambiar Estado Reporte ──────────────────────────────────────────────────

@patch("app.core.supabase_client.get_supabase")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_cambiar_estado_reporte_not_found(mock_repo_cls, mock_get_sb):
    user = Usuario(id="func-1", nombre="Funcionario", tipo="municipalidad", activo=True, comuna_id=1)
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo

    from app.domain.errors import ReporteNotFoundError
    with pytest.raises(ReporteNotFoundError):
        cambiar_estado_reporte("rep-1", "En atencion", user, None)


@patch("app.core.supabase_client.get_supabase")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_cambiar_estado_reporte_comuna_mismatch(mock_repo_cls, mock_get_sb):
    user = Usuario(id="func-1", nombre="Funcionario", tipo="municipalidad", activo=True, comuna_id=2)
    rep = Reporte(id="rep-1", usuario_id="user-1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En espera")
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = rep
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(ComunaMismatchError):
        cambiar_estado_reporte("rep-1", "En atencion", user, None)


@patch("app.core.supabase_client.get_supabase")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_cambiar_estado_reporte_invalid_transition(mock_repo_cls, mock_get_sb):
    user = Usuario(id="func-1", nombre="Funcionario", tipo="municipalidad", activo=True, comuna_id=1)
    rep = Reporte(id="rep-1", usuario_id="user-1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="Atendido")
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = rep
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(InvalidStateTransitionError):
        cambiar_estado_reporte("rep-1", "En atencion", user, None)


@patch("app.core.supabase_client.get_supabase")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_cambiar_estado_reporte_descartado_sin_comentario(mock_repo_cls, mock_get_sb):
    user = Usuario(id="func-1", nombre="Funcionario", tipo="municipalidad", activo=True, comuna_id=1)
    rep = Reporte(id="rep-1", usuario_id="user-1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En espera")
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = rep
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(ValidationError):
        cambiar_estado_reporte("rep-1", "Descartado", user, "")


@patch("app.core.supabase_client.get_supabase")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_cambiar_estado_reporte_estado_no_catalogo(mock_repo_cls, mock_get_sb):
    user = Usuario(id="func-1", nombre="Funcionario", tipo="municipalidad", activo=True, comuna_id=1)
    rep = Reporte(id="rep-1", usuario_id="user-1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En espera")
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = rep
    mock_repo_cls.return_value = mock_repo

    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data=None)
    mock_get_sb.return_value = mock_sb

    with pytest.raises(ValidationError):
        cambiar_estado_reporte("rep-1", "En atencion", user, None)


@patch("app.core.supabase_client.get_supabase")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_cambiar_estado_reporte_success(mock_repo_cls, mock_get_sb):
    user = Usuario(id="func-1", nombre="Funcionario", tipo="municipalidad", activo=True, comuna_id=1)
    rep_espera = Reporte(id="rep-1", usuario_id="user-1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En espera")
    rep_atencion = Reporte(id="rep-1", usuario_id="user-1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En atencion", atendido_por_id="func-1")

    mock_repo = MagicMock()
    mock_repo.get_by_id.side_effect = [rep_espera, rep_atencion]
    mock_repo_cls.return_value = mock_repo

    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"id": 2})
    mock_get_sb.return_value = mock_sb

    result = cambiar_estado_reporte("rep-1", "En atencion", user, None)
    assert result.estado_actual == "En atencion"
    assert result.atendido_por_id == "func-1"
    mock_repo.cambiar_estado.assert_called_once_with("rep-1", 2, "func-1", None, "func-1")


# ── 5. Crear Reporte ──────────────────────────────────────────────────────────

@patch("app.application.crear_reporte.get_supabase")
@patch("app.infrastructure.db.rpc.crear_reporte_con_validacion")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_crear_reporte_comuna_not_exists(mock_repo_cls, mock_rpc, mock_get_sb):
    user = Usuario(id="user-1", nombre="Ciudadano", tipo="ciudadano", activo=True)
    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data=None)
    mock_get_sb.return_value = mock_sb

    with pytest.raises(ValidationError) as exc:
        crear_reporte(usuario=user, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, comuna_id=99)
    assert "comuna_id 99 no existe" in str(exc.value)


@patch("app.application.crear_reporte.get_supabase")
@patch("app.infrastructure.db.rpc.crear_reporte_con_validacion")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_crear_reporte_missing_comuna(mock_repo_cls, mock_rpc, mock_get_sb):
    user = Usuario(id="user-1", nombre="Ciudadano", tipo="ciudadano", activo=True, comuna_id=None)

    with pytest.raises(ValidationError) as exc:
        crear_reporte(usuario=user, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, comuna_id=None)
    assert "Falta completar onboarding" in str(exc.value)


@patch("app.application.crear_reporte.get_supabase")
@patch("app.infrastructure.db.rpc.crear_reporte_con_validacion")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_crear_reporte_external_error(mock_repo_cls, mock_rpc, mock_get_sb):
    user = Usuario(id="user-1", nombre="Ciudadano", tipo="ciudadano", activo=True, comuna_id=1)
    mock_rpc.side_effect = Exception("Db failure")

    with pytest.raises(ExternalServiceError):
        crear_reporte(usuario=user, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)


@patch("app.application.crear_reporte.get_supabase")
@patch("app.infrastructure.db.rpc.crear_reporte_con_validacion")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_crear_reporte_success(mock_repo_cls, mock_rpc, mock_get_sb):
    user = Usuario(id="user-1", nombre="Ciudadano", tipo="ciudadano", activo=True, comuna_id=1)
    mock_rpc.return_value = ("rep-123", 456)
    rep = Reporte(id="rep-123", usuario_id="user-1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, estado_actual="En espera")

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = rep
    mock_repo_cls.return_value = mock_repo

    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"id": 1})
    mock_get_sb.return_value = mock_sb

    result = crear_reporte(usuario=user, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0, comuna_id=1)
    assert result == rep
    mock_rpc.assert_called_once()
    mock_repo.get_by_id.assert_called_once_with("rep-123")


# ── 6. Obtener Heatmap ────────────────────────────────────────────────────────

@patch("app.infrastructure.db.lectura_repo.LecturaRepository")
def test_obtener_heatmap_invalid_bucket(mock_repo_cls):
    with pytest.raises(ValidationError):
        obtener_heatmap(-70.65, -33.45, -70.55, -33.40, "2026-06-03T00:00:00Z", "2026-06-03T12:00:00Z", 7)


@patch("app.infrastructure.db.lectura_repo.LecturaRepository")
def test_obtener_heatmap_invalid_dates(mock_repo_cls):
    with pytest.raises(ValidationError):
        obtener_heatmap(-70.65, -33.45, -70.55, -33.40, "2026-06-03T12:00:00Z", "2026-06-03T00:00:00Z", 5)


@patch("app.infrastructure.db.lectura_repo.LecturaRepository")
def test_obtener_heatmap_window_exceeded(mock_repo_cls):
    # settings.heatmap_max_window_days is 7
    with pytest.raises(ValidationError):
        obtener_heatmap(-70.65, -33.45, -70.55, -33.40, "2026-05-01T00:00:00Z", "2026-05-15T00:00:00Z", 5)


@patch("app.infrastructure.db.lectura_repo.LecturaRepository")
def test_obtener_heatmap_success(mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo.heatmap.return_value = ([{"lat": 1.0, "lng": 2.0}], "matview")
    mock_repo_cls.return_value = mock_repo

    res, fuente = obtener_heatmap(-70.65, -33.45, -70.55, -33.40, "2026-06-03T00:00:00Z", "2026-06-03T12:00:00Z", 5)
    assert res == [{"lat": 1.0, "lng": 2.0}]
    assert fuente == "matview"


# ── 7. Obtener Resumen Horario ────────────────────────────────────────────────

@patch("app.application.obtener_resumen_horario.SensorRepository")
@patch("app.application.obtener_resumen_horario.ResumenHorarioRepository")
def test_obtener_resumen_horario_invalid_window(mock_resumen_cls, mock_sensor_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    d1 = datetime(2026, 6, 3, 12, 0)
    d2 = datetime(2026, 6, 3, 11, 0)
    with pytest.raises(ValidationError):
        obtener_resumen_horario(actor=user, sensor_id="s1", desde=d1, hasta=d2)


@patch("app.application.obtener_resumen_horario.SensorRepository")
@patch("app.application.obtener_resumen_horario.ResumenHorarioRepository")
def test_obtener_resumen_horario_window_too_large(mock_resumen_cls, mock_sensor_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    d1 = datetime(2026, 1, 1, 0, 0)
    d2 = datetime(2026, 5, 1, 0, 0)
    with pytest.raises(ValidationError):
        obtener_resumen_horario(actor=user, sensor_id="s1", desde=d1, hasta=d2)


@patch("app.application.obtener_resumen_horario.SensorRepository")
@patch("app.application.obtener_resumen_horario.ResumenHorarioRepository")
def test_obtener_resumen_horario_sensor_not_found(mock_resumen_cls, mock_sensor_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    mock_sens_repo = MagicMock()
    mock_sens_repo.get_by_id.return_value = None
    mock_sensor_cls.return_value = mock_sens_repo

    d1 = datetime(2026, 6, 3, 0, 0)
    d2 = datetime(2026, 6, 3, 12, 0)
    with pytest.raises(SensorNotFoundError):
        obtener_resumen_horario(actor=user, sensor_id="s1", desde=d1, hasta=d2)


@patch("app.application.obtener_resumen_horario.SensorRepository")
@patch("app.application.obtener_resumen_horario.ResumenHorarioRepository")
def test_obtener_resumen_horario_comuna_mismatch(mock_resumen_cls, mock_sensor_cls):
    user = Usuario(id="func-1", nombre="Funcionario", tipo="municipalidad", activo=True, comuna_id=1)
    sensor = Sensor(id="s1", comuna_id=2, nombre="Sensor Comuna 2", latitud=-33.0, longitud=-70.0, activo=True)

    mock_sens_repo = MagicMock()
    mock_sens_repo.get_by_id.return_value = sensor
    mock_sensor_cls.return_value = mock_sens_repo

    d1 = datetime(2026, 6, 3, 0, 0)
    d2 = datetime(2026, 6, 3, 12, 0)
    with pytest.raises(ComunaMismatchError):
        obtener_resumen_horario(actor=user, sensor_id="s1", desde=d1, hasta=d2)


@patch("app.application.obtener_resumen_horario.SensorRepository")
@patch("app.application.obtener_resumen_horario.ResumenHorarioRepository")
def test_obtener_resumen_horario_success(mock_resumen_cls, mock_sensor_cls):
    user = Usuario(id="func-1", nombre="Funcionario", tipo="municipalidad", activo=True, comuna_id=1)
    sensor = Sensor(id="s1", comuna_id=1, nombre="Sensor Comuna 1", latitud=-33.0, longitud=-70.0, activo=True)

    mock_sens_repo = MagicMock()
    mock_sens_repo.get_by_id.return_value = sensor
    mock_sensor_cls.return_value = mock_sens_repo

    ref_at = datetime.now()
    filas = [
        ResumenHorario(sensor_id="s1", hora=datetime(2026, 6, 3, 10, 0), avg_db=65.2, min_db=40.0, max_db=85.0, p95_db=78.0, n_lecturas=120, refrescado_at=ref_at)
    ]
    mock_res_repo = MagicMock()
    mock_res_repo.listar.return_value = filas
    mock_res_repo.max_refrescado_at.return_value = ref_at
    mock_resumen_cls.return_value = mock_res_repo

    d1 = datetime(2026, 6, 3, 0, 0)
    d2 = datetime(2026, 6, 3, 12, 0)
    result = obtener_resumen_horario(actor=user, sensor_id="s1", desde=d1, hasta=d2)
    assert result["sensor_id"] == "s1"
    assert result["horas"] == filas
    assert result["refrescado_at"] == ref_at


# ── 8. Promover Usuario ────────────────────────────────────────────────────────

@patch("app.application.promover_usuario.get_supabase")
@patch("app.application.promover_usuario.UsuarioRepository")
def test_promover_usuario_tipo_invalido(mock_repo_cls, mock_get_sb):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    with pytest.raises(TipoInvalidoError):
        promover_usuario(actor=actor, target_id="u2", nuevo_tipo="invalido", comuna_id=None)


@patch("app.application.promover_usuario.get_supabase")
@patch("app.application.promover_usuario.UsuarioRepository")
def test_promover_usuario_self_demote(mock_repo_cls, mock_get_sb):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    with pytest.raises(CannotDemoteSelfError):
        promover_usuario(actor=actor, target_id="admin-1", nuevo_tipo="ciudadano", comuna_id=None)


@patch("app.application.promover_usuario.get_supabase")
@patch("app.application.promover_usuario.UsuarioRepository")
def test_promover_usuario_municipal_sin_comuna(mock_repo_cls, mock_get_sb):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    with pytest.raises(ComunaIdRequiredError):
        promover_usuario(actor=actor, target_id="u2", nuevo_tipo="municipalidad", comuna_id=None)


@patch("app.application.promover_usuario.get_supabase")
@patch("app.application.promover_usuario.UsuarioRepository")
def test_promover_usuario_comuna_not_found(mock_repo_cls, mock_get_sb):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data=None)
    mock_get_sb.return_value = mock_sb

    with pytest.raises(ComunaNotFoundError):
        promover_usuario(actor=actor, target_id="u2", nuevo_tipo="municipalidad", comuna_id=99)


@patch("app.application.promover_usuario.get_supabase")
@patch("app.application.promover_usuario.UsuarioRepository")
def test_promover_usuario_target_not_found(mock_repo_cls, mock_get_sb):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo

    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"id": 1})
    mock_get_sb.return_value = mock_sb

    from app.domain.errors import UsuarioNotFoundError
    with pytest.raises(UsuarioNotFoundError):
        promover_usuario(actor=actor, target_id="u2", nuevo_tipo="admin", comuna_id=1)


@patch("app.application.promover_usuario.get_supabase")
@patch("app.application.promover_usuario.UsuarioRepository")
def test_promover_usuario_success(mock_repo_cls, mock_get_sb):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    target = Usuario(id="u2", nombre="Ciudadano", tipo="ciudadano", activo=True)
    promovido = Usuario(id="u2", nombre="Ciudadano", tipo="municipalidad", activo=True, comuna_id=1)

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = target
    mock_repo.promover.return_value = promovido
    mock_repo_cls.return_value = mock_repo

    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"id": 1})
    mock_get_sb.return_value = mock_sb

    result = promover_usuario(actor=actor, target_id="u2", nuevo_tipo="municipalidad", comuna_id=1)
    assert result.tipo == "municipalidad"
    assert result.comuna_id == 1
    mock_repo.promover.assert_called_once_with(user_id="u2", nuevo_tipo="municipalidad", comuna_id=1, actualizar_comuna=True)


@patch("app.application.promover_usuario.get_supabase")
@patch("app.application.promover_usuario.UsuarioRepository")
def test_promover_usuario_promover_returns_none(mock_repo_cls, mock_get_sb):
    actor = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    target = Usuario(id="u2", nombre="Ciudadano", tipo="ciudadano", activo=True)

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = target
    mock_repo.promover.return_value = None
    mock_repo_cls.return_value = mock_repo

    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"id": 1})
    mock_get_sb.return_value = mock_sb

    from app.domain.errors import UsuarioNotFoundError
    with pytest.raises(UsuarioNotFoundError):
        promover_usuario(actor=actor, target_id="u2", nuevo_tipo="admin", comuna_id=1)


# ── 9. Listar Usuarios ────────────────────────────────────────────────────────

@patch("app.application.listar_usuarios.get_supabase")
@patch("app.application.listar_usuarios.UsuarioRepository")
def test_listar_usuarios(mock_repo_cls, mock_get_sb):
    usuarios = [
        Usuario(id="u1", nombre="N1", tipo="ciudadano", activo=True, comuna_id=1),
        Usuario(id="u2", nombre="N2", tipo="municipalidad", activo=True, comuna_id=2)
    ]
    mock_repo = MagicMock()
    mock_repo.listar.return_value = (usuarios, "next-cursor-xyz")
    mock_repo_cls.return_value = mock_repo

    mock_sb = MagicMock()
    mock_sb.table().select().in_().execute.return_value = MagicMock(data=[
        {"id": 1, "nombre": "Santiago"},
        {"id": 2, "nombre": "Providencia"}
    ])
    mock_get_sb.return_value = mock_sb

    res_users, cursor, comunas = listar_usuarios(tipo=None, comuna_id=None, activo=None, q=None, limit=10, cursor=None)
    assert res_users == usuarios
    assert cursor == "next-cursor-xyz"
    assert comunas == {1: "Santiago", 2: "Providencia"}


# ── 10. Agregar Comentario ────────────────────────────────────────────────────

@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.usuario_repo.UsuarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_agregar_comentario_reporte_not_found(mock_rep_cls, mock_user_cls, mock_com_cls):
    user = Usuario(id="f1", nombre="F", tipo="municipalidad", activo=True, comuna_id=1)
    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = None
    mock_rep_cls.return_value = mock_rep

    from app.domain.errors import ReporteNotFoundError
    with pytest.raises(ReporteNotFoundError):
        agregar_comentario("r1", user, "externo", "hola", None, None)


@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.usuario_repo.UsuarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_agregar_comentario_ciudadano_forbidden(mock_rep_cls, mock_user_cls, mock_com_cls):
    user = Usuario(id="u1", nombre="Ciudadano", tipo="ciudadano", activo=True, comuna_id=1)
    rep = Reporte(id="r1", usuario_id="u1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)

    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = rep
    mock_rep_cls.return_value = mock_rep

    with pytest.raises(ForbiddenError):
        agregar_comentario("r1", user, "externo", "hola", None, None)


@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.usuario_repo.UsuarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_agregar_comentario_comuna_mismatch(mock_rep_cls, mock_user_cls, mock_com_cls):
    user = Usuario(id="f1", nombre="F", tipo="municipalidad", activo=True, comuna_id=2)
    rep = Reporte(id="r1", usuario_id="u1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)

    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = rep
    mock_rep_cls.return_value = mock_rep

    with pytest.raises(ComunaMismatchError):
        agregar_comentario("r1", user, "externo", "hola", None, None)


@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.usuario_repo.UsuarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_agregar_comentario_delegado_not_found(mock_rep_cls, mock_user_cls, mock_com_cls):
    user = Usuario(id="f1", nombre="F", tipo="municipalidad", activo=True, comuna_id=1)
    rep = Reporte(id="r1", usuario_id="u1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)

    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = rep
    mock_rep_cls.return_value = mock_rep

    mock_user = MagicMock()
    mock_user.get_by_id.return_value = None
    mock_user_cls.return_value = mock_user

    with pytest.raises(ValidationError) as exc:
        agregar_comentario("r1", user, "interno", "hola", "f2", datetime.now())
    assert "Usuario f2 no existe" in str(exc.value)


@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.usuario_repo.UsuarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_agregar_comentario_delegado_not_municipal(mock_rep_cls, mock_user_cls, mock_com_cls):
    user = Usuario(id="f1", nombre="F", tipo="municipalidad", activo=True, comuna_id=1)
    rep = Reporte(id="r1", usuario_id="u1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)
    delegado = Usuario(id="f2", nombre="D", tipo="ciudadano", activo=True)

    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = rep
    mock_rep_cls.return_value = mock_rep

    mock_user = MagicMock()
    mock_user.get_by_id.return_value = delegado
    mock_user_cls.return_value = mock_user

    with pytest.raises(ValidationError) as exc:
        agregar_comentario("r1", user, "interno", "hola", "f2", datetime.now())
    assert "El usuario delegado debe ser de tipo 'municipalidad'" in str(exc.value)


@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.usuario_repo.UsuarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_agregar_comentario_success(mock_rep_cls, mock_user_cls, mock_com_cls):
    user = Usuario(id="f1", nombre="F", tipo="municipalidad", activo=True, comuna_id=1)
    rep = Reporte(id="r1", usuario_id="u1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)
    delegado = Usuario(id="f2", nombre="D", tipo="municipalidad", activo=True, comuna_id=1)

    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = rep
    mock_rep_cls.return_value = mock_rep

    mock_user = MagicMock()
    mock_user.get_by_id.return_value = delegado
    mock_user_cls.return_value = mock_user

    now = datetime.now()
    mock_com = MagicMock()
    mock_com.crear.return_value = {"id": 99, "cuerpo": "hola"}
    mock_com_cls.return_value = mock_com

    result = agregar_comentario("r1", user, "interno", "hola", "f2", now)
    assert result == {"id": 99, "cuerpo": "hola"}
    mock_com.crear.assert_called_once_with(
        reporte_id="r1",
        autor_id="f1",
        visibilidad="interno",
        cuerpo="hola",
        delegado_a_id="f2",
        delegado_at=now
    )


# ── 11. Listar Comentarios ───────────────────────────────────────────────────

@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_listar_comentarios_forbidden(mock_rep_cls, mock_com_cls):
    user = Usuario(id="u-otro", nombre="Otro", tipo="ciudadano", activo=True)
    rep = Reporte(id="r1", usuario_id="u1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)

    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = rep
    mock_rep_cls.return_value = mock_rep

    with pytest.raises(ForbiddenError):
        listar_comentarios("r1", user)


@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_listar_comentarios_admin_sees_all(mock_rep_cls, mock_com_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    rep = Reporte(id="r1", usuario_id="u1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)

    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = rep
    mock_rep_cls.return_value = mock_rep

    mock_com = MagicMock()
    mock_com.listar_por_reporte.return_value = [{"id": 1, "visibilidad": "interno"}]
    mock_com_cls.return_value = mock_com

    result = listar_comentarios("r1", user)
    assert len(result) == 1
    mock_com.listar_por_reporte.assert_called_once_with("r1", solo_externos=False)


@patch("app.infrastructure.db.reporte_comentario_repo.ReporteComentarioRepository")
@patch("app.infrastructure.db.reporte_repo.ReporteRepository")
def test_listar_comentarios_owner_sees_externals(mock_rep_cls, mock_com_cls):
    user = Usuario(id="u1", nombre="Ciudadano", tipo="ciudadano", activo=True)
    rep = Reporte(id="r1", usuario_id="u1", comuna_id=1, titulo="T", descripcion="D", latitud=-33.0, longitud=-70.0)

    mock_rep = MagicMock()
    mock_rep.get_by_id.return_value = rep
    mock_rep_cls.return_value = mock_rep

    mock_com = MagicMock()
    mock_com.listar_por_reporte.return_value = [{"id": 1, "visibilidad": "externo"}]
    mock_com_cls.return_value = mock_com

    result = listar_comentarios("r1", user)
    assert len(result) == 1
    mock_com.listar_por_reporte.assert_called_once_with("r1", solo_externos=True)


# ── 12. Reportes Admin Archivos (Subir, Listar, Descargar, Eliminar) ──────────

@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_subir_archivo_name_length(mock_storage_cls, mock_repo_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    with pytest.raises(ValidationError):
        subir_archivo(usuario=user, nombre="", tipo="pdf", mime_type="application/pdf", contenido=b"data")
    with pytest.raises(ValidationError):
        subir_archivo(usuario=user, nombre="a" * 201, tipo="pdf", mime_type="application/pdf", contenido=b"data")


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_subir_archivo_invalid_mime(mock_storage_cls, mock_repo_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    with pytest.raises(ValidationError):
        subir_archivo(usuario=user, nombre="A", tipo="pdf", mime_type="text/plain", contenido=b"data")


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_subir_archivo_invalid_date_range(mock_storage_cls, mock_repo_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    d1 = datetime(2026, 6, 3, 12, 0)
    d2 = datetime(2026, 6, 3, 10, 0)
    with pytest.raises(ValidationError):
        subir_archivo(usuario=user, nombre="A", tipo="pdf", mime_type="application/pdf", contenido=b"data", rango_desde=d1, rango_hasta=d2)


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_subir_archivo_empty(mock_storage_cls, mock_repo_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    with pytest.raises(ValidationError):
        subir_archivo(usuario=user, nombre="A", tipo="pdf", mime_type="application/pdf", contenido=b"")


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_subir_archivo_too_large(mock_storage_cls, mock_repo_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    # settings.archivo_max_size_mb is typically 15, we trigger validation by generating a payload larger than that
    payload_size = (settings.archivo_max_size_mb + 1) * 1024 * 1024
    with pytest.raises(ValidationError):
        subir_archivo(usuario=user, nombre="A", tipo="pdf", mime_type="application/pdf", contenido=b"0" * payload_size)


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_subir_archivo_db_failure_compensation(mock_storage_cls, mock_repo_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    mock_storage = MagicMock()
    mock_storage_cls.return_value = mock_storage

    mock_repo = MagicMock()
    mock_repo.insert.side_effect = Exception("Db fail")
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(Exception) as exc:
        subir_archivo(usuario=user, nombre="A.pdf", tipo="pdf", mime_type="application/pdf", contenido=b"pdfdata")
    assert "Db fail" in str(exc.value)
    mock_storage.upload.assert_called_once()
    mock_storage.remove.assert_called_once()


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_subir_archivo_success(mock_storage_cls, mock_repo_cls):
    user = Usuario(id="admin-1", nombre="Admin", tipo="admin", activo=True)
    mock_storage = MagicMock()
    mock_storage_cls.return_value = mock_storage

    arch = ReporteArchivoAdmin(id="a1", generado_por_id="admin-1", nombre="A.pdf", tipo="pdf", mime_type="application/pdf", tamano_bytes=7, object_path="path")
    mock_repo = MagicMock()
    mock_repo.insert.return_value = arch
    mock_repo_cls.return_value = mock_repo

    res = subir_archivo(usuario=user, nombre="A.pdf", tipo="pdf", mime_type="application/pdf", contenido=b"pdfdata")
    assert res == arch
    mock_storage.upload.assert_called_once()


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
def test_listar_archivos_invalid_tipo(mock_repo_cls):
    with pytest.raises(ValidationError):
        listar_archivos(tipo="invalido", generado_por_id=None, limit=10, cursor=None)


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
def test_listar_archivos_success(mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo.listar.return_value = ([], None)
    mock_repo_cls.return_value = mock_repo

    listar_archivos(tipo="pdf", generado_por_id=None, limit=10, cursor=None)
    mock_repo.listar.assert_called_once_with(tipo="pdf", generado_por_id=None, limit=10, cursor=None)


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_obtener_url_descarga_not_found(mock_storage_cls, mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(NotFoundError):
        obtener_url_descarga(archivo_id="a1")


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_obtener_url_descarga_success(mock_storage_cls, mock_repo_cls):
    arch = ReporteArchivoAdmin(id="a1", generado_por_id="admin-1", nombre="A.pdf", tipo="pdf", mime_type="application/pdf", tamano_bytes=7, object_path="path")
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = arch
    mock_repo_cls.return_value = mock_repo

    mock_storage = MagicMock()
    mock_storage.signed_url.return_value = "http://signed-url"
    mock_storage_cls.return_value = mock_storage

    url, ttl = obtener_url_descarga(archivo_id="a1")
    assert url == "http://signed-url"
    assert ttl == settings.storage_signed_url_ttl_seconds


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_eliminar_archivo_not_found(mock_storage_cls, mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(NotFoundError):
        eliminar_archivo(archivo_id="a1")


@patch("app.application.reportes_admin_archivos.ReporteArchivoAdminRepository")
@patch("app.application.reportes_admin_archivos.ReportesAdminStorage")
def test_eliminar_archivo_success(mock_storage_cls, mock_repo_cls):
    arch = ReporteArchivoAdmin(id="a1", generado_por_id="admin-1", nombre="A.pdf", tipo="pdf", mime_type="application/pdf", tamano_bytes=7, object_path="path")
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = arch
    mock_repo_cls.return_value = mock_repo

    mock_storage = MagicMock()
    mock_storage_cls.return_value = mock_storage

    eliminar_archivo(archivo_id="a1")
    mock_storage.remove.assert_called_once_with("path")
    mock_repo.delete.assert_called_once_with("a1")


# ── 13. Sensores (Listar, Obtener, Resumen, Crear, Actualizar, Desactivar) ─────

@patch("app.application.sensores.SensorRepository")
def test_listar_sensores_admin(mock_repo_cls):
    user = Usuario(id="a1", nombre="Admin", tipo="admin", activo=True)
    mock_repo = MagicMock()
    mock_repo.listar.return_value = ([], None)
    mock_repo_cls.return_value = mock_repo

    listar_sensores(actor=user, comuna_id=5, estado_salud=None, activo=True, limit=10, cursor=None)
    mock_repo.listar.assert_called_once_with(comuna_id=5, estado_salud=None, activo=True, limit=10, cursor=None)


@patch("app.application.sensores.SensorRepository")
def test_listar_sensores_municipalidad(mock_repo_cls):
    user = Usuario(id="f1", nombre="F", tipo="municipalidad", activo=True, comuna_id=12)
    mock_repo = MagicMock()
    mock_repo.listar.return_value = ([], None)
    mock_repo_cls.return_value = mock_repo

    # Debería ignorar comuna_id=5 y forzar comuna_id=12
    listar_sensores(actor=user, comuna_id=5, estado_salud=None, activo=True, limit=10, cursor=None)
    mock_repo.listar.assert_called_once_with(comuna_id=12, estado_salud=None, activo=True, limit=10, cursor=None)


@patch("app.application.sensores.SensorRepository")
def test_obtener_sensor_not_found(mock_repo_cls):
    user = Usuario(id="a1", nombre="Admin", tipo="admin", activo=True)
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(SensorNotFoundAppError):
        obtener_sensor(actor=user, sensor_id="s1")


@patch("app.application.sensores.SensorRepository")
def test_obtener_sensor_comuna_mismatch(mock_repo_cls):
    user = Usuario(id="f1", nombre="F", tipo="municipalidad", activo=True, comuna_id=1)
    sensor = Sensor(id="s1", comuna_id=2, nombre="Sensor", latitud=0, longitud=0, activo=True)

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = sensor
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(ComunaMismatchError):
        obtener_sensor(actor=user, sensor_id="s1")


@patch("app.application.sensores.SensorRepository")
def test_obtener_sensor_success(mock_repo_cls):
    user = Usuario(id="f1", nombre="F", tipo="municipalidad", activo=True, comuna_id=1)
    sensor = Sensor(id="s1", comuna_id=1, nombre="Sensor", latitud=0, longitud=0, activo=True)

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = sensor
    mock_repo_cls.return_value = mock_repo

    res = obtener_sensor(actor=user, sensor_id="s1")
    assert res == sensor


@patch("app.application.sensores.SensorRepository")
def test_obtener_resumen_sensores(mock_repo_cls):
    user = Usuario(id="a1", nombre="Admin", tipo="admin", activo=True)
    mock_repo = MagicMock()
    mock_repo.resumen.return_value = {"total": 5}
    mock_repo_cls.return_value = mock_repo

    res = obtener_resumen_sensores(actor=user, comuna_id=1)
    assert res == {"total": 5}
    mock_repo.resumen.assert_called_once_with(comuna_id=1)


@patch("app.application.sensores.get_supabase")
@patch("app.application.sensores.SensorRepository")
def test_crear_sensor_comuna_not_found(mock_repo_cls, mock_get_sb):
    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data=None)
    mock_get_sb.return_value = mock_sb

    with pytest.raises(ComunaNotFoundAppError):
        crear_sensor(nombre="S", comuna_id=99, latitud=0, longitud=0)


@patch("app.application.sensores.get_supabase")
@patch("app.application.sensores.SensorRepository")
def test_crear_sensor_success(mock_repo_cls, mock_get_sb):
    sensor = Sensor(id="s1", comuna_id=1, nombre="Sensor", latitud=0, longitud=0, activo=True)
    mock_repo = MagicMock()
    mock_repo.crear.return_value = sensor
    mock_repo_cls.return_value = mock_repo

    mock_sb = MagicMock()
    mock_sb.table().select().eq().maybe_single().execute.return_value = MagicMock(data={"id": 1})
    mock_get_sb.return_value = mock_sb

    res = crear_sensor(nombre="Sensor", comuna_id=1, latitud=0, longitud=0)
    assert res == sensor
    mock_repo.crear.assert_called_once_with(nombre="Sensor", comuna_id=1, latitud=0, longitud=0)


@patch("app.application.sensores.SensorRepository")
def test_actualizar_sensor_not_found(mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(SensorNotFoundAppError):
        actualizar_sensor(sensor_id="s1", nombre="New", latitud=None, longitud=None, activo=None)


@patch("app.application.sensores.SensorRepository")
def test_actualizar_sensor_success(mock_repo_cls):
    sensor = Sensor(id="s1", comuna_id=1, nombre="Old", latitud=0, longitud=0, activo=True)
    sensor_updated = Sensor(id="s1", comuna_id=1, nombre="New", latitud=0, longitud=0, activo=True)

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = sensor
    mock_repo.actualizar.return_value = sensor_updated
    mock_repo_cls.return_value = mock_repo

    res = actualizar_sensor(sensor_id="s1", nombre="New", latitud=None, longitud=None, activo=None)
    assert res == sensor_updated
    mock_repo.actualizar.assert_called_once_with(sensor_id="s1", nombre="New", latitud=None, longitud=None, activo=None)


@patch("app.application.sensores.SensorRepository")
def test_actualizar_sensor_returns_none(mock_repo_cls):
    sensor = Sensor(id="s1", comuna_id=1, nombre="Old", latitud=0, longitud=0, activo=True)

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = sensor
    mock_repo.actualizar.return_value = None
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(SensorNotFoundAppError):
        actualizar_sensor(sensor_id="s1", nombre="New", latitud=None, longitud=None, activo=None)


@patch("app.application.sensores.SensorRepository")
def test_desactivar_sensor_not_found(mock_repo_cls):
    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = None
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(SensorNotFoundAppError):
        desactivar_sensor(sensor_id="s1")


@patch("app.application.sensores.SensorRepository")
def test_desactivar_sensor_success(mock_repo_cls):
    sensor = Sensor(id="s1", comuna_id=1, nombre="S", latitud=0, longitud=0, activo=True)
    sensor_desact = Sensor(id="s1", comuna_id=1, nombre="S", latitud=0, longitud=0, activo=False)

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = sensor
    mock_repo.desactivar.return_value = sensor_desact
    mock_repo_cls.return_value = mock_repo

    res = desactivar_sensor(sensor_id="s1")
    assert res.activo is False


@patch("app.application.sensores.SensorRepository")
def test_desactivar_sensor_returns_none(mock_repo_cls):
    sensor = Sensor(id="s1", comuna_id=1, nombre="S", latitud=0, longitud=0, activo=True)

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = sensor
    mock_repo.desactivar.return_value = None
    mock_repo_cls.return_value = mock_repo

    with pytest.raises(SensorNotFoundAppError):
        desactivar_sensor(sensor_id="s1")
