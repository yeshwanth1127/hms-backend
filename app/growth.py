"""Aggregate operational growth metrics and manual Google booking-link preparation."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .staff_access import permission_required, require_growth_read, require_google_manage, require_growth_audit, require_google_read
from .config import settings
from .db import get_db
from .models import Appointment, Branch, Reservation, GoogleBookingLink, GrowthAudit, StaffUser
from .services import DomainError

router = APIRouter(prefix="/api/v1/admin", tags=["growth"])
page_router = APIRouter()




def require_workspace_read(staff: StaffUser = Depends(permission_required("growth.read")), db: Session = Depends(get_db)):
    from .client_modules import is_enabled
    if not any(is_enabled(db, key) for key in ("google_business", "growth_analytics")):
        raise DomainError("MODULE_DISABLED", "Your clinic has not enabled a growth module.", 403)
    return staff


class LinkInput(BaseModel):
    booking_url: HttpUrl = Field(max_length=2048)


def branch_or_404(db: Session, branch_id: str) -> Branch:
    branch = db.get(Branch, branch_id)
    if not branch:
        raise DomainError("BRANCH_NOT_FOUND", "Branch was not found.", 404)
    return branch


@page_router.get("/growth", include_in_schema=False)
def growth_page():
    return RedirectResponse("/staff/google_business/overview", status_code=307)


@router.get("/growth/summary")
def summary(start_date: date | None = None, end_date: date | None = None,
            branch_id: str | None = None, reporting_timezone: str = "Asia/Kolkata",
            cohort: Literal["created", "visit"] = "created", include_demo: bool = False,
            _: StaffUser = Depends(require_growth_read), db: Session = Depends(get_db)):
    branch = branch_or_404(db, branch_id) if branch_id else None
    try:
        tz = ZoneInfo(branch.timezone if branch else reporting_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise DomainError("INVALID_TIMEZONE", "Choose a valid reporting timezone.", 422)
    now = datetime.now(timezone.utc)
    end = end_date or now.astimezone(tz).date()
    start = start_date or end - timedelta(days=29)
    if start > end or end == date.max or (end - start).days > 365:
        raise DomainError("INVALID_DATE_RANGE", "Choose an ordered range of at most 366 days.", 422)
    lower = datetime.combine(start, time.min, tz).astimezone(timezone.utc)
    upper = datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(timezone.utc)
    column = Appointment.created_at if cohort == "created" else Reservation.starts_at
    filters = [column >= lower, column < upper]
    if branch:
        filters.append(Reservation.branch_id == branch.id)
    if not include_demo:
        filters.append(Appointment.is_demo.is_(False))

    def grouped(column):
        rows = db.execute(select(column, func.count(Appointment.id)).join(
            Reservation, Appointment.reservation_id == Reservation.id
        ).where(*filters).group_by(column).order_by(column)).all()
        return {key: count for key, count in rows}

    by_status = grouped(Appointment.status)
    total = sum(by_status.values())
    retained = sum(by_status.get(key, 0) for key in ("confirmed", "checked_in", "completed"))
    past_filters = [*filters, Reservation.ends_at <= now]
    past_rows = db.execute(select(Appointment.status, func.count(Appointment.id)).join(
        Reservation, Appointment.reservation_id == Reservation.id
    ).where(*past_filters).group_by(Appointment.status)).all()
    past = dict(past_rows)
    attended = past.get("checked_in", 0) + past.get("completed", 0)
    resolved = attended + past.get("no_show", 0)
    return {
        "generated_at": now, "environment": "demo_included" if include_demo else "production_records_only",
        "filters": {"start_date": start, "end_date": end, "branch_id": branch_id,
                    "timezone": str(tz), "cohort": cohort, "include_demo": include_demo},
        "summary": {"appointments_created": total if cohort == "created" else None,
                    "appointments_in_cohort": total, "retained_confirmations": retained,
                    "cancelled": by_status.get("cancelled", 0),
                    "retained_confirmation_share": round(retained / total * 100, 1) if total else None,
                    "attendance_rate_resolved": round(attended / resolved * 100, 1) if resolved else None,
                    "attendance_denominator": resolved, "past_attended": attended,
                    "past_no_show": past.get("no_show", 0),
                    "past_cancelled": past.get("cancelled", 0),
                    "past_outcome_unknown": sum(value for key, value in past.items()
                                                if key not in {"checked_in", "completed", "cancelled", "no_show"})},
        "by_status": by_status, "by_channel": grouped(Appointment.origin_channel),
        "by_acquisition_source": grouped(Appointment.acquisition_source),
        "sources": {"backend": "available", "google": "not_connected", "posthog": "not_connected"},
        "unavailable_metrics": ["visitor_to_booking_conversion", "google_impressions", "slot_utilization"],
        "definitions": {
            "retained_confirmation_share": "Current confirmed, checked-in or completed records / all records in the cohort; not visitor conversion.",
            "attendance_rate_resolved": "Attended / (attended + no-show), for visits ended by now; unknown and cancelled outcomes are reported separately.",
            "acquisition_source": "Allowlisted booking-entry attribution; independent of delivery channel and not verified Google identity.",
        },
    }


def link_row(item: GoogleBookingLink):
    return {"branch_id": item.branch_id, "booking_url": item.booking_url,
            "updated_at": item.updated_at, "mode": "manual_setup",
            "google_publish_state": "not_published_by_this_app", "public_visibility": "unverified"}


@router.get("/google/booking-links")
def links(_: StaffUser = Depends(require_google_read), db: Session = Depends(get_db)):
    return {"mode": "manual_setup", "connection_status": "not_connected",
            "links": [link_row(item) for item in db.scalars(select(GoogleBookingLink)).all()],
            "requirements": ["Live authenticated website booking", "Google profile manager access",
                             "Business Profile API approval and OAuth for automated publishing"],
            "native_slots": "requires_separate_healthcare_partner_eligibility"}


@router.put("/google/booking-links/{branch_id}")
def save_link(branch_id: str, body: LinkInput, actor: StaffUser = Depends(require_google_manage),
              db: Session = Depends(get_db)):
    branch = branch_or_404(db, branch_id)
    if branch.is_virtual or not branch.is_active:
        raise DomainError("INELIGIBLE_BRANCH", "Choose an active physical clinic branch.", 422)
    parts = urlsplit(str(body.booking_url))
    if parts.scheme != "https" or parts.username or parts.password or parts.fragment:
        raise DomainError("INVALID_BOOKING_URL", "Use an HTTPS booking URL without credentials or a fragment.", 422)
    approved = {value.strip().rstrip("/") for value in settings.booking_allowed_origins.split(",") if value.strip()}
    if not approved:
        raise DomainError("BOOKING_ORIGINS_NOT_CONFIGURED", "Configure BOOKING_ALLOWED_ORIGINS with the clinic's approved HTTPS origin first.", 503)
    if f"{parts.scheme}://{parts.netloc}" not in approved:
        raise DomainError("UNAPPROVED_BOOKING_ORIGIN", "Choose the clinic's approved booking origin.", 422)
    # A controlled landing path must implement these routing parameters before publication.
    params = parse_qsl(parts.query, keep_blank_values=True)
    if any(key not in {"branch", "source"} for key, _ in params):
        raise DomainError("INVALID_BOOKING_URL", "Booking URLs may contain only branch and source parameters.", 422)
    url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                     urlencode({"branch": branch.slug, "source": "google_business"}), ""))
    if len(url) > 2048:
        raise DomainError("INVALID_BOOKING_URL", "Booking URL is too long.", 422)
    item = db.get(GoogleBookingLink, branch_id)
    before = item.booking_url if item else None
    if before != url:
        if item:
            item.booking_url = url
        else:
            item = GoogleBookingLink(branch_id=branch_id, booking_url=url)
            db.add(item)
        db.add(GrowthAudit(branch_id=branch_id, actor=actor.id, action="booking_link_prepared",
                           change={"before": before, "after": url}))
        db.commit()
        db.refresh(item)
    return link_row(item)


@router.get("/google/changes")
def changes(branch_id: str | None = None, limit: int = Query(50, ge=1, le=100),
            _: StaffUser = Depends(require_growth_audit), db: Session = Depends(get_db)):
    query = select(GrowthAudit, StaffUser.display_name).outerjoin(StaffUser, StaffUser.id == GrowthAudit.actor).order_by(GrowthAudit.created_at.desc()).limit(limit)
    if branch_id:
        branch_or_404(db, branch_id)
        query = query.where(GrowthAudit.branch_id == branch_id)
    return [{"id": item.id, "branch_id": item.branch_id, "actor": item.actor,
             "actor_name": name or "Former staff account", "action": item.action, "change": item.change, "created_at": item.created_at}
            for item, name in db.execute(query).all()]


@router.get("/growth/catalogue")
def growth_catalogue(_: StaffUser = Depends(require_workspace_read), db: Session = Depends(get_db)):
    return {"branches": [{"id": branch.id, "slug": branch.slug, "name": branch.name,
                          "is_active": branch.is_active, "is_virtual": branch.is_virtual}
                         for branch in db.scalars(select(Branch).order_by(Branch.name)).all()]}


@router.get("/google/setup")
def google_setup(_: StaffUser = Depends(require_google_read)):
    return {"profile_status": "not_connected", "preview_mode": "draft_only",
            "steps": ["Prepare factual clinic name, physical address, category, phone, website and hours",
                      "Clinic owner creates the profile in their Google account",
                      "Complete the verification method Google offers",
                      "Grant the designated growth manager Google access",
                      "Connect the verified profile to this backend through approved OAuth"],
            "create_url": "https://business.google.com/add",
            "verification_help": "https://support.google.com/business/answer/7107242",
            "native_slots": "not_available_until_partner_eligibility_is_confirmed"}


@router.get("/google/capabilities")
def google_capabilities(_: StaffUser = Depends(require_google_read)):
    return {"mode": "planning_only", "google_connected": False, "capabilities": [
        {"title": "Profile details & opening hours", "state": "Google supported · not connected",
         "description": "Name, category, address, phone, website, regular and special hours. Use accurate clinic details; doctor schedules remain separate.",
         "reference": "https://developers.google.com/my-business/reference/businessinformation/rest"},
        {"title": "Appointment link", "state": "Recommended first booking path",
         "description": "Send patients straight to a branch-specific live booking page. We can prepare links locally; Google approval, appearance and API publishing are separate.",
         "reference": "https://developers.google.com/my-business/reference/placeactions/rest"},
        {"title": "Slots directly inside Google", "state": "Conditional future integration",
         "description": "Requires an eligible healthcare/country integration and partner acceptance. The preview uses example times; no native slot capability has been granted.",
         "reference": "https://developers.google.com/actions-center/verticals/appointments/redirect/support"},
        {"title": "Photos, services & clinic updates", "state": "Verify support for this profile",
         "description": "Approved exterior/interior photos, factual services and useful posts can improve the listing. Available fields, post actions and API support depend on the profile.",
         "reference": "https://developers.google.com/my-business/reference/rest/"},
        {"title": "Review management", "state": "Staff-reviewed workflow",
         "description": "Read genuine reviews and prepare replies. No invented ratings, review filtering or patient-specific public disclosures. A reply is published only through an approved workflow.",
         "reference": "https://developers.google.com/my-business/content/review-data"},
        {"title": "Google discovery & action reports", "state": "API connection required",
         "description": "Supported impressions, website clicks, call clicks, directions and monthly search-keyword metrics. A call click is not proof of a connected call or appointment.",
         "reference": "https://developers.google.com/my-business/reference/performance/rpc/google.mybusiness.performance.v1"},
        {"title": "Website conversion insights", "state": "PostHog workstream · not connected",
         "description": "Consented booking funnels, form friction and CTA experiments. Backend confirmations remain the operational source of truth; no patient fields go into product analytics.",
         "reference": "https://posthog.com/docs/product-analytics/funnels"},
        {"title": "Messaging & WhatsApp", "state": "Check current profile eligibility",
         "description": "The old Google Business Messages inbox/API and call history were retired. Verified profiles in supported regions may offer WhatsApp/text contact links; our website WhatsApp booking path is separate.",
         "reference": "https://support.google.com/business/answer/15013580"},
        {"title": "Paid search & location promotion", "state": "Separate Ads account and budget",
         "description": "A later acquisition workstream with spend controls and healthcare advertising review. No campaign or spending is configured by this dashboard.",
         "reference": "https://support.google.com/adspolicy/answer/176031"},
        {"title": "Clinic attendance & retention", "state": "Backend operations",
         "description": "Measure persisted confirmations, cancellations and attendance. Reminders, rescheduling and opt-in waitlists can help fill genuine capacity; they are not Google Profile controls.",
         "reference": "/docs"},
    ]}
