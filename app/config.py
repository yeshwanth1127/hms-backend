from functools import lru_cache
from pydantic import field_validator

from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    demo_mode: bool = False
    demo_workspace: str = "./.local/clinic-demo"
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
    web_booking_enabled: bool = False
    web_booking_origin: str = ""
    whatsapp_booking_number: str = ""
    slot_hold_minutes: int = 7
    rate_limits_enabled: bool = True
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
    sarvam_api_key: SecretStr = SecretStr("")
    sarvam_org_id: str = ""
    sarvam_workspace_id: str = ""
    sarvam_app_id: str = ""
    sarvam_app_version: int | None = Field(default=None, ge=1)
    sarvam_agent_display_name: str = "Aanya"
    voice_website_booking_url: str = "/schedule-appointment"
    voice_calls_per_ip_hour: int = Field(default=5, ge=1, le=100)
    voice_calls_per_day: int = Field(default=200, ge=1, le=100000)
    voice_max_concurrent: int = Field(default=10, ge=1, le=1000)
    voice_session_minutes: int = Field(default=20, ge=1, le=120)
    voice_recording_access_days: int = Field(default=30, ge=1, le=90)
    # Set only after checking the provider recording response in this workspace.
    sarvam_recording_url_field: str = ""
    voice_recording_hosts: str = ""


    @field_validator("sarvam_app_version", mode="before")
    @classmethod
    def empty_sarvam_version(cls, value):
        # An unconfigured optional version is blank in the deployment example.
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
