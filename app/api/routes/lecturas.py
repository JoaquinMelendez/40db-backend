from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import current_user_municipal_o_admin
from app.api.schemas.lectura import ResumenHorarioItem, ResumenHorarioResponse
from app.application.obtener_resumen_horario import obtener_resumen_horario
from app.domain.entities import Usuario
from app.domain.errors import ValidationError

router = APIRouter(prefix="/lecturas", tags=["lecturas"])


def _parse_iso(name: str, value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"{name} debe ser ISO 8601 (ej. 2026-05-17T00:00:00Z).")


@router.get("/resumen", response_model=ResumenHorarioResponse)
async def resumen_horario_endpoint(
    sensor_id: str = Query(...),
    desde: str = Query(..., description="ISO 8601"),
    hasta: str = Query(..., description="ISO 8601"),
    actor: Usuario = Depends(current_user_municipal_o_admin),
):
    desde_dt = _parse_iso("desde", desde)
    hasta_dt = _parse_iso("hasta", hasta)

    data = obtener_resumen_horario(
        actor=actor,
        sensor_id=sensor_id,
        desde=desde_dt,
        hasta=hasta_dt,
    )

    return ResumenHorarioResponse(
        sensor_id=data["sensor_id"],
        sensor_nombre=data["sensor_nombre"],
        desde=data["desde"],
        hasta=data["hasta"],
        horas=[
            ResumenHorarioItem(
                hora=r.hora,
                avg_db=r.avg_db,
                min_db=r.min_db,
                max_db=r.max_db,
                p95_db=r.p95_db,
                n_lecturas=r.n_lecturas,
            )
            for r in data["horas"]
        ],
        refrescado_at=data["refrescado_at"],
    )
