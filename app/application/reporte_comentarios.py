"""Use cases para comentarios sobre un reporte (api.md §4.28 / §4.29).

Reglas de autorización:
- Escribir (interno y externo): municipalidad de la comuna del reporte, o admin.
- Leer:
    * dueño del reporte (ciudadano) → solo externos.
    * municipalidad de la comuna → ambos.
    * admin → ambos.
    * cualquier otro → ForbiddenError.
"""

from typing import Optional
from datetime import datetime

from app.domain.entities import Usuario
from app.domain.errors import (
    ReporteNotFoundError, ForbiddenError, ComunaMismatchError, ValidationError,
)


def _cargar_reporte_o_404(reporte_id: str):
    from app.infrastructure.db.reporte_repo import ReporteRepository
    reporte = ReporteRepository().get_by_id(reporte_id)
    if reporte is None:
        raise ReporteNotFoundError(f"Reporte {reporte_id} no encontrado.")
    return reporte


def _exigir_funcionario_de_comuna(usuario: Usuario, comuna_id: int) -> None:
    if usuario.tipo == "admin":
        return
    if usuario.tipo != "municipalidad":
        raise ForbiddenError("Solo municipalidad o admin pueden comentar este reporte.")
    if usuario.comuna_id != comuna_id:
        raise ComunaMismatchError(
            "Solo funcionarios de la misma comuna pueden comentar este reporte."
        )


def agregar_comentario(
    reporte_id: str,
    usuario: Usuario,
    visibilidad: str,
    cuerpo: str,
    delegado_a_id: Optional[str],
    delegado_at: Optional[datetime],
) -> dict:
    from app.infrastructure.db.reporte_comentario_repo import ReporteComentarioRepository
    from app.infrastructure.db.usuario_repo import UsuarioRepository

    reporte = _cargar_reporte_o_404(reporte_id)
    _exigir_funcionario_de_comuna(usuario, reporte.comuna_id)

    # Validar delegación: schema ya garantizó coherencia (pair + visibilidad).
    # Acá validamos que el destinatario exista y sea municipalidad.
    if delegado_a_id is not None:
        destino = UsuarioRepository().get_by_id(delegado_a_id)
        if destino is None:
            raise ValidationError(f"Usuario {delegado_a_id} no existe.")
        if destino.tipo != "municipalidad":
            raise ValidationError("El usuario delegado debe ser de tipo 'municipalidad'.")

    return ReporteComentarioRepository().crear(
        reporte_id=reporte_id,
        autor_id=usuario.id,
        visibilidad=visibilidad,
        cuerpo=cuerpo,
        delegado_a_id=delegado_a_id,
        delegado_at=delegado_at,
    )


def listar_comentarios(reporte_id: str, usuario: Usuario) -> list[dict]:
    from app.infrastructure.db.reporte_comentario_repo import ReporteComentarioRepository

    reporte = _cargar_reporte_o_404(reporte_id)
    solo_externos = _resolver_filtro_visibilidad(usuario, reporte)
    return ReporteComentarioRepository().listar_por_reporte(
        reporte_id, solo_externos=solo_externos
    )


def _resolver_filtro_visibilidad(usuario: Usuario, reporte) -> bool:
    """Devuelve True si el caller solo puede ver externos.

    Levanta ForbiddenError si no puede ver ningún comentario.
    """
    if usuario.tipo == "admin":
        return False
    if usuario.tipo == "municipalidad" and usuario.comuna_id == reporte.comuna_id:
        return False
    if usuario.id == reporte.usuario_id:
        return True
    raise ForbiddenError("No tenés permiso para ver los comentarios de este reporte.")
