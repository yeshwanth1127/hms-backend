"""Owner-chosen limits on what `staff` accounts may change. Administrators can always do everything.

Clinics differ: some let nurses block time or edit doctors, others keep that with the owner.
Consultation fees are never delegated (enforced in admin.update_doctor).
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from . import audit
from .db import get_db
from .models import StaffPermission
from .services import DomainError
from .staff_auth import require_staff, require_staff_owner

# key: (label shown to the owner, default for staff)
CAPABILITIES = {
    "doctors.manage": ("Show or hide doctors and change visit types", True),
    "schedules.manage": ("Add and remove clinic hours", True),
    "schedule.block": ("Block time and remove blocks", True),
    "clinic.manage": ("Edit clinic address and arrival details", True),
    "media.manage": ("Upload doctor photos and department guides", True),
    "campaigns.manage": ("Create, test, approve and pause WhatsApp campaigns", False),
    "followups.manage": ("Change automatic WhatsApp care messages", False),
}
router = APIRouter(prefix="/api/v1/staff/permissions", tags=["staff-permissions"])


def staff_may(db: Session, key: str) -> bool:
    row = db.get(StaffPermission, key)
    return row.allowed if row else CAPABILITIES[key][1]


def require_capability(key: str):
    assert key in CAPABILITIES, key
    from .admin import require_admin  # admin imports this module

    def check(request: Request, actor: str = Depends(require_admin), db: Session = Depends(get_db)):
        user = getattr(request.state, "staff_user", None)
        # No staff user means the non-production machine key, which require_admin already accepted.
        if user is not None and user.role != "admin" and not staff_may(db, key):
            raise DomainError("STAFF_PERMISSION_DENIED", "The clinic owner has not allowed staff to make this change.", 403)
        return actor
    return check


def effective(db: Session, role: str) -> dict:
    return {key: role == "admin" or (role == "staff" and staff_may(db, key)) for key in CAPABILITIES}


@router.get("")
def permissions(user=Depends(require_staff), db: Session = Depends(get_db)):
    return {"role": user.role, "allowed": effective(db, user.role),
            "staff": [{"key": key, "label": label, "allowed": staff_may(db, key)} for key, (label, _) in CAPABILITIES.items()]}


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed: bool


@router.put("/{key}")
def change(key: str, body: Change, _=Depends(require_staff_owner), db: Session = Depends(get_db)):
    if key not in CAPABILITIES:
        raise DomainError("PERMISSION_NOT_FOUND", "Unknown staff permission.", 404)
    row = db.get(StaffPermission, key) or StaffPermission(key=key)
    audit.note(allowed={"from": staff_may(db, key), "to": body.allowed})
    row.allowed = body.allowed
    db.add(row)
    db.commit()
    return {"key": key, "allowed": row.allowed}
