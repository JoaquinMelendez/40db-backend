import base64
import json
from typing import Optional
from app.core.supabase_client import get_supabase
from app.domain.entities import Usuario


def _row_to_usuario(row: dict, email: Optional[str] = None) -> Usuario:
    return Usuario(
        id=row["id"],
        nombre=row["nombre"],
        tipo=row["tipo"],
        activo=row["activo"],
        telefono=row.get("telefono"),
        comuna_id=row.get("comuna_id"),
        email=email,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _encode_cursor(created_at: str, id: str) -> str:
    return base64.b64encode(json.dumps({"created_at": created_at, "id": id}).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, str]:
    data = json.loads(base64.b64decode(cursor).decode())
    return data["created_at"], data["id"]


class UsuarioRepository:
    def __init__(self):
        self._db = get_supabase()

    def get_by_id(self, user_id: str) -> Optional[Usuario]:
        try:
            result = self._db.table("usuario").select("*").eq("id", user_id).maybe_single().execute()
            row = result.data
            if not row:
                return None
            return _row_to_usuario(row)
        except Exception:
            return None

    def update_me(self, user_id: str, telefono: Optional[str], comuna_id: Optional[int]) -> Usuario:
        from app.domain.errors import ExternalServiceError
        patch = {}
        if telefono is not None:
            patch["telefono"] = telefono
        if comuna_id is not None:
            patch["comuna_id"] = comuna_id
        try:
            result = self._db.table("usuario").update(patch).eq("id", user_id).execute()
            row = result.data[0]
            return _row_to_usuario(row)
        except Exception as e:
            raise ExternalServiceError(f"Error al actualizar usuario: {e}") from e

    def set_activo(self, user_id: str, activo: bool) -> Optional[Usuario]:
        from app.domain.errors import ExternalServiceError
        try:
            result = self._db.table("usuario").update({"activo": activo}).eq("id", user_id).execute()
            if not result.data:
                return None
            return _row_to_usuario(result.data[0])
        except Exception as e:
            raise ExternalServiceError(f"Error al cambiar activo: {e}") from e

    def promover(
        self,
        user_id: str,
        nuevo_tipo: str,
        comuna_id: Optional[int],
        # nuevo_tipo='ciudadano' no toca comuna_id (auth.md §8.2).
        # nuevo_tipo='admin' acepta comuna_id opcional o null.
        # nuevo_tipo='municipalidad' exige comuna_id (validado en use case).
        actualizar_comuna: bool = True,
    ) -> Optional[Usuario]:
        from app.domain.errors import ExternalServiceError
        patch: dict = {"tipo": nuevo_tipo}
        if actualizar_comuna:
            patch["comuna_id"] = comuna_id
        try:
            result = self._db.table("usuario").update(patch).eq("id", user_id).execute()
            if not result.data:
                return None
            return _row_to_usuario(result.data[0])
        except Exception as e:
            raise ExternalServiceError(f"Error al promover usuario: {e}") from e
