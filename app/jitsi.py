"""Jitsi is a media transport; HMS authorization is completed before this module is called."""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

from .config import settings


def _part(value: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")


def mint_join_grant(*, room: str, actor_id: str, display_name: str, moderator: bool) -> dict:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jitsi_token_minutes)
    header = _part({"alg": "HS256", "typ": "JWT"})
    payload = _part({
        "aud": settings.jitsi_app_id, "iss": settings.jitsi_issuer,
        "sub": settings.jitsi_domain, "room": room,
        "iat": int(now.timestamp()), "nbf": int(now.timestamp()) - 5, "exp": int(expires.timestamp()),
        "context": {"user": {"id": actor_id, "name": display_name,
                               "moderator": "true" if moderator else "false"}},
    })
    signature = base64.urlsafe_b64encode(hmac.new(settings.jitsi_secret.encode(),
                                                   f"{header}.{payload}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return {"domain": settings.jitsi_domain, "room_name": room,
            "jwt": f"{header}.{payload}.{signature}", "expires_at": expires}
