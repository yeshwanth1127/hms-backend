from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.config import settings
from app.limits import Limits
from app.main import app


async def echo(request):
    return JSONResponse({"bytes": len(await request.body())})


def client(monkeypatch, now):
    monkeypatch.setattr(settings, "rate_limits_enabled", True)
    inner = Starlette(routes=[Route("/{path:path}", echo, methods=["GET", "POST"])])
    return TestClient(Limits(inner, clock=lambda: now[0]))


def test_public_writes_are_budgeted_per_minute_and_reset(monkeypatch):
    now = [0.0]
    c = client(monkeypatch, now)
    for _ in range(60):
        assert c.post("/api/v1/web/booking/session").status_code == 200
    blocked = c.post("/api/v1/web/booking/session")
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert blocked.headers["retry-after"] == "60"
    assert c.get("/api/v1/doctors").status_code == 200  # reads keep their own budget
    now[0] = 61
    assert c.post("/api/v1/web/booking/session").status_code == 200


def test_staff_sessions_get_their_own_budget_and_services_are_exempt(monkeypatch):
    now = [0.0]
    c = client(monkeypatch, now)
    for _ in range(600):
        assert c.get("/api/v1/admin/appointments", cookies={"hms_staff_session": "nurse-a"}).status_code == 200
    assert c.get("/api/v1/admin/appointments", cookies={"hms_staff_session": "nurse-a"}).status_code == 429
    # A second nurse behind the same clinic address is unaffected.
    assert c.get("/api/v1/admin/appointments", cookies={"hms_staff_session": "nurse-b"}).status_code == 200
    for _ in range(700):
        assert c.post("/api/v1/integrations/whatsapp/inbound/claim",
                      headers={"X-Service-Key": settings.whatsapp_service_api_key}).status_code == 200


def test_one_address_has_an_overall_ceiling_even_with_fresh_cookies(monkeypatch):
    now = [0.0]
    c = client(monkeypatch, now)
    for i in range(1200):
        c.get("/api/v1/admin/x", cookies={"hms_staff_session": f"forged-{i}"})
    assert c.get("/api/v1/admin/x", cookies={"hms_staff_session": "forged-new"}).status_code == 429


def test_oversized_bodies_are_rejected_before_parsing_or_auth(monkeypatch):
    now = [0.0]
    c = client(monkeypatch, now)
    assert c.post("/api/v1/web/booking/session", content=b"x" * (256 * 1024 + 1)).status_code == 413
    streamed = c.post("/api/v1/web/booking/session", content=iter([b"x" * 200_000, b"x" * 200_000]))
    assert streamed.status_code == 413
    upload = c.post("/api/v1/admin/doctors/d/photo", content=b"x" * (1024 * 1024),
                    headers={"content-type": "multipart/form-data; boundary=x"})
    assert upload.json() == {"bytes": 1024 * 1024}


def test_real_app_rejects_large_unauthenticated_body_with_413():
    with TestClient(app) as c:
        response = c.post("/api/v1/staff/login", content=b"{" + b" " * (300 * 1024) + b"}",
                          headers={"content-type": "application/json"})
        chunked = c.post("/api/v1/staff/login", content=iter([b"{" + b" " * 200_000, b" " * 200_000 + b"}"]),
                         headers={"content-type": "application/json"})
    assert response.status_code == 413
    # FastAPI rewraps errors raised mid-read as 400; what matters is reading stopped at the cap.
    assert chunked.status_code in (400, 413)
