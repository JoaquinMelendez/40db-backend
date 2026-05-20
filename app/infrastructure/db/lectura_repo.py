import logging
from app.core.supabase_client import get_supabase

log = logging.getLogger(__name__)


class LecturaRepository:
    def __init__(self):
        self._db = get_supabase()

    def insert(self, sensor_id: str, nivel_db: float, timestamp_medicion: str) -> None:
        """Inserta una lectura. ON CONFLICT DO NOTHING (idempotencia QoS 1)."""
        try:
            self._db.table("lectura").upsert(
                {
                    "sensor_id": sensor_id,
                    "nivel_db": nivel_db,
                    "timestamp_medicion": timestamp_medicion,
                },
                on_conflict="sensor_id,timestamp_medicion",
                ignore_duplicates=True,
            ).execute()
        except Exception as e:
            from app.domain.errors import ExternalServiceError
            raise ExternalServiceError(f"Error al insertar lectura: {e}") from e

    def heatmap(
        self,
        min_lng: float,
        min_lat: float,
        max_lng: float,
        max_lat: float,
        time_start: str,
        time_end: str,
        bucket_minutes: int,
        grid_size_deg: float,
    ) -> list[dict]:
        """Agrega lecturas por celda + bucket temporal (bbdd.md §5.4).
        Implementado como función Postgres (heatmap_agregado) para usar con rpc().
        """
        try:
            result = self._db.rpc(
                "heatmap_agregado",
                {
                    "p_min_lng": min_lng,
                    "p_min_lat": min_lat,
                    "p_max_lng": max_lng,
                    "p_max_lat": max_lat,
                    "p_time_start": time_start,
                    "p_time_end": time_end,
                    "p_bucket_minutes": bucket_minutes,
                    "p_grid_size_deg": grid_size_deg,
                },
            ).execute()
            return result.data or []
        except Exception as e:
            from app.domain.errors import ExternalServiceError
            raise ExternalServiceError(f"Error en heatmap: {e}") from e
