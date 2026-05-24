from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from app.core.config import settings

router = APIRouter(prefix="/heatmaps", tags=["heatmaps"])


@router.get("")
async def heatmap(
    bbox: str = Query(..., description="minLng,minLat,maxLng,maxLat"),
    time_start: str = Query(...),
    time_end: str = Query(...),
    bucket_minutes: int = Query(5),
):
    from app.domain.errors import ValidationError as DomainValidationError

    # Parsear bbox
    try:
        parts = [float(x) for x in bbox.split(",")]
        assert len(parts) == 4
        min_lng, min_lat, max_lng, max_lat = parts
    except Exception:
        raise DomainValidationError("bbox debe tener formato minLng,minLat,maxLng,maxLat.")

    from app.application.obtener_heatmap import obtener_heatmap
    rows, fuente = obtener_heatmap(
        min_lng=min_lng, min_lat=min_lat,
        max_lng=max_lng, max_lat=max_lat,
        time_start=time_start, time_end=time_end,
        bucket_minutes=bucket_minutes,
    )

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["lng_cell"], row["lat_cell"]],
            },
            "properties": {
                "nivel_db_avg": float(row["nivel_db_avg"]),
                "nivel_db_max": float(row["nivel_db_max"]),
                "lectura_count": row["lectura_count"],
                "bucket_start": row["bucket_start"],
            },
        })

    return JSONResponse({
        "type": "FeatureCollection",
        "metadata": {
            "bucket_minutes": bucket_minutes,
            "grid_size_deg": settings.heatmap_grid_size_deg,
            "total_cells": len(features),
            "fuente": fuente,
        },
        "features": features,
    })
