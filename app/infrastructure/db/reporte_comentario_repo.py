from typing import Optional
from datetime import datetime
from app.core.supabase_client import get_supabase


# PostgREST embed: traemos autor y delegado_a como mini-objetos {id, nombre}.
# Notar los `!` con el nombre del FK constraint NO son necesarios acá porque
# `autor_id` y `delegado_a_id` son FKs simples (no compuestas como las del
# reporte → lectura).
SELECT_COMENTARIO = (
    "id, visibilidad, cuerpo, delegado_at, created_at, "
    "autor:autor_id(id, nombre), "
    "delegado_a:delegado_a_id(id, nombre)"
)


def _row_to_comentario(row: dict) -> dict:
    """Mapea la fila de PostgREST al shape del schema ComentarioResponse."""
    return {
        "id": row["id"],
        "visibilidad": row["visibilidad"],
        "cuerpo": row["cuerpo"],
        "autor": row.get("autor"),
        "delegado_a": row.get("delegado_a"),
        "delegado_at": row.get("delegado_at"),
        "created_at": row["created_at"],
    }


class ReporteComentarioRepository:
    def __init__(self):
        self._db = get_supabase()

    def crear(
        self,
        reporte_id: str,
        autor_id: str,
        visibilidad: str,
        cuerpo: str,
        delegado_a_id: Optional[str] = None,
        delegado_at: Optional[datetime] = None,
    ) -> dict:
        from app.domain.errors import ExternalServiceError
        payload = {
            "reporte_id": reporte_id,
            "autor_id": autor_id,
            "visibilidad": visibilidad,
            "cuerpo": cuerpo,
            "delegado_a_id": delegado_a_id,
            "delegado_at": delegado_at.isoformat() if delegado_at else None,
        }
        try:
            result = (
                self._db.table("reporte_comentario")
                .insert(payload)
                .execute()
            )
            inserted_id = result.data[0]["id"]
            row = (
                self._db.table("reporte_comentario")
                .select(SELECT_COMENTARIO)
                .eq("id", inserted_id)
                .single()
                .execute()
                .data
            )
            return _row_to_comentario(row)
        except Exception as e:
            raise ExternalServiceError(f"Error al crear comentario: {e}") from e

    def listar_por_reporte(
        self,
        reporte_id: str,
        solo_externos: bool = False,
    ) -> list[dict]:
        """Lista comentarios ordenados por created_at ASC.

        Si `solo_externos`, filtra a visibilidad='externo' (caller = dueño
        ciudadano). El use case decide el flag según el rol del caller.
        """
        from app.domain.errors import ExternalServiceError
        try:
            q = (
                self._db.table("reporte_comentario")
                .select(SELECT_COMENTARIO)
                .eq("reporte_id", reporte_id)
                .order("created_at")
            )
            if solo_externos:
                q = q.eq("visibilidad", "externo")
            rows = q.execute().data or []
        except Exception as e:
            raise ExternalServiceError(f"Error al listar comentarios: {e}") from e
        return [_row_to_comentario(r) for r in rows]
