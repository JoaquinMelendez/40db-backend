import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Configure environment variables for test execution
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "eyJtest")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-32-chars-minimum-here")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("STORAGE_BUCKET_REPORTES_ADMIN", "reportes-admin")
os.environ.setdefault("MQTT_BROKER_URL", "ssl://localhost:8883")
os.environ.setdefault("MQTT_CLIENT_ID", "test-client")
os.environ.setdefault("MQTT_USER", "test-user")
os.environ.setdefault("MQTT_PASSWORD", "test-password")

import pytest
from app.domain.entities import EvidenciaIot
from app.domain.errors import ExternalServiceError
from app.infrastructure.db.sensor_repo import SensorNombreDuplicadoError

# ── 1. Mocks Helpers ─────────────────────────────────────────────────────────

class SupabaseChainMock:
    def __init__(self, execute_vals=None):
        self.execute_vals = execute_vals or []
        self.call_index = 0
        self.auth = MagicMock()
        self.storage = MagicMock()

    def __getattr__(self, name):
        # Dynamically support arbitrary chained methods
        def method(*args, **kwargs):
            return self
        return method

    def execute(self):
        if self.call_index < len(self.execute_vals):
            val = self.execute_vals[self.call_index]
            self.call_index += 1
        else:
            val = None
        
        res = MagicMock()
        res.data = val
        return res


# ── 2. MQTT Ingestor Tests ───────────────────────────────────────────────────

@patch("paho.mqtt.client.Client")
@patch("app.application.registrar_lectura.registrar_lectura")
def test_mqtt_ingestor_lifecycle_and_message(mock_registrar, mock_mqtt_client_cls):
    from app.core.config import settings
    settings.mqtt_broker_url = "ssl://localhost:8883"
    settings.mqtt_client_id = "test-client"
    settings.mqtt_user = "test-user"
    settings.mqtt_password = "test-password"

    from app.infrastructure.mqtt.ingestor import MqttIngestor
    
    mock_client = MagicMock()
    mock_mqtt_client_cls.return_value = mock_client
    
    ingestor = MqttIngestor()
    
    # Check initial status
    assert ingestor.status() == "reconnecting"
    
    # Start ingestor
    ingestor.start()
    assert ingestor._client == mock_client
    mock_client.connect_async.assert_called_once()
    mock_client.loop_start.assert_called_once()
    
    # Test on_connect success (rc = 0)
    ingestor._on_connect(mock_client, None, None, 0)
    assert ingestor.status() == "ok"
    mock_client.subscribe.assert_called_once_with("40db/sensores/+/lectura", qos=1)
    
    # Test on_connect failure (rc != 0)
    ingestor._on_connect(mock_client, None, None, 1)
    assert ingestor.status() == "reconnecting"
    
    # Test on_disconnect
    ingestor._on_disconnect(mock_client, None, 1)
    assert ingestor.status() == "reconnecting"
    
    # Test stop
    ingestor.stop()
    mock_client.loop_stop.assert_called_once()
    mock_client.disconnect.assert_called_once()
    
    # Test on_message - invalid topic
    msg_invalid_topic = MagicMock()
    msg_invalid_topic.topic = "40db/sensores/lectura"
    ingestor._on_message(mock_client, None, msg_invalid_topic)
    mock_registrar.assert_not_called()
    
    # Test on_message - invalid JSON payload
    msg_invalid_json = MagicMock()
    msg_invalid_json.topic = "40db/sensores/s1/lectura"
    msg_invalid_json.payload = b"not-json"
    ingestor._on_message(mock_client, None, msg_invalid_json)
    mock_registrar.assert_not_called()
    
    # Test on_message - incomplete payload (missing fields)
    msg_missing_fields = MagicMock()
    msg_missing_fields.topic = "40db/sensores/s1/lectura"
    msg_missing_fields.payload = b'{"nivel_db": 60}'
    ingestor._on_message(mock_client, None, msg_missing_fields)
    mock_registrar.assert_not_called()
    
    # Test on_message - level out of range low (< 20)
    msg_out_low = MagicMock()
    msg_out_low.topic = "40db/sensores/s1/lectura"
    msg_out_low.payload = b'{"nivel_db": 19.9, "timestamp_medicion": "2026-06-03T12:00:00Z"}'
    ingestor._on_message(mock_client, None, msg_out_low)
    mock_registrar.assert_not_called()
    
    # Test on_message - level out of range high (> 130)
    msg_out_high = MagicMock()
    msg_out_high.topic = "40db/sensores/s1/lectura"
    msg_out_high.payload = b'{"nivel_db": 131.0, "timestamp_medicion": "2026-06-03T12:00:00Z"}'
    ingestor._on_message(mock_client, None, msg_out_high)
    mock_registrar.assert_not_called()
    
    # Test on_message - happy path
    msg_happy = MagicMock()
    msg_happy.topic = "40db/sensores/s-100/lectura"
    msg_happy.payload = b'{"nivel_db": 75.5, "timestamp_medicion": "2026-06-03T12:00:00Z"}'
    ingestor._on_message(mock_client, None, msg_happy)
    mock_registrar.assert_called_once_with(sensor_id="s-100", nivel_db=75.5, timestamp_medicion="2026-06-03T12:00:00Z")
    
    # Test on_message - registrar raises exception (resilient check)
    mock_registrar.reset_mock()
    mock_registrar.side_effect = Exception("db error")
    ingestor._on_message(mock_client, None, msg_happy)
    mock_registrar.assert_called_once()  # Exception is caught and logged


