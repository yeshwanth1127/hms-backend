from functools import lru_cache

from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./avocado.db"
    redis_url: str = "redis://localhost:6379/0"
    allowed_origins: str = "http://localhost:5567,http://127.0.0.1:5567"
    booking_allowed_origins: str = ""
    posthog_growth_enabled: bool = False
    posthog_api_host: str = "https://us.posthog.com"
    posthog_project_id: int | None = Field(default=None, gt=0)
    posthog_read_key: SecretStr = SecretStr("")
    staff_origin: str = ""
    slot_hold_minutes: int = 7
    admin_api_key: str = "dev-admin-key"
    voice_service_api_key: str = "dev-voice-service-key"
    whatsapp_service_api_key: str = "dev-whatsapp-service-key"
    whatsapp_owner_secret: str = "dev-whatsapp-owner-secret"
    media_dir: str = "./uploads"
    media_scan_socket: str | None = None
    whatsapp_test_recipients: str = ""
    clinic_phone: str = ""
    reception_hours: str = "Contact the clinic for reception hours."
    reception_response: str = "Reception will reply during opening hours."
    whatsapp_outreach_enabled: bool = False

    # Sarvam Voice Agents — used only by the public web wrapper to mint
    # short-lived signed WebSocket URLs. Never expose to the browser.
    sarvam_api_key: str = ""
    sarvam_org_id: str = ""
    sarvam_workspace_id: str = ""
    sarvam_app_id: str = ""
    sarvam_app_version: int | None = None
    sarvam_agent_display_name: str = "Aanya"

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
