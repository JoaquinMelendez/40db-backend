"""Endpoints para archivos generados desde el panel admin
(/admin-dashboard/reportes — docs/integracion-backend §8).

Diseno:
  - Upload multipart vIa backend (el invariante "backend es el unico cliente
    de Supabase" no permite que el front toque Storage directo).
  - Descarga: el backend devuelve una signed URL de corta duracion y el
    front hace GET directo a Storage. Asi no hacemos proxy del binario.
"""
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.api.deps import current_user_admin
from app.api.schemas.reporte_archivo_admin import (
    ArchivoDescargaResponse,
    ListaArchivosResponse,
    ReporteArchivoAdminResponse,
)
from app.domain.entities import ReporteArchivoAdmin, Usuario

router = APIRouter(prefix="/reportes-admin/archivos", tags=["reportes-admin"])


def _to_response(a: ReporteArchivoAdmin) -> ReporteArchivoAdminResponse:
    return ReporteArchivoAdminResponse(
        id=a.id,
        nombre=a.nombre,
        tipo=a.tipo,
        mime_type=a.mime_type,
        tamano_bytes=a.tamano_bytes,
        generado_por_id=a.generado_por_id,
        generado_por_nombre=a.generado_por_nombre,
        rango_desde=a.rango_desde,
        rango_hasta=a.rango_hasta,
        created_at=a.created_at,
    )


@router.post("", response_model=ReporteArchivoAdminResponse, status_code=201)
async def subir_archivo(
    archivo: UploadFile = File(...),
    nombre: str = Form(..., min_length=1, max_length=200),
    tipo: Literal["pdf", "csv", "imagen"] = Form(...),
    rango_desde: Optional[datetime] = Form(None),
    rango_hasta: Optional[datetime] = Form(None),
    usuario: Usuario = Depends(current_user_admin),
):
    contenido = await archivo.read()
    mime_type = archivo.content_type or "application/octet-stream"

    from app.application.reportes_admin_archivos import subir_archivo as _uc
    res = _uc(
        usuario=usuario,
        nombre=nombre,
        tipo=tipo,
        mime_type=mime_type,
        contenido=contenido,
        rango_desde=rango_desde,
        rango_hasta=rango_hasta,
    )
    return _to_response(res)


@router.get("", response_model=ListaArchivosResponse)
async def listar_archivos(
    tipo: Optional[Literal["pdf", "csv", "imagen"]] = Query(None),
    generado_por_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    _: Usuario = Depends(current_user_admin),
):
    from app.application.reportes_admin_archivos import listar_archivos as _uc
    archivos, next_cursor = _uc(
        tipo=tipo,
        generado_por_id=generado_por_id,
        limit=limit,
        cursor=cursor,
    )
    return ListaArchivosResponse(
        data=[_to_response(a) for a in archivos],
        next_cursor=next_cursor,
    )


@router.get("/{archivo_id}/descarga", response_model=ArchivoDescargaResponse)
async def obtener_descarga(
    archivo_id: str,
    _: Usuario = Depends(current_user_admin),
):
    from app.application.reportes_admin_archivos import obtener_url_descarga
    url, ttl = obtener_url_descarga(archivo_id=archivo_id)
    return ArchivoDescargaResponse(url=url, expires_in_seconds=ttl)


@router.delete("/{archivo_id}", status_code=204)
async def eliminar_archivo(
    archivo_id: str,
    _: Usuario = Depends(current_user_admin),
):
    from app.application.reportes_admin_archivos import eliminar_archivo as _uc
    _uc(archivo_id=archivo_id)
