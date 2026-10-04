from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from .config import settings


router = APIRouter(tags=["voice-agent"])


@router.get("/api/v1/voice-agent/config")
def voice_agent_config():
    configured = all((
        settings.sarvam_api_key,
        settings.sarvam_org_id,
        settings.sarvam_workspace_id,
        settings.sarvam_agent_id,
    ))
    return {
        "enabled": configured,
        "provider": "sarvam",
        "agent_name": settings.sarvam_agent_name,
        "org_id": settings.sarvam_org_id if configured else None,
        "workspace_id": settings.sarvam_workspace_id if configured else None,
        "agent_id": settings.sarvam_agent_id if configured else None,
        "runtime_base_url": "/api/v1/sarvam-runtime/",
    }


@router.get("/api/v1/sarvam-runtime/orgs/{org_id}/workspaces/{workspace_id}/apps/{app_id}/url")
async def sarvam_signed_url(
    org_id: str,
    workspace_id: str,
    app_id: str,
    interaction_type: str = Query(default="call", pattern="^(call|chat)$"),
    version: int | None = Query(default=None, ge=1),
):
    if not settings.sarvam_api_key:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "VOICE_AGENT_NOT_CONFIGURED", "message": "Sarvam voice agent is not configured."}},
        )

    if (org_id, workspace_id, app_id) != (
        settings.sarvam_org_id,
        settings.sarvam_workspace_id,
        settings.sarvam_agent_id,
    ):
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "VOICE_AGENT_NOT_FOUND", "message": "Voice agent configuration was not found."}},
        )

    upstream = urljoin(
        settings.sarvam_runtime_url.rstrip("/") + "/",
        f"orgs/{org_id}/workspaces/{workspace_id}/apps/{app_id}/url",
    )
    params: dict[str, str | int] = {"interaction_type": interaction_type}
    if version is not None:
        params["version"] = version

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            result = await client.get(upstream, params=params, headers={"X-API-Key": settings.sarvam_api_key})
    except httpx.RequestError:
        return JSONResponse(
            status_code=502,
            content={"error": {"code": "VOICE_PROVIDER_UNAVAILABLE", "message": "The voice service is temporarily unavailable."}},
        )

    response_headers = {}
    retry_after = result.headers.get("x-retry-after")
    if retry_after:
        response_headers["x-retry-after"] = retry_after
    return Response(
        content=result.content,
        status_code=result.status_code,
        media_type=result.headers.get("content-type", "application/json").split(";", 1)[0],
        headers=response_headers,
    )
