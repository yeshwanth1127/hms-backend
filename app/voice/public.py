from typing import Literal
from fastapi import APIRouter, Depends, Request, Response, Query
from pydantic import BaseModel, ConfigDict, StrictBool, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..config import settings
from ..client_modules import ensure_module
from ..db import get_db
from ..models import VoiceSession, utcnow
from ..services import DomainError
from . import provider
from .admission import COOKIE, NOTICE, NOTICE_VERSION, admit, guest, origin_check, gate

router = APIRouter(prefix="/api/v1/web", tags=["web-voice"])


class Admission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recording_consent: StrictBool

    @field_validator("recording_consent")
    @classmethod
    def require_consent(cls, value):
        if not value:
            raise ValueError("Recording consent is required to start a call")
        return value

    notice_version: Literal["recording-v1"]


@router.get("/voice/config")
def config(response: Response, db: Session = Depends(get_db)):
    ensure_module(db, "voice")
    if not provider.configured():
        raise DomainError(
            "VOICE_NOT_CONFIGURED",
            "Voice calling is not configured. Please contact reception.",
            503,
        )
    response.headers["Cache-Control"] = "no-store"
    return {
        "org_id": settings.sarvam_org_id,
        "workspace_id": settings.sarvam_workspace_id,
        "app_id": settings.sarvam_app_id,
        "version": settings.sarvam_app_version,
        "agent_name": settings.sarvam_agent_display_name,
        "runtime_base_url": "/api/v1/web/sarvam/",
        "sample_rate": 16000,
        "session_seconds": settings.voice_session_minutes * 60,
        "recording_notice": NOTICE.format(days=settings.voice_recording_access_days),
        "notice_version": NOTICE_VERSION,
        "website_booking_url": settings.voice_website_booking_url,
    }


@router.post("/voice/sessions", status_code=201)
def start(
    body: Admission, request: Request, response: Response, db: Session = Depends(get_db)
):
    origin_check(request)
    session, token = admit(db, request)
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.voice_session_minutes * 60,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="strict",
        path="/api/v1/web",
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "runtime_session_id": session.runtime_session_id,
        "agent_version": session.agent_version,
    }


@router.get("/sarvam/orgs/{org_id}/workspaces/{workspace_id}/apps/{app_id}/url")
def mint(
    org_id: str,
    workspace_id: str,
    app_id: str,
    request: Request,
    response: Response,
    interaction_type: Literal["call"] = Query("call"),
    version: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    origin_check(request)
    ensure_module(db, "voice")
    if not provider.configured() or [org_id, workspace_id, app_id] != [
        settings.sarvam_org_id,
        settings.sarvam_workspace_id,
        settings.sarvam_app_id,
    ]:
        raise DomainError(
            "VOICE_AGENT_FORBIDDEN", "Unknown or unavailable voice agent.", 403
        )
    session = guest(db, request)
    if (
        version is not None
        and version != session.agent_version
        or session.agent_version != settings.sarvam_app_version
    ):
        raise DomainError(
            "VOICE_VERSION_FORBIDDEN",
            "Start a new call with the approved agent version.",
            403,
        )
    gate(db)
    session = db.scalar(
        select(VoiceSession)
        .where(VoiceSession.id == session.id)
        .execution_options(populate_existing=True)
    )
    if session.mint_claimed or session.status != "issued":
        raise DomainError(
            "VOICE_URL_ALREADY_ISSUED",
            "Start a new call. Each connection can be used once.",
            409,
        )
    session.mint_claimed = True
    db.commit()
    try:
        data = provider.mint()
        session.provider_reference = data["reference_id"]
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        session.status = "error"
        session.ended_at = utcnow()
        db.commit()
        raise DomainError(
            "VOICE_PROVIDER_INVALID",
            "The provider returned a reused session reference.",
            502,
        ) from exc
    except Exception:
        db.rollback()
        session.status = "error"
        session.ended_at = utcnow()
        db.commit()
        raise
    response.headers["Cache-Control"] = "no-store"
    return {**data, "guest_id": session.runtime_session_id}


@router.post("/voice/sessions/end")
def browser_end(request: Request, response: Response, db: Session = Depends(get_db)):
    origin_check(request)
    session = guest(db, request)
    gate(db)
    session = db.scalar(
        select(VoiceSession)
        .where(VoiceSession.id == session.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Browser termination is an abandonment hint, never proof of call completion.
    if session.status in ("issued", "active"):
        session.status = "abandoned"
        session.ended_at = utcnow()
        db.commit()
    response.delete_cookie(COOKIE, path="/api/v1/web")
    response.headers["Cache-Control"] = "no-store"
    return {"status": session.status}
