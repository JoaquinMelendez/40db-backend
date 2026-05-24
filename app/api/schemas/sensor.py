from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class SensorResponse(BaseModel):
    id: str
    nombre: str
    comuna_id: int
    comuna_nombre: Optional[str] = None
    latitud: float
    longitud: float
    activo: bool
    estado_salud: Optional[str] = None
    ultima_lectura_at: Optional[datetime] = None
    ultima_lectura_db: Optional[float] = None
    created_at: Optional[datetime] = None


class ListaSensoresResponse(BaseModel):
    data: list[SensorResponse]
    next_cursor: Optional[str] = None


class ResumenSensoresResponse(BaseModel):
    total: int
    online: int
    intermitente: int
    offline: int
    sin_lecturas: int
    calculado_at: Optional[datetime] = None


class CrearSensorRequest(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    comuna_id: int
    latitud: float = Field(ge=-90, le=90)
    longitud: float = Field(ge=-180, le=180)


class ActualizarSensorRequest(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=3, max_length=120)
    latitud: Optional[float] = Field(default=None, ge=-90, le=90)
    longitud: Optional[float] = Field(default=None, ge=-180, le=180)
    activo: Optional[bool] = None

    @model_validator(mode="after")
    def _al_menos_uno(self) -> "ActualizarSensorRequest":
        if all(v is None for v in (self.nombre, self.latitud, self.longitud, self.activo)):
            raise ValueError("Debés enviar al menos un campo para actualizar.")
        return self


class DesactivarSensorResponse(BaseModel):
    id: str
    activo: bool
    estado_salud: Optional[str] = None
