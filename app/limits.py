"""Per-client request budgets and request body caps, applied before any route or body parsing.

FastAPI reads JSON and multipart bodies before running auth dependencies, so the body cap
must live here to stop unauthenticated memory/disk exhaustion.
"""
import hashlib
import json
import secrets
import time
import uuid

from starlette.exceptions import HTTPException

from .config import settings

UPLOAD_PATHS = ("/api/v1/admin/", "/api/v1/integrations/whatsapp/cases/")
UPLOAD_BYTES = 20 * 1024 * 1024
BODY_BYTES = 256 * 1024
WRITE = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_WRITES = ("/api/v1/web/", "/api/v1/staff/login", "/api/v1/slot-holds", "/api/v1/appointments")
STAFF = ("/api/v1/admin/", "/api/v1/staff/")


def budgets(method: str, path: str, ip: str, staff_cookie: str | None):
    """(bucket, per-minute limit) pairs; every one must have room. Flood control only: mobile CGNAT and a
    clinic's NAT put many real people on one address. Abuse budgets live in the DB (verification, holds, login)."""
    yield "ip:" + ip, 1200
    if method in WRITE and path.startswith(PUBLIC_WRITES):
        yield "public-write:" + ip, 60
    elif path.startswith("/api/") and not path.startswith(STAFF):
        yield "public:" + ip, 600
    if staff_cookie and path.startswith(STAFF):
        yield "staff:" + hashlib.sha256(staff_cookie.encode()).hexdigest(), 600


def is_service(headers: dict) -> bool:
    key = headers.get("x-service-key", "").encode("latin-1")
    return bool(key) and any(secrets.compare_digest(key, s.encode()) for s in (
        settings.whatsapp_service_api_key, settings.voice_service_api_key))


class Limits:
    # ponytail: in-process fixed window; matches the single PM2 uvicorn worker. Move to nginx
    # limit_req or Redis before running more than one worker, or limits multiply per worker.
    def __init__(self, app, clock=time.monotonic):
        self.app, self.clock, self.window, self.counts = app, clock, -1, {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        path, method = scope["path"], scope["method"]
        cap = UPLOAD_BYTES if path.startswith(UPLOAD_PATHS) and "multipart/" in headers.get("content-type", "") else BODY_BYTES
        if headers.get("content-length", "0").isdigit() and int(headers.get("content-length", "0")) > cap:
            return await reject(send, 413, "REQUEST_TOO_LARGE", "The request is too large.")
        if settings.rate_limits_enabled and not is_service(headers):
            window = int(self.clock() // 60)
            if window != self.window:
                self.window, self.counts = window, {}
            cookies = dict(p.strip().split("=", 1) for p in headers.get("cookie", "").split(";") if "=" in p)
            ip = scope["client"][0] if scope.get("client") else "unknown"
            buckets = list(budgets(method, path, ip, cookies.get("hms_staff_session")))
            if any(self.counts.get(b, 0) >= limit for b, limit in buckets):
                retry = str(60 - int(self.clock() % 60))
                return await reject(send, 429, "RATE_LIMITED", "Too many requests. Wait a moment and try again.", retry)
            for b, _ in buckets:
                self.counts[b] = self.counts.get(b, 0) + 1

        received = 0

        async def capped():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > cap:  # chunked bodies have no Content-Length to check up front
                raise HTTPException(413, "The request is too large.")
            return message

        await self.app(scope, capped, send)


async def reject(send, status, code, message, retry_after=None):
    body = json.dumps({"error": {"code": code, "message": message, "request_id": f"req_{uuid.uuid4().hex}"}}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
               (b"cache-control", b"no-store")]
    if retry_after:
        headers.append((b"retry-after", retry_after.encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
