from typing import Optional
from app.core.supabase_client import get_supabase
from app.domain.entities import Usuario


class UsuarioRepository:
    def __init__(self):
        self._db = get_supabase()

    def get_by_id(self, user_id: str) -> Optional[Usuario]:
        try:
            result = self._db.table("usuario").select("*").eq("id", user_id).maybe_single().execute()
            row = result.data
            if not row:
                return None
            return Usuario(
                id=row["id"],
                nombre=row["nombre"],
                tipo=row["tipo"],
                activo=row["activo"],
                telefono=row.get("telefono"),
                comuna_id=row.get("comuna_id"),
            )
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
            return Usuario(
                id=row["id"],
                nombre=row["nombre"],
                tipo=row["tipo"],
                activo=row["activo"],
                telefono=row.get("telefono"),
                comuna_id=row.get("comuna_id"),
            )
        except Exception as e:
            raise ExternalServiceError(f"Error al actualizar usuario: {e}") from e
