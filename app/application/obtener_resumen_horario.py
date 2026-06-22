"""Use case: serie horaria pre-agregada de un sensor (api.md §4.27).

Reglas de autorización:
- admin: cualquier sensor.
- municipalidad: solo sensores de su comuna_id.
"""
from datetime import datetime, timedelta

from app.domain.entities import Usuario
from app.domain.errors import ComunaMismatchError, NotFoundError, ValidationError
from app.infrastructure.db.resumen_horario_repo import ResumenHorarioRepository
from app.infrastructure.db.sensor_repo import SensorRepository

MAX_VENTANA_DIAS = 90


class SensorNotFoundError(NotFoundError):
    code = "sensor_not_found"


def obtener_resumen_horario(
    *,
    actor: Usuario,
    sensor_id: str,
    desde: datetime,
    hasta: datetime,
) -> dict:
    if hasta <= desde:
        raise ValidationError("hasta debe ser posterior a desde.")
    if (hasta - desde) > timedelta(days=MAX_VENTANA_DIAS):
        raise ValidationError(f"La ventana no puede superar {MAX_VENTANA_DIAS} días.")

    sensor = SensorRepository().get_by_id(sensor_id)
    if sensor is None:
        raise SensorNotFoundError(f"Sensor {sensor_id} no encontrado.")

    if actor.tipo == "municipalidad" and sensor.comuna_id != actor.comuna_id:
        raise ComunaMismatchError("No tenés permiso para ver datos de sensores de otra comuna.")

    repo = ResumenHorarioRepository()
    filas = repo.listar(sensor_id=sensor_id, desde=desde, hasta=hasta)
    refrescado_at = repo.max_refrescado_at(filas)

    return {
        "sensor_id": sensor.id,
        "sensor_nombre": sensor.nombre,
        "desde": desde,
        "hasta": hasta,
        "horas": filas,
        "fuente": "lectura_resumen_horaria",
        "refrescado_at": refrescado_at,
    }
