from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BranchOut(APIModel):
    id: str
    slug: str
    name: str
    area: str
    address: str = ""
    directions_url: str = ""
    arrival_instructions: str = ""
    timezone: str
    is_virtual: bool


class DepartmentOut(APIModel):
    id: str
    slug: str
    name: str
    tagline: str
    description: str
    guide_asset_id: str | None = None


class DoctorOut(APIModel):
    id: str
    slug: str
    name: str
    title: str
    bio: str
    experience_years: int
    consultation_fee: int
    accepts_virtual: bool
    image_url: str | None
    photo_asset_id: str | None = None
    departments: list[DepartmentOut]
    branches: list[BranchOut]


class VoiceDoctorOut(DoctorOut):
    in_person_branches: list[BranchOut]
    virtual_branches: list[BranchOut]


class VoiceDoctorsResponse(APIModel):
    """Envelope so voice-agent Jinja templates can iterate `doctors` by name."""
    doctors: list[VoiceDoctorOut]
    count: int


class VoiceBranchesResponse(APIModel):
    """Envelope so voice-agent Jinja templates can iterate `branches` by name."""
    branches: list[BranchOut]
    count: int


class AvailabilitySlot(APIModel):
    doctor_id: str
    branch_id: str
    consultation_type: str
    starts_at: datetime
    ends_at: datetime


class AvailabilityResponse(APIModel):
    slots: list[AvailabilitySlot]
    timezone: str


class HoldCreate(BaseModel):
    doctor_id: str
    branch_id: str
    consultation_type: Literal["in_person", "virtual"]
    starts_at: datetime
    ends_at: datetime
    owner_key: str = Field(min_length=3, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=120)


class HoldOut(APIModel):
    id: str
    doctor_id: str
    branch_id: str
    consultation_type: str
    starts_at: datetime
    ends_at: datetime
    status: str
    expires_at: datetime | None

    @field_validator('starts_at', 'ends_at', 'expires_at')
    @classmethod
    def utc_output(cls, value):
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


class AppointmentCreate(BaseModel):
    hold_id: str
    owner_key: str = Field(min_length=3, max_length=160)
    patient_name: str = Field(min_length=2, max_length=160)
    patient_phone: str = Field(min_length=7, max_length=32)
    patient_email: EmailStr | None = None
    reason: str | None = Field(default=None, max_length=800)
    acquisition_source: Literal["unknown", "direct", "google_business", "organic_search", "paid", "referral"] = "unknown"
    origin_channel: Literal["web", "voice", "staff", "whatsapp"] = "web"
    consent_to_reminders: bool = False
    idempotency_key: str = Field(min_length=8, max_length=120)

    @model_validator(mode="before")
    @classmethod
    def blank_optional_fields(cls, data):
        if isinstance(data, dict):
            if isinstance(data.get("patient_email"), str) and not data["patient_email"].strip():
                data["patient_email"] = None
            if data.get("reason") == "":
                data["reason"] = None
            if data.get("origin_channel") in (None, ""):
                data["origin_channel"] = "web"
        return data


class AppointmentOut(APIModel):
    consultation_fee: int | None = None
    id: str
    confirmation_code: str
    patient_name: str
    patient_phone: str
    patient_email: str | None
    reason: str | None
    status: str
    origin_channel: str
    consent_to_reminders: bool = False
    created_at: datetime
    reservation: HoldOut


class VoiceAppointmentSummary(APIModel):
    id: str
    confirmation_code: str
    status: str
    starts_at: datetime
    ends_at: datetime
    doctor_name: str
    branch_name: str
    consultation_type: str


class VoiceAppointmentsResponse(APIModel):
    """Envelope so voice-agent Jinja templates can iterate `appointments` by name."""
    appointments: list[VoiceAppointmentSummary]
    count: int


class WhatsAppAppointmentOut(AppointmentOut):
    address: str = ""
    directions_url: str = ""
    arrival_instructions: str = ""
    doctor_name: str
    branch_name: str
    timezone: str


class CancelRequest(BaseModel):
    actor_id: str = Field(min_length=2, max_length=160)
    reason: str = Field(min_length=2, max_length=240)


class DoctorAdminUpdate(BaseModel):
    is_active: bool | None = None
    consultation_fee: int | None = Field(default=None, ge=0, le=100000)
    accepts_virtual: bool | None = None


