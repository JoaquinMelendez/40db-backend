from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional
from datetime import datetime


class UsuarioRef(BaseModel):
    id: str
    nombre: str


class CrearComentarioRequest(BaseModel):
    """POST /reportes/{id}/comentarios

    Reglas (espejo del CHECK chk_delegacion_pair de la DB):
    - `delegado_a_id` y `delegado_at` van juntos o ninguno.
    - Si hay delegación, la visibilidad debe ser 'interno'.
    """
    visibilidad: Literal["interno", "externo"]
    cuerpo: str = Field(min_length=1, max_length=2000)
    delegado_a_id: Optional[str] = None
    delegado_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _validar_delegacion(self):
        cuerpo_trim = (self.cuerpo or "").strip()
        if not cuerpo_trim:
            raise ValueError("cuerpo no puede ser solo espacios")
        # Reasignar el cuerpo ya trimeado simplifica al repo aguas abajo.
        object.__setattr__(self, "cuerpo", cuerpo_trim)

        tiene_id = self.delegado_a_id is not None
        tiene_at = self.delegado_at is not None
        if tiene_id != tiene_at:
            raise ValueError("delegado_a_id y delegado_at deben ir juntos o ninguno")
        if tiene_id and self.visibilidad != "interno":
            raise ValueError("La delegación solo aplica a comentarios internos")
        return self


class ComentarioResponse(BaseModel):
    id: int
    visibilidad: Literal["interno", "externo"]
    cuerpo: str
    autor: UsuarioRef
    delegado_a: Optional[UsuarioRef] = None
    delegado_at: Optional[datetime] = None
    created_at: datetime


class ListaComentariosResponse(BaseModel):
    data: list[ComentarioResponse]
