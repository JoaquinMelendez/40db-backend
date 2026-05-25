from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class BuscarEvidenciaResponse(BaseModel):
    evidencia: Optional["EvidenciaSchema"]


class EvidenciaSchema(BaseModel):
    lectura_id: int
    sensor_id: str
    sensor_nombre: str
    nivel_db: float
    distancia_metros: float
    timestamp_medicion: datetime


class CrearReporteRequest(BaseModel):
    titulo: str = Field(min_length=3, max_length=120)
    descripcion: str = Field(min_length=10, max_length=2000)
    latitud: float = Field(ge=-90, le=90)
    longitud: float = Field(ge=-180, le=180)
    # api.md §4.5.1: cliente resuelve via Nominatim. Si viene, server valida
    # contra catalogo. Si no, fallback a usuario.comuna_id.
    comuna_id: Optional[int] = None
    lectura_evidencia_id: Optional[int] = None


class ReporteResumen(BaseModel):
    id: str
    titulo: str
    estado_actual: Optional[str]
    created_at: Optional[datetime]


class HistorialItem(BaseModel):
    estado: str
    comentario: Optional[str]
    created_at: datetime
    usuario: Optional[dict]


class ReporteDetalle(BaseModel):
    id: str
    usuario_id: str
    atendido_por_id: Optional[str]
    comuna_id: int
    titulo: str
    descripcion: str
    latitud: float
    longitud: float
    estado_actual: Optional[str]
    historial: Optional[list] = None
    # Filtrado según rol del caller (dueño ve solo externos; municipalidad/admin
    # ven ambos). El use case decide qué incluir. Detalle en api.md §4.8.
    comentarios: Optional[list] = None
    lectura_evidencia: Optional[EvidenciaSchema]
    created_at: Optional[datetime]


class ListaReportesResponse(BaseModel):
    data: list[ReporteResumen]
    next_cursor: Optional[str]


class CambiarEstadoRequest(BaseModel):
    nuevo_estado: str
    comentario: Optional[str] = None


BuscarEvidenciaResponse.model_rebuild()
