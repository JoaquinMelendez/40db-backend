"""Use case: listar usuarios (admin, api.md §4.20)."""
from typing import Optional

from app.core.supabase_client import get_supabase
from app.domain.entities import Usuario
from app.infrastructure.db.usuario_repo import UsuarioRepository


def listar_usuarios(
    *,
    tipo: Optional[str],
    comuna_id: Optional[int],
    activo: Optional[bool],
    q: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> tuple[list[Usuario], Optional[str], dict[int, str]]:
    """Devuelve (usuarios, next_cursor, comuna_nombres) — el route enriquece."""
    usuarios, next_cursor = UsuarioRepository().listar(
        tipo=tipo,
        comuna_id=comuna_id,
        activo=activo,
        q=q,
        limit=limit,
        cursor=cursor,
    )

    comuna_ids = {u.comuna_id for u in usuarios if u.comuna_id is not None}
    nombres: dict[int, str] = {}
    if comuna_ids:
        db = get_supabase()
        r = db.table("comuna").select("id, nombre").in_("id", list(comuna_ids)).execute()
        nombres = {row["id"]: row["nombre"] for row in (r.data or [])}
    return usuarios, next_cursor, nombres