class ScheduleRuleCreate(BaseModel):
    doctor_id: str
    branch_id: str
    consultation_type: Literal["in_person", "virtual"] = "in_person"
    schedule_date: date | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    starts_at_local: time
    ends_at_local: time
    slot_minutes: int = Field(default=30, ge=10, le=240)
    effective_from: date | None = None
    effective_until: date | None = None

    @model_validator(mode="after")
    def normalize_schedule_dates(self):
        if self.schedule_date is None:
            if self.effective_from is None or self.weekday is None:
                raise ValueError("schedule_date is required for new schedules")
            offset = (self.weekday - self.effective_from.weekday()) % 7
            self.schedule_date = self.effective_from + timedelta(days=offset)
        if self.weekday is None:
            self.weekday = self.schedule_date.weekday()
        if self.weekday != self.schedule_date.weekday():
            raise ValueError("weekday must match schedule_date")
        if self.effective_from is None:
            self.effective_from = self.schedule_date
        if self.schedule_date < self.effective_from:
            raise ValueError("schedule_date cannot be before effective_from")
        if self.effective_until is not None and self.effective_until < self.schedule_date:
            raise ValueError("effective_until cannot be before schedule_date")
        return self


class ScheduleRuleOut(APIModel):
    id: str
    doctor_id: str
    branch_id: str
    consultation_type: str
    schedule_date: date
    weekday: int
    starts_at_local: time
    ends_at_local: time
    slot_minutes: int
    effective_from: date
    effective_until: date | None
    is_active: bool


class AppointmentStatusUpdate(BaseModel):
    status: Literal["confirmed", "checked_in", "completed", "cancelled", "no_show"]
    reason: str | None = Field(default=None, max_length=240)


class VoiceSessionCreate(BaseModel):
    runtime_session_id: str = Field(min_length=8, max_length=80)
    channel: Literal["web_voice", "phone"] = "web_voice"
    interaction_id: str = Field(min_length=8, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")
    agent_version: int = Field(ge=1)
    provider_reference: str | None = Field(default=None, max_length=160)
    recording_consent: bool = False


class VoiceSessionEvent(BaseModel):
    event_id: str = Field(min_length=8, max_length=160)
    tool_name: str = Field(min_length=2, max_length=80)
    kind: Literal["tool", "turn"] = "tool"
    outcome: Literal["success", "error", "cancelled"] = "success"
    intent: str | None = Field(default=None, max_length=120)
    appointment_id: str | None = None


class VoiceSessionEnd(BaseModel):
    event_id: str = Field(min_length=8, max_length=160)
    status: Literal["completed", "abandoned", "error"] = "completed"


class WhatsAppHoldCreate(BaseModel):
    sender_id: str = Field(pattern=r"^[0-9]{7,20}$")
    doctor_id: str
    branch_id: str
    consultation_type: Literal["in_person", "virtual"] = "in_person"
    starts_at: datetime
    ends_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=120)


class WhatsAppAppointmentCreate(BaseModel):
    expected_fee: int | None = Field(default=None, ge=0)
    outreach_id: str | None = Field(default=None, max_length=36)
    sender_id: str = Field(pattern=r"^[0-9]{7,20}$")
    hold_id: str
    patient_name: str = Field(min_length=2, max_length=160)
    consent_to_reminders: bool = False
    idempotency_key: str = Field(min_length=8, max_length=120)


class WhatsAppReschedule(BaseModel):
    sender_id: str = Field(pattern=r"^[0-9]{7,20}$")
    new_hold_id: str
    idempotency_key: str = Field(min_length=8, max_length=120)


class WhatsAppCancel(BaseModel):
    sender_id: str = Field(pattern=r"^[0-9]{7,20}$")
    reason: str = Field(min_length=2, max_length=240)


class WhatsAppCaseCreate(BaseModel):
    sender_id: str = Field(pattern=r"^[0-9]{7,20}$")
    kind: Literal["issue", "feedback"]
    description: str = Field(min_length=1, max_length=2000)
    rating: int | None = Field(default=None, ge=1, le=5)
    idempotency_key: str = Field(min_length=8, max_length=120)


class SupportCaseStatusUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"]


class ReminderComplete(BaseModel):
    status: Literal["sent", "failed", "uncertain"]
    error: str | None = Field(default=None, max_length=240)


class WhatsAppConversationSave(BaseModel):
    state: dict
    last_message_id: str = Field(min_length=8, max_length=120)
    last_reply: dict


class WhatsAppInboundCreate(BaseModel):
    message_id: str = Field(min_length=8, max_length=120)
    sender_id: str = Field(pattern=r"^[0-9]{7,20}$")
    payload: dict


class WhatsAppInboundTransition(BaseModel):
    claim_token: str = Field(min_length=32, max_length=64)
    error: str | None = Field(default=None, max_length=240)
