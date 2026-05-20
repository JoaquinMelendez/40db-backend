from fastapi import APIRouter
from app.core.supabase_client import get_supabase

router = APIRouter(tags=["catalogos"])


@router.get("/comunas")
async def list_comunas():
    result = get_supabase().table("comuna").select("id, nombre, region, codigo").order("nombre").execute()
    return result.data or []


@router.get("/tipos-estado")
async def list_tipos_estado():
    result = get_supabase().table("tipo_estado").select("id, nombre, descripcion, orden").order("orden").execute()
    return result.data or []
