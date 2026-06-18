"""
Tests de Seguridad
==================
Verifican el comportamiento del backend frente a abusos de autenticación y
autorización en el borde HTTP. A diferencia de los tests unitarios de `deps`
(en test_api.py), acá se ejercita el flujo real de la API end-to-end:

  - Autenticación obligatoria: ningún endpoint protegido responde sin token.
  - Resistencia del JWT a manipulación: alg=none, firma inválida, expirado,
    audiencia incorrecta, algoritmo no soportado, sin subject, token basura.
  - Autorización / escalación de privilegios: un rol inferior no alcanza
    endpoints de un rol superior (403).
  - Usuario inhabilitado: un token válido de un usuario inactivo o inexistente
    no concede acceso (401).
  - No fuga de información: un error interno no expone stack traces ni detalles.

Decisiones de diseño:
  - Los ataques al JWT se prueban contra GET /usuarios/me porque solo exige
    `current_user`: la verificación del token falla ANTES de tocar la DB, así
    que no hace falta mockear Supabase.
  - Para autorización se usa un token VÁLIDO + se mockea el UsuarioRepository
    para fijar el rol del actor; así se ejercita la cadena real
    (decode JWT → carga usuario → gate de rol) sin red.
"""

import base64
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.domain.entities import Usuario

client = TestClient(app)
client_no_raise = TestClient(app, raise_server_exceptions=False)

API = settings.api_prefix  # "/api/v1"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _token(sub="sec-user", secret=None, alg="HS256", aud="authenticated",
           exp_delta=3600, **extra) -> str:
    """Construye un JWT firmado. Por defecto válido (HS256, secreto real,
    audiencia correcta, no expirado). Cada parámetro permite degradar una
    propiedad para simular un ataque."""
    secret = settings.supabase_jwt_secret if secret is None else secret
    payload = {"exp": int((datetime.now(timezone.utc) + timedelta(seconds=exp_delta)).timestamp())}
    if sub is not None:
        payload["sub"] = sub
    if aud is not None:
        payload["aud"] = aud
    payload.update(extra)
    return jwt.encode(payload, secret, algorithm=alg)


def _token_alg_none(sub="sec-user", aud="authenticated") -> str:
    """JWT forjado con alg=none y firma vacía (ataque clásico de algoritmo)."""
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    header = b64({"alg": "none", "typ": "JWT"})
    body = b64({"sub": sub, "aud": aud})
    return f"{header}.{body}."  # firma vacía


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _patch_actor(usuario: Usuario):
    """Mockea el UsuarioRepository de deps para que current_user cargue al
    actor dado (con el rol que queramos), sin tocar la DB."""
    p = patch("app.api.deps.UsuarioRepository")
    m = p.start()
    m.return_value.get_by_id.return_value = usuario
    return p


CIUDADANO = Usuario(id="sec-c", nombre="Ciudadano", tipo="ciudadano", activo=True, comuna_id=1)
MUNICIPAL = Usuario(id="sec-m", nombre="Municipal", tipo="municipalidad", activo=True, comuna_id=1)
ADMIN = Usuario(id="sec-a", nombre="Admin", tipo="admin", activo=True)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()
    patch.stopall()


# ══════════════════════════════════════════════════════════════════════════════
# 1. Autenticación obligatoria: sin token ⇒ 401
# ══════════════════════════════════════════════════════════════════════════════

