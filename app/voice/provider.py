"""Bounded Sarvam adapter. No provider payloads or secrets go to diagnostics."""

from urllib.parse import quote, urlparse
import json
import ipaddress
import socket
import httpx
from ..config import settings
from ..services import DomainError

BASE = "https://apps.sarvam.ai"
MAX_RECORDING_BYTES = 50 * 1024 * 1024


def configured():
    return bool(
        settings.sarvam_api_key.get_secret_value()
        and settings.sarvam_org_id
        and settings.sarvam_workspace_id
        and settings.sarvam_app_id
        and settings.sarvam_app_version
    )


def scope_path():
    return "/".join(
        quote(x, safe="")
        for x in [
            settings.sarvam_org_id,
            settings.sarvam_workspace_id,
            settings.sarvam_app_id,
        ]
    )


def request_json(path, params=None):
    try:
        with httpx.Client(
            timeout=15, follow_redirects=False, trust_env=False
        ) as client:
            with client.stream(
                "GET",
                BASE + path,
                params=params,
                headers={"X-API-Key": settings.sarvam_api_key.get_secret_value()},
            ) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 128 * 1024:
                        raise ValueError("Oversized provider response")
                    chunks.append(chunk)
                return json.loads(b"".join(chunks))
    except (httpx.HTTPError, ValueError) as exc:
        raise DomainError(
            "VOICE_PROVIDER_UNAVAILABLE",
            "The voice provider could not complete this request. Try again later.",
            502,
        ) from exc


def mint():
    path = (
        "/api/app-runtime/orgs/"
        + quote(settings.sarvam_org_id, safe="")
        + "/workspaces/"
        + quote(settings.sarvam_workspace_id, safe="")
        + "/apps/"
        + quote(settings.sarvam_app_id, safe="")
        + "/url"
    )
    data = request_json(
        path, {"interaction_type": "call", "version": settings.sarvam_app_version}
    )
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("reference_id"), str)
        or not 1 <= len(data["reference_id"]) <= 160
        or not isinstance(data.get("url"), str)
    ):
        raise DomainError(
            "VOICE_PROVIDER_INVALID",
            "The voice provider returned an invalid session.",
            502,
        )
    try:
        parsed = urlparse(data["url"])
        port = parsed.port
    except ValueError as exc:
        raise DomainError(
            "VOICE_PROVIDER_INVALID",
            "The voice provider returned an invalid session.",
            502,
        ) from exc
    if (
        parsed.scheme != "wss"
        or not parsed.hostname
        or not (
            parsed.hostname == "sarvam.ai" or parsed.hostname.endswith(".sarvam.ai")
        )
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise DomainError(
            "VOICE_PROVIDER_INVALID",
            "The voice provider returned an invalid session.",
            502,
        )
    return {"url": data["url"], "reference_id": data["reference_id"]}


def recording_url(interaction_id):
    # Sarvam documents the endpoint but not the response schema. Deployment must
    # set the exact verified field path; unknown shapes fail closed.
    field = settings.sarvam_recording_url_field
    if not field or not settings.voice_recording_hosts:
        raise DomainError(
            "VOICE_RECORDING_NOT_CONFIGURED",
            "Recording playback needs provider configuration. No recording has been downloaded.",
            503,
        )
    data = request_json(
        "/api/analytics/v1/"
        + scope_path()
        + "/recordings/"
        + quote(interaction_id, safe="")
    )
    for part in field.split("."):
        if not isinstance(data, dict) or part not in data:
            raise DomainError(
                "VOICE_RECORDING_PENDING",
                "The provider recording is not available yet.",
                409,
            )
        data = data[part]
    if not isinstance(data, str):
        raise DomainError(
            "VOICE_RECORDING_INVALID",
            "The provider recording could not be opened.",
            502,
        )
    validate_recording_url(data)
    return data


def validate_recording_url(url):
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise DomainError(
            "VOICE_RECORDING_INVALID",
            "The provider recording address was rejected.",
            502,
        ) from exc
    hosts = {
        h.strip().lower()
        for h in settings.voice_recording_hosts.split(",")
        if h.strip()
    }
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise DomainError(
            "VOICE_RECORDING_INVALID",
            "The provider recording address was rejected.",
            502,
        )
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(a[4][0]).is_global for a in addresses
        ):
            raise ValueError("Non-public address")
    except (OSError, ValueError) as exc:
        raise DomainError(
            "VOICE_RECORDING_INVALID",
            "The provider recording address was rejected.",
            502,
        ) from exc


def download_recording(url):
    validate_recording_url(url)
    try:
        with httpx.Client(
            timeout=20, follow_redirects=False, trust_env=False
        ) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                mime = (
                    response.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                if mime not in {
                    "audio/mpeg",
                    "audio/wav",
                    "audio/x-wav",
                    "audio/ogg",
                    "audio/webm",
                    "audio/mp4",
                }:
                    raise ValueError("Unexpected audio content")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RECORDING_BYTES:
                        raise ValueError("Oversized audio")
                    chunks.append(chunk)
                if not size:
                    raise ValueError("Empty audio")
                return b"".join(chunks), mime
    except (httpx.HTTPError, ValueError) as exc:
        raise DomainError(
            "VOICE_RECORDING_UNAVAILABLE",
            "The recording could not be retrieved. Try again later.",
            502,
        ) from exc
