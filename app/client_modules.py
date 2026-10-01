"""Server-side optional module switches for one client/clinic deployment."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy.orm import Session
from .db import get_db
from .models import ClientModule, ModuleAudit, StaffUser
from .services import DomainError
from .staff_access import authenticated_staff
from .admin import require_admin

router = APIRouter(prefix="/api/v1/staff/modules", tags=["client-modules"])
MODULES = {
    "voice": {"name": "Voice", "description": "Sarvam calls, booking outcomes and admin recording review.", "permission": "voice.read"},
    "whatsapp": {"name": "WhatsApp", "description": "Bot conversations, reception handoff and consented outreach.", "permission": "whatsapp.manage"},
    "google_business": {"name": "Google Business", "description": "Profile setup, booking links and patient journey previews.", "permission": "google.manage"},
    "growth_analytics": {"name": "Growth analytics", "description": "Appointment attribution, confirmation and attendance reports.", "permission": "growth.read"},
}


def is_enabled(db: Session, key: str) -> bool:
    record = db.get(ClientModule, key)
    return bool(record.enabled) if record else key == "whatsapp"


def ensure_module(db: Session, key: str):
    if key not in MODULES or not is_enabled(db, key):
        raise DomainError("MODULE_DISABLED", "This module is disabled for your clinic. Ask the clinic owner to enable it.", 403)


def owner(staff: StaffUser = Depends(authenticated_staff)):
    if staff.role != "admin":
        raise DomainError("STAFF_PERMISSION_DENIED", "Only the clinic owner can change enabled modules.", 403)
    return staff


class ModuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.get("")
def catalogue(staff: StaffUser = Depends(authenticated_staff), db: Session = Depends(get_db)):
    from .staff_access import ROLES
    permissions = ROLES.get(staff.role, frozenset())
    if staff.role in {"admin", "staff"}:
        permissions = permissions | {"whatsapp.manage"}
    return {"scope": "clinic_deployment", "can_manage": staff.role == "admin", "modules": [
        {"key": key, **value, "enabled": is_enabled(db, key),
         "accessible": is_enabled(db, key) and value["permission"] in permissions}
        for key, value in MODULES.items()]}


@router.put("/{key}")
def update(key: str, body: ModuleUpdate, staff: StaffUser = Depends(owner), db: Session = Depends(get_db)):
    if key not in MODULES:
        raise DomainError("MODULE_NOT_FOUND", "Unknown optional module.", 404)
    item = db.get(ClientModule, key)
    if not item:
        item = ClientModule(key=key, enabled=key == "whatsapp")
        db.add(item)
    if item.enabled != body.enabled:
        item.enabled = body.enabled
        db.add(ModuleAudit(module_key=key, actor=staff.id, enabled=body.enabled))
    db.commit()
    return {"key": key, "enabled": item.enabled, "data_retained": True}


def require_whatsapp_module(request: Request, _=Depends(require_admin), db: Session = Depends(get_db)):
    ensure_module(db, "whatsapp")
