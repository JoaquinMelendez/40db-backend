"""Use cases para archivos generados desde el panel admin
(vista /admin-dashboard/reportes — docs/integracion-backend §8).
"""
import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Optional

from ulid import ULID

from app.core.config import settings
from app.domain.entities import ReporteArchivoAdmin, Usuario
from app.domain.errors import NotFoundError, ValidationError
from app.infrastructure.db.reporte_archivo_admin_repo import ReporteArchivoAdminRepository
from app.infrastructure.storage.reportes_admin_storage import ReportesAdminStorage


# Mapeo tipo (categoria de presentacion) → set de mime-types aceptados.
_MIME_VALIDOS = {
    "pdf": {"application/pdf"},
    "csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
    "imagen": {"image/png", "image/jpeg", "image/webp"},
}

_EXT_POR_MIME = {
    "application/pdf": ".pdf",
    "text/csv": ".csv",
    "application/csv": ".csv",
    "application/vnd.ms-excel": ".csv",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _sanitizar_nombre(nombre: str) -> str:
    """Convierte el nombre original en un slug seguro para usar en el object_path.
    El nombre legible original se preserva intacto en la columna `nombre`.
    """
    stem = PurePosixPath(nombre).stem or "archivo"
    slug = _SLUG_RE.sub("-", stem).strip("-").lower()
    return slug[:60] or "archivo"


def _validar_mime(tipo: str, mime_type: str) -> None:
    permitidos = _MIME_VALIDOS.get(tipo)
    if not permitidos:
        raise ValidationError(f"Tipo de archivo no soportado: {tipo}.")
    if mime_type not in permitidos:
        raise ValidationError(
            f"El mime_type '{mime_type}' no es valido para tipo='{tipo}'."
        )


def _validar_rango(desde: Optional[datetime], hasta: Optional[datetime]) -> None:
    if desde and hasta and desde > hasta:
        raise ValidationError("rango_desde no puede ser posterior a rango_hasta.")


def subir_archivo(
    *,
    usuario: Usuario,
    nombre: str,
    tipo: str,
    mime_type: str,
    contenido: bytes,
    rango_desde: Optional[datetime] = None,
    rango_hasta: Optional[datetime] = None,
) -> ReporteArchivoAdmin:
    """Sube un archivo al bucket y registra la metadata.

    Pre: el caller ya verifico que `usuario.tipo == 'admin'` (route dep).
    """
    nombre = (nombre or "").strip()
    if len(nombre) < 1 or len(nombre) > 200:
        raise ValidationError("El nombre del archivo debe tener entre 1 y 200 caracteres.")

    _validar_mime(tipo, mime_type)
    _validar_rango(rango_desde, rango_hasta)

    tamano = len(contenido)
    if tamano == 0:
        raise ValidationError("El archivo esta vacio.")
    limite = settings.archivo_max_size_mb * 1024 * 1024
    if tamano > limite:
        raise ValidationError(
            f"El archivo supera el tamano maximo permitido ({settings.archivo_max_size_mb} MB)."
        )

    ext = _EXT_POR_MIME[mime_type]
    object_path = f"{usuario.id}/{ULID()}_{_sanitizar_nombre(nombre)}{ext}"

    storage = ReportesAdminStorage()
    repo = ReporteArchivoAdminRepository()

    storage.upload(object_path, contenido, mime_type)

    try:
        return repo.insert(
            generado_por_id=usuario.id,
            nombre=nombre,
            tipo=tipo,
            mime_type=mime_type,
            tamano_bytes=tamano,
            object_path=object_path,
            rango_desde=rango_desde,
            rango_hasta=rango_hasta,
        )
    except Exception:
        # Compensacion: si la metadata fallo, el objeto en el bucket queda
        # huerfano. Best-effort delete (si tambien falla, los errores propagan
        # el original; el objeto queda para limpieza manual).
        try:
            storage.remove(object_path)
        except Exception:
            pass
        raise


def listar_archivos(
    *,
    tipo: Optional[str],
    generado_por_id: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> tuple[list[ReporteArchivoAdmin], Optional[str]]:
    if tipo is not None and tipo not in _MIME_VALIDOS:
        raise ValidationError(f"Tipo invalido: {tipo}.")
    return ReporteArchivoAdminRepository().listar(
        tipo=tipo,
        generado_por_id=generado_por_id,
        limit=limit,
        cursor=cursor,
    )


def obtener_url_descarga(*, archivo_id: str) -> tuple[str, int]:
    """Devuelve (signed_url, ttl_seconds) para descargar el archivo."""
    repo = ReporteArchivoAdminRepository()
    archivo = repo.get_by_id(archivo_id)
    if archivo is None:
        raise NotFoundError(f"Archivo {archivo_id} no encontrado.")
    ttl = settings.storage_signed_url_ttl_seconds
    url = ReportesAdminStorage().signed_url(archivo.object_path, expires_in=ttl)
    return url, ttl


def eliminar_archivo(*, archivo_id: str) -> None:
    repo = ReporteArchivoAdminRepository()
    archivo = repo.get_by_id(archivo_id)
    if archivo is None:
        raise NotFoundError(f"Archivo {archivo_id} no encontrado.")
    # Borramos primero el blob; si falla, conservamos la metadata para reintento.
    ReportesAdminStorage().remove(archivo.object_path)
    repo.delete(archivo.id)
