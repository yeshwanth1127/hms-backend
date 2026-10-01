"""Public admission, trusted lifecycle, booking ownership and recording boundaries."""

from datetime import timedelta
import socket
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import pytest
import httpx
from pydantic import SecretStr
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db import Base, get_db
from app.config import settings
from app.models import (
    ClientModule,
    VoiceSession,
    VoiceRecordingAccess,
    VoiceRateLimit,
    StaffUser,
    utcnow,
)
from app.seed import seed_catalogue
from app.staff_auth import password_hash
from app.voice import provider
from app.services import DomainError

WEB = "/api/v1/web/voice"
MINT = "/api/v1/web/sarvam/orgs/org/workspaces/workspace/apps/app/url"
SERVICE = {"X-Service-Key": "dev-voice-service-key"}
CONSENT = {"recording_consent": True, "notice_version": "recording-v1"}
PASSWORD = "private-test-password"


@pytest.fixture
def voice(monkeypatch):
    pg = os.environ.get("HMS_VOICE_DATABASE_URL")
    schema = "voice_test_" + uuid4().hex
    if pg:
        raw_engine = create_engine(pg)
        with raw_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = raw_engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    for key, value in {
        "sarvam_api_key": SecretStr("private-provider-key"),
        "sarvam_org_id": "org",
        "sarvam_workspace_id": "workspace",
        "sarvam_app_id": "app",
        "sarvam_app_version": 7,
        "sarvam_recording_url_field": "recording.url",
        "voice_recording_hosts": "cdn.sarvam.ai",
        "voice_max_concurrent": 10,
        "voice_calls_per_ip_hour": 5,
    }.items():
        monkeypatch.setattr(settings, key, value)
    with factory() as db:
        seed_catalogue(db)
        db.add(ClientModule(key="voice", enabled=True))
        for username, role in [
            ("admin", "admin"),
            ("reception", "staff"),
            ("growth", "growth_manager"),
        ]:
            db.add(
                StaffUser(
                    username=username,
                    display_name=username,
                    role=role,
                    password_hash=password_hash(PASSWORD),
                )
            )
        db.commit()
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.pop(get_db)
    if pg:
        with raw_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        raw_engine.dispose()
    else:
        engine.dispose()


def admitted(client, monkeypatch):
    started = client.post(WEB + "/sessions", json=CONSENT)
    assert started.status_code == 201, started.text
    runtime = started.json()["runtime_session_id"]
    monkeypatch.setattr(
        provider,
        "mint",
        lambda: {
            "url": "wss://runtime.sarvam.ai/test",
            "reference_id": "ref-" + runtime,
        },
    )
    assert client.get(MINT, params={"version": 7}).status_code == 200
    body = {
        "runtime_session_id": runtime,
        "interaction_id": "interaction-" + runtime,
        "agent_version": 7,
        "channel": "web_voice",
        "provider_reference": "ref-" + runtime,
    }
    response = client.post(
        "/api/v1/integrations/voice/sessions", headers=SERVICE, json=body
    )
    assert response.status_code == 201, response.text
    return response.json()


def sign_in(client, name="admin"):
    result = client.post(
        "/api/v1/staff/login", json={"username": name, "password": PASSWORD}
    )
    assert result.status_code == 200
    return {"X-CSRF-Token": result.json()["csrf_token"]}