# ── 3. Reportes Admin Storage Tests ──────────────────────────────────────────

@patch("app.infrastructure.storage.reportes_admin_storage.get_supabase")
def test_reportes_admin_storage(mock_get_supabase):
    from app.core.config import settings
    settings.storage_bucket_reportes_admin = "reportes-admin"
    settings.storage_signed_url_ttl_seconds = 3600

    from app.infrastructure.storage.reportes_admin_storage import ReportesAdminStorage
    
    mock_bucket = MagicMock()
    mock_sb = MagicMock()
    mock_sb.storage.from_.return_value = mock_bucket
    mock_get_supabase.return_value = mock_sb
    
    storage = ReportesAdminStorage()
    
    # Test upload - happy path
    storage.upload("path/file.txt", b"content", "text/plain")
    mock_bucket.upload.assert_called_once_with(path="path/file.txt", file=b"content", file_options={"content-type": "text/plain", "upsert": "false"})
    
    # Test upload - error path
    mock_bucket.upload.side_effect = Exception("upload error")
    with pytest.raises(ExternalServiceError):
        storage.upload("path/file.txt", b"content", "text/plain")
        
    # Test signed_url - happy path (signedURL format)
    mock_bucket.upload.side_effect = None
    mock_bucket.create_signed_url.return_value = {"signedURL": "https://signed.url"}
    url = storage.signed_url("path/file.txt", 100)
    assert url == "https://signed.url"
    mock_bucket.create_signed_url.assert_called_with(path="path/file.txt", expires_in=100)
    
    # Test signed_url - happy path (signedUrl format)
    mock_bucket.create_signed_url.return_value = {"signedUrl": "https://signed-alt.url"}
    url = storage.signed_url("path/file.txt")
    assert url == "https://signed-alt.url"
    
    # Test signed_url - response missing URL
    mock_bucket.create_signed_url.return_value = {}
    with pytest.raises(ExternalServiceError, match="Respuesta sin signedURL"):
        storage.signed_url("path/file.txt")
        
    # Test signed_url - exception
    mock_bucket.create_signed_url.side_effect = Exception("url error")
    with pytest.raises(ExternalServiceError, match="No se pudo generar la signed URL"):
        storage.signed_url("path/file.txt")
        
    # Test remove - happy path
    mock_bucket.remove.side_effect = None
    storage.remove("path/file.txt")
    mock_bucket.remove.assert_called_once_with(["path/file.txt"])
    
    # Test remove - exception
    mock_bucket.remove.side_effect = Exception("remove error")
    with pytest.raises(ExternalServiceError, match="No se pudo eliminar el archivo"):
        storage.remove("path/file.txt")


# ── 4. DB RPC Tests ──────────────────────────────────────────────────────────

@patch("app.infrastructure.db.rpc.get_supabase")
def test_db_rpc_buscar_evidencia(mock_get_supabase):
    from app.infrastructure.db.rpc import buscar_evidencia
    
    # Empty result
    mock_sb_empty = SupabaseChainMock([[]])
    mock_get_supabase.return_value = mock_sb_empty
    res = buscar_evidencia(-33.0, -70.0, 100, 80.0, 5)
    assert res is None
    
    # Successful result, sensor exists
    row_evidencia = {
        "lectura_id": 42,
        "sensor_id": "sensor-1",
        "nivel_db": 85.5,
        "distancia_metros": 12.3,
        "timestamp_medicion": "2026-06-03T12:00:00Z"
    }
    mock_sb_success = SupabaseChainMock([
        [row_evidencia],  # rpc data
        {"nombre": "Sensor Comunitario"}  # sensor query data
    ])
    mock_get_supabase.return_value = mock_sb_success
    
    res = buscar_evidencia(-33.0, -70.0, 100, 80.0, 5)
    assert res is not None
    assert isinstance(res, EvidenciaIot)
    assert res.lectura_id == 42
    assert res.sensor_nombre == "Sensor Comunitario"
    
    # Successful result, sensor query empty (falls back to sensor_id)
    mock_sb_no_sensor = SupabaseChainMock([
        [row_evidencia],
        None
    ])
    mock_get_supabase.return_value = mock_sb_no_sensor
    res = buscar_evidencia(-33.0, -70.0, 100, 80.0, 5)
    assert res is not None
    assert res.sensor_nombre == "sensor-1"