class TestAutenticacionObligatoria:

    # (método, path, body) de endpoints protegidos representativos de cada rol.
    PROTEGIDOS = [
        ("GET", f"{API}/usuarios/me", None),
        ("GET", f"{API}/reportes/mios", None),
        ("GET", f"{API}/reportes/comuna/1", None),
        ("GET", f"{API}/sensores", None),
        ("GET", f"{API}/sensores/resumen", None),
        ("GET", f"{API}/usuarios", None),
        ("GET", f"{API}/reportes-admin/archivos", None),
        ("POST", f"{API}/reportes", {
            "titulo": "Ruido", "descripcion": "Descripcion suficientemente larga",
            "latitud": -33.45, "longitud": -70.65}),
        ("POST", f"{API}/sensores", {
            "nombre": "S1", "comuna_id": 1, "latitud": -33.45, "longitud": -70.65}),
        ("PATCH", f"{API}/usuarios/sec-x/activo", {"activo": False}),
        ("DELETE", f"{API}/sensores/sec-x", None),
    ]

    @pytest.mark.parametrize("method,path,body", PROTEGIDOS)
    def test_sin_token_responde_401(self, method, path, body):
        r = client.request(method, path, json=body)
        assert r.status_code == 401, f"{method} {path} debería exigir auth"

    @pytest.mark.parametrize("method,path,body", PROTEGIDOS)
    def test_token_basura_responde_401(self, method, path, body):
        r = client.request(method, path, headers=_auth("esto-no-es-un-jwt"), json=body)
        assert r.status_code == 401

    def test_esquema_no_bearer_es_rechazado(self):
        # Un esquema distinto a Bearer (Basic) no debe autenticar.
        r = client.get(f"{API}/usuarios/me",
                       headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# 2. Resistencia del JWT a manipulación (todos ⇒ 401)
# ══════════════════════════════════════════════════════════════════════════════

class TestJWTResistenciaAtaques:

    ENDPOINT = f"{API}/usuarios/me"

    def test_alg_none_es_rechazado(self):
        # Ataque clásico: forjar un token sin firma declarando alg=none.
        r = client.get(self.ENDPOINT, headers=_auth(_token_alg_none()))
        assert r.status_code == 401

    def test_firma_con_secreto_incorrecto_es_rechazada(self):
        # Token HS256 bien formado pero firmado con un secreto que no es el
        # nuestro (intento de falsificación).
        token = _token(secret="secreto-del-atacante-distinto-todo-mal")
        r = client.get(self.ENDPOINT, headers=_auth(token))
        assert r.status_code == 401

    def test_payload_manipulado_invalida_la_firma(self):
        # Tomamos un token válido y alteramos un byte del payload: la firma
        # deja de validar.
        valido = _token(sub="sec-user")
        header, body, sig = valido.split(".")
        body_tampered = body[:-2] + ("AA" if not body.endswith("AA") else "BB")
        r = client.get(self.ENDPOINT, headers=_auth(f"{header}.{body_tampered}.{sig}"))
        assert r.status_code == 401

    def test_token_expirado_es_rechazado(self):
        token = _token(exp_delta=-3600)  # expiró hace una hora
        r = client.get(self.ENDPOINT, headers=_auth(token))
        assert r.status_code == 401

    def test_audiencia_incorrecta_es_rechazada(self):
        token = _token(aud="otra-audiencia")
        r = client.get(self.ENDPOINT, headers=_auth(token))
        assert r.status_code == 401

    def test_algoritmo_no_soportado_es_rechazado(self):
        # HS512 no está en la lista blanca de algoritmos.
        token = _token(alg="HS512")
        r = client.get(self.ENDPOINT, headers=_auth(token))
        assert r.status_code == 401

    def test_token_sin_subject_es_rechazado(self):
        # Firma válida pero sin claim `sub`: no hay a quién autenticar.
        token = _token(sub=None)
        r = client.get(self.ENDPOINT, headers=_auth(token))
        assert r.status_code == 401

    def test_respuesta_401_no_filtra_secreto_ni_traza(self):
        r = client.get(self.ENDPOINT, headers=_auth(_token(secret="otro")))
        cuerpo = r.text.lower()
        assert settings.supabase_jwt_secret.lower() not in cuerpo
        assert "traceback" not in cuerpo


# ══════════════════════════════════════════════════════════════════════════════
# 3. Autorización: escalación de privilegios (rol inferior ⇒ 403)
# ══════════════════════════════════════════════════════════════════════════════

class TestAutorizacionRoles:

    # Endpoints que exigen un rol superior al del actor.
    SOLO_ADMIN = [
        ("POST", f"{API}/sensores", {
            "nombre": "S1", "comuna_id": 1, "latitud": -33.45, "longitud": -70.65}),
        ("GET", f"{API}/usuarios", None),
        ("PATCH", f"{API}/usuarios/sec-x/activo", {"activo": False}),
        ("GET", f"{API}/reportes-admin/archivos", None),
    ]
    SOLO_MUNICIPAL = [
        ("GET", f"{API}/reportes/comuna/1", None),
    ]
    MUNICIPAL_O_ADMIN = [
        ("GET", f"{API}/sensores", None),
        ("GET", f"{API}/sensores/resumen", None),
        ("GET", f"{API}/lecturas/resumen", None),
    ]

    def _request(self, actor, method, path, body):
        p = _patch_actor(actor)
        try:
            return client.request(method, path, headers=_auth(_token(sub=actor.id)), json=body)
        finally:
            p.stop()

    @pytest.mark.parametrize("method,path,body", SOLO_ADMIN)
    def test_ciudadano_no_alcanza_endpoints_admin(self, method, path, body):
        r = self._request(CIUDADANO, method, path, body)
        assert r.status_code == 403

    @pytest.mark.parametrize("method,path,body", SOLO_ADMIN)
    def test_municipal_no_alcanza_endpoints_admin(self, method, path, body):
        r = self._request(MUNICIPAL, method, path, body)
        assert r.status_code == 403

    @pytest.mark.parametrize("method,path,body", SOLO_MUNICIPAL)
    def test_ciudadano_no_alcanza_endpoints_municipal(self, method, path, body):
        r = self._request(CIUDADANO, method, path, body)
        assert r.status_code == 403

    @pytest.mark.parametrize("method,path,body", MUNICIPAL_O_ADMIN)
    def test_ciudadano_no_alcanza_endpoints_municipal_o_admin(self, method, path, body):
        r = self._request(CIUDADANO, method, path, body)
        assert r.status_code == 403

    def test_control_positivo_admin_pasa_el_gate(self):
        # Control de no-vacuidad: el MISMO endpoint que da 403 al ciudadano,
        # con un admin NO da 403 (el gate de rol deja pasar; lo que siga es
        # otra capa). Confirma que los 403 anteriores son del gate de rol.
        r = self._request(ADMIN, "GET", f"{API}/usuarios", None)
        assert r.status_code != 403


# ══════════════════════════════════════════════════════════════════════════════
# 4. Usuario inhabilitado: token válido pero sin derecho de acceso (401)
# ══════════════════════════════════════════════════════════════════════════════

class TestUsuarioInhabilitado:

    def test_usuario_inactivo_no_accede(self):
        inactivo = Usuario(id="sec-i", nombre="Inactivo", tipo="ciudadano", activo=False)
        p = _patch_actor(inactivo)
        try:
            r = client.get(f"{API}/usuarios/me", headers=_auth(_token(sub="sec-i")))
        finally:
            p.stop()
        assert r.status_code == 401

    def test_usuario_inexistente_no_accede(self):
        # Token válido pero el `sub` no corresponde a ningún usuario en la DB.
        p = patch("app.api.deps.UsuarioRepository")
        m = p.start()
        m.return_value.get_by_id.return_value = None
        try:
            r = client.get(f"{API}/usuarios/me", headers=_auth(_token(sub="fantasma")))
        finally:
            p.stop()
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# 5. No fuga de información: un error interno no expone detalles
# ══════════════════════════════════════════════════════════════════════════════

class TestNoFugaDeInformacion:

    def test_error_interno_devuelve_mensaje_generico(self):
        # Forzamos una excepción no controlada en la carga del usuario.
        secreto_interno = "detalle-sensible-de-implementacion-12345"
        p = patch("app.api.deps.UsuarioRepository")
        m = p.start()
        m.return_value.get_by_id.side_effect = RuntimeError(secreto_interno)
        try:
            r = client_no_raise.get(f"{API}/usuarios/me", headers=_auth(_token(sub="x")))
        finally:
            p.stop()

        assert r.status_code == 500
        body = r.json()
        assert body["error"]["code"] == "internal_error"
        # El detalle interno y cualquier traza NO deben aparecer en la respuesta.
        assert secreto_interno not in r.text
        assert "traceback" not in r.text.lower()
        assert "runtimeerror" not in r.text.lower()
