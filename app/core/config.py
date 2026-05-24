from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Supabase (obligatorias) ───────────────────────────────────────────────
    supabase_url: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # ── App ───────────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    # Parámetros de validación (overrides de la RPC)
    validacion_radio_metros: int = 100
    validacion_ventana_minutos: int = 10
    validacion_umbral_db: float = 65.0

    # Heatmap
    heatmap_grid_size_deg: float = 0.001
    heatmap_max_window_days: int = 7

    # Storage: archivos generados desde el panel admin (PDF/CSV/imagen).
    # Bucket privado; URLs de descarga firmadas con duración corta.
    storage_bucket_reportes_admin: str = "reportes-admin"
    storage_signed_url_ttl_seconds: int = 300
    archivo_max_size_mb: int = 20

    # ── MQTT (opcionales) ─────────────────────────────────────────────────────
    mqtt_broker_url: Optional[str] = None
    mqtt_user: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_client_id: str = "40db-backend"

    @property
    def mqtt_enabled(self) -> bool:
        return bool(self.mqtt_broker_url and self.mqtt_user and self.mqtt_password)


settings = Settings()
