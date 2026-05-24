"""Use cases de sensores (api.md §4.14-§4.19).

Reglas de comuna por rol:
- admin: cross-comuna (filtro opcional por comuna_id query param).
- municipalidad: forzado a usuario.comuna_id (cualquier comuna_id query
  enviado se ignora silenciosamente — el filtro de su comuna manda).
"""
from typing import Optional

from app.core.supabase_client import get_supabase
from app.domain.entities import Sensor, Usuario
from app.domain.errors import (
    ComunaMismatchError,
    NotFoundError,
    ValidationError,
)
from app.infrastructure.db.sensor_repo import SensorRepository


class SensorNotFoundError(NotFoundError):
    code = "sensor_not_found"


class ComunaNotFoundError(ValidationError):
    code = "comuna_not_found"
    http_status = 422


def _resolver_comuna_filtro(actor: Usuario, comuna_id_query: Optional[int]) -> Optional[int]:
    """Resuelve qué comuna_id filtrar según el rol del actor.

    - admin: respeta el query (None = todas).
    - municipalidad: fuerza usuario.comuna_id, ignora el query.
    """
    if actor.tipo == "admin":
        return comuna_id_query
    return actor.comuna_id


def _validar_comuna(comuna_id: int) -> None:
    db = get_supabase()
    r = db.table("comuna").select("id").eq("id", comuna_id).maybe_single().execute()
    if not r.data:
        raise ComunaNotFoundError(f"comuna {comuna_id} no existe.")


def listar_sensores(
    *,
    actor: Usuario,
    comuna_id: Optional[int],
    estado_salud: Optional[str],
    activo: Optional[bool],
    limit: int,
    cursor: Optional[str],
) -> tuple[list[Sensor], Optional[str]]:
    comuna_filtro = _resolver_comuna_filtro(actor, comuna_id)
    return SensorRepository().listar(
        comuna_id=comuna_filtro,
        estado_salud=estado_salud,
        activo=activo,
        limit=limit,
        cursor=cursor,
    )


def obtener_sensor(*, actor: Usuario, sensor_id: str) -> Sensor:
    sensor = SensorRepository().get_by_id(sensor_id)
    if sensor is None:
        raise SensorNotFoundError(f"Sensor {sensor_id} no encontrado.")

    # municipalidad solo accede a sensores de su comuna.
    if actor.tipo == "municipalidad" and sensor.comuna_id != actor.comuna_id:
        raise ComunaMismatchError(
            "No tenés permiso para ver sensores de otra comuna."
        )
    return sensor


def obtener_resumen_sensores(
    *, actor: Usuario, comuna_id: Optional[int]
) -> dict:
    comuna_filtro = _resolver_comuna_filtro(actor, comuna_id)
    return SensorRepository().resumen(comuna_id=comuna_filtro)


def crear_sensor(
    *,
    nombre: str,
    comuna_id: int,
    latitud: float,
    longitud: float,
) -> Sensor:
    _validar_comuna(comuna_id)
    return SensorRepository().crear(
        nombre=nombre,
        comuna_id=comuna_id,
        latitud=latitud,
        longitud=longitud,
    )


def actualizar_sensor(
    *,
    sensor_id: str,
    nombre: Optional[str],
    latitud: Optional[float],
    longitud: Optional[float],
    activo: Optional[bool],
) -> Sensor:
    repo = SensorRepository()
    if repo.get_by_id(sensor_id) is None:
        raise SensorNotFoundError(f"Sensor {sensor_id} no encontrado.")

    updated = repo.actualizar(
        sensor_id=sensor_id,
        nombre=nombre,
        latitud=latitud,
        longitud=longitud,
        activo=activo,
    )
    if updated is None:
        raise SensorNotFoundError(f"Sensor {sensor_id} no encontrado.")
    return updated


def desactivar_sensor(*, sensor_id: str) -> Sensor:
    repo = SensorRepository()
    if repo.get_by_id(sensor_id) is None:
        raise SensorNotFoundError(f"Sensor {sensor_id} no encontrado.")

    updated = repo.desactivar(sensor_id)
    if updated is None:
        raise SensorNotFoundError(f"Sensor {sensor_id} no encontrado.")
    return updated
