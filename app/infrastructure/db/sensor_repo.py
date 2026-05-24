"""Repositorio de sensores.

Listado / detalle usan la RPC sensores_con_salud (D10 en bbdd.md). El
resumen agregado usa resumen_salud_sensores. Las mutaciones (crear,
actualizar, desactivar) son operaciones directas sobre `sensor`.
"""
import base64
import json
from typing import Optional

from app.core.supabase_client import get_supabase
from app.domain.entities import Sensor
from app.domain.errors import ExternalServiceError, ValidationError


def _row_to_sensor(row: dict, comuna_nombre: Optional[str] = None) -> Sensor:
    return Sensor(
        id=row["id"],
        comuna_id=row["comuna_id"],
        nombre=row["nombre"],
        latitud=float(row["latitud"]),
        longitud=float(row["longitud"]),
        activo=row["activo"],
        estado_salud=row.get("estado_salud"),
        ultima_lectura_at=row.get("ultima_lectura_at"),
        ultima_lectura_db=float(row["ultima_lectura_db"]) if row.get("ultima_lectura_db") is not None else None,
        comuna_nombre=comuna_nombre,
        created_at=row.get("created_at"),
    )


def _encode_cursor(nombre: str, id: str) -> str:
    return base64.b64encode(json.dumps({"nombre": nombre, "id": id}).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    data = json.loads(base64.b64decode(cursor).decode())
    return data["nombre"], data["id"]


class SensorNombreDuplicadoError(ValidationError):
    code = "sensor_nombre_already_exists"
    http_status = 422


class SensorRepository:
    def __init__(self):
        self._db = get_supabase()

    def _comuna_nombres(self, ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        r = self._db.table("comuna").select("id, nombre").in_("id", list(set(ids))).execute()
        return {row["id"]: row["nombre"] for row in (r.data or [])}

    def listar(
        self,
        comuna_id: Optional[int],
        estado_salud: Optional[str],
        activo: Optional[bool],
        limit: int,
        cursor: Optional[str],
    ) -> tuple[list[Sensor], Optional[str]]:
        try:
            result = self._db.rpc("sensores_con_salud", {"p_comuna_id": comuna_id}).execute()
        except Exception as e:
            raise ExternalServiceError(f"Error listando sensores: {e}") from e

        rows = result.data or []

        if estado_salud is not None:
            rows = [r for r in rows if r.get("estado_salud") == estado_salud]
        if activo is not None:
            rows = [r for r in rows if r.get("activo") == activo]

        rows.sort(key=lambda r: (r["nombre"], r["id"]))

        if cursor:
            c_nombre, c_id = _decode_cursor(cursor)
            rows = [r for r in rows if (r["nombre"], r["id"]) > (c_nombre, c_id)]

        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last["nombre"], last["id"])

        nombres = self._comuna_nombres([r["comuna_id"] for r in rows])
        return [_row_to_sensor(r, nombres.get(r["comuna_id"])) for r in rows], next_cursor

    def get_by_id(self, sensor_id: str) -> Optional[Sensor]:
        try:
            result = self._db.rpc("sensores_con_salud", {"p_comuna_id": None}).execute()
        except Exception as e:
            raise ExternalServiceError(f"Error obteniendo sensor: {e}") from e

        for row in (result.data or []):
            if row["id"] == sensor_id:
                nombres = self._comuna_nombres([row["comuna_id"]])
                return _row_to_sensor(row, nombres.get(row["comuna_id"]))
        return None

    def resumen(self, comuna_id: Optional[int]) -> dict:
        try:
            result = self._db.rpc("resumen_salud_sensores", {"p_comuna_id": comuna_id}).execute()
        except Exception as e:
            raise ExternalServiceError(f"Error obteniendo resumen: {e}") from e

        if not result.data:
            return {"total": 0, "online": 0, "intermitente": 0, "offline": 0, "sin_lecturas": 0, "calculado_at": None}
        return result.data[0]

    def crear(self, nombre: str, comuna_id: int, latitud: float, longitud: float) -> Sensor:
        try:
            result = self._db.table("sensor").insert({
                "nombre": nombre,
                "comuna_id": comuna_id,
                "latitud": latitud,
                "longitud": longitud,
            }).execute()
        except Exception as e:
            msg = str(e).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                raise SensorNombreDuplicadoError(
                    f"Ya existe un sensor con nombre {nombre!r}."
                ) from e
            raise ExternalServiceError(f"Error creando sensor: {e}") from e

        new_id = result.data[0]["id"]
        sensor = self.get_by_id(new_id)
        if sensor is None:
            raise ExternalServiceError("Sensor creado pero no se pudo leer.")
        return sensor

    def actualizar(
        self,
        sensor_id: str,
        nombre: Optional[str],
        latitud: Optional[float],
        longitud: Optional[float],
        activo: Optional[bool],
    ) -> Optional[Sensor]:
        patch: dict = {}
        if nombre is not None:
            patch["nombre"] = nombre
        if latitud is not None:
            patch["latitud"] = latitud
        if longitud is not None:
            patch["longitud"] = longitud
        if activo is not None:
            patch["activo"] = activo
        if not patch:
            return self.get_by_id(sensor_id)

        try:
            result = self._db.table("sensor").update(patch).eq("id", sensor_id).execute()
        except Exception as e:
            msg = str(e).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                raise SensorNombreDuplicadoError(
                    f"Ya existe un sensor con nombre {nombre!r}."
                ) from e
            raise ExternalServiceError(f"Error actualizando sensor: {e}") from e

        if not result.data:
            return None
        return self.get_by_id(sensor_id)

    def desactivar(self, sensor_id: str) -> Optional[Sensor]:
        return self.actualizar(sensor_id, nombre=None, latitud=None, longitud=None, activo=False)
