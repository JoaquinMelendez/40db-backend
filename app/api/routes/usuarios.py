from fastapi import APIRouter, Depends
from app.api.deps import current_user
from app.domain.entities import Usuario
from app.domain.errors import ValidationError
from app.api.schemas.usuario import UsuarioResponse, ActualizarUsuarioRequest

router = APIRouter(prefix="/usuarios", tags=["usuarios"])


def _enrich_usuario(usuario: Usuario) -> UsuarioResponse:
    comuna_nombre = None
    if usuario.comuna_id:
        from app.core.supabase_client import get_supabase
        r = get_supabase().table("comuna").select("nombre").eq("id", usuario.comuna_id).maybe_single().execute()
        if r.data:
            comuna_nombre = r.data["nombre"]
    return UsuarioResponse(
        id=usuario.id,
        nombre=usuario.nombre,
        telefono=usuario.telefono,
        tipo=usuario.tipo,
        comuna_id=usuario.comuna_id,
        comuna_nombre=comuna_nombre,
        activo=usuario.activo,
    )


@router.get("/me", response_model=UsuarioResponse)
async def get_me(usuario: Usuario = Depends(current_user)):
    return _enrich_usuario(usuario)


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
    return _enrich_usuario(updated)
