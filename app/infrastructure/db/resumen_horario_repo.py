"""Repositorio del rollup horario (lectura_resumen_horaria).

La tabla la refresca pg_cron cada hora (bbdd.md §13). Acá solo leemos.
"""
from datetime import datetime
from typing import Optional

from app.core.supabase_client import get_supabase
from app.domain.entities import ResumenHorario
from app.domain.errors import ExternalServiceError


def _parse_ts(value) -> datetime:
    """Supabase devuelve timestamptz como string ISO 8601."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _row_to_resumen(row: dict) -> ResumenHorario:
    return ResumenHorario(
        sensor_id=row["sensor_id"],
        hora=_parse_ts(row["hora"]),
        avg_db=float(row["avg_db"]),
        min_db=float(row["min_db"]),
        max_db=float(row["max_db"]),
        p95_db=float(row["p95_db"]),
        n_lecturas=int(row["n_lecturas"]),
        refrescado_at=_parse_ts(row["refrescado_at"]),
    )


class ResumenHorarioRepository:
    def __init__(self):
        self._db = get_supabase()

    def listar(
        self,
        sensor_id: str,
        desde: datetime,
        hasta: datetime,
    ) -> list[ResumenHorario]:
        """Lee filas en [desde, hasta) ordenadas por hora asc.

        `desde` y `hasta` se pasan como ISO 8601. La tabla está indexada por
        (sensor_id, hora DESC) — la query es un range scan barato.
        """
        try:
            result = (
                self._db.table("lectura_resumen_horaria")
                .select("sensor_id, hora, avg_db, min_db, max_db, p95_db, n_lecturas, refrescado_at")
                .eq("sensor_id", sensor_id)
                .gte("hora", desde.isoformat())
                .lt("hora", hasta.isoformat())
                .order("hora", desc=False)
                .execute()
            )
        except Exception as e:
            raise ExternalServiceError(f"Error leyendo lectura_resumen_horaria: {e}") from e

        return [_row_to_resumen(r) for r in (result.data or [])]

    def max_refrescado_at(self, filas: list[ResumenHorario]) -> Optional[datetime]:
        if not filas:
            return None
        return max(f.refrescado_at for f in filas)
