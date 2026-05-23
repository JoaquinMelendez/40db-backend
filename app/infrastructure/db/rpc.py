"""Wrappers para las RPCs de Postgres (bbdd.md §5)."""
from datetime import datetime, timezone
from typing import Optional
from app.core.supabase_client import get_supabase
from app.domain.entities import EvidenciaIot


def buscar_evidencia(
    latitud: float,
    longitud: float,
    radio_metros: int,
    umbral_db: float,
    ventana_minutos: int,
) -> Optional[EvidenciaIot]:
    """Llama a validar_reporte_ruido (single). Usada por GET /buscar-evidencia."""
    db = get_supabase()
    result = db.rpc("validar_reporte_ruido", {
        "p_latitud": latitud,
        "p_longitud": longitud,
        "p_tiempo_reporte": datetime.now(timezone.utc).isoformat(),
        "p_radio_metros": radio_metros,
        "p_umbral_db": umbral_db,
        "p_ventana_minutos": ventana_minutos,
    }).execute()

    if not result.data:
        return None

    row = result.data[0]
    # Enriquecer con nombre del sensor
    sensor = db.table("sensor").select("nombre").eq("id", row["sensor_id"]).maybe_single().execute()
    nombre = sensor.data["nombre"] if sensor.data else row["sensor_id"]

    return EvidenciaIot(
        lectura_id=row["lectura_id"],
        sensor_id=row["sensor_id"],
        sensor_nombre=nombre,
        nivel_db=float(row["nivel_db"]),
        distancia_metros=float(row["distancia_metros"]),
        timestamp_medicion=row["timestamp_medicion"],
    )


def crear_reporte_con_validacion(
    usuario_id: str,
    comuna_id: int,
    titulo: str,
    descripcion: str,
    latitud: float,
    longitud: float,
    lectura_evidencia_id: Optional[int],
    radio_metros: int,
    umbral_db: float,
    ventana_minutos: int,
) -> tuple[str, Optional[int]]:
    """Llama a la RPC compuesta atómica. Devuelve (reporte_id, lectura_evidencia_id).

    La RPC SQL devuelve además `lectura_evidencia_timestamp` porque la FK a `lectura`
    es compuesta (D8 / ADR 08). Ese timestamp solo lo necesita SQL para satisfacer la
    FK y se persiste internamente por el UPDATE dentro de la RPC. El dominio Python
    no lo expone — el caller hidrata el objeto EvidenciaIot vía repo, que ya trae
    timestamp_medicion desde el JOIN a `lectura`.
    """
    db = get_supabase()
    result = db.rpc("crear_reporte_con_validacion", {
        "p_usuario_id": usuario_id,
        "p_comuna_id": comuna_id,
        "p_titulo": titulo,
        "p_descripcion": descripcion,
        "p_latitud": latitud,
        "p_longitud": longitud,
        "p_lectura_evidencia_id": lectura_evidencia_id,
        "p_radio_metros": radio_metros,
        "p_umbral_db": umbral_db,
        "p_ventana_minutos": ventana_minutos,
    }).execute()

    row = result.data[0]
    return row["reporte_id"], row.get("lectura_evidencia_id")
