"""Staff-only asset and support intake surfaces."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .admin import require_admin
from .client_modules import require_whatsapp_module
from .db import get_db
from .media import asset_row, media_path, save_upload
from .models import CaseAttachment, Department, Doctor, MediaAsset, ReminderJob, SupportCase, WhatsAppInbound
from .schemas import SupportCaseStatusUpdate
from .services import DomainError

router = APIRouter(prefix="/api/v1/admin", tags=["admin-whatsapp"], dependencies=[Depends(require_whatsapp_module)])
page_router = APIRouter()


@page_router.get("/whatsapp-assets", include_in_schema=False)
def upload_page():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/staff/whatsapp")


@router.get("/whatsapp-assets")
def asset_inventory(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    departments = db.scalars(select(Department).order_by(Department.name)).all()
    doctors = db.scalars(select(Doctor).order_by(Doctor.name)).unique().all()
    return {
        "departments": [{"id": item.id, "slug": item.slug, "name": item.name,
                         "guide": asset_row(db.get(MediaAsset, item.guide_asset_id)) if item.guide_asset_id else None}
                        for item in departments],
        "doctors": [{"id": item.id, "name": item.name, "title": item.title,
                     "departments": [value.name for value in item.departments],
                     "photo": asset_row(db.get(MediaAsset, item.photo_asset_id)) if item.photo_asset_id else None}
                    for item in doctors],
    }


@router.post("/departments/{department_id}/guide", status_code=201)
async def guide_upload(department_id: str, file: UploadFile = File(),
                       _: str = Depends(require_admin), db: Session = Depends(get_db)):
    department = db.get(Department, department_id)
    if not department:
        raise DomainError("DEPARTMENT_NOT_FOUND", "Department was not found.", 404)
    asset = await save_upload(db, file, "guide")
    db.flush()
    department.guide_asset_id = asset.id
    db.commit()
    return asset_row(asset)


@router.post("/doctors/{doctor_id}/photo", status_code=201)
async def photo_upload(doctor_id: str, file: UploadFile = File(),
                       _: str = Depends(require_admin), db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if not doctor:
        raise DomainError("DOCTOR_NOT_FOUND", "Doctor was not found.", 404)
    asset = await save_upload(db, file, "photo")
    db.flush()
    doctor.photo_asset_id = asset.id
    db.commit()
    return asset_row(asset)


@router.get("/whatsapp-cases")
def cases(limit: int = 100, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    if limit < 1 or limit > 500:
        raise DomainError("INVALID_LIMIT", "Limit must be between 1 and 500.", 422)
    items = db.scalars(select(SupportCase).order_by(SupportCase.created_at.desc()).limit(limit)).all()
    return [{"id": item.id, "kind": item.kind, "description": item.description,
             "rating": item.rating, "status": item.status, "sender_id": item.sender_id,
             "created_at": item.created_at,
             "attachments": [{"id": attached.id, "asset": asset_row(db.get(MediaAsset, attached.asset_id))}
                             for attached in db.scalars(select(CaseAttachment).where(CaseAttachment.case_id == item.id)).all()]}
            for item in items]


@router.get("/whatsapp-delivery-issues")
def delivery_issues(_: str = Depends(require_admin), db: Session = Depends(get_db)):
    inbound_counts = dict(db.execute(select(WhatsAppInbound.status, func.count()).group_by(WhatsAppInbound.status)).all())
    reminder_counts = dict(db.execute(select(ReminderJob.status, func.count()).group_by(ReminderJob.status)).all())
    inbound = db.scalars(select(WhatsAppInbound).where(WhatsAppInbound.status.in_(("failed", "uncertain")))
                         .order_by(WhatsAppInbound.created_at.desc()).limit(100)).all()
    reminders = db.scalars(select(ReminderJob).where(ReminderJob.status.in_(("failed", "uncertain")))
                           .order_by(ReminderJob.created_at.desc()).limit(100)).all()
    return {
        "counts": {"inbound": inbound_counts, "reminders": reminder_counts},
        "inbound": [{"message_id": item.message_id, "status": item.status,
                     "created_at": item.created_at, "attempts": item.attempts}
                    for item in inbound],
        "reminders": [{"id": item.id, "appointment_id": item.appointment_id,
                       "status": item.status, "attempts": item.attempts}
                      for item in reminders],
    }


@router.patch("/whatsapp-cases/{case_id}")
def case_status(case_id: str, body: SupportCaseStatusUpdate,
                _: str = Depends(require_admin), db: Session = Depends(get_db)):
    item = db.get(SupportCase, case_id)
    if not item:
        raise DomainError("CASE_NOT_FOUND", "Case was not found.", 404)
    item.status = body.status
    db.commit()
    return {"id": item.id, "status": item.status}


@router.get("/whatsapp-case-assets/{asset_id}")
def case_asset(asset_id: str, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    attached = db.scalar(select(CaseAttachment).where(CaseAttachment.asset_id == asset_id))
    asset = db.get(MediaAsset, asset_id)
    if not attached or not asset:
        raise DomainError("ASSET_NOT_FOUND", "Attachment was not found.", 404)
    path = media_path(asset.storage_name)
    if not path.is_file():
        raise DomainError("ASSET_MISSING", "Attachment is missing from storage.", 503)
    return FileResponse(path, media_type=asset.mime_type, filename=asset.original_name,
                        headers={"Cache-Control": "private, no-store"})
