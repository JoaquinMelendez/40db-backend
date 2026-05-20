from typing import Optional
from app.domain.entities import EvidenciaIot
from app.core.config import settings


def buscar_evidencia(latitud: float, longitud: float) -> Optional[EvidenciaIot]:
    from app.infrastructure.db.rpc import buscar_evidencia as _rpc
    return _rpc(
        latitud=latitud,
        longitud=longitud,
        radio_metros=settings.validacion_radio_metros,
        umbral_db=settings.validacion_umbral_db,
        ventana_minutos=settings.validacion_ventana_minutos,
    )
