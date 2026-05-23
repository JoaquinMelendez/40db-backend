import base64, json
from typing import Optional
from app.core.supabase_client import get_supabase
from app.domain.entities import Reporte, EvidenciaIot


def _row_to_reporte(row: dict) -> Reporte:
    evidencia = None
    if row.get("lectura_evidencia_id") and row.get("lectura"):
        l = row["lectura"]
        evidencia = EvidenciaIot(
            lectura_id=l["id"],
            sensor_id=l["sensor_id"],
            sensor_nombre=l.get("sensor", {}).get("nombre", ""),
            nivel_db=float(l["nivel_db"]),
            distancia_metros=0.0,   # no disponible en SELECT simple
            timestamp_medicion=l["timestamp_medicion"],
        )
    return Reporte(
        id=row["id"],
        usuario_id=row["usuario_id"],
        comuna_id=row["comuna_id"],
        titulo=row["titulo"],
        descripcion=row["descripcion"],
        latitud=float(row["latitud"]),
        longitud=float(row["longitud"]),
        lectura_evidencia_id=row.get("lectura_evidencia_id"),
        lectura_evidencia=evidencia,
        atendido_por_id=row.get("atendido_por_id"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _encode_cursor(created_at: str, id: str) -> str:
    return base64.b64encode(json.dumps({"created_at": created_at, "id": id}).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    data = json.loads(base64.b64decode(cursor).decode())
    return data["created_at"], data["id"]


# PostgREST resuelve embeds por nombre de FK constraint cuando el FK es compuesto
# (lectura_evidencia_id, lectura_evidencia_timestamp) — D8 / ADR 08. La sintaxis
# `target!constraint_name(...)` es obligatoria; usar el nombre de columna como hint
# (la forma original `lectura:lectura_evidencia_id(...)`) deja de funcionar porque
# esa columna ya no es FK por sí sola.
SELECT_REPORTE = (
    "*, "
    "lectura:lectura!fk_reporte_lectura_evidencia(id, sensor_id, nivel_db, timestamp_medicion, "
    "sensor:sensor_id(nombre))"
)


class ReporteRepository:
    def __init__(self):
        self._db = get_supabase()

    def get_by_id(self, reporte_id: str) -> Optional[Reporte]:
        result = self._db.table("reporte").select(SELECT_REPORTE).eq("id", reporte_id).maybe_single().execute()
        if not result.data:
            return None
        r = _row_to_reporte(result.data)
        r.estado_actual = self._get_estado_actual(reporte_id)
        r.historial = self._get_historial(reporte_id)
        return r

    def list_by_usuario(
        self, usuario_id: str, limit: int, cursor: Optional[str], estado: Optional[str]
    ) -> tuple[list[Reporte], Optional[str]]:
        q = (
            self._db.table("reporte")
            .select("id, titulo, created_at, comuna_id, lectura_evidencia_id")
            .eq("usuario_id", usuario_id)
            .order("created_at", desc=True)
            .order("id", desc=True)
            .limit(limit + 1)
        )
        if cursor:
            ca, rid = _decode_cursor(cursor)
            q = q.lt("created_at", ca)

        rows = q.execute().data or []
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last["created_at"], last["id"])

        reportes = []
        for row in rows:
            estado_actual = self._get_estado_actual(row["id"])
            if estado and estado_actual != estado:
                continue
            reportes.append(Reporte(
                id=row["id"],
                usuario_id=usuario_id,
                comuna_id=row["comuna_id"],
                titulo=row["titulo"],
                descripcion="",
                latitud=0, longitud=0,
                estado_actual=estado_actual,
                lectura_evidencia_id=row.get("lectura_evidencia_id"),
                created_at=row.get("created_at"),
            ))
        return reportes, next_cursor

    def list_by_comuna(
        self, comuna_id: int, limit: int, cursor: Optional[str], estado: Optional[str]
    ) -> tuple[list[Reporte], Optional[str]]:
        q = (
            self._db.table("reporte")
            .select("id, titulo, usuario_id, created_at, lectura_evidencia_id")
            .eq("comuna_id", comuna_id)
            .order("created_at", desc=True)
            .order("id", desc=True)
            .limit(limit + 1)
        )
        if cursor:
            ca, rid = _decode_cursor(cursor)
            q = q.lt("created_at", ca)

        rows = q.execute().data or []
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last["created_at"], last["id"])

        reportes = []
        for row in rows:
            estado_actual = self._get_estado_actual(row["id"])
            if estado and estado_actual != estado:
                continue
            reportes.append(Reporte(
                id=row["id"],
                usuario_id=row["usuario_id"],
                comuna_id=comuna_id,
                titulo=row["titulo"],
                descripcion="",
                latitud=0, longitud=0,
                estado_actual=estado_actual,
                lectura_evidencia_id=row.get("lectura_evidencia_id"),
                created_at=row.get("created_at"),
            ))
        return reportes, next_cursor

    def get_historial(self, reporte_id: str) -> list[dict]:
        return self._get_historial(reporte_id)

    def cambiar_estado(
        self,
        reporte_id: str,
        tipo_estado_id: int,
        usuario_id: str,
        comentario: Optional[str],
        atendido_por_id: Optional[str] = None,
    ) -> None:
        from app.domain.errors import ExternalServiceError
        try:
            self._db.table("historial_estado").insert({
                "reporte_id": reporte_id,
                "tipo_estado_id": tipo_estado_id,
                "usuario_id": usuario_id,
                "comentario": comentario,
            }).execute()
            if atendido_por_id:
                self._db.table("reporte").update(
                    {"atendido_por_id": atendido_por_id}
                ).eq("id", reporte_id).execute()
        except Exception as e:
            raise ExternalServiceError(f"Error al cambiar estado: {e}") from e

    def _get_estado_actual(self, reporte_id: str) -> Optional[str]:
        result = (
            self._db.table("historial_estado")
            .select("tipo_estado:tipo_estado_id(nombre)")
            .eq("reporte_id", reporte_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["tipo_estado"]["nombre"]
        return None

    def _get_historial(self, reporte_id: str) -> list[dict]:
        result = (
            self._db.table("historial_estado")
            .select("comentario, created_at, tipo_estado:tipo_estado_id(nombre), usuario:usuario_id(id, nombre)")
            .eq("reporte_id", reporte_id)
            .order("created_at")
            .execute()
        )
        historial = []
        for row in (result.data or []):
            historial.append({
                "estado": row["tipo_estado"]["nombre"],
                "comentario": row.get("comentario"),
                "created_at": row["created_at"],
                "usuario": row.get("usuario"),
            })
        return historial
