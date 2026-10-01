"""Public web session mint for the Avocado SaaS voice wrapper.

The browser SDK asks our backend for a signed Sarvam WebSocket URL.
The Sarvam API key never leaves this server.
"""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from .config import settings
from .services import DomainError

router = APIRouter(prefix="/api/v1/web", tags=["web-voice"])

SARVAM_RUNTIME_BASE = "https://apps.sarvam.ai/api/app-runtime/"


def _configured() -> bool:
    return bool(
        settings.sarvam_api_key
        and settings.sarvam_org_id
        and settings.sarvam_workspace_id
        and settings.sarvam_app_id
    )


def _assert_agent_scope(org_id: str, workspace_id: str, app_id: str) -> None:
    if not _configured():
        raise DomainError(
            "VOICE_WEB_NOT_CONFIGURED",
            "Voice web sessions are not configured on this server.",
            503,
        )
    if not (
        secrets.compare_digest(org_id, settings.sarvam_org_id)
        and secrets.compare_digest(workspace_id, settings.sarvam_workspace_id)
        and secrets.compare_digest(app_id, settings.sarvam_app_id)
    ):
        raise DomainError("VOICE_AGENT_FORBIDDEN", "Unknown voice agent.", 403)


@router.get("/voice/config")
def voice_config():
    """Public config the browser needs to start a call (no secrets)."""
    if not _configured():
        raise DomainError(
            "VOICE_WEB_NOT_CONFIGURED",
            "Voice web sessions are not configured on this server.",
            503,
        )
    return {
        "org_id": settings.sarvam_org_id,
        "workspace_id": settings.sarvam_workspace_id,
        "app_id": settings.sarvam_app_id,
        "version": settings.sarvam_app_version or None,
        "agent_name": settings.sarvam_agent_display_name,
        "runtime_base_url": "/api/v1/web/sarvam/",
        "sample_rate": 16000,
    }


@router.get("/sarvam/orgs/{org_id}/workspaces/{workspace_id}/apps/{app_id}/url")
def mint_signed_url(
    request: Request,
    org_id: str,
    workspace_id: str,
    app_id: str,
    interaction_type: str = Query(default="call"),
    version: int | None = Query(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """SDK-compatible signed URL mint. Proxies Sarvam with the server key."""
    _assert_agent_scope(org_id, workspace_id, app_id)
    _ = x_api_key

    params: dict[str, Any] = {"interaction_type": interaction_type}
    pinned = version if version is not None else settings.sarvam_app_version
    if pinned:
        params["version"] = pinned

    upstream = (
        f"{SARVAM_RUNTIME_BASE}orgs/{org_id}/workspaces/{workspace_id}/apps/{app_id}/url"
        f"?{urlencode(params)}"
    )
    req = UrlRequest(upstream, headers={"X-API-Key": settings.sarvam_api_key}, method="GET")
    try:
        with urlopen(req, timeout=20) as response:
            payload = response.read().decode()
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        detail = exc.read().decode(errors="ignore")[:400]
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": "VOICE_SESSION_REJECTED",
                    "message": "The voice runtime refused to start a session.",
                    "upstream_status": exc.code,
                    "request_id": getattr(request.state, "request_id", None),
                    "detail": detail,
                }
            },
        )
    except URLError as exc:
        raise DomainError(
            "VOICE_SESSION_UNAVAILABLE",
            "Could not reach the voice runtime. Try again in a moment.",
            502,
        ) from exc

    if status != 200:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": "VOICE_SESSION_REJECTED",
                    "message": "The voice runtime refused to start a session.",
                    "upstream_status": status,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
        )

    try:
        data = json.loads(payload) if payload else None
    except json.JSONDecodeError as exc:
        raise DomainError(
            "VOICE_SESSION_INVALID",
            "The voice runtime returned an invalid session.",
            502,
        ) from exc

    if not isinstance(data, dict) or not data.get("url") or not data.get("reference_id"):
        raise DomainError(
            "VOICE_SESSION_INVALID",
            "The voice runtime returned an invalid session.",
            502,
        )

    data["guest_id"] = f"web-{uuid.uuid4().hex[:12]}"
    return data