def test_admission_requires_explicit_consent_and_pins_single_use_version(
    voice, monkeypatch
):
    c, f = voice
    calls = []
    monkeypatch.setattr(
        provider,
        "mint",
        lambda: calls.append(1)
        or {"url": "wss://runtime.sarvam.ai/test", "reference_id": "ref-single"},
    )
    assert c.get(MINT).status_code == 403
    for value in [False, 1, "true"]:
        assert (
            c.post(
                WEB + "/sessions", json={**CONSENT, "recording_consent": value}
            ).status_code
            == 422
        )
    assert (
        c.post(
            WEB + "/sessions", json=CONSENT, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    started = c.post(WEB + "/sessions", json=CONSENT)
    assert started.status_code == 201
    assert "HttpOnly" in started.headers["set-cookie"]
    assert "private-provider-key" not in c.get(WEB + "/config").text
    assert c.post(WEB + "/sessions", json=CONSENT).status_code == 409
    assert c.get(MINT, params={"version": 8}).status_code == 403
    assert c.get(MINT.replace("/apps/app/", "/apps/other/")).status_code == 403
    assert c.get(MINT, params={"interaction_type": "chat"}).status_code == 422
    assert c.get(MINT, params={"version": 7}).status_code == 200
    assert c.get(MINT).status_code == 409
    assert calls == [1]
    with f() as db:
        row = db.scalar(select(VoiceSession))
        assert (
            row.agent_version == 7
            and row.recording_consent_at
            and row.provider_reference == "ref-single"
        )
        assert row.admission_hash not in str(c.cookies)


def test_expiry_quota_and_proxy_header_do_not_bypass_budgets(voice, monkeypatch):
    c, f = voice
    monkeypatch.setattr(settings, "voice_calls_per_ip_hour", 1)
    assert c.post(WEB + "/sessions", json=CONSENT).status_code == 201
    with f() as db:
        row = db.scalar(select(VoiceSession))
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert c.get(MINT).status_code == 403
    c.cookies.clear()
    assert (
        c.post(
            WEB + "/sessions", json=CONSENT, headers={"X-Forwarded-For": "another-ip"}
        ).status_code
        == 429
    )
    with f() as db:
        assert (
            db.scalar(
                select(VoiceRateLimit).where(VoiceRateLimit.key.like("ip:%"))
            ).count
            == 1
        )


def test_concurrent_capacity_is_reclaimed_on_timeout(voice, monkeypatch):
    c, f = voice
    monkeypatch.setattr(settings, "voice_max_concurrent", 1)
    assert c.post(WEB + "/sessions", json=CONSENT).status_code == 201
    c.cookies.clear()
    assert c.post(WEB + "/sessions", json=CONSENT).status_code == 429
    with f() as db:
        row = db.scalar(select(VoiceSession))
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert c.post(WEB + "/sessions", json=CONSENT).status_code == 201


def test_unadmitted_runtime_and_foreign_owner_cannot_book(voice):
    c, _ = voice
    assert (
        c.post(
            "/api/v1/integrations/voice/sessions",
            headers=SERVICE,
            json={
                "runtime_session_id": "unadmitted-web",
                "interaction_id": "interaction-123",
                "agent_version": 7,
            },
        ).status_code
        == 403
    )
    doctor = c.get("/api/v1/doctors").json()[0]
    branch = doctor["branches"][0]
    body = {
        "doctor_id": doctor["id"],
        "branch_id": branch["id"],
        "starts_at": "2026-12-01T04:00:00Z",
        "ends_at": "2026-12-01T04:30:00Z",
        "consultation_type": "in_person",
        "owner_key": "foreign-owner",
        "idempotency_key": "untracked-hold-123",
    }
    assert (
        c.post(
            "/api/v1/integrations/voice/slot-holds", headers=SERVICE, json=body
        ).status_code
        == 403
    )
    assert (
        c.get(
            "/api/v1/integrations/voice/appointments",
            headers=SERVICE,
            params={"patient_phone": "+919888888888"},
        ).status_code
        == 422
    )
    assert (
        c.get(
            "/api/v1/integrations/voice/doctors",
            headers=SERVICE,
            params={"department": "made up specialty"},
        ).json()["count"]
        == 0
    )
    assert (
        c.get(
            "/api/v1/integrations/voice/doctors",
            headers=SERVICE,
            params={"branch": "made up branch"},
        ).json()["count"]
        == 0
    )


def test_lifecycle_retries_are_idempotent_and_disabled_module_can_receive_end(
    voice, monkeypatch
):
    c, f = voice
    row = admitted(c, monkeypatch)
    runtime = row["runtime_session_id"]
    base = f"/api/v1/integrations/voice/sessions/{runtime}"
    event = {
        "event_id": "turn-event-0001",
        "kind": "turn",
        "tool_name": "dialogue",
        "intent": "find_doctor",
    }
    assert (
        c.post(base + "/events", headers=SERVICE, json=event).json()["turn_count"] == 1
    )
    assert (
        c.post(base + "/events", headers=SERVICE, json=event).json()["turn_count"] == 1
    )
    assert (
        c.post(
            base + "/events", headers=SERVICE, json={**event, "intent": "book"}
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/api/v1/integrations/voice/sessions",
            headers=SERVICE,
            json={
                "runtime_session_id": runtime,
                "interaction_id": "other-interaction",
                "agent_version": 7,
                "provider_reference": "ref-" + runtime,
            },
        ).status_code
        == 409
    )
    with f() as db:
        db.get(ClientModule, "voice").enabled = False
        db.commit()
    assert c.get(MINT).status_code == 403
    end = {"event_id": "end-event-0001", "status": "completed"}
    first = c.patch(base, headers=SERVICE, json=end)
    assert first.status_code == 200
    assert (
        c.patch(base, headers=SERVICE, json=end).json()["ended_at"]
        == first.json()["ended_at"]
    )
    assert (
        c.patch(
            base,
            headers=SERVICE,
            json={**end, "event_id": "end-event-0002", "status": "error"},
        ).status_code
        == 409
    )


def finished(c, monkeypatch):
    row = admitted(c, monkeypatch)
    assert (
        c.patch(
            "/api/v1/integrations/voice/sessions/" + row["runtime_session_id"],
            headers=SERVICE,
            json={"event_id": "completed-0001", "status": "completed"},
        ).status_code
        == 200
    )
    return row


def test_recordings_admin_csrf_only_no_signed_url_leak_and_audit(voice, monkeypatch):
    c, f = voice
    row = finished(c, monkeypatch)
    path = f"/api/v1/staff/voice/sessions/{row['id']}/recording"
    assert c.post(path).status_code == 401
    staff = sign_in(c, "reception")
    assert c.get("/api/v1/staff/voice").status_code == 200
    assert c.post(path, headers=staff).status_code == 403
    assert c.get("/api/v1/staff/voice/recording-access").status_code == 403
    sign_in(c, "growth")
    assert c.get("/api/v1/staff/voice").status_code == 403
    admin = sign_in(c)
    assert c.post(path).status_code == 403
    monkeypatch.setattr(
        provider, "recording_url", lambda _: "https://cdn.sarvam.ai/signed-secret"
    )
    monkeypatch.setattr(
        provider, "download_recording", lambda _: (b"fixture-audio", "audio/mpeg")
    )
    result = c.post(path, headers=admin)
    assert result.status_code == 200 and result.content == b"fixture-audio"
    assert result.headers["cache-control"] == "no-store, private"
    assert "signed-secret" not in c.get("/api/v1/staff/voice").text
    log = c.get("/api/v1/staff/voice/recording-access").json()
    assert (
        len(log) == 1
        and log[0]["outcome"] == "delivered"
        and log[0]["actor"] == "admin"
    )


@pytest.mark.parametrize(
    "state,status",
    [("no_consent", 403), ("expired", 410), ("pending", 409), ("not_configured", 503)],
)
def test_recording_guards_never_contact_provider(voice, monkeypatch, state, status):
    c, f = voice
    row = finished(c, monkeypatch)
    with f() as db:
        item = db.get(VoiceSession, row["id"])
        if state == "no_consent":
            item.recording_consent_at = None
        if state == "expired":
            item.recording_available_until = utcnow() - timedelta(seconds=1)
        if state == "pending":
            item.interaction_id = None
        db.commit()
    if state == "not_configured":
        monkeypatch.setattr(settings, "sarvam_recording_url_field", "")
    monkeypatch.setattr(
        provider, "recording_url", lambda _: pytest.fail("Guard contacted provider")
    )
    result = c.post(
        f"/api/v1/staff/voice/sessions/{row['id']}/recording", headers=sign_in(c)
    )
    assert result.status_code == status
    with f() as db:
        assert db.scalar(select(VoiceRecordingAccess)).outcome == state


def test_provider_error_is_generic_and_failed_mint_is_not_retryable(voice, monkeypatch):
    c, f = voice
    assert c.post(WEB + "/sessions", json=CONSENT).status_code == 201
    original_client = httpx.Client

    def fail(request):
        raise httpx.ConnectError("private-provider-key")

    monkeypatch.setattr(
        provider.httpx,
        "Client",
        lambda **kw: original_client(transport=httpx.MockTransport(fail), **kw),
    )
    response = c.get(MINT)
    assert response.status_code == 502 and "private-provider-key" not in response.text
    assert c.get(MINT).status_code == 409
    with f() as db:
        assert db.scalar(select(VoiceSession)).status == "error"


def test_recording_adapter_fails_closed_on_unknown_schema_host_and_private_dns(
    voice, monkeypatch
):
    monkeypatch.setattr(
        provider,
        "request_json",
        lambda *a, **kw: {"unexpected": "https://cdn.sarvam.ai/audio"},
    )
    with pytest.raises(DomainError) as error:
        provider.recording_url("interaction-id")
    assert error.value.code == "VOICE_RECORDING_PENDING"
    for url in [
        "http://cdn.sarvam.ai/audio",
        "https://evil.example/audio",
        "https://cdn.sarvam.ai:invalid/audio",
        "https://user:pass@cdn.sarvam.ai/audio",
    ]:
        with pytest.raises(DomainError):
            provider.validate_recording_url(url)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))]
    )
    with pytest.raises(DomainError):
        provider.validate_recording_url("https://cdn.sarvam.ai/audio")
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )
    monkeypatch.setattr(
        provider,
        "request_json",
        lambda *a, **kw: {"recording": {"url": "https://cdn.sarvam.ai/audio"}},
    )
    assert provider.recording_url("interaction-id") == "https://cdn.sarvam.ai/audio"


