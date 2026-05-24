from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import current_user, current_user_admin
from app.api.schemas.usuario import (
    ActualizarUsuarioRequest,
    CambiarActivoRequest,
    ListaUsuariosResponse,
    PromoverUsuarioRequest,
    UsuarioResponse,
)
from app.domain.entities import Usuario
from app.domain.errors import ValidationError

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


def _comuna_nombre(comuna_id: Optional[int]) -> Optional[str]:
    if comuna_id is None:
        return None
    from app.core.supabase_client import get_supabase
    r = get_supabase().table("comuna").select("nombre").eq("id", comuna_id).maybe_single().execute()
    return r.data["nombre"] if r.data else None


def _to_response(usuario: Usuario, comuna_nombre: Optional[str] = None) -> UsuarioResponse:
    return UsuarioResponse(
        id=usuario.id,
        nombre=usuario.nombre,
        telefono=usuario.telefono,
        tipo=usuario.tipo,
        comuna_id=usuario.comuna_id,
        comuna_nombre=comuna_nombre,
        activo=usuario.activo,
        email=usuario.email,
        created_at=usuario.created_at,
    )


@router.get("/me", response_model=UsuarioResponse)
async def get_me(usuario: Usuario = Depends(current_user)):
    return _to_response(usuario, comuna_nombre=_comuna_nombre(usuario.comuna_id))


@router.patch("/me", response_model=UsuarioResponse)
async def patch_me(
    body: ActualizarUsuarioRequest,
    usuario: Usuario = Depends(current_user),
):
    if body.telefono is None and body.comuna_id is None:
        raise ValidationError("Debés enviar al menos un campo para actualizar.")

    if body.comuna_id is not None:
        from app.core.supabase_client import get_supabase
        r = get_supabase().table("comuna").select("id").eq("id", body.comuna_id).maybe_single().execute()
        if not r.data:
            raise ValidationError(f"La comuna {body.comuna_id} no existe.")

    from app.infrastructure.db.usuario_repo import UsuarioRepository
    repo = UsuarioRepository()
    updated = repo.update_me(usuario.id, body.telefono, body.comuna_id)
    return _to_response(updated, comuna_nombre=_comuna_nombre(updated.comuna_id))


# ── Endpoints admin (api.md §4.20-§4.22) ─────────────────────────────────────


@router.get("", response_model=ListaUsuariosResponse)
async def listar_usuarios(
    tipo: Optional[str] = Query(None),
    comuna_id: Optional[int] = Query(None),
    activo: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    _: Usuario = Depends(current_user_admin),
):
    from app.application.listar_usuarios import listar_usuarios as _uc
    usuarios, next_cursor, comuna_nombres = _uc(
        tipo=tipo,
        comuna_id=comuna_id,
        activo=activo,
        q=q,
        limit=limit,
        cursor=cursor,
    )
    return ListaUsuariosResponse(
        data=[_to_response(u, comuna_nombre=comuna_nombres.get(u.comuna_id) if u.comuna_id else None) for u in usuarios],
        next_cursor=next_cursor,
    )


@router.patch("/{usuario_id}/activo", response_model=UsuarioResponse)
async def patch_activo(
    usuario_id: str,
    body: CambiarActivoRequest,
    actor: Usuario = Depends(current_user_admin),
):
    from app.application.cambiar_activo_usuario import cambiar_activo_usuario
    updated = cambiar_activo_usuario(actor=actor, target_id=usuario_id, activo=body.activo)
    return _to_response(updated, comuna_nombre=_comuna_nombre(updated.comuna_id))


@router.patch("/{usuario_id}/promover", response_model=UsuarioResponse)
async def patch_promover(
    usuario_id: str,
    body: PromoverUsuarioRequest,
    actor: Usuario = Depends(current_user_admin),
):
    from app.application.promover_usuario import promover_usuario
    updated = promover_usuario(
        actor=actor,
        target_id=usuario_id,
        nuevo_tipo=body.nuevo_tipo,
        comuna_id=body.comuna_id,
    )
    return _to_response(updated, comuna_nombre=_comuna_nombre(updated.comuna_id))
