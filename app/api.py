from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Appointment, Branch, Department, Doctor, Reservation
from .schemas import (
    AppointmentCreate, AppointmentOut, AvailabilityResponse, BranchOut, CancelRequest,
    DepartmentOut, DoctorOut, HoldCreate, HoldOut,
)
from .services import availability, cancel_appointment, confirm_appointment, create_hold

router = APIRouter(prefix="/api/v1")


def require_public_booking_pilot() -> None:
    if settings.app_env == "production":
        from .services import DomainError
        raise DomainError("PATIENT_AUTH_REQUIRED", "Use an authenticated booking channel.", 403)


@router.get("/branches", response_model=list[BranchOut])
def branches(db: Session = Depends(get_db)):
    return db.scalars(select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.name)).all()


@router.get("/departments", response_model=list[DepartmentOut])
def departments(db: Session = Depends(get_db)):
    return db.scalars(select(Department).where(Department.is_active.is_(True)).order_by(Department.name)).all()


@router.get("/doctors", response_model=list[DoctorOut])
def doctors(department: str | None = None, branch: str | None = None, db: Session = Depends(get_db)):
    items = db.scalars(select(Doctor).where(Doctor.is_active.is_(True)).order_by(Doctor.name)).unique().all()
    if department:
        items = [item for item in items if any(d.slug == department or d.id == department for d in item.departments)]
    if branch:
        items = [item for item in items if any(b.slug == branch or b.id == branch for b in item.branches)]
    return items


@router.get("/doctors/{doctor_id}", response_model=DoctorOut)
def doctor(doctor_id: str, db: Session = Depends(get_db)):
    item = db.scalar(select(Doctor).where((Doctor.id == doctor_id) | (Doctor.slug == doctor_id)))
    if not item:
        from .services import DomainError
        raise DomainError("DOCTOR_NOT_FOUND", "Doctor was not found.", 404)
    return item


@router.get("/availability", response_model=AvailabilityResponse)
def get_availability(doctor_id: str, branch_id: str, start_date: date,
                     end_date: date, consultation_type: str = Query("in_person", pattern="^(in_person|virtual)$"),
                     db: Session = Depends(get_db)):
    slots, timezone_name = availability(db, doctor_id, branch_id, start_date, end_date, consultation_type)
    return AvailabilityResponse(slots=slots, timezone=timezone_name)


@router.post("/slot-holds", response_model=HoldOut, status_code=201)
def hold_create(body: HoldCreate, _: None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    return create_hold(db, body)


@router.get("/slot-holds/{hold_id}", response_model=HoldOut)
def hold_get(hold_id: str, owner_key: str, _: None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    hold = db.get(Reservation, hold_id)
    if not hold or hold.owner_key != owner_key:
        from .services import DomainError
        raise DomainError("HOLD_NOT_FOUND", "The slot hold was not found.", 404)
    return hold


@router.delete("/slot-holds/{hold_id}", status_code=204)
def hold_release(hold_id: str, owner_key: str, _: None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    hold = db.get(Reservation, hold_id)
    if hold and hold.owner_key == owner_key and hold.status == "active":
        hold.status = "released"
        db.commit()


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
def appointment_create(body: AppointmentCreate, _: None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    return confirm_appointment(db, body)


@router.get("/appointments/{appointment_id}", response_model=AppointmentOut)
def appointment_get(appointment_id: str, owner_key: str = Header(alias="X-Owner-Key"),
                    _: None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    item = db.get(Appointment, appointment_id)
    if not item or item.reservation.owner_key != owner_key:
        from .services import DomainError
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    return item


@router.patch("/appointments/{appointment_id}/cancel", response_model=AppointmentOut)
def appointment_cancel(appointment_id: str, body: CancelRequest,
                       owner_key: str = Header(alias="X-Owner-Key"),
                       _: None = Depends(require_public_booking_pilot), db: Session = Depends(get_db)):
    item = db.get(Appointment, appointment_id)
    if not item or item.reservation.owner_key != owner_key:
        from .services import DomainError
        raise DomainError("APPOINTMENT_NOT_FOUND", "Appointment was not found.", 404)
    return cancel_appointment(db, item, body.actor_id, body.reason)
