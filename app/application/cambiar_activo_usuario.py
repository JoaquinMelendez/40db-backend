"""Use case: activar/desactivar un usuario (soft-disable).

Reglas (api.md §4.21):
- Solo admin lo invoca (guard en la dependency).
- Admin no puede desactivarse a sí mismo (id == current_user.id).
- Un usuario inactivo no puede autenticarse: `current_user` devuelve 401
  cuando `usuario.activo = false`.
"""
from app.domain.entities import Usuario
from app.domain.errors import UsuarioNotFoundError, ValidationError
from app.infrastructure.db.usuario_repo import UsuarioRepository


class CannotDeactivateSelfError(ValidationError):
    code = "cannot_deactivate_self"
    http_status = 422


def cambiar_activo_usuario(
    *,
    actor: Usuario,
    target_id: str,
    activo: bool,
) -> Usuario:
    if target_id == actor.id and not activo:
        raise CannotDeactivateSelfError(
            "Un admin no puede desactivarse a sí mismo."
        )

    repo = UsuarioRepository()
    target = repo.get_by_id(target_id)
    if target is None:
        raise UsuarioNotFoundError(f"Usuario {target_id} no encontrado.")

    updated = repo.set_activo(target_id, activo)
    if updated is None:
        raise UsuarioNotFoundError(f"Usuario {target_id} no encontrado.")
    return updated
