from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


class UsuarioResponse(BaseModel):
    id: str
    nombre: str
    telefono: Optional[str] = None
    tipo: str
    comuna_id: Optional[int] = None
    comuna_nombre: Optional[str] = None
    activo: bool
    email: Optional[str] = None
    created_at: Optional[datetime] = None


class ActualizarUsuarioRequest(BaseModel):
    telefono: Optional[str] = Field(None, pattern=r"^\+?[0-9]{7,15}$")
    comuna_id: Optional[int] = None


class ListaUsuariosResponse(BaseModel):
    data: list[UsuarioResponse]
    next_cursor: Optional[str] = None


class CambiarActivoRequest(BaseModel):
    activo: bool


class PromoverUsuarioRequest(BaseModel):
    nuevo_tipo: Literal["ciudadano", "municipalidad", "admin"]
    comuna_id: Optional[int] = None
