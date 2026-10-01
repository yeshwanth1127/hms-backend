"""Consent, reception and bounded, staff-approved WhatsApp outreach."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, UploadFile, Request
from fastapi.responses import FileResponse
from .media import save_upload, asset_row, media_path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .staff_auth import staff_label
from .admin import require_admin
from .client_modules import require_whatsapp_module
from .config import settings
from .db import get_db
from .models import (Appointment, Branch, Department, Doctor, MediaAsset, ReminderJob, SupportCase,
                     WhatsAppCampaign, WhatsAppCaseMessage, WhatsAppContact, WhatsAppConsentEvent,
                     WhatsAppDeliveryReceipt, WhatsAppFollowupRule, WhatsAppHandoff,
                     WhatsAppOutbound, WhatsAppTemplate, utcnow)
from .services import DomainError
from .whatsapp import require_whatsapp_service, owner_key

admin_router = APIRouter(prefix="/api/v1/admin/whatsapp", tags=["whatsapp-operations"], dependencies=[Depends(require_whatsapp_module)])
service_router = APIRouter(prefix="/api/v1/integrations/whatsapp", tags=["whatsapp-outreach"])
SENDER = r"^[0-9]{7,20}$"
ACTIVE_SENDS = ("sending", "accepted", "sent", "delivered", "read", "uncertain")


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreferenceChange(StrictBody):
    source_message_id: str = Field(min_length=8, max_length=120)
    service_messages: bool | None = None
    marketing: bool | None = None
    stopped_all: bool | None = None
    language: str | None = Field(default=None, pattern=r"^(en|hi|kn)$")
    branch_id: str | None = Field(default=None, max_length=36)
    interests: list[str] | None = Field(default=None, max_length=20)


class SenderMessage(StrictBody):
    sender_id: str = Field(pattern=SENDER)
    source_message_id: str = Field(min_length=8, max_length=120)
    text: str = Field(default="", max_length=4000)


class StaffHandoff(StrictBody):
    status: str = Field(pattern=r"^(waiting|active|closed)$")
    assigned_to: str = Field(min_length=2, max_length=100)


class StaffReply(StrictBody):
    actor: str = Field(min_length=2, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=120)


class BranchDetails(StrictBody):
    address: str = Field(max_length=500)
    directions_url: str = Field(default="", max_length=500)
    arrival_instructions: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_url(self):
        if self.directions_url and not re.fullmatch(r"https://(?:maps\.google\.com|www\.google\.com|maps\.app\.goo\.gl|goo\.gl)/[^\s]+", self.directions_url):
            raise ValueError("Use an HTTPS Google Maps directions link")
        return self


class TemplateSync(StrictBody):
    templates: list[dict] = Field(max_length=1000)


class Audience(StrictBody):
    branch_id: str | None = Field(default=None, max_length=36)
    interest: str | None = Field(default=None, max_length=80)


class CampaignCreate(StrictBody):
    title: str = Field(min_length=3, max_length=120)
    template_id: str = Field(max_length=80)
    parameters: list[str] = Field(max_length=10)
    asset_id: str | None = Field(default=None, max_length=36)
    audience: Audience = Field(default_factory=Audience)
    scheduled_at: datetime
    rate_paise: int = Field(ge=1, le=100000)
    budget_paise: int = Field(ge=1, le=100000000)

    @model_validator(mode="after")
    def validate_values(self):
        if self.scheduled_at.tzinfo is None:
            raise ValueError("Schedule must include its timezone")
        if any(not p.strip() or len(p) > 200 for p in self.parameters):
            raise ValueError("Each template parameter must contain 1–200 characters")
        return self


class CampaignTest(StrictBody):
    sender_id: str = Field(pattern=SENDER)
    actor: str = Field(min_length=2, max_length=100)


class CampaignApproval(StrictBody):
    audience_hash: str = Field(min_length=64, max_length=64)
    expected_count: int = Field(ge=1, le=1000)
    actor: str = Field(min_length=2, max_length=100)
    test_received: bool


class Transition(StrictBody):
    claim_token: str = Field(min_length=32, max_length=64)
    meta_message_id: str | None = Field(default=None, min_length=8, max_length=120)
    error: str | None = Field(default=None, max_length=240)


class Receipt(StrictBody):
    meta_message_id: str = Field(min_length=8, max_length=120)
    status: str = Field(pattern=r"^(sent|delivered|read|failed)$")
    timestamp: int = Field(ge=0, le=2147483647)


class RuleChange(StrictBody):
    template_id: str = Field(max_length=80)
    delay_hours: int = Field(ge=0, le=720)
    enabled: bool = False


class ManualFollowup(StrictBody):
    due_at: datetime
    actor: str = Field(min_length=2, max_length=100)


class Engagement(StrictBody):
    sender_id: str = Field(pattern=SENDER)
    action: str = Field(default="open", pattern=r"^(open|stop)$")


def ensure_contact(db, sender):
    item = db.get(WhatsAppContact, sender)
    if not item:
        # A savepoint makes parallel first messages safe without rolling back
        # the enclosing inbound event transaction.
        from sqlalchemy.exc import IntegrityError
        try:
            with db.begin_nested():
                item = WhatsAppContact(sender_id=sender, service_messages=False)
                db.add(item)
                db.flush()
        except IntegrityError:
            item = db.get(WhatsAppContact, sender)
    return item


def handoff_row(db, sender):
    item = db.get(WhatsAppHandoff, sender)
    return ({"status": item.status, "case_id": item.case_id, "assigned_to": item.assigned_to}
            if item and item.status != "closed" else None)


def preferences_row(db, contact):
    return {"service_messages": contact.service_messages, "marketing": contact.marketing,
            "stopped_all": contact.stopped_all, "language": contact.language,
            "branch_id": contact.branch_id, "interests": contact.interests,
            "handoff": handoff_row(db, contact.sender_id),
            "reception": {"phone": settings.clinic_phone, "hours": settings.reception_hours,
                          "response": settings.reception_response}}


def change_preferences(db, sender, body):
    contact = ensure_contact(db, sender)
    contact = db.scalar(select(WhatsAppContact).where(WhatsAppContact.sender_id == sender).with_for_update())
    prior = db.scalar(select(WhatsAppConsentEvent).where(WhatsAppConsentEvent.source_message_id == body.source_message_id))
    changes = body.model_dump(exclude={"source_message_id"}, exclude_none=True)
    if not changes:
        raise DomainError("NO_CHOICES", "Choose a message preference.", 422)
    if prior:
        if prior.sender_id != sender or prior.choices != changes:
            raise DomainError("CONSENT_CONFLICT", "This consent event was already recorded.", 409)
        return contact
    if body.branch_id and not db.scalar(select(Branch.id).where(Branch.id == body.branch_id, Branch.is_active.is_(True))):
        raise DomainError("BRANCH_NOT_FOUND", "Choose an existing clinic.", 422)
    if body.interests is not None:
        valid = set(db.scalars(select(Department.slug).where(Department.is_active.is_(True))))
        if not set(body.interests) <= valid:
            raise DomainError("INVALID_INTEREST", "Choose an existing specialty interest.", 422)
    for name, value in changes.items():
        setattr(contact, name, None if name == "branch_id" and value == "" else value)
    if contact.stopped_all:
        contact.marketing = contact.service_messages = False
    contact.updated_at = utcnow()
    db.add(WhatsAppConsentEvent(sender_id=sender, source_message_id=body.source_message_id, choices=changes))
    # The send authorization endpoint also rechecks consent under a row lock.
    for job in db.scalars(select(WhatsAppOutbound).where(
            WhatsAppOutbound.sender_id == sender, WhatsAppOutbound.status.in_(("pending", "claimed")))).all():
        template = db.get(WhatsAppTemplate, job.template_id) if job.template_id else None
        prohibited = contact.stopped_all or (template and template.category == "MARKETING" and not contact.marketing)
        prohibited |= (job.purpose not in ("campaign", "test", "staff") and not contact.service_messages)
        if prohibited:
            job.status = "cancelled"
            job.claim_token = None
    if not contact.service_messages:
        for job in db.scalars(select(ReminderJob).where(ReminderJob.sender_id == sender, ReminderJob.status == "pending")).all():
            job.status = "cancelled"
    return contact


@service_router.get("/preferences/{sender_id}")
def preferences(sender_id: str, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    if not re.fullmatch(SENDER, sender_id):
        raise DomainError("INVALID_SENDER", "Invalid WhatsApp sender.", 422)
    contact = ensure_contact(db, sender_id)
    db.commit()
    return preferences_row(db, contact)


@service_router.put("/preferences/{sender_id}")
def preference_change(sender_id: str, body: PreferenceChange, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    if not re.fullmatch(SENDER, sender_id):
        raise DomainError("INVALID_SENDER", "Invalid WhatsApp sender.", 422)
    contact = change_preferences(db, sender_id, body)
    db.commit()
    return preferences_row(db, contact)


@service_router.post("/reception")
def reception(body: SenderMessage, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    contact = ensure_contact(db, body.sender_id)
    db.scalar(select(WhatsAppContact).where(WhatsAppContact.sender_id == contact.sender_id).with_for_update())
    handoff = db.get(WhatsAppHandoff, body.sender_id)
    if not handoff or handoff.status == "closed":
        case = SupportCase(owner_key=owner_key(body.sender_id), sender_id=body.sender_id, kind="issue",
                           description=body.text or "Reception assistance requested via WhatsApp",
                           idempotency_key=f"handoff:{body.source_message_id}"[:120])
        db.add(case)
        db.flush()
        if not handoff:
            handoff = WhatsAppHandoff(sender_id=body.sender_id, case_id=case.id)
            db.add(handoff)
        else:
            handoff.case_id = case.id
        handoff.status = "waiting"
        handoff.assigned_to = None
    db.commit()
    return {**handoff_row(db, body.sender_id), "hours": settings.reception_hours,
            "response": settings.reception_response, "phone": settings.clinic_phone}


@service_router.post("/reception/messages")
def reception_message(body: SenderMessage, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    handoff = db.get(WhatsAppHandoff, body.sender_id)
    if not handoff or handoff.status == "closed":
        raise DomainError("HANDOFF_CLOSED", "Reception conversation is no longer active.", 409)
    prior = db.scalar(select(WhatsAppCaseMessage).where(WhatsAppCaseMessage.source_message_id == body.source_message_id))
    if not prior:
        db.add(WhatsAppCaseMessage(case_id=handoff.case_id, source_message_id=body.source_message_id,
                                  direction="inbound", text=body.text or "Attachment sent"))
        db.commit()
    elif prior.case_id != handoff.case_id:
        raise DomainError("MESSAGE_CONFLICT", "Message is already recorded.", 409)
    return {"saved": True}


@service_router.post("/reception/{sender_id}/resume")
def resume(sender_id: str, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    item = db.get(WhatsAppHandoff, sender_id)
    if item:
        item.status = "closed"
        item.updated_at = utcnow()
        db.commit()
    return {"resumed": True}


@admin_router.get("/reception")
def reception_list(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(WhatsAppHandoff).where(WhatsAppHandoff.status != "closed").order_by(WhatsAppHandoff.updated_at).limit(100)).all()
    result = []
    for item in items:
        contact = db.get(WhatsAppContact, item.sender_id)
        messages = db.scalars(select(WhatsAppCaseMessage).where(WhatsAppCaseMessage.case_id == item.case_id).order_by(WhatsAppCaseMessage.created_at.desc()).limit(30)).all()
        result.append({"sender_id": item.sender_id, "case_id": item.case_id, "status": item.status,
                       "assigned_to": item.assigned_to, "can_reply": bool(not contact.stopped_all and contact.last_inbound_at and utc(contact.last_inbound_at) > utcnow() - timedelta(hours=24)),
                       "messages": [{"direction": m.direction, "text": m.text, "actor": m.actor, "created_at": utc(m.created_at)} for m in reversed(messages)]})
    return result


@admin_router.patch("/reception/{sender_id}")
def reception_assign(sender_id: str, body: StaffHandoff, request: Request, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if getattr(request.state, "staff_user", None):
        user = request.state.staff_user
        body.assigned_to = staff_label(user)
    handoff = db.get(WhatsAppHandoff, sender_id)
    if not handoff:
        raise DomainError("HANDOFF_NOT_FOUND", "Reception conversation was not found.", 404)
    handoff.status, handoff.assigned_to, handoff.updated_at = body.status, body.assigned_to, utcnow()
    case = db.get(SupportCase, handoff.case_id)
    case.status = "resolved" if body.status == "closed" else "in_progress"
    db.commit()
    return {"updated": True}


@admin_router.post("/reception/{sender_id}/reply", status_code=202)
def reception_reply(sender_id: str, body: StaffReply, request: Request, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if getattr(request.state, "staff_user", None):
        user = request.state.staff_user
        body.actor = staff_label(user)
    handoff = db.get(WhatsAppHandoff, sender_id)
    contact = db.get(WhatsAppContact, sender_id)
    if not handoff or handoff.status == "closed" or not contact or contact.stopped_all:
        raise DomainError("HANDOFF_UNAVAILABLE", "Reception conversation is not available for messaging.", 409)
    if not contact.last_inbound_at or utc(contact.last_inbound_at) <= utcnow() - timedelta(hours=24):
        raise DomainError("WINDOW_CLOSED", "The patient must message again before a free-text reply.", 409)
    dedupe = f"staff:{body.idempotency_key}"
    prior = db.scalar(select(WhatsAppOutbound).where(WhatsAppOutbound.dedupe_key == dedupe))
    if prior:
        if prior.sender_id != sender_id or prior.text != body.text:
            raise DomainError("MESSAGE_CONFLICT", "This reply key was already used.", 409)
        return {"id": prior.id, "status": prior.status}
    job = WhatsAppOutbound(dedupe_key=dedupe, sender_id=sender_id, case_id=handoff.case_id,
                          purpose="staff", text=body.text, due_at=utcnow(), approved_actor=body.actor)
    db.add(job)
    db.add(WhatsAppCaseMessage(case_id=handoff.case_id, source_message_id=body.idempotency_key,
                              direction="outbound", text=body.text, actor=body.actor))
    db.commit()
    return {"id": job.id, "status": job.status}


@admin_router.patch("/branches/{branch_id}")
def branch_details(branch_id: str, body: BranchDetails, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    branch = db.get(Branch, branch_id)
    if not branch:
        raise DomainError("BRANCH_NOT_FOUND", "Clinic was not found.", 404)
    for key, value in body.model_dump().items():
        setattr(branch, key, value)
    db.commit()
    return {"updated": True}


def template_spec(template):
    count = 0
    header = None
    buttons = []
    for component in template.components:
        kind = component.get("type")
        if kind == "BODY":
            text = component.get("text", "")
            if not isinstance(text, str) or not text or len(text) > 4096:
                raise DomainError("UNSUPPORTED_TEMPLATE", "Use a text body under 4096 characters.", 422)
            values = set(re.findall(r"\{\{(\d+)\}\}", text))
            count = len(values)
            if set(values) != {str(i) for i in range(1, count + 1)} or re.search(r"\{\{[^0-9}]", text):
                raise DomainError("UNSUPPORTED_TEMPLATE", "Use consecutive numeric body parameters.", 422)
        elif kind == "HEADER":
            if not isinstance(component.get("text", ""), str):
                raise DomainError("UNSUPPORTED_TEMPLATE", "Invalid template header.", 422)
            header = component.get("format")
            if header not in ("TEXT", "IMAGE", "DOCUMENT") or (header == "TEXT" and "{{" in component.get("text", "")):
                raise DomainError("UNSUPPORTED_TEMPLATE", "Use a static text, image or PDF header.", 422)
        elif kind == "BUTTONS":
            values = component.get("buttons", [])
            if not isinstance(values, list) or len(values) > 10 or any(not isinstance(b, dict) or not isinstance(b.get("text", ""), str) for b in values):
                raise DomainError("UNSUPPORTED_TEMPLATE", "Invalid template buttons.", 422)
            for index, b in enumerate(values):
                if b.get("type") == "QUICK_REPLY":
                    label = b.get("text", "").lower()
                    action = "stop" if re.search(r"stop|unsubscribe|opt.out", label) else "contact" if re.search(r"contact|reception|help", label) else "book" if re.search(r"book|schedule|rebook", label) else "feedback" if re.search(r"rate|feedback|review", label) else "open"
                    buttons.append({"index": index, "action": action})
                elif b.get("type") not in ("URL", "PHONE_NUMBER") or not isinstance(b.get("url", ""), str) or "{{" in b.get("url", ""):
                    raise DomainError("UNSUPPORTED_TEMPLATE", "Dynamic links and special buttons are not supported.", 422)
        elif kind != "FOOTER":
            raise DomainError("UNSUPPORTED_TEMPLATE", "This template layout is not supported.", 422)
    if not any(c.get("type") == "BODY" for c in template.components):
        raise DomainError("UNSUPPORTED_TEMPLATE", "A message body is required.", 422)
    return {"parameters": count, "header": header, "buttons": buttons}


def approved_template(db, template_id, expected=None):
    item = db.get(WhatsAppTemplate, template_id)
    if not item or item.status != "APPROVED" or utc(item.synced_at) < utcnow() - timedelta(hours=2):
        raise DomainError("TEMPLATE_UNAVAILABLE", "Sync a currently approved Meta template first.", 409)
    if expected and item.fingerprint != expected:
        raise DomainError("TEMPLATE_CHANGED", "Template changed; review a new draft.", 409)
    template_spec(item)
    return item


def validate_content(db, template, parameters, asset_id):
    spec = template_spec(template)
    if len(parameters) != spec["parameters"]:
        raise DomainError("PARAMETERS_REQUIRED", f"This template needs {spec['parameters']} body parameters.", 422)
    media = spec["header"] in ("IMAGE", "DOCUMENT")
    if media != bool(asset_id):
        raise DomainError("HEADER_REQUIRED", "Choose the matching header image/PDF, or remove the attachment.", 422)
    if asset_id:
        asset = db.get(MediaAsset, asset_id)
        valid = asset and asset.kind in ("guide", "photo", "campaign")
        valid = valid and (asset.mime_type.startswith("image/") if spec["header"] == "IMAGE" else asset.mime_type == "application/pdf")
        if not valid:
            raise DomainError("INVALID_ASSET", "Use an approved staff-uploaded image or PDF.", 422)


@service_router.post("/templates/sync")
def template_sync(body: TemplateSync, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    valid = []
    for item in body.templates:
        if not re.fullmatch(r"[0-9]{1,80}", str(item.get("id", ""))) or not re.fullmatch(r"[a-z0-9_]{1,100}", str(item.get("name", ""))):
            raise DomainError("INVALID_TEMPLATE", "Invalid Meta template identity.", 422)
        if item.get("category") not in ("UTILITY", "MARKETING", "AUTHENTICATION") or not isinstance(item.get("components"), list) or len(json.dumps(item)) > 32000:
            raise DomainError("INVALID_TEMPLATE", "Invalid Meta template data.", 422)
        if not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", str(item.get("language", ""))):
            raise DomainError("INVALID_TEMPLATE", "Invalid template language.", 422)
        if not isinstance(item.get("status"), str) or len(item["status"]) > 24 or any(not isinstance(c, dict) for c in item["components"]):
            raise DomainError("INVALID_TEMPLATE", "Invalid template status or components.", 422)
        if any(not isinstance(item.get(k), str) for k in ("name", "language", "category")):
            raise DomainError("INVALID_TEMPLATE", "Template fields must be strings.", 422)
        valid.append(item)
    ids = set()
    for data in valid:
        template_id = str(data["id"])
        ids.add(template_id)
        item = db.get(WhatsAppTemplate, template_id)
        if not item:
            item = WhatsAppTemplate(id=template_id)
            db.add(item)
        for key in ("name", "language", "category", "components", "status"):
            setattr(item, key, data[key])
        item.fingerprint = fingerprint({key: data[key] for key in ("name", "language", "category", "components")})
        item.synced_at = utcnow()
    for item in db.scalars(select(WhatsAppTemplate)).all():
        if item.id not in ids:
            item.status = "REMOVED"
    db.commit()
    return {"synced": len(ids)}


@admin_router.get("/templates")
def templates(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    items = db.scalars(select(WhatsAppTemplate).order_by(WhatsAppTemplate.name)).all()
    result = []
    for item in items:
        try:
            spec = template_spec(item)
        except DomainError:
            spec = None
        result.append({"id": item.id, "name": item.name, "language": item.language, "category": item.category,
                       "status": item.status, "components": item.components, "spec": spec, "synced_at": utc(item.synced_at)})
    return result


def campaign_row(db, campaign):
    counts = dict(db.execute(select(WhatsAppOutbound.status, func.count()).where(
        WhatsAppOutbound.campaign_id == campaign.id, WhatsAppOutbound.purpose == "campaign").group_by(WhatsAppOutbound.status)).all())
    engaged = db.scalar(select(func.count()).select_from(WhatsAppOutbound).where(WhatsAppOutbound.campaign_id == campaign.id, WhatsAppOutbound.purpose == "campaign", WhatsAppOutbound.engaged_at.is_not(None))) or 0
    converted = db.scalar(select(func.count()).select_from(WhatsAppOutbound).where(WhatsAppOutbound.campaign_id == campaign.id, WhatsAppOutbound.purpose == "campaign", WhatsAppOutbound.converted_appointment_id.is_not(None))) or 0
    opted_out = db.scalar(select(func.count()).select_from(WhatsAppOutbound).where(WhatsAppOutbound.campaign_id == campaign.id, WhatsAppOutbound.purpose == "campaign", WhatsAppOutbound.opted_out_at.is_not(None))) or 0
    return {"unsubscribes_from_buttons": opted_out, "id": campaign.id, "title": campaign.title, "status": campaign.status, "template_id": campaign.template_id,
            "parameters": campaign.parameters, "asset_id": campaign.asset_id, "scheduled_at": utc(campaign.scheduled_at),
            "audience": campaign.audience, "rate_paise": campaign.rate_paise, "budget_paise": campaign.budget_paise,
            "approved_count": campaign.approved_count, "counts": counts, "engaged": engaged, "bookings": converted}


def audience_contacts(db, campaign):
    template = approved_template(db, campaign.template_id, campaign.template_fingerprint)
    if campaign.audience.get("branch_id") and not db.scalar(select(Branch.id).where(Branch.id == campaign.audience["branch_id"], Branch.is_active.is_(True))):
        raise DomainError("BRANCH_UNAVAILABLE", "The selected audience clinic is no longer active.", 409)
    query = select(WhatsAppContact).where(WhatsAppContact.marketing.is_(True), WhatsAppContact.stopped_all.is_(False)).order_by(WhatsAppContact.sender_id)
    if campaign.audience.get("branch_id"):
        query = query.where(WhatsAppContact.branch_id == campaign.audience["branch_id"])
    query = query.where(WhatsAppContact.language == template.language.split("_")[0])
    items = db.scalars(query.limit(10001)).all()
    if len(items) > 10000:
        raise DomainError("AUDIENCE_TOO_LARGE", "Narrow the audience before previewing.", 422)
    items = [c for c in items if c.language == template.language.split("_")[0]
             and (not campaign.audience.get("interest") or (not c.interests or campaign.audience["interest"] in c.interests))]
    if len(items) > 1000:
        raise DomainError("AUDIENCE_TOO_LARGE", "Limit a pilot campaign to 1,000 recipients.", 422)
    return items


def preview_row(db, campaign):
    template = approved_template(db, campaign.template_id, campaign.template_fingerprint)
    people = audience_contacts(db, campaign)
    body = next((c.get("text", "") for c in template.components if c.get("type") == "BODY"), "")
    for n, value in enumerate(campaign.parameters, 1):
        body = body.replace("{{" + str(n) + "}}", value)
    digest = fingerprint([(c.sender_id, utc(c.updated_at).isoformat()) for c in people])
    estimate = len(people) * campaign.rate_paise
    return {"body": body, "recipients": len(people), "audience_hash": digest, "estimated_cost_paise": estimate,
            "within_budget": estimate <= campaign.budget_paise, "rate_is_staff_estimate": True,
            "header_asset_id": campaign.asset_id, "template_language": template.language}


@admin_router.get("/campaigns")
def campaigns(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return [campaign_row(db, c) for c in db.scalars(select(WhatsAppCampaign).order_by(WhatsAppCampaign.created_at.desc()).limit(100)).all()]


@admin_router.post("/campaigns", status_code=201)
def campaign_create(body: CampaignCreate, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    template = approved_template(db, body.template_id)
    if template.category != "MARKETING":
        raise DomainError("MARKETING_TEMPLATE_REQUIRED", "Campaigns must use a Meta-approved marketing template.", 422)
    if utc(body.scheduled_at) > utcnow() + timedelta(days=30):
        raise DomainError("SCHEDULE_TOO_FAR", "Schedule within the next 30 days.", 422)
    validate_content(db, template, body.parameters, body.asset_id)
    if body.audience.branch_id and not db.scalar(select(Branch.id).where(Branch.id == body.audience.branch_id, Branch.is_active.is_(True))):
        raise DomainError("BRANCH_NOT_FOUND", "Choose an existing audience clinic.", 422)
    if body.audience.interest and not db.scalar(select(Department.id).where(Department.slug == body.audience.interest, Department.is_active.is_(True))):
        raise DomainError("INVALID_INTEREST", "Choose an existing specialty audience.", 422)
    data = body.model_dump()
    data["audience"] = body.audience.model_dump(exclude_none=True)
    campaign = WhatsAppCampaign(**data, template_fingerprint=template.fingerprint)
    db.add(campaign)
    db.commit()
    return campaign_row(db, campaign)


@admin_router.get("/campaigns/{campaign_id}/preview")
def campaign_preview(campaign_id: str, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(WhatsAppCampaign, campaign_id)
    if not item:
        raise DomainError("CAMPAIGN_NOT_FOUND", "Campaign was not found.", 404)
    return preview_row(db, item)


@admin_router.post("/campaigns/{campaign_id}/test", status_code=202)
def campaign_test(campaign_id: str, body: CampaignTest, request: Request, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if getattr(request.state, "staff_user", None):
        user = request.state.staff_user
        body.actor = staff_label(user)
    campaign = db.get(WhatsAppCampaign, campaign_id)
    if not campaign or campaign.status != "draft":
        raise DomainError("CAMPAIGN_UNAVAILABLE", "Choose an unscheduled draft.", 409)
    if body.sender_id not in {n.strip() for n in settings.whatsapp_test_recipients.split(",") if n.strip()}:
        raise DomainError("TEST_RECIPIENT_REQUIRED", "Configure a verified test recipient on the server first.", 422)
    approved_template(db, campaign.template_id, campaign.template_fingerprint)
    ensure_contact(db, body.sender_id)
    job = WhatsAppOutbound(dedupe_key=f"test:{campaign.id}:{secrets.token_hex(8)}", sender_id=body.sender_id,
                          campaign_id=campaign.id, template_id=campaign.template_id,
                          template_fingerprint=campaign.template_fingerprint, parameters=campaign.parameters,
                          asset_id=campaign.asset_id, purpose="test", due_at=utcnow(), approved_actor=body.actor)
    db.add(job)
    db.commit()
    return {"id": job.id, "status": job.status}


@admin_router.post("/campaigns/{campaign_id}/approve")
def campaign_approve(campaign_id: str, body: CampaignApproval, request: Request, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if getattr(request.state, "staff_user", None):
        user = request.state.staff_user
        body.actor = staff_label(user)
    campaign = db.scalar(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id).with_for_update())
    if not campaign or campaign.status != "draft":
        raise DomainError("CAMPAIGN_UNAVAILABLE", "Choose an unscheduled draft.", 409)
    if not body.test_received or not db.scalar(select(WhatsAppOutbound.id).where(
            WhatsAppOutbound.campaign_id == campaign.id, WhatsAppOutbound.purpose == "test",
            WhatsAppOutbound.status.in_(("accepted", "sent", "delivered", "read"))).limit(1)):
        raise DomainError("TEST_REQUIRED", "Send the test and confirm that it arrived before approval.", 409)
    preview = preview_row(db, campaign)
    if preview["recipients"] != body.expected_count or preview["audience_hash"] != body.audience_hash:
        raise DomainError("AUDIENCE_CHANGED", "Audience changed. Refresh the preview before approval.", 409)
    if not preview["within_budget"]:
        raise DomainError("BUDGET_EXCEEDED", "Estimated campaign cost exceeds the spending cap.", 422)
    people = audience_contacts(db, campaign)
    for contact in people:
        db.add(WhatsAppOutbound(dedupe_key=f"campaign:{campaign.id}:{contact.sender_id}", sender_id=contact.sender_id,
                               campaign_id=campaign.id, template_id=campaign.template_id,
                               template_fingerprint=campaign.template_fingerprint, parameters=campaign.parameters,
                               asset_id=campaign.asset_id, purpose="campaign", due_at=campaign.scheduled_at, approved_actor=body.actor))
    campaign.status, campaign.approved_by, campaign.approved_count = "scheduled", body.actor, len(people)
    db.commit()
    return campaign_row(db, campaign)


@admin_router.post("/campaigns/{campaign_id}/pause")
def campaign_pause(campaign_id: str, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    campaign = db.get(WhatsAppCampaign, campaign_id)
    if not campaign:
        raise DomainError("CAMPAIGN_NOT_FOUND", "Campaign was not found.", 404)
    campaign.status = "paused"
    for job in db.scalars(select(WhatsAppOutbound).where(WhatsAppOutbound.campaign_id == campaign.id,
            WhatsAppOutbound.status.in_(("pending", "claimed")))).all():
        job.status, job.claim_token = "cancelled", None
    db.commit()
    return {"paused": True}


def queue_followup(db, appointment, kind, due_at=None):
    if appointment.origin_channel != "whatsapp" or not appointment.consent_to_reminders:
        return
    rule = db.get(WhatsAppFollowupRule, kind)
    if not rule or not rule.enabled:
        return
    sender = appointment.patient_phone.lstrip("+")
    contact = ensure_contact(db, sender)
    if not contact.service_messages or contact.stopped_all:
        return
    try:
        template = approved_template(db, rule.template_id, rule.template_fingerprint)
    except DomainError:
        return False
    dedupe = f"care:{kind}:{appointment.id}"
    if db.scalar(select(WhatsAppOutbound.id).where(WhatsAppOutbound.dedupe_key == dedupe)):
        return
    doctor, branch = db.get(Doctor, appointment.reservation.doctor_id), db.get(Branch, appointment.reservation.branch_id)
    when = utc(appointment.reservation.starts_at).astimezone(ZoneInfo(branch.timezone)).strftime("%d %b %Y, %I:%M %p")
    db.add(WhatsAppOutbound(dedupe_key=dedupe, sender_id=sender, appointment_id=appointment.id,
                           template_id=template.id, template_fingerprint=template.fingerprint,
                           parameters=[appointment.confirmation_code, doctor.name, when], purpose=kind,
                           due_at=due_at or utcnow() + timedelta(hours=rule.delay_hours)))


@admin_router.get("/followup-rules")
def followup_rules(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"kind": r.kind, "enabled": r.enabled, "template_id": r.template_id, "delay_hours": r.delay_hours}
            for r in db.scalars(select(WhatsAppFollowupRule)).all()]


@admin_router.put("/followup-rules/{kind}")
def followup_rule(kind: str, body: RuleChange, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if kind not in ("feedback", "no_show", "followup"):
        raise DomainError("INVALID_RULE", "Choose feedback, no_show or followup.", 422)
    existing = db.get(WhatsAppFollowupRule, kind)
    if existing and not body.enabled and body.template_id == existing.template_id:
        existing.enabled = False
        db.commit()
        return {"saved": True}
    template = approved_template(db, body.template_id)
    spec = template_spec(template)
    if spec["parameters"] != 3 or spec["header"] not in (None, "TEXT") or template.category == "AUTHENTICATION":
        raise DomainError("INVALID_TEMPLATE", "Care templates need three body fields: reference, doctor, visit time.", 422)
    item = db.get(WhatsAppFollowupRule, kind)
    if not item:
        item = WhatsAppFollowupRule(kind=kind)
        db.add(item)
    item.template_id, item.template_fingerprint = template.id, template.fingerprint
    item.delay_hours, item.enabled = body.delay_hours, body.enabled
    db.commit()
    return {"saved": True}


@admin_router.post("/appointments/{appointment_id}/followup", status_code=202)
def manual_followup(appointment_id: str, body: ManualFollowup, request: Request, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if getattr(request.state, "staff_user", None):
        user = request.state.staff_user
        body.actor = staff_label(user)
    if body.due_at.tzinfo is None or utc(body.due_at) <= utcnow() or utc(body.due_at) > utcnow() + timedelta(days=180):
        raise DomainError("INVALID_DATE", "Choose a future follow-up date within 180 days with a timezone.", 422)
    appointment = db.get(Appointment, appointment_id)
    if not appointment or appointment.status != "completed":
        raise DomainError("VISIT_NOT_COMPLETED", "Schedule doctor-requested follow-up after a completed visit.", 409)
    rule = db.get(WhatsAppFollowupRule, "followup")
    if not rule or not rule.enabled or not appointment.consent_to_reminders:
        raise DomainError("FOLLOWUP_UNAVAILABLE", "Enable a follow-up template and obtain visit-message consent first.", 409)
    queue_followup(db, appointment, "followup", utc(body.due_at))
    if not db.scalar(select(WhatsAppOutbound.id).where(WhatsAppOutbound.dedupe_key == f"care:followup:{appointment.id}")):
        raise DomainError("FOLLOWUP_UNAVAILABLE", "Check current template approval and message preferences.", 409)
    job = db.scalar(select(WhatsAppOutbound).where(WhatsAppOutbound.dedupe_key == f"care:followup:{appointment.id}"))
    if utc(job.due_at) != utc(body.due_at):
        raise DomainError("FOLLOWUP_EXISTS", "This visit already has a follow-up. Review its scheduled message before adding another.", 409)
    job.approved_actor = body.actor
    db.commit()
    return {"scheduled": True, "approved_by": body.actor}


def job_allowed(db, job, contact):
    if not contact or contact.stopped_all:
        return False
    handoff = db.get(WhatsAppHandoff, job.sender_id)
    if job.purpose == "staff":
        return bool(handoff and handoff.status != "closed" and contact.last_inbound_at and utc(contact.last_inbound_at) > utcnow() - timedelta(hours=24))
    template = approved_template(db, job.template_id, job.template_fingerprint)
    if job.purpose == "test":
        return job.sender_id in {n.strip() for n in settings.whatsapp_test_recipients.split(",")}
    if handoff and handoff.status != "closed":
        return False
    if template.category == "MARKETING" and not contact.marketing:
        return False
    if contact.language != template.language.split("_")[0]:
        return False
    if job.purpose == "campaign":
        campaign = db.get(WhatsAppCampaign, job.campaign_id)
        branch = db.get(Branch, campaign.audience.get("branch_id")) if campaign and campaign.audience.get("branch_id") else None
        return bool(campaign and campaign.status == "scheduled" and
                    (not campaign.audience.get("branch_id") or (branch and branch.is_active)) and
                    (not campaign.audience.get("branch_id") or contact.branch_id == campaign.audience["branch_id"]) and
                    (not campaign.audience.get("interest") or (not contact.interests or campaign.audience["interest"] in contact.interests)))
    item = db.get(Appointment, job.appointment_id)
    expected = "no_show" if job.purpose == "no_show" else "completed"
    rule = db.get(WhatsAppFollowupRule, job.purpose)
    if not rule or not rule.enabled or rule.template_id != job.template_id or rule.template_fingerprint != job.template_fingerprint:
        return False
    return bool(contact.service_messages and item and item.status == expected and item.consent_to_reminders)


def job_row(db, job):
    template = db.get(WhatsAppTemplate, job.template_id) if job.template_id else None
    spec = template_spec(template) if template else {"buttons": [], "header": None}
    return {"id": job.id, "sender_id": job.sender_id, "purpose": job.purpose, "text": job.text,
            "claim_token": job.claim_token, "template": {"name": template.name, "language": template.language} if template else None,
            "parameters": job.parameters, "asset_id": job.asset_id, "header_type": spec["header"],
            "buttons": [{"index": b["index"], "payload": f"outreach.{b['action']}.{job.id}"} for b in spec["buttons"]]}


@service_router.post("/outreach/claim")
def outbound_claim(_: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    from .client_modules import is_enabled
    if not is_enabled(db, "whatsapp"):
        return None
    now = utcnow()
    stale = db.scalars(select(WhatsAppOutbound).where(WhatsAppOutbound.status.in_(("claimed", "sending")),
        WhatsAppOutbound.claimed_at < now - timedelta(minutes=15)).with_for_update(skip_locked=True)).all()
    for job in stale:
        # Never retry a worker death while preparing or sending proactive outreach.
        job.status, job.claim_token = "uncertain" if job.status == "sending" else "failed", None
    db.flush()
    query = select(WhatsAppOutbound).where(WhatsAppOutbound.status == "pending", WhatsAppOutbound.due_at <= now)
    if not settings.whatsapp_outreach_enabled:
        query = query.where(WhatsAppOutbound.purpose == "test")
    for job in db.scalars(query
                           .order_by(WhatsAppOutbound.due_at).limit(50).with_for_update(skip_locked=True)).all():
        if not settings.whatsapp_outreach_enabled and job.purpose != "test":
            continue
        try:
            allowed = job_allowed(db, job, db.get(WhatsAppContact, job.sender_id))
        except DomainError:
            allowed = False
        if not allowed:
            job.status = "cancelled"
            continue
        job.status, job.claim_token, job.claimed_at = "claimed", secrets.token_hex(32), now
        db.commit()
        return job_row(db, job)
    db.commit()
    return None


@service_router.post("/outreach/{job_id}/sending")
def outbound_sending(job_id: str, body: Transition, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    pending = db.get(WhatsAppOutbound, job_id)
    if pending:
        db.scalar(select(WhatsAppContact).where(WhatsAppContact.sender_id == pending.sender_id).with_for_update())
    job = db.scalar(select(WhatsAppOutbound).where(WhatsAppOutbound.id == job_id).with_for_update().execution_options(populate_existing=True))
    if not job or job.status != "claimed" or job.claim_token != body.claim_token or not job.claimed_at or utc(job.claimed_at) < utcnow() - timedelta(minutes=15):
        raise DomainError("CLAIM_LOST", "Message claim is no longer active.", 409)
    from .client_modules import is_enabled
    if not is_enabled(db, "whatsapp"):
        job.status, job.claim_token = "pending", None
        db.commit()
        return {"send": False, "reason": "module_disabled"}
    contact = db.scalar(select(WhatsAppContact).where(WhatsAppContact.sender_id == job.sender_id).with_for_update())
    if not settings.whatsapp_outreach_enabled and job.purpose != "test":
        job.status, job.claim_token = "cancelled", None
        db.commit()
        return {"send": False}
    try:
        allowed = job_allowed(db, job, contact)
    except DomainError:
        allowed = False
    if not allowed:
        job.status, job.claim_token = "cancelled", None
        db.commit()
        return {"send": False}
    template = db.get(WhatsAppTemplate, job.template_id) if job.template_id else None
    if template and job.purpose != "test":
        branch = db.get(Branch, contact.branch_id) if contact.branch_id else None
        zone = ZoneInfo(branch.timezone if branch else "Asia/Kolkata")
        local = utcnow().astimezone(zone)
        if local.hour < 9 or local.hour >= 19:
            tomorrow = local.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1 if local.hour >= 19 else 0)
            job.due_at, job.status, job.claim_token = tomorrow.astimezone(timezone.utc), "pending", None
            db.commit()
            return {"send": False, "reason": "quiet_hours"}
        recent = [] if template.category != "MARKETING" else db.scalars(select(WhatsAppOutbound).join(WhatsAppTemplate, WhatsAppOutbound.template_id == WhatsAppTemplate.id).where(
            WhatsAppOutbound.sender_id == job.sender_id, WhatsAppTemplate.category == "MARKETING",
            WhatsAppOutbound.purpose != "test", WhatsAppOutbound.status.in_(ACTIVE_SENDS),
            WhatsAppOutbound.sending_at > utcnow() - timedelta(days=30))).all()
        if len(recent) >= 2 or any(utc(j.sending_at) > utcnow() - timedelta(days=7) for j in recent):
            job.status, job.claim_token, job.last_error = "cancelled", None, "Marketing frequency limit"
            db.commit()
            return {"send": False, "reason": "frequency_limit"}
    job.status, job.sending_at = "sending", utcnow()
    db.commit()
    return {"send": True}


def apply_receipt(job, receipt):
    rank = {"accepted": 0, "sent": 1, "delivered": 2, "read": 3}
    if receipt.status == "failed":
        if job.status not in ("delivered", "read"):
            job.status, job.last_error = "failed", "Meta reported delivery failure; do not retry automatically"
    elif rank.get(receipt.status, -1) > rank.get(job.status, -1):
        job.status = receipt.status


def lock_receipt(db, message_id, status, timestamp):
    from sqlalchemy.exc import IntegrityError
    item = db.scalar(select(WhatsAppDeliveryReceipt).where(WhatsAppDeliveryReceipt.meta_message_id == message_id).with_for_update())
    if not item:
        try:
            with db.begin_nested():
                item = WhatsAppDeliveryReceipt(meta_message_id=message_id, status=status, timestamp=timestamp)
                db.add(item)
                db.flush()
        except IntegrityError:
            item = db.scalar(select(WhatsAppDeliveryReceipt).where(WhatsAppDeliveryReceipt.meta_message_id == message_id).with_for_update())
    return item


@service_router.post("/outreach/{job_id}/sent")
def outbound_sent(job_id: str, body: Transition, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    if not body.meta_message_id:
        raise DomainError("RECEIPT_REQUIRED", "A Meta message receipt is required.", 422)
    # Receipt-before-job lock order matches webhook processing. A placeholder
    # closes the race between an early callback and storing the send response.
    prior = lock_receipt(db, body.meta_message_id, "accepted", 0)
    job = db.scalar(select(WhatsAppOutbound).where(WhatsAppOutbound.id == job_id).with_for_update())
    if not job or job.status != "sending" or job.claim_token != body.claim_token:
        raise DomainError("CLAIM_LOST", "Message claim is no longer active.", 409)
    job.status, job.meta_message_id, job.claim_token = "accepted", body.meta_message_id, None
    apply_receipt(job, prior)
    db.commit()
    return {"status": job.status}


@service_router.post("/outreach/{job_id}/failed")
def outbound_failed(job_id: str, body: Transition, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    job = db.get(WhatsAppOutbound, job_id)
    if not job or job.status not in ("claimed", "sending") or job.claim_token != body.claim_token:
        raise DomainError("CLAIM_LOST", "Message claim is no longer active.", 409)
    job.status = "uncertain" if job.status == "sending" else "failed"
    job.last_error, job.claim_token = body.error, None
    db.commit()
    return {"status": job.status}


@service_router.post("/delivery-status")
def receipt(body: Receipt, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    item = lock_receipt(db, body.meta_message_id, body.status, body.timestamp)
    if item:
        rank = {"sent": 1, "delivered": 2, "read": 3}
        if (body.status == "failed" and item.status not in ("delivered", "read") and body.timestamp >= item.timestamp) or rank.get(body.status, 0) > rank.get(item.status, 0):
            item.status = body.status
        item.timestamp = max(item.timestamp, body.timestamp)
    job = db.scalar(select(WhatsAppOutbound).where(WhatsAppOutbound.meta_message_id == body.meta_message_id))
    if job:
        apply_receipt(job, item)
    db.commit()
    return {"recorded": True}


@service_router.post("/outreach/{job_id}/engage")
def engage(job_id: str, body: Engagement, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    job = db.get(WhatsAppOutbound, job_id)
    if not job or job.sender_id != body.sender_id or job.status not in ACTIVE_SENDS or utc(job.created_at) < utcnow() - timedelta(days=30):
        raise DomainError("LINK_EXPIRED", "This message action has expired. Send hi for the menu.", 404)
    job.engaged_at = job.engaged_at or utcnow()
    if body.action == "stop":
        job.opted_out_at = job.opted_out_at or utcnow()
    db.commit()
    return {"appointment_id": job.appointment_id, "campaign_id": job.campaign_id}


@admin_router.get("/outbound")
def outbound_list(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": j.id, "purpose": j.purpose, "sender_id": j.sender_id, "status": j.status,
             "due_at": utc(j.due_at), "campaign_id": j.campaign_id, "appointment_id": j.appointment_id,
             "last_error": j.last_error, "meta_message_id": j.meta_message_id}
            for j in db.scalars(select(WhatsAppOutbound).order_by(WhatsAppOutbound.created_at.desc()).limit(100)).all()]


@service_router.post("/reminders/{job_id}/authorize")
def authorize_reminder(job_id: str, _: None = Depends(require_whatsapp_service), db: Session = Depends(get_db)):
    from .client_modules import is_enabled
    if not is_enabled(db, "whatsapp"):
        return {"send": False, "reason": "module_disabled"}
    job = db.get(ReminderJob, job_id)
    if not job or job.status != "claimed":
        return {"send": False}
    contact = db.get(WhatsAppContact, job.sender_id)
    appointment = db.get(Appointment, job.appointment_id)
    if ((contact and (contact.stopped_all or not contact.service_messages)) or not appointment
            or not appointment.consent_to_reminders or appointment.status != "confirmed"
            or utc(appointment.reservation.starts_at) <= utcnow()):
        job.status = "cancelled"
        db.commit()
        return {"send": False}
    doctor, branch = db.get(Doctor, appointment.reservation.doctor_id), db.get(Branch, appointment.reservation.branch_id)
    local = utcnow().astimezone(ZoneInfo(branch.timezone))
    if local.hour < 9 or local.hour >= 19:
        next_morning = local.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1 if local.hour >= 19 else 0)
        job.status, job.due_at = "pending", next_morning.astimezone(timezone.utc)
        db.commit()
        return {"send": False, "reason": "quiet_hours"}
    return {"send": True, "confirmation_code": appointment.confirmation_code, "doctor_name": doctor.name,
            "starts_at": utc(appointment.reservation.starts_at), "timezone": branch.timezone}


@admin_router.post("/campaign-assets", status_code=201)
async def campaign_upload(file: UploadFile = File(), _: str = Depends(require_admin), db: Session = Depends(get_db)):
    asset = await save_upload(db, file, "campaign")
    db.commit()
    return asset_row(asset)


@admin_router.get("/campaign-assets")
def campaign_assets(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return [asset_row(asset) for asset in db.scalars(select(MediaAsset).where(MediaAsset.kind.in_(("campaign", "photo", "guide")))
            .order_by(MediaAsset.created_at.desc()).limit(200)).all()]


@admin_router.get("/assets/{asset_id}")
def staff_asset(asset_id: str, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    asset = db.get(MediaAsset, asset_id)
    if not asset or asset.kind not in ("campaign", "photo", "guide"):
        raise DomainError("ASSET_NOT_FOUND", "Staff asset was not found.", 404)
    path = media_path(asset.storage_name)
    if not path.is_file():
        raise DomainError("ASSET_MISSING", "The uploaded asset is missing from storage.", 503)
    return FileResponse(path, media_type=asset.mime_type, filename=asset.original_name,
                        headers={"Cache-Control": "no-store"})


@admin_router.get("/operations-config")
def operations_config(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    return {"environment": settings.app_env, "outreach_enabled": settings.whatsapp_outreach_enabled,
            "test_recipients": [n.strip() for n in settings.whatsapp_test_recipients.split(",") if re.fullmatch(SENDER, n.strip())],
            "marketing_contacts": db.scalar(select(func.count()).select_from(WhatsAppContact).where(WhatsAppContact.marketing.is_(True), WhatsAppContact.stopped_all.is_(False))) or 0,
            "reception": {"phone": settings.clinic_phone, "hours": settings.reception_hours, "response": settings.reception_response}}
