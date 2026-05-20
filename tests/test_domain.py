"""Tests de lógica de dominio pura (sin DB, sin red)."""
import os
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "eyJtest")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret-32-chars-minimum-here")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

import pytest
from app.domain.errors import (
    DomainError, NotFoundError, ForbiddenError, InvalidTokenError,
    ReporteNotFoundError, ComunaMismatchError, InvalidStateTransitionError,
    ExternalServiceError, ValidationError,
)
from app.application.cambiar_estado_reporte import _TRANSICIONES_VALIDAS


# ── Jerarquía de excepciones ─────────────────────────────────────────────────

def test_not_found_es_domain_error():
    err = ReporteNotFoundError("test")
    assert isinstance(err, DomainError)
    assert isinstance(err, NotFoundError)
    assert err.http_status == 404
    assert err.code == "reporte_not_found"


def test_invalid_token_es_unauthorized():
    err = InvalidTokenError("expirado")
    assert err.http_status == 401
    assert err.code == "invalid_token"


def test_comuna_mismatch_es_forbidden():
    err = ComunaMismatchError("otra comuna")
    assert err.http_status == 403
    assert err.code == "comuna_mismatch"


def test_external_service_error():
    err = ExternalServiceError("supabase caído")
    assert err.http_status == 503


# ── Máquina de estados ────────────────────────────────────────────────────────

def test_transicion_valida_espera_atencion():
    assert "En atencion" in _TRANSICIONES_VALIDAS["En espera"]


def test_transicion_valida_atencion_atendido():
    assert "Atendido" in _TRANSICIONES_VALIDAS["En atencion"]


def test_no_se_puede_saltar_espera_a_atendido():
    assert "Atendido" not in _TRANSICIONES_VALIDAS["En espera"]


def test_estados_terminales_sin_transicion():
    assert _TRANSICIONES_VALIDAS["Atendido"] == set()
    assert _TRANSICIONES_VALIDAS["Descartado"] == set()


def test_descartado_permitido_desde_espera():
    assert "Descartado" in _TRANSICIONES_VALIDAS["En espera"]


def test_descartado_permitido_desde_atencion():
    assert "Descartado" in _TRANSICIONES_VALIDAS["En atencion"]


# ── Cursor paginación ─────────────────────────────────────────────────────────

def test_cursor_encode_decode():
    from app.infrastructure.db.reporte_repo import _encode_cursor, _decode_cursor
    created_at = "2026-05-19T12:00:00+00:00"
    rid = "some-uuid"
    cursor = _encode_cursor(created_at, rid)
    decoded_ca, decoded_id = _decode_cursor(cursor)
    assert decoded_ca == created_at
    assert decoded_id == rid


# ── Validación de heatmap ─────────────────────────────────────────────────────

def test_bucket_minutes_invalido():
    from app.application.obtener_heatmap import obtener_heatmap
    from app.domain.errors import ValidationError as DomainValidationError
    with pytest.raises(DomainValidationError):
        obtener_heatmap(
            min_lng=-70.65, min_lat=-33.45,
            max_lng=-70.55, max_lat=-33.40,
            time_start="2026-05-19T00:00:00Z",
            time_end="2026-05-19T23:59:59Z",
            bucket_minutes=7,  # no está en {1,5,15,60}
        )


def test_ventana_mayor_a_limite():
    from app.application.obtener_heatmap import obtener_heatmap
    from app.domain.errors import ValidationError as DomainValidationError
    with pytest.raises(DomainValidationError):
        obtener_heatmap(
            min_lng=-70.65, min_lat=-33.45,
            max_lng=-70.55, max_lat=-33.40,
            time_start="2026-01-01T00:00:00Z",
            time_end="2026-01-15T00:00:00Z",  # 14 días > 7 max
            bucket_minutes=5,
        )
