from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BranchOut(APIModel):
    id: str
    slug: str
    name: str
    area: str
    timezone: str
    is_virtual: bool


class DepartmentOut(APIModel):
    id: str
    slug: str
    name: str
    tagline: str
    description: str


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
    departments: list[DepartmentOut]
    branches: list[BranchOut]


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


class AppointmentCreate(BaseModel):
    hold_id: str
    owner_key: str = Field(min_length=3, max_length=160)
    patient_name: str = Field(min_length=2, max_length=160)
    patient_phone: str = Field(min_length=7, max_length=32)
    patient_email: EmailStr | None = None
    reason: str | None = Field(default=None, max_length=800)
    origin_channel: Literal["web", "voice", "staff"] = "web"
    idempotency_key: str = Field(min_length=8, max_length=120)


class AppointmentOut(APIModel):
    id: str
    confirmation_code: str
    patient_name: str
    patient_phone: str
    patient_email: str | None
    reason: str | None
    status: str
    origin_channel: str
    created_at: datetime
    reservation: HoldOut


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
    weekday: int = Field(ge=0, le=6)
    starts_at_local: time
    ends_at_local: time
    slot_minutes: int = Field(default=30, ge=10, le=240)
    effective_from: date
    effective_until: date | None = None


class ScheduleRuleOut(APIModel):
    id: str
    doctor_id: str
    branch_id: str
    consultation_type: str
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


class VoiceSessionEvent(BaseModel):
    tool_name: str = Field(min_length=2, max_length=80)
    kind: Literal["tool", "turn"] = "tool"
    outcome: Literal["success", "error", "cancelled"] = "success"
    intent: str | None = Field(default=None, max_length=120)
    appointment_id: str | None = None


class VoiceSessionEnd(BaseModel):
    status: Literal["completed", "abandoned", "error"] = "completed"