def test_voice_defaults_disabled_including_legacy_history(voice):
    c, factory = voice
    with factory() as db:
        db.delete(db.get(ClientModule, "voice"))
        db.commit()
    assert c.get(WEB + "/config").status_code == 403
    assert c.post(WEB + "/sessions", json=CONSENT).status_code == 403
    assert (
        c.get("/api/v1/integrations/voice/doctors", headers=SERVICE).status_code == 403
    )
    assert (
        c.get(
            "/api/v1/admin/voice-sessions", headers={"X-Admin-Key": "dev-admin-key"}
        ).status_code
        == 403
    )


def test_trusted_web_binding_requires_the_matching_provider_reference(
    voice, monkeypatch
):
    c, factory = voice
    issued = c.post(WEB + "/sessions", json=CONSENT).json()
    monkeypatch.setattr(
        provider,
        "mint",
        lambda: {
            "url": "wss://runtime.sarvam.ai/test",
            "reference_id": "real-session-reference",
        },
    )
    assert c.get(MINT).status_code == 200
    body = {
        "runtime_session_id": issued["runtime_session_id"],
        "interaction_id": "trusted-interaction",
        "agent_version": 7,
    }
    assert (
        c.post(
            "/api/v1/integrations/voice/sessions", headers=SERVICE, json=body
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/v1/integrations/voice/sessions",
            headers=SERVICE,
            json={**body, "provider_reference": "wrong-session-reference"},
        ).status_code
        == 409
    )
    assert (
        c.post(
            "/api/v1/integrations/voice/sessions",
            headers=SERVICE,
            json={**body, "provider_reference": "real-session-reference"},
        ).status_code
        == 201
    )


