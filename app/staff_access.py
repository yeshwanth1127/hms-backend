"""Growth permissions layered over the shared staff username/password session."""
from fastapi import Depends
from sqlalchemy.orm import Session
from .db import get_db
from .models import StaffUser
from .staff_auth import require_staff
from .services import DomainError

ROLES = {
    "admin": frozenset({"growth.read", "google.manage", "growth.audit.read"}),
    "growth_manager": frozenset({"growth.read", "google.manage", "growth.audit.read"}),
    "staff": frozenset(),
}
authenticated_staff = require_staff


def permission_required(permission: str, module: str | None = None):
    def check(staff: StaffUser = Depends(require_staff), db: Session = Depends(get_db)):
        if permission not in ROLES.get(staff.role, frozenset()):
            raise DomainError("STAFF_PERMISSION_DENIED", "Your role does not allow access to this module.", 403)
        if module:
            from .client_modules import ensure_module
            ensure_module(db, module)
        return staff
    return check


require_growth_read = permission_required("growth.read", "growth_analytics")
require_google_read = permission_required("growth.read", "google_business")
require_google_manage = permission_required("google.manage", "google_business")
require_growth_audit = permission_required("growth.audit.read", "google_business")
