import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Table, Text, Time, Column, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def patient_code() -> str:
    return f"EXO-P-{uuid.uuid4().hex[:8].upper()}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Hospital(Base):
    __tablename__ = "hospitals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    virtual_opd_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HospitalMembership(Base):
    __tablename__ = "hospital_memberships"
    __table_args__ = (UniqueConstraint("hospital_id", "user_id", "role", name="uq_membership_role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    membership_id: Mapped[str] = mapped_column(ForeignKey("hospital_memberships.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (UniqueConstraint("hospital_id", "user_id", name="uq_patient_user_hospital"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    patient_code: Mapped[str] = mapped_column(String(24), unique=True, index=True, default=patient_code)
    access_code_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


doctor_departments = Table(
    "doctor_departments", Base.metadata,
    Column("doctor_id", String(36), ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True),
    Column("department_id", String(36), ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
)
doctor_branches = Table(
    "doctor_branches", Base.metadata,
    Column("doctor_id", String(36), ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True),
    Column("branch_id", String(36), ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True),
)


class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    area: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    tagline: Mapped[str] = mapped_column(String(240), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    guide_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True)


class Doctor(Base):
    __tablename__ = "doctors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(240))
    bio: Mapped[str] = mapped_column(Text, default="")
    experience_years: Mapped[int] = mapped_column(Integer)
    consultation_fee: Mapped[int] = mapped_column(Integer)
    accepts_virtual: Mapped[bool] = mapped_column(Boolean, default=False)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, unique=True)
    departments: Mapped[list[Department]] = relationship(secondary=doctor_departments, lazy="selectin")
    branches: Mapped[list[Branch]] = relationship(secondary=doctor_branches, lazy="selectin")


class ScheduleRule(Base):
    __tablename__ = "schedule_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    consultation_type: Mapped[str] = mapped_column(String(32), default="in_person")
    schedule_date: Mapped[date] = mapped_column(Date, index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    starts_at_local: Mapped[time] = mapped_column(Time)
    ends_at_local: Mapped[time] = mapped_column(Time)
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(240), default="Unavailable")


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        Index("uq_live_doctor_reservation", "doctor_id", "starts_at", "ends_at", unique=True,
              postgresql_where=text("status IN ('active','booked')"), sqlite_where=text("status IN ('active','booked')")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    doctor_id: Mapped[str] = mapped_column(ForeignKey("doctors.id"), index=True)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    consultation_type: Mapped[str] = mapped_column(String(32))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active")
    owner_key: Mapped[str] = mapped_column(String(160))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    confirmation_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id"), unique=True)
    hospital_id: Mapped[str | None] = mapped_column(ForeignKey("hospitals.id"), nullable=True, index=True)
    patient_id: Mapped[str | None] = mapped_column(ForeignKey("patients.id"), nullable=True, index=True)
    patient_name: Mapped[str] = mapped_column(String(160))
    patient_phone: Mapped[str] = mapped_column(String(32))
    patient_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(800), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="confirmed")
    origin_channel: Mapped[str] = mapped_column(String(24), default="web")
    consent_to_reminders: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    reservation: Mapped[Reservation] = relationship(lazy="joined")


class Teleconsultation(Base):
    __tablename__ = "teleconsultations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), unique=True, index=True)
    room_key: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="scheduled", index=True)
    doctor_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by_actor_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ended_by_actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TeleconsultationConsent(Base):
    __tablename__ = "teleconsultation_consents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    teleconsultation_id: Mapped[str] = mapped_column(ForeignKey("teleconsultations.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    document_version: Mapped[str] = mapped_column(String(40))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_by_actor_type: Mapped[str] = mapped_column(String(32))
    captured_by_actor_id: Mapped[str] = mapped_column(String(36))


class TeleconsultationEvent(Base):
    __tablename__ = "teleconsultation_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    hospital_id: Mapped[str] = mapped_column(ForeignKey("hospitals.id"), index=True)
    teleconsultation_id: Mapped[str] = mapped_column(ForeignKey("teleconsultations.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(36))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppointmentStatusHistory(Base):
    __tablename__ = "appointment_status_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(32))
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    storage_name: Mapped[str] = mapped_column(String(100), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportCase(Base):
    __tablename__ = "support_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_key: Mapped[str] = mapped_column(String(160), index=True)
    sender_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="open")
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseAttachment(Base):
    __tablename__ = "case_attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("support_cases.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"), unique=True)
    source_message_id: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReminderJob(Base):
    __tablename__ = "reminder_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"), unique=True, index=True)
    sender_id: Mapped[str] = mapped_column(String(32))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RescheduleOperation(Base):
    __tablename__ = "reschedule_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    owner_key: Mapped[str] = mapped_column(String(160))
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"))
    new_reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppConversation(Base):
    __tablename__ = "whatsapp_conversations"
    sender_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[dict] = mapped_column(JSON)
    last_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_reply: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VoiceSession(Base):
    """Operational voice metadata owned by Core API; audio remains in the voice runtime."""
    __tablename__ = "voice_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    runtime_session_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    channel: Mapped[str] = mapped_column(String(24), default="web_voice")
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    last_intent: Mapped[str | None] = mapped_column(String(120), nullable=True)
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceToolCall(Base):
    __tablename__ = "voice_tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    voice_session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(80), index=True)
    outcome: Mapped[str] = mapped_column(String(24), default="success")
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
