import base64
import json
from datetime import datetime
from typing import Optional

from app.core.supabase_client import get_supabase
from app.domain.entities import ReporteArchivoAdmin
from app.domain.errors import ExternalServiceError


def _row_to_entity(row: dict, generado_por_nombre: Optional[str] = None) -> ReporteArchivoAdmin:
    return ReporteArchivoAdmin(
        id=row["id"],
        generado_por_id=row["generado_por_id"],
        nombre=row["nombre"],
        tipo=row["tipo"],
        mime_type=row["mime_type"],
        tamano_bytes=row["tamano_bytes"],
        object_path=row["object_path"],
        rango_desde=row.get("rango_desde"),
        rango_hasta=row.get("rango_hasta"),
        created_at=row.get("created_at"),
        generado_por_nombre=generado_por_nombre,
    )


def _encode_cursor(created_at: str, id: str) -> str:
    return base64.b64encode(
        json.dumps({"created_at": created_at, "id": id}).encode()
    ).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    data = json.loads(base64.b64decode(cursor).decode())
    return data["created_at"], data["id"]


class ReporteArchivoAdminRepository:
    def __init__(self):
        self._db = get_supabase()

    def insert(
        self,
        *,
        generado_por_id: str,
        nombre: str,
        tipo: str,
        mime_type: str,
        tamano_bytes: int,
        object_path: str,
        rango_desde: Optional[datetime],
        rango_hasta: Optional[datetime],
    ) -> ReporteArchivoAdmin:
        payload = {
            "generado_por_id": generado_por_id,
            "nombre": nombre,
            "tipo": tipo,
            "mime_type": mime_type,
            "tamano_bytes": tamano_bytes,
            "object_path": object_path,
            "rango_desde": rango_desde.isoformat() if rango_desde else None,
            "rango_hasta": rango_hasta.isoformat() if rango_hasta else None,
        }
        try:
            res = self._db.table("reporte_archivo_admin").insert(payload).execute()
        except Exception as e:
            raise ExternalServiceError(f"Error guardando metadata de archivo: {e}") from e
        return _row_to_entity(res.data[0])

    def get_by_id(self, archivo_id: str) -> Optional[ReporteArchivoAdmin]:
        try:
            res = (
                self._db.table("reporte_archivo_admin")
                .select("*")
                .eq("id", archivo_id)
                .maybe_single()
                .execute()
            )
            if not res or not res.data:
                return None
            return _row_to_entity(res.data)
        except Exception:
            return None

    def delete(self, archivo_id: str) -> None:
        try:
            self._db.table("reporte_archivo_admin").delete().eq("id", archivo_id).execute()
        except Exception as e:
            raise ExternalServiceError(f"Error eliminando metadata: {e}") from e

    def listar(
        self,
        *,
        tipo: Optional[str],
        generado_por_id: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> tuple[list[ReporteArchivoAdmin], Optional[str]]:
        try:
            query = (
                self._db.table("reporte_archivo_admin")
                .select("*")
                .order("created_at", desc=True)
                .order("id", desc=True)
                .limit(limit + 1)
            )
            if tipo is not None:
                query = query.eq("tipo", tipo)
            if generado_por_id is not None:
                query = query.eq("generado_por_id", generado_por_id)
            if cursor:
                ca, _ = _decode_cursor(cursor)
                query = query.lt("created_at", ca)
            rows = query.execute().data or []
        except Exception as e:
            raise ExternalServiceError(f"Error listando archivos: {e}") from e

        next_cursor: Optional[str] = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last["created_at"], last["id"])

        # Hidrato nombres del autor (N+1 acotado: max `limit` rows).
        autor_ids = list({r["generado_por_id"] for r in rows})
        nombres: dict[str, str] = {}
        if autor_ids:
            try:
                ures = (
                    self._db.table("usuario")
                    .select("id, nombre")
                    .in_("id", autor_ids)
                    .execute()
                )
                nombres = {u["id"]: u["nombre"] for u in (ures.data or [])}
            except Exception:
                nombres = {}

        entidades = [_row_to_entity(row, nombres.get(row["generado_por_id"])) for row in rows]
        return entidades, next_cursor
