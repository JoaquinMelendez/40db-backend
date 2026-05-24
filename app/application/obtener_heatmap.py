from app.core.config import settings
from app.domain.errors import ValidationError

BUCKET_MINUTES_PERMITIDOS = {1, 5, 15, 60}


def obtener_heatmap(
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    time_start: str,
    time_end: str,
    bucket_minutes: int,
) -> tuple[list[dict], str]:
    """Devuelve (rows, fuente). fuente ∈ {"matview","rpc"} — ver lectura_repo."""
    from datetime import datetime, timezone

    if bucket_minutes not in BUCKET_MINUTES_PERMITIDOS:
        raise ValidationError(f"bucket_minutes debe ser uno de {sorted(BUCKET_MINUTES_PERMITIDOS)}.")

    ts = datetime.fromisoformat(time_start.replace("Z", "+00:00"))
    te = datetime.fromisoformat(time_end.replace("Z", "+00:00"))
    delta_days = (te - ts).total_seconds() / 86400
    if delta_days <= 0:
        raise ValidationError("time_end debe ser posterior a time_start.")
    if delta_days > settings.heatmap_max_window_days:
        raise ValidationError(f"La ventana no puede superar {settings.heatmap_max_window_days} días.")

    from app.infrastructure.db.lectura_repo import LecturaRepository
    repo = LecturaRepository()
    return repo.heatmap(
        min_lng=min_lng,
        min_lat=min_lat,
        max_lng=max_lng,
        max_lat=max_lat,
        time_start=time_start,
        time_end=time_end,
        bucket_minutes=bucket_minutes,
        grid_size_deg=settings.heatmap_grid_size_deg,
    )
