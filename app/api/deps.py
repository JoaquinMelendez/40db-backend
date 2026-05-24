from typing import Optional
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from jwt import PyJWKClient

from app.core.config import settings
from app.domain.entities import Usuario
from app.domain.errors import InvalidTokenError, UnauthorizedError, ForbiddenError, ComunaMismatchError
from app.infrastructure.db.usuario_repo import UsuarioRepository

bearer = HTTPBearer(auto_error=False)

# JWKS client (cache interno de las claves públicas). Lazy.
_jwks_client: Optional[PyJWKClient] = None

# Algoritmos asimétricos soportados (Supabase usa ES256 en versiones nuevas;
# RS256 si el proyecto se configuró con otra keypair).
_ASYM_ALGS = {"ES256", "ES384", "RS256", "RS384"}


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")
    return _jwks_client


def _decode_jwt(token: str) -> dict:
    # El header determina si verificamos con JWKS (asimétrico) o secret (HS256).
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise InvalidTokenError("Token mal formado.")

    alg = header.get("alg", "")

    if alg in _ASYM_ALGS:
        try:
            key = _get_jwks_client().get_signing_key_from_jwt(token).key
        except Exception as e:
            raise InvalidTokenError(f"No se pudo obtener la clave de firma: {e}")
        algorithms = [alg]
    elif alg == "HS256":
        key = settings.supabase_jwt_secret
        algorithms = ["HS256"]
    else:
        raise InvalidTokenError(f"Algoritmo de firma no soportado: {alg}")

    try:
        return jwt.decode(token, key, algorithms=algorithms, audience="authenticated")
    except jwt.ExpiredSignatureError:
        raise InvalidTokenError("Token expirado.")
    except jwt.InvalidTokenError as e:
        raise InvalidTokenError(f"Token inválido: {e}")


async def current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> Usuario:
    if not creds:
        raise UnauthorizedError("Se requiere autenticación.")
    payload = _decode_jwt(creds.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise InvalidTokenError("Token sin subject.")

    repo = UsuarioRepository()
    user = repo.get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("Usuario no encontrado.")
    if not user.activo:
        raise UnauthorizedError("Usuario inactivo.")
    return user


async def current_user_municipal(
    user: Usuario = Depends(current_user),
) -> Usuario:
    if user.tipo != "municipalidad":
        raise ForbiddenError("Se requiere rol municipalidad.")
    return user


async def current_user_admin(
    user: Usuario = Depends(current_user),
) -> Usuario:
    if user.tipo != "admin":
        raise ForbiddenError("Se requiere rol admin.")
    return user


async def current_user_municipal_o_admin(
    user: Usuario = Depends(current_user),
) -> Usuario:
    if user.tipo not in ("municipalidad", "admin"):
        raise ForbiddenError("Se requiere rol municipalidad o admin.")
    return user


def current_user_municipal_de_comuna(comuna_id: int):
    """Factory: exige ser funcionario de esa comuna. El admin NO bypasea
    este check — para acciones admin-cross-comuna usar `current_user_admin`
    o `current_user_municipal_o_admin` y resolver la comuna en el use case.
    """
    async def _dep(user: Usuario = Depends(current_user_municipal)) -> Usuario:
        if user.comuna_id != comuna_id:
            raise ComunaMismatchError(
                f"Solo funcionarios de la comuna {comuna_id} pueden realizar esta acción."
            )
        return user
    return _dep