def test_provider_mint_is_pinned_and_audio_host_receives_no_secret(voice, monkeypatch):
    original_client = httpx.Client
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.host == "apps.sarvam.ai":
            return httpx.Response(
                200,
                json={
                    "url": "wss://runtime.sarvam.ai/connect",
                    "reference_id": "provider-test-reference",
                },
            )
        return httpx.Response(
            200, content=b"audio-fixture", headers={"content-type": "audio/mpeg"}
        )

    monkeypatch.setattr(
        provider.httpx,
        "Client",
        lambda **kw: original_client(transport=httpx.MockTransport(respond), **kw),
    )
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )
    assert provider.mint()["reference_id"] == "provider-test-reference"
    assert seen[0].url.params["version"] == "7"
    assert seen[0].headers["X-API-Key"] == "private-provider-key"
    assert (
        provider.download_recording("https://cdn.sarvam.ai/audio")[0]
        == b"audio-fixture"
    )
    assert "x-api-key" not in seen[1].headers and "cookie" not in seen[1].headers


@pytest.mark.parametrize(
    "mime,content",
    [("text/html", b"unexpected"), ("audio/mpeg", b""), ("audio/mpeg", b"too-large")],
)
def test_recording_download_rejects_invalid_empty_and_oversized_audio(
    voice, monkeypatch, mime, content
):
    original_client = httpx.Client
    monkeypatch.setattr(provider, "MAX_RECORDING_BYTES", 4)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443))]
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, content=content, headers={"content-type": mime})
    )
    monkeypatch.setattr(
        provider.httpx,
        "Client",
        lambda **kw: original_client(transport=transport, **kw),
    )
    with pytest.raises(DomainError) as error:
        provider.download_recording("https://cdn.sarvam.ai/audio")
    assert error.value.code == "VOICE_RECORDING_UNAVAILABLE"