@patch("app.infrastructure.db.rpc.get_supabase")
def test_db_rpc_crear_reporte_con_validacion(mock_get_supabase):
    from app.infrastructure.db.rpc import crear_reporte_con_validacion
    
    mock_sb = SupabaseChainMock([[{"reporte_id": "rep-abc", "lectura_evidencia_id": 99}]])
    mock_get_supabase.return_value = mock_sb
    
    rep_id, ev_id = crear_reporte_con_validacion(
        usuario_id="u1", comuna_id=1, titulo="Ruido", descripcion="Desc",
        latitud=-33.0, longitud=-70.0, lectura_evidencia_id=None,
        radio_metros=100, umbral_db=80.0, ventana_minutos=5
    )
    assert rep_id == "rep-abc"
    assert ev_id == 99


# ── 5. UsuarioRepository Tests ────────────────────────────────────────────────

@patch("app.infrastructure.db.usuario_repo.get_supabase")
def test_usuario_repository(mock_get_supabase):
    from app.infrastructure.db.usuario_repo import UsuarioRepository
    
    row_user = {"id": "u1", "nombre": "User 1", "tipo": "ciudadano", "activo": True, "created_at": "2026-06-03T12:00:00Z"}
    
    # 1. get_by_id - happy path
    mock_sb = SupabaseChainMock([row_user])
    mock_get_supabase.return_value = mock_sb
    repo = UsuarioRepository()
    u = repo.get_by_id("u1")
    assert u is not None
    assert u.id == "u1"
    assert u.nombre == "User 1"
    
    # get_by_id - empty
    mock_sb_empty = SupabaseChainMock([None])
    mock_get_supabase.return_value = mock_sb_empty
    repo = UsuarioRepository()
    assert repo.get_by_id("u2") is None
    
    # get_by_id - exception
    mock_sb_err = SupabaseChainMock([])
    # Trigger exception on table access
    mock_sb_err.table = MagicMock(side_effect=Exception("db down"))
    mock_get_supabase.return_value = mock_sb_err
    repo = UsuarioRepository()
    assert repo.get_by_id("u1") is None

    # 2. update_me - happy path
    mock_sb_upd = SupabaseChainMock([[row_user]])
    mock_get_supabase.return_value = mock_sb_upd
    repo = UsuarioRepository()
    res = repo.update_me("u1", telefono="+56911112222", comuna_id=2)
    assert res.id == "u1"
    
    # update_me - error path
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("update failure"))
    mock_get_supabase.return_value = mock_sb_err
    repo = UsuarioRepository()
    with pytest.raises(ExternalServiceError):
        repo.update_me("u1", "+569", 2)

    # 3. set_activo - happy path
    mock_sb_act = SupabaseChainMock([[row_user]])
    mock_get_supabase.return_value = mock_sb_act
    repo = UsuarioRepository()
    res = repo.set_activo("u1", True)
    assert res is not None
    
    # set_activo - empty result
    mock_sb_act_empty = SupabaseChainMock([[]])
    mock_get_supabase.return_value = mock_sb_act_empty
    repo = UsuarioRepository()
    assert repo.set_activo("u1", True) is None
    
    # set_activo - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = UsuarioRepository()
    with pytest.raises(ExternalServiceError):
        repo.set_activo("u1", True)

    # 4. promover - happy path
    mock_sb_prom = SupabaseChainMock([[row_user]])
    mock_get_supabase.return_value = mock_sb_prom
    repo = UsuarioRepository()
    res = repo.promover("u1", "municipalidad", 1)
    assert res is not None
    
    # promover - empty result
    mock_sb_prom_empty = SupabaseChainMock([[]])
    mock_get_supabase.return_value = mock_sb_prom_empty
    repo = UsuarioRepository()
    assert repo.promover("u1", "admin", None) is None
    
    # promover - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = UsuarioRepository()
    with pytest.raises(ExternalServiceError):
        repo.promover("u1", "admin", None)

    # 5. _fetch_email
    mock_sb_email = SupabaseChainMock([])
    res_user = MagicMock()
    res_user.user = MagicMock(email="test@email.com")
    mock_sb_email.auth.admin.get_user_by_id.return_value = res_user
    mock_get_supabase.return_value = mock_sb_email
    repo = UsuarioRepository()
    assert repo._fetch_email("u1") == "test@email.com"
    
    # _fetch_email - exception
    mock_sb_email.auth.admin.get_user_by_id.side_effect = Exception("auth error")
    repo = UsuarioRepository()
    assert repo._fetch_email("u1") is None

    # 6. listar - happy path (with limit pagination and email fetching)
    mock_sb_list = SupabaseChainMock([
        [
            {"id": "u1", "nombre": "User 1", "tipo": "ciudadano", "activo": True, "created_at": "2026-06-03T12:00:00Z"},
            {"id": "u2", "nombre": "User 2", "tipo": "ciudadano", "activo": True, "created_at": "2026-06-03T11:00:00Z"},
        ]
    ])
    # Mock auth response for fetch email in loop
    res_user1 = MagicMock()
    res_user1.user = MagicMock(email="u1@test.com")
    mock_sb_list.auth.admin.get_user_by_id.return_value = res_user1
    
    mock_get_supabase.return_value = mock_sb_list
    repo = UsuarioRepository()
    users, cursor = repo.listar(tipo="ciudadano", comuna_id=1, activo=True, q="User", limit=1, cursor=None)
    assert len(users) == 1
    assert users[0].id == "u1"
    assert cursor is not None  # limit was 1, we returned 2 rows from mock, so cursor should be generated
    
    # Decode cursor test
    mock_sb_list_paged = SupabaseChainMock([[]])
    mock_get_supabase.return_value = mock_sb_list_paged
    repo = UsuarioRepository()
    users_with_cursor, _ = repo.listar(tipo=None, comuna_id=None, activo=None, q=None, limit=10, cursor=cursor)
    
    # listar - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("list error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = UsuarioRepository()
    with pytest.raises(ExternalServiceError):
        repo.listar(None, None, None, None, 10, None)


