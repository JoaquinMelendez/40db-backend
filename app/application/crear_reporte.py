from typing import Optional
from app.domain.entities import Reporte, EvidenciaIot
from app.domain.errors import ExternalServiceError
from app.core.config import settings


def crear_reporte(
    usuario_id: str,
    comuna_id: int,
    titulo: str,
    descripcion: str,
    latitud: float,
    longitud: float,
    lectura_evidencia_id: Optional[int] = None,
) -> Reporte:
    from app.infrastructure.db.rpc import crear_reporte_con_validacion
    from app.infrastructure.db.reporte_repo import ReporteRepository

    try:
        reporte_id, evidencia_id = crear_reporte_con_validacion(
            usuario_id=usuario_id,
            comuna_id=comuna_id,
            titulo=titulo,
            descripcion=descripcion,
            latitud=latitud,
            longitud=longitud,
            lectura_evidencia_id=lectura_evidencia_id,
            radio_metros=settings.validacion_radio_metros,
            umbral_db=settings.validacion_umbral_db,
            ventana_minutos=settings.validacion_ventana_minutos,
        )
    except Exception as e:
        raise ExternalServiceError(f"Error al crear reporte: {e}") from e

    repo = ReporteRepository()
    reporte = repo.get_by_id(reporte_id)
    return reporte
