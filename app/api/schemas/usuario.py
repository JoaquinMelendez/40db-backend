from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class UsuarioResponse(BaseModel):
    id: str
    nombre: str
    telefono: Optional[str]
    tipo: str
    comuna_id: Optional[int]
    comuna_nombre: Optional[str] = None
    activo: bool
    created_at: Optional[datetime] = None


class ActualizarUsuarioRequest(BaseModel):
    telefono: Optional[str] = Field(None, pattern=r"^\+?[0-9]{7,15}$")
    comuna_id: Optional[int] = None
