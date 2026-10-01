import pytest
from pydantic import ValidationError

from app.config import Settings


def test_optional_voice_version_accepts_empty_environment(monkeypatch):
    monkeypatch.setenv("SARVAM_APP_VERSION", "")
    assert Settings(_env_file=None).sarvam_app_version is None
    monkeypatch.setenv("SARVAM_APP_VERSION", "7")
    assert Settings(_env_file=None).sarvam_app_version == 7
    monkeypatch.setenv("SARVAM_APP_VERSION", "invalid-version")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
