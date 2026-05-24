"""Use case: promover/degradar a un usuario (cambio de tipo y/o comuna).

Reglas (auth.md §8.2):
- nuevo_tipo ∈ {'ciudadano', 'municipalidad', 'admin'}.
- nuevo_tipo='municipalidad' exige `comuna_id` válido.
- nuevo_tipo='admin' acepta `comuna_id` opcional (afinidad informativa).
- nuevo_tipo='ciudadano' NO modifica `comuna_id` (preserva la actual).
- Admin no puede degradarse a sí mismo (id == current_user.id).
"""
from typing import Optional

from app.core.supabase_client import get_supabase
from app.domain.entities import Usuario
from app.domain.errors import (
    UsuarioNotFoundError,
    ValidationError,
)
from app.infrastructure.db.usuario_repo import UsuarioRepository

TIPOS_VALIDOS = ("ciudadano", "municipalidad", "admin")


class CannotDemoteSelfError(ValidationError):
    code = "cannot_demote_self"
    http_status = 422


class ComunaIdRequiredError(ValidationError):
    code = "comuna_id_required"
    http_status = 422


class ComunaNotFoundError(ValidationError):
    code = "comuna_not_found"
    http_status = 422


class TipoInvalidoError(ValidationError):
    code = "tipo_invalido"
    http_status = 422


def promover_usuario(
    *,
    actor: Usuario,
    target_id: str,
    nuevo_tipo: str,
    comuna_id: Optional[int],
) -> Usuario:
    if nuevo_tipo not in TIPOS_VALIDOS:
        raise TipoInvalidoError(
            f"tipo invalido: {nuevo_tipo!r}. Esperado uno de {TIPOS_VALIDOS}."
        )

    # No self-demote: bloquea cualquier cambio sobre el propio admin que
    # implique perder el rol. Sin esta guard, un admin podría dejar la
    # plataforma sin admin por error (soft-lockout).
    if target_id == actor.id and nuevo_tipo != "admin":
        raise CannotDemoteSelfError(
            "Un admin no puede degradarse a sí mismo."
        )

    if nuevo_tipo == "municipalidad" and comuna_id is None:
        raise ComunaIdRequiredError(
            "comuna_id es obligatorio para nuevo_tipo='municipalidad'."
        )

    if comuna_id is not None:
        db = get_supabase()
        r = db.table("comuna").select("id").eq("id", comuna_id).maybe_single().execute()
        if not r.data:
            raise ComunaNotFoundError(f"comuna {comuna_id} no existe.")

    repo = UsuarioRepository()
    target = repo.get_by_id(target_id)
    if target is None:
        raise UsuarioNotFoundError(f"Usuario {target_id} no encontrado.")

    # Para 'ciudadano' se preserva la comuna actual; para los otros se
    # setea (o limpia, si admin viene con comuna_id=None).
    actualizar_comuna = nuevo_tipo != "ciudadano"
    updated = repo.promover(
        user_id=target_id,
        nuevo_tipo=nuevo_tipo,
        comuna_id=comuna_id,
        actualizar_comuna=actualizar_comuna,
    )
    if updated is None:
        raise UsuarioNotFoundError(f"Usuario {target_id} no encontrado.")
    return updated
