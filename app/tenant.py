from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Hospital
from .services import DomainError


def current_hospital(x_hospital_slug: str | None = Header(default=None, alias="X-Hospital-Slug"),
                     db: Session = Depends(get_db)) -> Hospital:
    slug = (x_hospital_slug or settings.default_hospital_slug).strip().lower()
    hospital = db.scalar(select(Hospital).where(Hospital.slug == slug))
    if not hospital:
        raise DomainError("HOSPITAL_NOT_FOUND", "Hospital was not found.", 404)
    return hospital