@pytest.mark.skipif(
    not os.environ.get("HMS_VOICE_DATABASE_URL"),
    reason="PostgreSQL cross-connection admission concurrency",
)
def test_postgres_concurrent_admission_capacity_and_single_use_mint(voice, monkeypatch):
    _, factory = voice
    monkeypatch.setattr(settings, "voice_calls_per_ip_hour", 3)
    monkeypatch.setattr(settings, "voice_max_concurrent", 10)

    def admit_call(_):
        # Independent cookies and DB connections, matching separate callers/workers.
        c = TestClient(app)
        try:
            response = c.post(WEB + "/sessions", json=CONSENT)
            return response.status_code, response.headers.get("set-cookie")
        finally:
            c.close()

    with ThreadPoolExecutor(6) as threads:
        results = list(threads.map(admit_call, range(6)))
    assert Counter(r[0] for r in results) == {201: 3, 429: 3}
    with factory() as db:
        rows = db.scalars(select(VoiceSession)).all()
        assert len(rows) == 3
        for row in rows:
            row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    monkeypatch.setattr(settings, "voice_calls_per_ip_hour", 20)
    monkeypatch.setattr(settings, "voice_max_concurrent", 2)
    with ThreadPoolExecutor(5) as threads:
        results = list(threads.map(admit_call, range(5)))
    assert Counter(r[0] for r in results) == {201: 2, 429: 3}
    cookie = next(r[1].split(";")[0] for r in results if r[0] == 201)
    calls = []

    def mint():
        calls.append(1)
        return {
            "url": "wss://runtime.sarvam.ai/test",
            "reference_id": "pg-mint-reference",
        }

    monkeypatch.setattr(provider, "mint", mint)

    def mint_call(_):
        c = TestClient(app)
        try:
            return c.get(MINT, headers={"Cookie": cookie}).status_code
        finally:
            c.close()

    with ThreadPoolExecutor(5) as threads:
        outcomes = list(threads.map(mint_call, range(5)))
    assert Counter(outcomes) == {200: 1, 409: 4}
    assert calls == [1]


def test_browser_abandonment_does_not_overwrite_a_trusted_completion(
    voice, monkeypatch
):
    c, factory = voice
    row = admitted(c, monkeypatch)
    path = "/api/v1/integrations/voice/sessions/" + row["runtime_session_id"]
    assert c.post(WEB + "/sessions/end").json()["status"] == "abandoned"
    assert (
        c.patch(
            path,
            headers=SERVICE,
            json={"event_id": "trusted-end-event", "status": "completed"},
        ).status_code
        == 200
    )
    # A delayed/replayed browser hint has only the original opaque guest token.
    from app.voice.admission import COOKIE, digest
    import secrets

    token = secrets.token_urlsafe(32)
    with factory() as db:
        db.get(VoiceSession, row["id"]).admission_hash = digest(token)
        db.commit()
    c.cookies.set(COOKIE, token)
    assert c.post(WEB + "/sessions/end").json()["status"] == "completed"
