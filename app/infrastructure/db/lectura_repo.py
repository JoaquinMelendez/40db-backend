import logging
from datetime import datetime, timedelta, timezone

from app.core.supabase_client import get_supabase

log = logging.getLogger(__name__)

# Ventana cubierta por mv_heatmap_celda_bucket (bbdd.md §13.3).
MATVIEW_HEATMAP_VENTANA = timedelta(days=7)
# Bucket fijo de la matview (5 min). Para otros buckets cae al RPC.
MATVIEW_HEATMAP_BUCKET_MIN = 5


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
    ) -> tuple[list[dict], str]:
        """Agrega lecturas por celda + bucket temporal.

        Devuelve (rows, fuente) donde fuente ∈ {"matview", "rpc"}. Si la query
        encaja en la ventana cubierta por `mv_heatmap_celda_bucket` (bucket=5
        min, ambos timestamps dentro de los últimos 7 días) se sirve desde la
        matview — orden de magnitud más rápido. En el resto de los casos se
        invoca el RPC `heatmap_agregado` (bbdd.md §5.4).
        """
        if self._matview_aplica(time_start, time_end, bucket_minutes):
            try:
                rows = self._heatmap_desde_matview(
                    min_lng, min_lat, max_lng, max_lat, time_start, time_end
                )
                return rows, "matview"
            except Exception as e:
                # Fallback graceful: si el adapter de matview falla, caer al
                # RPC en vez de devolver error al usuario.
                log.warning("Matview heatmap falló, fallback a RPC: %s", e)

        return self._heatmap_desde_rpc(
            min_lng, min_lat, max_lng, max_lat,
            time_start, time_end, bucket_minutes, grid_size_deg,
        ), "rpc"

    def _matview_aplica(self, time_start: str, time_end: str, bucket_minutes: int) -> bool:
        if bucket_minutes != MATVIEW_HEATMAP_BUCKET_MIN:
            return False
        try:
            ts = datetime.fromisoformat(time_start.replace("Z", "+00:00"))
        except ValueError:
            return False
        # La matview contiene buckets de los últimos 7 días al momento del
        # último REFRESH. Ser un poco más estricto que esto (margen de 1h) para
        # cubrir el caso de que el cron de refresh se haya saltado un ciclo.
        umbral = datetime.now(timezone.utc) - MATVIEW_HEATMAP_VENTANA + timedelta(hours=1)
        return ts >= umbral

    def _heatmap_desde_matview(
        self,
        min_lng: float, min_lat: float, max_lng: float, max_lat: float,
        time_start: str, time_end: str,
    ) -> list[dict]:
        # Margen de medio paso de grilla para incluir celdas cuyos centros
        # caen justo en el borde del bbox (el RPC filtra por sensor.coords;
        # la matview ya colapsó esa info en lng_cell/lat_cell).
        margen = 0.001 / 2
        result = (
            self._db.table("mv_heatmap_celda_bucket")
            .select("lng_cell, lat_cell, bucket_start, nivel_db_avg, nivel_db_max, lectura_count")
            .gte("lng_cell", min_lng - margen)
            .lte("lng_cell", max_lng + margen)
            .gte("lat_cell", min_lat - margen)
            .lte("lat_cell", max_lat + margen)
            .gte("bucket_start", time_start)
            .lt("bucket_start", time_end)
            .order("bucket_start")
            .order("lat_cell")
            .order("lng_cell")
            .execute()
        )
        return result.data or []

    def _heatmap_desde_rpc(
        self,
        min_lng: float, min_lat: float, max_lng: float, max_lat: float,
        time_start: str, time_end: str, bucket_minutes: int, grid_size_deg: float,
    ) -> list[dict]:
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
