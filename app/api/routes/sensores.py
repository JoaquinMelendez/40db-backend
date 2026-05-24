from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import current_user_admin, current_user_municipal_o_admin
from app.api.schemas.sensor import (
    ActualizarSensorRequest,
    CrearSensorRequest,
    DesactivarSensorResponse,
    ListaSensoresResponse,
    ResumenSensoresResponse,
    SensorResponse,
)
from app.application import sensores as uc
from app.domain.entities import Sensor, Usuario

router = APIRouter(prefix="/sensores", tags=["sensores"])


def _to_response(s: Sensor) -> SensorResponse:
    return SensorResponse(
        id=s.id,
        nombre=s.nombre,
        comuna_id=s.comuna_id,
        comuna_nombre=s.comuna_nombre,
        latitud=s.latitud,
        longitud=s.longitud,
        activo=s.activo,
        estado_salud=s.estado_salud,
        ultima_lectura_at=s.ultima_lectura_at,
        ultima_lectura_db=s.ultima_lectura_db,
        created_at=s.created_at,
    )


@router.get("/resumen", response_model=ResumenSensoresResponse)
async def resumen_sensores(
    comuna_id: Optional[int] = Query(None),
    actor: Usuario = Depends(current_user_municipal_o_admin),
):
    resumen = uc.obtener_resumen_sensores(actor=actor, comuna_id=comuna_id)
    return ResumenSensoresResponse(**resumen)


@router.get("", response_model=ListaSensoresResponse)
async def listar_sensores(
    comuna_id: Optional[int] = Query(None),
    estado_salud: Optional[str] = Query(None),
    activo: Optional[bool] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    actor: Usuario = Depends(current_user_municipal_o_admin),
):
    sensores, next_cursor = uc.listar_sensores(
        actor=actor,
        comuna_id=comuna_id,
        estado_salud=estado_salud,
        activo=activo,
        limit=limit,
        cursor=cursor,
    )
    return ListaSensoresResponse(
        data=[_to_response(s) for s in sensores],
        next_cursor=next_cursor,
    )


@router.get("/{sensor_id}", response_model=SensorResponse)
async def obtener_sensor(
    sensor_id: str,
    actor: Usuario = Depends(current_user_municipal_o_admin),
):
    return _to_response(uc.obtener_sensor(actor=actor, sensor_id=sensor_id))


@router.post("", response_model=SensorResponse, status_code=201)
async def crear_sensor(
    body: CrearSensorRequest,
    _: Usuario = Depends(current_user_admin),
):
    sensor = uc.crear_sensor(
        nombre=body.nombre,
        comuna_id=body.comuna_id,
        latitud=body.latitud,
        longitud=body.longitud,
    )
    return _to_response(sensor)


@router.patch("/{sensor_id}", response_model=SensorResponse)
async def actualizar_sensor(
    sensor_id: str,
    body: ActualizarSensorRequest,
    _: Usuario = Depends(current_user_admin),
):
    sensor = uc.actualizar_sensor(
        sensor_id=sensor_id,
        nombre=body.nombre,
        latitud=body.latitud,
        longitud=body.longitud,
        activo=body.activo,
    )
    return _to_response(sensor)


@router.delete("/{sensor_id}", response_model=DesactivarSensorResponse)
async def desactivar_sensor(
    sensor_id: str,
    _: Usuario = Depends(current_user_admin),
):
    sensor = uc.desactivar_sensor(sensor_id=sensor_id)
    return DesactivarSensorResponse(
        id=sensor.id,
        activo=sensor.activo,
        estado_salud=sensor.estado_salud,
    )
