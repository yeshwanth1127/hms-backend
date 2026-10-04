from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite:///./avocado.db"
    redis_url: str = "redis://localhost:6379/0"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5567,http://127.0.0.1:5567"
    slot_hold_minutes: int = 7
    admin_api_key: str = "dev-admin-key"
    voice_service_api_key: str = "dev-voice-service-key"
    whatsapp_service_api_key: str = "dev-whatsapp-service-key"
    whatsapp_owner_secret: str = "dev-whatsapp-owner-secret"
    media_dir: str = "./uploads"
    session_cookie_name: str = "exora_session"
    session_hours: int = 12
    secure_cookies: bool = False
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "change-me-in-production"
    jitsi_domain: str = "meet.exora.local"
    jitsi_app_id: str = "exora-hms"
    jitsi_issuer: str = "exora-hms"
    jitsi_secret: str = "dev-jitsi-secret-change-me"
    jitsi_token_minutes: int = 5
    teleconsultation_join_early_minutes: int = 15
    teleconsultation_join_late_minutes: int = 60
    teleconsultation_consent_version: str = "2026-10-02"
    default_hospital_slug: str = "exora-demo"
    sarvam_api_key: str = ""
    sarvam_org_id: str = "019f7b91-eaca-7818-8fc0-25d1ff90fbfe"
    sarvam_workspace_id: str = "019f7b91-eade-7262-9caf-22133694b2d5"
    sarvam_agent_id: str = "Conversatio-47382521-7c72"
    sarvam_agent_name: str = "Avocado Health Front Desk"
    sarvam_runtime_url: str = "https://apps.sarvam.ai/api/app-runtime/"

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
