import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import router
from .admin import router as admin_router
from .integrations import router as integrations_router
from .config import settings
from .db import Base, SessionLocal, engine
from .seed import seed_catalogue
from .services import DomainError


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env == "production" and settings.admin_api_key == "dev-admin-key":
        raise RuntimeError("ADMIN_API_KEY must be changed in production")
    if settings.app_env == "production" and settings.voice_service_api_key == "dev-voice-service-key":
        raise RuntimeError("VOICE_SERVICE_API_KEY must be changed in production")
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
    return response


@app.exception_handler(DomainError)
async def domain_error(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"error": {
        "code": exc.code, "message": exc.message, "request_id": request.state.request_id,
    }})


@app.get("/api/health/live")
def live():
    return {"alive": True}


@app.get("/api/health/ready")
def ready():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"ready": True}


app.include_router(router)
app.include_router(admin_router)
app.include_router(integrations_router)
