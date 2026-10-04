from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_voice_agent_config_never_exposes_api_key():
    original = settings.sarvam_api_key
    settings.sarvam_api_key = "secret-test-key"
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/voice-agent/config")
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is True
        assert body["provider"] == "sarvam"
        assert body["agent_id"] == settings.sarvam_agent_id
        assert "api_key" not in body
        assert "secret-test-key" not in response.text
    finally:
        settings.sarvam_api_key = original


def test_signed_url_proxy_rejects_unconfigured_and_unknown_agents():
    original = settings.sarvam_api_key
    path = (
        f"/api/v1/sarvam-runtime/orgs/{settings.sarvam_org_id}/workspaces/"
        f"{settings.sarvam_workspace_id}/apps/{settings.sarvam_agent_id}/url"
    )
    try:
        with TestClient(app) as client:
            settings.sarvam_api_key = ""
            assert client.get(path).status_code == 503
            settings.sarvam_api_key = "secret-test-key"
            unknown = path.replace(settings.sarvam_agent_id, "unknown-agent")
            assert client.get(unknown).status_code == 404
            assert client.get(path, params={"interaction_type": "invalid"}).status_code == 422
    finally:
        settings.sarvam_api_key = original
