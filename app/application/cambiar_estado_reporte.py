from typing import Optional
from app.domain.entities import Reporte, Usuario
from app.domain.errors import (
    ReporteNotFoundError, ComunaMismatchError,
    InvalidStateTransitionError, ValidationError,
)

# Máquina de estados (bbdd.md §7)
_TRANSICIONES_VALIDAS = {
    "En espera":   {"En atencion", "Descartado"},
    "En atencion": {"Atendido", "Descartado"},
    "Atendido":    set(),
    "Descartado":  set(),
}


def cambiar_estado_reporte(
    reporte_id: str,
    nuevo_estado: str,
    usuario: Usuario,
    comentario: Optional[str],
) -> Reporte:
    from app.infrastructure.db.reporte_repo import ReporteRepository
    from app.core.supabase_client import get_supabase

    repo = ReporteRepository()
    reporte = repo.get_by_id(reporte_id)
    if reporte is None:
        raise ReporteNotFoundError(f"Reporte {reporte_id} no encontrado.")

    # Verificar que el funcionario pertenece a la misma comuna del reporte
    if usuario.comuna_id != reporte.comuna_id:
        raise ComunaMismatchError("Solo funcionarios de la misma comuna pueden atender este reporte.")

    estado_actual = reporte.estado_actual or "En espera"
    permitidos = _TRANSICIONES_VALIDAS.get(estado_actual, set())
    if nuevo_estado not in permitidos:
        raise InvalidStateTransitionError(
            f"Transición '{estado_actual}' → '{nuevo_estado}' no está permitida."
        )

    if nuevo_estado == "Descartado" and not comentario:
        raise ValidationError("El comentario es obligatorio al descartar un reporte.")

    # Resolver tipo_estado_id desde nombre
    db = get_supabase()
    ts = db.table("tipo_estado").select("id").eq("nombre", nuevo_estado).maybe_single().execute()
    if not ts.data:
        raise ValidationError(f"Estado '{nuevo_estado}' no existe en el catálogo.")
    tipo_estado_id = ts.data["id"]

    atendido_por = usuario.id if nuevo_estado == "En atencion" else None
    repo.cambiar_estado(reporte_id, tipo_estado_id, usuario.id, comentario, atendido_por)

    return repo.get_by_id(reporte_id)