# ── 6. LecturaRepository Tests ───────────────────────────────────────────────

@patch("app.infrastructure.db.lectura_repo.get_supabase")
def test_lectura_repository(mock_get_supabase):
    from app.infrastructure.db.lectura_repo import LecturaRepository
    
    # 1. insert - happy path
    mock_sb = SupabaseChainMock([None])
    mock_get_supabase.return_value = mock_sb
    repo = LecturaRepository()
    repo.insert("sensor-1", 75.0, "2026-06-03T12:00:00Z")
    
    # insert - error path
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("insert error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = LecturaRepository()
    with pytest.raises(ExternalServiceError):
        repo.insert("sensor-1", 75.0, "2026-06-03T12:00:00Z")

    # 2. _matview_aplica checks
    # Case A: minutes != 5 -> False
    repo = LecturaRepository()
    assert repo._matview_aplica("2026-06-03T12:00:00Z", "2026-06-03T13:00:00Z", 10) is False
    
    # Case B: invalid time format -> False
    assert repo._matview_aplica("invalid-time", "2026-06-03T13:00:00Z", 5) is False
    
    # Case C: timestamps too old -> False
    old_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert repo._matview_aplica(old_time, "2026-06-03T13:00:00Z", 5) is False

    # Case D: valid -> True
    recent_time = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert repo._matview_aplica(recent_time, "2026-06-03T13:00:00Z", 5) is True

    # 3. heatmap - matview path happy path
    mock_sb_matview = SupabaseChainMock([[{"lng_cell": -70.6, "lat_cell": -33.4, "bucket_start": "2026-06-03T12:00:00Z", "nivel_db_avg": 65.0, "nivel_db_max": 75.0, "lectura_count": 12}]])
    mock_get_supabase.return_value = mock_sb_matview
    repo = LecturaRepository()
    rows, source = repo.heatmap(-70.7, -33.5, -70.5, -33.3, recent_time, "2026-06-03T13:00:00Z", 5, 0.001)
    assert source == "matview"
    assert len(rows) == 1
    
    # 4. heatmap - matview error fallback to RPC
    # Mock matview fails, fallback RPC succeeds
    mock_sb_fallback = SupabaseChainMock([
        # RPC query succeeds
        [{"lng_cell": -70.6, "lat_cell": -33.4, "nivel_db_avg": 70.0}]
    ])
    # Make table call raise exception to trigger fallback
    mock_sb_fallback.table = MagicMock(side_effect=Exception("matview index invalid"))
    mock_get_supabase.return_value = mock_sb_fallback
    repo = LecturaRepository()
    rows, source = repo.heatmap(-70.7, -33.5, -70.5, -33.3, recent_time, "2026-06-03T13:00:00Z", 5, 0.001)
    assert source == "rpc"
    assert len(rows) == 1

    # 5. heatmap - RPC direct happy path
    mock_sb_rpc = SupabaseChainMock([[{"lng_cell": -70.6, "lat_cell": -33.4, "nivel_db_avg": 70.0}]])
    mock_get_supabase.return_value = mock_sb_rpc
    repo = LecturaRepository()
    # bucket_minutes = 10 -> enforces RPC direct path
    rows, source = repo.heatmap(-70.7, -33.5, -70.5, -33.3, recent_time, "2026-06-03T13:00:00Z", 10, 0.001)
    assert source == "rpc"
    assert len(rows) == 1
    
    # 6. heatmap - RPC direct error path
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.rpc = MagicMock(side_effect=Exception("rpc error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = LecturaRepository()
    with pytest.raises(ExternalServiceError):
        repo.heatmap(-70.7, -33.5, -70.5, -33.3, recent_time, "2026-06-03T13:00:00Z", 10, 0.001)


# ── 7. ReporteArchivoAdminRepository Tests ───────────────────────────────────

@patch("app.infrastructure.db.reporte_archivo_admin_repo.get_supabase")
def test_reporte_archivo_admin_repository(mock_get_supabase):
    from app.infrastructure.db.reporte_archivo_admin_repo import ReporteArchivoAdminRepository
    
    row_meta = {
        "id": "file-1",
        "generado_por_id": "u1",
        "nombre": "Report.xlsx",
        "tipo": "excel",
        "mime_type": "application/vnd.ms-excel",
        "tamano_bytes": 1024,
        "object_path": "reports/report.xlsx",
        "created_at": "2026-06-03T12:00:00Z"
    }
    
    # 1. insert
    mock_sb = SupabaseChainMock([[row_meta]])
    mock_get_supabase.return_value = mock_sb
    repo = ReporteArchivoAdminRepository()
    res = repo.insert(
        generado_por_id="u1", nombre="Report.xlsx", tipo="excel",
        mime_type="application/vnd.ms-excel", tamano_bytes=1024,
        object_path="reports/report.xlsx", rango_desde=None, rango_hasta=None
    )
    assert res.id == "file-1"
    
    # insert - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("db failure"))
    mock_get_supabase.return_value = mock_sb_err
    repo = ReporteArchivoAdminRepository()
    with pytest.raises(ExternalServiceError):
        repo.insert(
            generado_por_id="u1", nombre="Report.xlsx", tipo="excel",
            mime_type="application/vnd.ms-excel", tamano_bytes=1024,
            object_path="reports/report.xlsx", rango_desde=None, rango_hasta=None
        )
        
    # 2. get_by_id - happy path
    mock_sb = SupabaseChainMock([row_meta])
    mock_get_supabase.return_value = mock_sb
    repo = ReporteArchivoAdminRepository()
    assert repo.get_by_id("file-1").id == "file-1"
    
    # get_by_id - empty
    mock_sb_empty = SupabaseChainMock([None])
    mock_get_supabase.return_value = mock_sb_empty
    repo = ReporteArchivoAdminRepository()
    assert repo.get_by_id("file-empty") is None
    
    # get_by_id - error (graceful return None)
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = ReporteArchivoAdminRepository()
    assert repo.get_by_id("file-err") is None

    # 3. delete - happy path
    mock_sb = SupabaseChainMock([None])
    mock_get_supabase.return_value = mock_sb
    repo = ReporteArchivoAdminRepository()
    repo.delete("file-1")
    
    # delete - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = ReporteArchivoAdminRepository()
    with pytest.raises(ExternalServiceError):
        repo.delete("file-1")

    # 4. listar - happy path (with pagination & user name hydration)
    mock_sb_list = SupabaseChainMock([
        [row_meta],  # reporte_archivo_admin query
        [{"id": "u1", "nombre": "Admin User"}]  # usuario metadata hydration query
    ])
    mock_get_supabase.return_value = mock_sb_list
    repo = ReporteArchivoAdminRepository()
    files, cursor = repo.listar(tipo="excel", generado_por_id="u1", limit=10, cursor=None)
    assert len(files) == 1
    assert files[0].id == "file-1"
    assert files[0].generado_por_nombre == "Admin User"
    
    # test cursor pagination encoding/decoding
    mock_sb_list_paged = SupabaseChainMock([
        [
            row_meta,
            dict(row_meta, id="file-2", created_at="2026-06-03T11:00:00Z")
        ],
        []
    ])
    mock_get_supabase.return_value = mock_sb_list_paged
    repo = ReporteArchivoAdminRepository()
    files_p, cursor_p = repo.listar(tipo=None, generado_por_id=None, limit=1, cursor=None)
    assert cursor_p is not None
    
    # decode check
    mock_sb_decoded = SupabaseChainMock([[]])
    mock_get_supabase.return_value = mock_sb_decoded
    repo = ReporteArchivoAdminRepository()
    repo.listar(tipo=None, generado_por_id=None, limit=10, cursor=cursor_p)
    
    # listar - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("err"))
    mock_get_supabase.return_value = mock_sb_err
    repo = ReporteArchivoAdminRepository()
    with pytest.raises(ExternalServiceError):
        repo.listar(tipo=None, generado_por_id=None, limit=10, cursor=None)


# ── 8. ReporteComentarioRepository Tests ─────────────────────────────────────

@patch("app.infrastructure.db.reporte_comentario_repo.get_supabase")
def test_reporte_comentario_repository(mock_get_supabase):
    from app.infrastructure.db.reporte_comentario_repo import ReporteComentarioRepository
    
    row_comment = {
        "id": 1,
        "visibilidad": "externo",
        "cuerpo": "Un comentario de prueba.",
        "created_at": "2026-06-03T12:00:00Z",
        "autor": {"id": "u1", "nombre": "User 1"},
        "delegado_a": None,
        "delegado_at": None
    }
    
    # 1. crear - happy path
    # First: insert result to get ID. Second: select query to hydrate autor
    mock_sb = SupabaseChainMock([
        [{"id": 1}],
        row_comment
    ])
    mock_get_supabase.return_value = mock_sb
    repo = ReporteComentarioRepository()
    c = repo.crear(reporte_id="rep-1", autor_id="u1", visibilidad="externo", cuerpo="Cuerpo", delegado_a_id=None, delegado_at=None)
    assert c["id"] == 1
    assert c["cuerpo"] == "Un comentario de prueba."
    
    # crear - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("insert comment failed"))
    mock_get_supabase.return_value = mock_sb_err
    repo = ReporteComentarioRepository()
    with pytest.raises(ExternalServiceError):
        repo.crear("rep-1", "u1", "externo", "cuerpo")

    # 2. listar_por_reporte - happy path
    mock_sb = SupabaseChainMock([[row_comment]])
    mock_get_supabase.return_value = mock_sb
    repo = ReporteComentarioRepository()
    comments = repo.listar_por_reporte("rep-1", solo_externos=True)
    assert len(comments) == 1
    assert comments[0]["id"] == 1
    
    # listar_por_reporte - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("list comment error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = ReporteComentarioRepository()
    with pytest.raises(ExternalServiceError):
        repo.listar_por_reporte("rep-1")


# ── 9. ReporteRepository Tests ───────────────────────────────────────────────

@patch("app.infrastructure.db.reporte_repo.get_supabase")
def test_reporte_repository(mock_get_supabase):
    from app.infrastructure.db.reporte_repo import ReporteRepository
    
    row_rep = {
        "id": "rep-1",
        "usuario_id": "u1",
        "comuna_id": 1,
        "titulo": "Ruido fuerte",
        "descripcion": "Descripción",
        "latitud": -33.4,
        "longitud": -70.6,
        "lectura_evidencia_id": None,
        "created_at": "2026-06-03T12:00:00Z"
    }
    
    # 1. get_by_id - empty
    mock_sb_empty = SupabaseChainMock([None])
    mock_get_supabase.return_value = mock_sb_empty
    repo = ReporteRepository()
    assert repo.get_by_id("rep-1") is None
    
    # 2. get_by_id - happy path
    # First: get reporte. Second: get_estado_actual. Third: get_historial
    mock_sb_success = SupabaseChainMock([
        row_rep,
        [{"tipo_estado": {"nombre": "En espera"}}],
        [{"comentario": "Iniciado", "created_at": "2026-06-03T12:00:00Z", "tipo_estado": {"nombre": "En espera"}, "usuario": {"id": "u1", "nombre": "User 1"}}]
    ])
    mock_get_supabase.return_value = mock_sb_success
    repo = ReporteRepository()
    r = repo.get_by_id("rep-1")
    assert r is not None
    assert r.id == "rep-1"
    assert r.estado_actual == "En espera"
    assert len(r.historial) == 1
    assert r.historial[0]["estado"] == "En espera"

    # 3. list_by_usuario - happy path
    # First: list query. Second, third: _get_estado_actual loop calls
    mock_sb_list = SupabaseChainMock([
        [
            {"id": "rep-1", "titulo": "R1", "created_at": "2026-06-03T12:00:00Z", "comuna_id": 1},
            {"id": "rep-2", "titulo": "R2", "created_at": "2026-06-03T11:00:00Z", "comuna_id": 1}
        ],
        [{"tipo_estado": {"nombre": "En espera"}}],
        [{"tipo_estado": {"nombre": "En espera"}}]
    ])
    mock_get_supabase.return_value = mock_sb_list
    repo = ReporteRepository()
    reportes, cursor = repo.list_by_usuario("u1", limit=1, cursor=None, estado="En espera")
    assert len(reportes) == 1
    assert reportes[0].id == "rep-1"
    assert cursor is not None
    
    # list_by_usuario - with cursor decode
    mock_sb_decoded = SupabaseChainMock([[], []])
    mock_get_supabase.return_value = mock_sb_decoded
    repo = ReporteRepository()
    repo.list_by_usuario("u1", limit=10, cursor=cursor, estado=None)

    # 4. list_by_comuna - happy path
    # First: list query. Second, third: _get_estado_actual loop calls
    mock_sb_list_comuna = SupabaseChainMock([
        [
            {"id": "rep-1", "titulo": "R1", "usuario_id": "u1", "created_at": "2026-06-03T12:00:00Z"},
            {"id": "rep-2", "titulo": "R2", "usuario_id": "u1", "created_at": "2026-06-03T11:00:00Z"}
        ],
        [{"tipo_estado": {"nombre": "En espera"}}],
        [{"tipo_estado": {"nombre": "Resuelto"}}]
    ])
    mock_get_supabase.return_value = mock_sb_list_comuna
    repo = ReporteRepository()
    reportes, cursor = repo.list_by_comuna(comuna_id=1, limit=1, cursor=None, estado="En espera")
    assert len(reportes) == 1
    assert reportes[0].id == "rep-1"
    assert cursor is not None
    
    # list_by_comuna - with cursor decode
    mock_sb_decoded = SupabaseChainMock([[], []])
    mock_get_supabase.return_value = mock_sb_decoded
    repo = ReporteRepository()
    repo.list_by_comuna(comuna_id=1, limit=10, cursor=cursor, estado=None)

    # 5. get_historial
    mock_sb_hist = SupabaseChainMock([
        [{"comentario": "Ok", "created_at": "2026-06-03T12:00:00Z", "tipo_estado": {"nombre": "En atencion"}}]
    ])
    mock_get_supabase.return_value = mock_sb_hist
    repo = ReporteRepository()
    hist = repo.get_historial("rep-1")
    assert len(hist) == 1
    assert hist[0]["estado"] == "En atencion"

    # 6. cambiar_estado - happy path
    mock_sb = SupabaseChainMock([None, None])
    mock_get_supabase.return_value = mock_sb
    repo = ReporteRepository()
    repo.cambiar_estado("rep-1", tipo_estado_id=2, usuario_id="u1", comentario="Iniciado", atendido_por_id="u2")
    
    # cambiar_estado - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("state change error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = ReporteRepository()
    with pytest.raises(ExternalServiceError):
        repo.cambiar_estado("rep-1", tipo_estado_id=2, usuario_id="u1", comentario=None)


# ── 10. ResumenHorarioRepository Tests ───────────────────────────────────────

@patch("app.infrastructure.db.resumen_horario_repo.get_supabase")
def test_resumen_horario_repository(mock_get_supabase):
    from app.infrastructure.db.resumen_horario_repo import ResumenHorarioRepository
    
    row_res = {
        "sensor_id": "sensor-1",
        "hora": "2026-06-03T12:00:00+00:00",
        "avg_db": 60.0,
        "min_db": 45.0,
        "max_db": 85.0,
        "p95_db": 75.0,
        "n_lecturas": 60,
        "refrescado_at": "2026-06-03T13:00:00+00:00"
    }
    
    # 1. listar - happy path
    mock_sb = SupabaseChainMock([[row_res]])
    mock_get_supabase.return_value = mock_sb
    repo = ResumenHorarioRepository()
    desde = datetime.now() - timedelta(hours=5)
    hasta = datetime.now()
    res = repo.listar("sensor-1", desde, hasta)
    assert len(res) == 1
    assert res[0].sensor_id == "sensor-1"
    assert res[0].avg_db == 60.0
    
    # Test max_refrescado_at
    assert repo.max_refrescado_at([]) is None
    assert repo.max_refrescado_at(res) == datetime.fromisoformat("2026-06-03T13:00:00+00:00")
    
    # 2. listar - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("query failed"))
    mock_get_supabase.return_value = mock_sb_err
    repo = ResumenHorarioRepository()
    with pytest.raises(ExternalServiceError):
        repo.listar("sensor-1", desde, hasta)


# ── 11. SensorRepository Tests ───────────────────────────────────────────────

@patch("app.infrastructure.db.sensor_repo.get_supabase")
def test_sensor_repository(mock_get_supabase):
    from app.infrastructure.db.sensor_repo import SensorRepository
    
    row_sensor_raw = {
        "id": "s1",
        "comuna_id": 1,
        "nombre": "Sensor Central",
        "latitud": -33.45,
        "longitud": -70.65,
        "activo": True,
        "ultima_lectura_db": 65.0,
        "ultima_lectura_at": "2026-06-03T12:00:00Z",
        "estado_salud": "online"
    }
    
    # 1. _comuna_nombres
    mock_sb = SupabaseChainMock([[{"id": 1, "nombre": "Santiago"}]])
    mock_get_supabase.return_value = mock_sb
    repo = SensorRepository()
    names = repo._comuna_nombres([1])
    assert names == {1: "Santiago"}
    
    # _comuna_nombres - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = SensorRepository()
    with pytest.raises(Exception):
        repo._comuna_nombres([1])

    # 2. get_by_id - empty
    mock_sb_empty = SupabaseChainMock([[]])
    mock_get_supabase.return_value = mock_sb_empty
    repo = SensorRepository()
    assert repo.get_by_id("s1") is None
    
    # 3. get_by_id - happy path
    # First: rpc return. Second: _comuna_nombres return
    mock_sb = SupabaseChainMock([
        [row_sensor_raw],
        [{"id": 1, "nombre": "Santiago"}]
    ])
    mock_get_supabase.return_value = mock_sb
    repo = SensorRepository()
    s = repo.get_by_id("s1")
    assert s is not None
    assert s.id == "s1"
    assert s.comuna_nombre == "Santiago"
    
    # get_by_id - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.rpc = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = SensorRepository()
    with pytest.raises(ExternalServiceError):
        repo.get_by_id("s1")

    # 4. resumen - happy path
    mock_sb = SupabaseChainMock([[{"total": 1, "online": 1, "intermitente": 0, "offline": 0, "sin_lecturas": 0, "calculado_at": None}]])
    mock_get_supabase.return_value = mock_sb
    repo = SensorRepository()
    res = repo.resumen(None)
    assert res["total"] == 1
    
    # resumen - empty
    mock_sb = SupabaseChainMock([[]])
    mock_get_supabase.return_value = mock_sb
    repo = SensorRepository()
    res = repo.resumen(None)
    assert res["total"] == 0
    
    # resumen - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.rpc = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = SensorRepository()
    with pytest.raises(ExternalServiceError):
        repo.resumen(None)

    # 5. crear - happy path
    # First: insert result. Second: get_by_id chain (rpc + comuna names)
    mock_sb = SupabaseChainMock([
        [{"id": "s1"}],
        [row_sensor_raw],
        [{"id": 1, "nombre": "Santiago"}]
    ])
    mock_get_supabase.return_value = mock_sb
    repo = SensorRepository()
    new_s = repo.crear("Sensor Central", 1, -33.45, -70.65)
    assert new_s.id == "s1"
    
    # crear - name duplicate
    mock_sb_dup = SupabaseChainMock([])
    mock_sb_dup.table = MagicMock(side_effect=Exception("23505 Duplicate key"))
    mock_get_supabase.return_value = mock_sb_dup
    repo = SensorRepository()
    with pytest.raises(SensorNombreDuplicadoError):
        repo.crear("Sensor Central", 1, -33.45, -70.65)
        
    # crear - other error
    mock_sb_dup = SupabaseChainMock([])
    mock_sb_dup.table = MagicMock(side_effect=Exception("other db error"))
    mock_get_supabase.return_value = mock_sb_dup
    repo = SensorRepository()
    with pytest.raises(ExternalServiceError):
        repo.crear("Sensor Central", 1, -33.45, -70.65)
        
    # crear - creation success but read fails (None return from get_by_id)
    mock_sb_none = SupabaseChainMock([
        [{"id": "s1"}],
        [] # empty rpc call in get_by_id
    ])
    mock_get_supabase.return_value = mock_sb_none
    repo = SensorRepository()
    with pytest.raises(ExternalServiceError, match="Sensor creado pero no se pudo leer"):
        repo.crear("Sensor Central", 1, -33.45, -70.65)

    # 6. actualizar - happy path
    # First: update result. Second: get_by_id chain
    mock_sb = SupabaseChainMock([
        [{"id": "s1"}],
        [row_sensor_raw],
        [{"id": 1, "nombre": "Santiago"}]
    ])
    mock_get_supabase.return_value = mock_sb
    repo = SensorRepository()
    upd_s = repo.actualizar("s1", nombre="Nuevo", latitud=None, longitud=None, activo=None)
    assert upd_s.id == "s1"
    
    # actualizar - other errors
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = SensorRepository()
    with pytest.raises(ExternalServiceError):
        repo.actualizar("s1", nombre="Nuevo", latitud=None, longitud=None, activo=None)
        
    # actualizar - duplicate name error
    mock_sb_dup = SupabaseChainMock([])
    mock_sb_dup.table = MagicMock(side_effect=Exception("duplicate key value violates unique constraint"))
    mock_get_supabase.return_value = mock_sb_dup
    repo = SensorRepository()
    with pytest.raises(SensorNombreDuplicadoError):
        repo.actualizar("s1", nombre="Nuevo", latitud=None, longitud=None, activo=None)

    # 7. desactivar - happy path
    # First: update result. Second: get_by_id chain
    mock_sb = SupabaseChainMock([
        [{"id": "s1"}],
        [row_sensor_raw],
        [{"id": 1, "nombre": "Santiago"}]
    ])
    mock_get_supabase.return_value = mock_sb
    repo = SensorRepository()
    des_s = repo.desactivar("s1")
    assert des_s.id == "s1"
    
    # desactivar - empty update
    mock_sb_empty = SupabaseChainMock([[]])
    mock_get_supabase.return_value = mock_sb_empty
    repo = SensorRepository()
    assert repo.desactivar("s1") is None
    
    # desactivar - error
    mock_sb_err = SupabaseChainMock([])
    mock_sb_err.table = MagicMock(side_effect=Exception("error"))
    mock_get_supabase.return_value = mock_sb_err
    repo = SensorRepository()
    with pytest.raises(ExternalServiceError):
        repo.desactivar("s1")

    # 8. listar - happy path (with filters and comuna names query)
    mock_sb = SupabaseChainMock([
        [row_sensor_raw],  # rpc list
        [{"id": 1, "nombre": "Santiago"}]  # comuna names list
    ])
    mock_get_supabase.return_value = mock_sb
    repo = SensorRepository()
    sensores, next_cursor = repo.listar(comuna_id=1, estado_salud="online", activo=True, limit=10, cursor=None)
    assert len(sensores) == 1
    assert sensores[0].id == "s1"
