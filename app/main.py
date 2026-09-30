import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import router
from .admin import router as admin_router
from .integrations import router as integrations_router
from .whatsapp import router as whatsapp_router
from .whatsapp_admin import router as whatsapp_admin_router, page_router as whatsapp_page_router
from .config import settings
from .db import Base, SessionLocal, engine
from .seed import seed_catalogue
from .services import DomainError


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env == "production":
        for name in ("admin_api_key", "voice_service_api_key", "whatsapp_service_api_key", "whatsapp_owner_secret"):
            value = getattr(settings, name)
            if len(value) < 32 or value.startswith(("dev-", "replace-", "test-")):
                raise RuntimeError(f"{name.upper()} must be a strong production secret")
        if not settings.database_url.startswith("postgresql+"):
            raise RuntimeError("Production requires PostgreSQL and completed migrations")
        if not settings.media_dir.startswith("/"):
            raise RuntimeError("MEDIA_DIR must be an absolute persistent directory in production")
        if not settings.media_scan_socket or not settings.media_scan_socket.startswith("/"):
            raise RuntimeError("MEDIA_SCAN_SOCKET must point to a private ClamAV Unix socket in production")
    if settings.app_env in {"development", "test"}:
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            seed_catalogue(db)
    yield


app = FastAPI(title="Avocado Health Core API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/v1/") or request.url.path == "/whatsapp-assets":
        response.headers["Cache-Control"] = "no-store"
    if request.url.path == "/whatsapp-assets":
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
    return response


@app.exception_handler(DomainError)
async def domain_error(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"error": {
        "code": exc.code, "message": exc.message, "request_id": request.state.request_id,
    }})


@app.get("/api/health/live")
def live():
    return {"alive": True, "service": "exora-hospital-backend", "api_version": "v1"}


@app.get("/api/health/ready")
def ready():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"ready": True, "service": "exora-hospital-backend", "api_version": "v1"}


app.include_router(router)
app.include_router(admin_router)
app.include_router(integrations_router)
app.include_router(whatsapp_router)
app.include_router(whatsapp_admin_router)
app.include_router(whatsapp_page_router)
