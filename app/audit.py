"""Clinic-wide audit trail: one append-only record per state-changing request.

The request middleware opens a context; auth code names the actor and handlers add before/after
detail with `note()`. Bodies, passwords and verification codes are never recorded.
"""
import csv
import io
import json
import logging
import secrets
from contextvars import ContextVar
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditEvent
from .staff_auth import require_staff_owner

log = logging.getLogger("hms.audit")
WRITES = {"POST", "PUT", "PATCH", "DELETE"}
_context: ContextVar[dict | None] = ContextVar("audit", default=None)
router = APIRouter(prefix="/api/v1/staff/audit", tags=["audit"])


def begin() -> dict:
    context = {"actor": None, "change": {}, "targets": {}}
    _context.set(context)
    return context


def actor(kind: str, ident: str, label: str) -> None:
    """Name who is acting. Later, more specific calls win (a staff session over a cookie guess)."""
    if (context := _context.get()) is not None:
        context["actor"] = (kind, str(ident)[:80], str(label)[:160])


def note(*, targets: dict | None = None, **change) -> None:
    """Attach what changed (before/after values, ids). Never pass free text or secrets."""
    if (context := _context.get()) is not None:
        context["change"].update(change)
        context["targets"].update({k: str(v) for k, v in (targets or {}).items() if v is not None})


def diff(before: dict, after: dict) -> dict:
    return {key: {"from": before.get(key), "to": after.get(key)} for key in after if before.get(key) != after.get(key)}


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


def resolve_actor(context: dict, request) -> None:
    """Services authenticate by header; everyone else is named by the auth code that accepted them."""
    if context["actor"] is None:
        key = request.headers.get("x-service-key", "").encode("latin-1", "replace")
        for name, secret in (("whatsapp", settings.whatsapp_service_api_key), ("voice", settings.voice_service_api_key)):
            if key and secret and secrets.compare_digest(key, secret.encode()):
                context["actor"] = ("service", name, f"{name.capitalize()} service")


def record(context: dict, *, app, method: str, scope: dict, status_code: int, request_id: str, client_ip: str) -> None:
    route = scope.get("route")
    targets = {**{k: str(v) for k, v in (scope.get("path_params") or {}).items()}, **context["targets"]}
    kind, ident, label = context["actor"] or ("anonymous", "anonymous", "Unidentified caller")
    row = dict(request_id=request_id, actor_type=kind, actor_id=ident, actor_label=label,
               action=f"{method} {getattr(route, 'path', scope['path'])}"[:160], targets=targets,
               target_text=" ".join(targets.values())[:400], change=_jsonable(context["change"]),
               status_code=status_code, client_ip=client_ip[:64])
    # Same database the request used (tests override get_db), on its own session.
    sessions = app.dependency_overrides.get(get_db, get_db)()
    try:
        db = next(sessions)
        db.add(AuditEvent(**row))
        db.commit()
    except Exception:  # never fail the clinic action because the audit store is down
        log.exception("AUDIT_WRITE_FAILED %s", json.dumps(row, default=str))
    finally:
        sessions.close()


def row(item: AuditEvent) -> dict:
    created = item.created_at if item.created_at.tzinfo else item.created_at.replace(tzinfo=timezone.utc)
    return {"id": item.id, "created_at": created.isoformat(), "request_id": item.request_id,
            "actor_type": item.actor_type, "actor_id": item.actor_id, "actor": item.actor_label,
            "action": item.action, "targets": item.targets, "change": item.change,
            "status_code": item.status_code, "outcome": "success" if item.status_code < 400 else "rejected",
            "client_ip": item.client_ip}


def search(db, actor_query, target, action, outcome, start, end):
    statement = select(AuditEvent)
    if actor_query:
        pattern = f"%{actor_query.strip()}%"
        statement = statement.where(AuditEvent.actor_label.ilike(pattern) | (AuditEvent.actor_id == actor_query.strip()))
    if target:
        statement = statement.where(AuditEvent.target_text.ilike(f"%{target.strip()}%"))
    if action:
        statement = statement.where(AuditEvent.action.ilike(f"%{action.strip()}%"))
    if outcome == "success":
        statement = statement.where(AuditEvent.status_code < 400)
    elif outcome == "rejected":
        statement = statement.where(AuditEvent.status_code >= 400)
    india = timezone(timedelta(hours=5, minutes=30))
    if start:
        statement = statement.where(AuditEvent.created_at >= datetime.combine(start, time.min, india))
    if end:
        statement = statement.where(AuditEvent.created_at < datetime.combine(end + timedelta(days=1), time.min, india))
    return statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id)


@router.get("")
def activity(actor: str | None = None, target: str | None = None, action: str | None = None,
             outcome: str | None = Query(None, pattern="^(success|rejected)$"), start: date | None = None,
             end: date | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
             _=Depends(require_staff_owner), db: Session = Depends(get_db)):
    items = db.scalars(search(db, actor, target, action, outcome, start, end).offset(offset).limit(limit + 1)).all()
    return {"items": [row(item) for item in items[:limit]], "more": len(items) > limit}


@router.get(".csv")
def export(actor: str | None = None, target: str | None = None, action: str | None = None,
           outcome: str | None = Query(None, pattern="^(success|rejected)$"), start: date | None = None,
           end: date | None = None, _=Depends(require_staff_owner), db: Session = Depends(get_db)):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["time", "actor", "actor_type", "action", "records", "change", "status", "request_id", "client_ip"])
    # ponytail: capped export; add streaming if one filter ever needs more than 50k rows.
    for item in db.scalars(search(db, actor, target, action, outcome, start, end).limit(50_000)):
        r = row(item)
        # Leading =,+,-,@ would run as spreadsheet formulas when opened in Excel.
        cells = [r["created_at"], r["actor"], r["actor_type"], r["action"], json.dumps(r["targets"]),
                 json.dumps(r["change"]), r["status_code"], r["request_id"], r["client_ip"]]
        writer.writerow(["'" + c if isinstance(c, str) and c[:1] in "=+-@" else c for c in cells])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="clinic-activity-log.csv"'})
