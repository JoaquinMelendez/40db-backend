from typing import Optional
from app.core.config import settings
from app.core.supabase_client import get_supabase
from app.domain.entities import Reporte, Usuario
from app.domain.errors import ExternalServiceError, ValidationError


def _resolver_comuna_id(usuario: Usuario, comuna_id: Optional[int]) -> int:
    """Resuelve la comuna efectiva del reporte (api.md §4.5.1).

    - Si viene `comuna_id`, valida contra catálogo.
    - Si no viene, fallback a `usuario.comuna_id`.
    - Si ambos son None, 422.
    """
    if comuna_id is not None:
        db = get_supabase()
        r = db.table("comuna").select("id").eq("id", comuna_id).maybe_single().execute()
        if not r.data:
            raise ValidationError(f"comuna_id {comuna_id} no existe.")
        return comuna_id

    if usuario.comuna_id is None:
        raise ValidationError(
            "Falta completar onboarding (comuna_id) o enviar comuna_id en el body."
        )
    return usuario.comuna_id


def crear_reporte(
    *,
    usuario: Usuario,
    titulo: str,
    descripcion: str,
    latitud: float,
    longitud: float,
    comuna_id: Optional[int] = None,
    lectura_evidencia_id: Optional[int] = None,
) -> Reporte:
    from app.infrastructure.db.rpc import crear_reporte_con_validacion
    from app.infrastructure.db.reporte_repo import ReporteRepository

    comuna_efectiva = _resolver_comuna_id(usuario, comuna_id)

    try:
        reporte_id, _evidencia_id = crear_reporte_con_validacion(
            usuario_id=usuario.id,
            comuna_id=comuna_efectiva,
            titulo=titulo,
            descripcion=descripcion,
            latitud=latitud,
            longitud=longitud,
            lectura_evidencia_id=lectura_evidencia_id,
            radio_metros=settings.validacion_radio_metros,
            umbral_db=settings.validacion_umbral_db,
            ventana_minutos=settings.validacion_ventana_minutos,
        )
    except ValidationError:
        raise
    except Exception as e:
        raise ExternalServiceError(f"Error al crear reporte: {e}") from e

    return ReporteRepository().get_by_id(reporte_id)
