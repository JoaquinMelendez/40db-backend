from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


class ReporteArchivoAdminResponse(BaseModel):
    id: str
    nombre: str
    tipo: Literal["pdf", "csv", "imagen"]
    mime_type: str
    tamano_bytes: int
    generado_por_id: str
    generado_por_nombre: Optional[str] = None
    rango_desde: Optional[datetime] = None
    rango_hasta: Optional[datetime] = None
    created_at: datetime


class ListaArchivosResponse(BaseModel):
    data: list[ReporteArchivoAdminResponse]
    next_cursor: Optional[str] = None


class ArchivoDescargaResponse(BaseModel):
    """Devuelve una signed URL temporal para que el front descargue el archivo
    directamente desde Supabase Storage sin que el backend haga proxy del binario.
    """
    url: str
    expires_in_seconds: int = Field(ge=1)
