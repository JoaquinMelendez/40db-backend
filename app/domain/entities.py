from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Usuario:
    id: str
    nombre: str
    tipo: str                    # 'ciudadano' | 'municipalidad'
    activo: bool
    telefono: Optional[str] = None
    comuna_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Sensor:
    id: str
    comuna_id: int
    nombre: str
    latitud: float
    longitud: float
    activo: bool


@dataclass
class Lectura:
    id: int
    sensor_id: str
    nivel_db: float
    timestamp_medicion: datetime


@dataclass
class EvidenciaIot:
    lectura_id: int
    sensor_id: str
    sensor_nombre: str
    nivel_db: float
    distancia_metros: float
    timestamp_medicion: datetime


@dataclass
class Reporte:
    id: str
    usuario_id: str
    comuna_id: int
    titulo: str
    descripcion: str
    latitud: float
    longitud: float
    estado_actual: Optional[str] = None
    lectura_evidencia_id: Optional[int] = None
    lectura_evidencia: Optional[EvidenciaIot] = None
    atendido_por_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
