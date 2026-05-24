from fastapi import APIRouter, Depends, Query
from typing import Optional

from app.api.deps import current_user, current_user_municipal
from app.domain.entities import Usuario
from app.domain.errors import ReporteNotFoundError, ForbiddenError, ComunaMismatchError
from app.api.schemas.reporte import (
    BuscarEvidenciaResponse, EvidenciaSchema,
    CrearReporteRequest, ReporteDetalle, ReporteResumen,
    ListaReportesResponse, CambiarEstadoRequest,
)

router = APIRouter(prefix="/reportes", tags=["reportes"])


def _evidencia_schema(ev) -> Optional[EvidenciaSchema]:
    if ev is None:
        return None
    return EvidenciaSchema(
        lectura_id=ev.lectura_id,
        sensor_id=ev.sensor_id,
        sensor_nombre=ev.sensor_nombre,
        nivel_db=ev.nivel_db,
        distancia_metros=ev.distancia_metros,
        timestamp_medicion=ev.timestamp_medicion,
    )


def _reporte_detalle(r) -> ReporteDetalle:
    return ReporteDetalle(
        id=r.id,
        usuario_id=r.usuario_id,
        atendido_por_id=r.atendido_por_id,
        comuna_id=r.comuna_id,
        titulo=r.titulo,
        descripcion=r.descripcion,
        latitud=r.latitud,
        longitud=r.longitud,
        estado_actual=r.estado_actual,
        historial=getattr(r, "historial", None),
        lectura_evidencia=_evidencia_schema(r.lectura_evidencia),
        created_at=r.created_at,
    )


@router.get("/buscar-evidencia", response_model=BuscarEvidenciaResponse)
async def buscar_evidencia(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    _: Usuario = Depends(current_user),
):
    from app.application.buscar_evidencia import buscar_evidencia as _uc
    evidencia = _uc(lat, lng)
    return BuscarEvidenciaResponse(evidencia=_evidencia_schema(evidencia))


@router.post("", response_model=ReporteDetalle, status_code=201)
async def crear_reporte(
    body: CrearReporteRequest,
    usuario: Usuario = Depends(current_user),
):
    from app.application.crear_reporte import crear_reporte as _uc

    reporte = _uc(
        usuario=usuario,
        titulo=body.titulo,
        descripcion=body.descripcion,
        latitud=body.latitud,
        longitud=body.longitud,
        comuna_id=body.comuna_id,
        lectura_evidencia_id=body.lectura_evidencia_id,
    )
    return _reporte_detalle(reporte)


@router.get("/mios", response_model=ListaReportesResponse)
async def mis_reportes(
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    usuario: Usuario = Depends(current_user),
):
    from app.infrastructure.db.reporte_repo import ReporteRepository
    repo = ReporteRepository()
    reportes, next_cursor = repo.list_by_usuario(usuario.id, limit, cursor, estado)
    return ListaReportesResponse(
        data=[ReporteResumen(id=r.id, titulo=r.titulo, estado_actual=r.estado_actual, created_at=r.created_at) for r in reportes],
        next_cursor=next_cursor,
    )


@router.get("/comuna/{comuna_id}", response_model=ListaReportesResponse)
async def reportes_por_comuna(
    comuna_id: int,
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    usuario: Usuario = Depends(current_user_municipal),
):
    if usuario.comuna_id != comuna_id:
        raise ComunaMismatchError("Solo podés ver reportes de tu propia comuna.")

    from app.infrastructure.db.reporte_repo import ReporteRepository
    repo = ReporteRepository()
    reportes, next_cursor = repo.list_by_comuna(comuna_id, limit, cursor, estado)
    return ListaReportesResponse(
        data=[ReporteResumen(id=r.id, titulo=r.titulo, estado_actual=r.estado_actual, created_at=r.created_at) for r in reportes],
        next_cursor=next_cursor,
    )


@router.get("/{reporte_id}", response_model=ReporteDetalle)
async def obtener_reporte(
    reporte_id: str,
    usuario: Usuario = Depends(current_user),
):
    from app.infrastructure.db.reporte_repo import ReporteRepository
    repo = ReporteRepository()
    reporte = repo.get_by_id(reporte_id)
    if reporte is None:
        raise ReporteNotFoundError(f"Reporte {reporte_id} no encontrado.")

    es_dueno = reporte.usuario_id == usuario.id
    es_municipal_de_comuna = (
        usuario.tipo == "municipalidad" and usuario.comuna_id == reporte.comuna_id
    )
    if not (es_dueno or es_municipal_de_comuna):
        raise ForbiddenError("No tenés permiso para ver este reporte.")

    return _reporte_detalle(reporte)


@router.patch("/{reporte_id}/estado", response_model=ReporteDetalle)
async def cambiar_estado(
    reporte_id: str,
    body: CambiarEstadoRequest,
    usuario: Usuario = Depends(current_user_municipal),
):
    from app.application.cambiar_estado_reporte import cambiar_estado_reporte
    reporte = cambiar_estado_reporte(
        reporte_id=reporte_id,
        nuevo_estado=body.nuevo_estado,
        usuario=usuario,
        comentario=body.comentario,
    )
    return _reporte_detalle(reporte)
