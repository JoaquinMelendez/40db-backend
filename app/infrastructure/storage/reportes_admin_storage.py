"""Adapter sobre Supabase Storage para el bucket de reportes admin.

El backend es el único cliente del bucket (mismo invariante que las tablas
con RLS-sin-policies). Toda la interacción con `supabase.storage` vive acá.
"""
from typing import Optional

from app.core.config import settings
from app.core.supabase_client import get_supabase
from app.domain.errors import ExternalServiceError


class ReportesAdminStorage:
    def __init__(self):
        self._bucket = get_supabase().storage.from_(settings.storage_bucket_reportes_admin)

    def upload(self, object_path: str, contenido: bytes, mime_type: str) -> None:
        try:
            self._bucket.upload(
                path=object_path,
                file=contenido,
                file_options={
                    "content-type": mime_type,
                    # 'upsert' false: el path ya incluye un ULID, no debería colisionar.
                    "upsert": "false",
                },
            )
        except Exception as e:
            raise ExternalServiceError(f"No se pudo subir el archivo a Storage: {e}") from e

    def signed_url(self, object_path: str, expires_in: Optional[int] = None) -> str:
        ttl = expires_in if expires_in is not None else settings.storage_signed_url_ttl_seconds
        try:
            res = self._bucket.create_signed_url(path=object_path, expires_in=ttl)
        except Exception as e:
            raise ExternalServiceError(f"No se pudo generar la signed URL: {e}") from e
        # storage3 devuelve {'signedURL': '...'} o {'signedUrl': '...'} según versión.
        url = res.get("signedURL") or res.get("signedUrl")
        if not url:
            raise ExternalServiceError("Respuesta sin signedURL desde Storage.")
        return url

    def remove(self, object_path: str) -> None:
        try:
            self._bucket.remove([object_path])
        except Exception as e:
            raise ExternalServiceError(f"No se pudo eliminar el archivo de Storage: {e}") from e
