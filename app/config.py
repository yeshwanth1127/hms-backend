from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./avocado.db"
    redis_url: str = "redis://localhost:6379/0"
    allowed_origins: str = "http://localhost:5567,http://127.0.0.1:5567"
    slot_hold_minutes: int = 7
    admin_api_key: str = "dev-admin-key"
    voice_service_api_key: str = "dev-voice-service-key"
    whatsapp_service_api_key: str = "dev-whatsapp-service-key"
    whatsapp_owner_secret: str = "dev-whatsapp-owner-secret"
    media_dir: str = "./uploads"
    media_scan_socket: str | None = None

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
