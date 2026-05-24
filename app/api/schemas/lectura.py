from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class ResumenHorarioItem(BaseModel):
    hora: datetime
    avg_db: float
    min_db: float
    max_db: float
    p95_db: float
    n_lecturas: int


class ResumenHorarioResponse(BaseModel):
    sensor_id: str
    sensor_nombre: str
    desde: datetime
    hasta: datetime
    horas: list[ResumenHorarioItem]
    fuente: Literal["lectura_resumen_horaria"] = "lectura_resumen_horaria"
    refrescado_at: Optional[datetime] = None
