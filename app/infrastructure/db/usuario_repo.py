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

    def _fetch_email(self, user_id: str) -> Optional[str]:
        """Lookup de email desde auth.users via supabase admin API.

        N+1 controlado: solo se invoca sobre la página devuelta (max 100).
        Si en el futuro pesa, mover a un RPC con JOIN auth.users.email.
        """
        try:
            res = self._db.auth.admin.get_user_by_id(user_id)
        except Exception:
            return None
        user = getattr(res, "user", None) if res is not None else None
        return getattr(user, "email", None) if user else None

    def listar(
        self,
        tipo: Optional[str],
        comuna_id: Optional[int],
        activo: Optional[bool],
        q: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> tuple[list[Usuario], Optional[str]]:
        from app.domain.errors import ExternalServiceError
        try:
            query = (
                self._db.table("usuario")
                .select("*")
                .order("created_at", desc=True)
                .order("id", desc=True)
                .limit(limit + 1)
            )
            if tipo is not None:
                query = query.eq("tipo", tipo)
            if comuna_id is not None:
                query = query.eq("comuna_id", comuna_id)
            if activo is not None:
                query = query.eq("activo", activo)
            if q:
                # MVP: solo búsqueda por nombre. La búsqueda por email
                # requeriría JOIN a auth.users — pendiente para cuando
                # exista un RPC dedicado o vista materializada.
                query = query.ilike("nombre", f"%{q}%")
            if cursor:
                ca, _rid = _decode_cursor(cursor)
                query = query.lt("created_at", ca)

            rows = query.execute().data or []
        except Exception as e:
            raise ExternalServiceError(f"Error listando usuarios: {e}") from e

        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            next_cursor = _encode_cursor(last["created_at"], last["id"])

        return [_row_to_usuario(row, email=self._fetch_email(row["id"])) for row in rows], next_cursor
