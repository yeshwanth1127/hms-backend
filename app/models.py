import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Table, Text, Time, Column, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    area: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(500), default="")
    directions_url: Mapped[str] = mapped_column(String(500), default="")
    arrival_instructions: Mapped[str] = mapped_column(String(500), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
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
    departments: Mapped[list[Department]] = relationship(secondary=doctor_departments, lazy="selectin")
    branches: Mapped[list[Branch]] = relationship(secondary=doctor_branches, lazy="selectin")


class ScheduleRule(Base):
    __tablename__ = "schedule_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
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
    consultation_fee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id"), unique=True)
    patient_name: Mapped[str] = mapped_column(String(160))
    patient_phone: Mapped[str] = mapped_column(String(32))
    patient_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(800), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="confirmed")
    acquisition_source: Mapped[str] = mapped_column(String(32), index=True, default="unknown")
    is_demo: Mapped[bool] = mapped_column(Boolean, index=True, default=True)
    origin_channel: Mapped[str] = mapped_column(String(24), default="web")
    consent_to_reminders: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    reservation: Mapped[Reservation] = relationship(lazy="joined")


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


class WhatsAppInbound(Base):
    __tablename__ = "whatsapp_inbound"
    message_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    sender_id: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


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
    provider_reference: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    interaction_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    agent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admission_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mint_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    recording_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recording_notice_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recording_available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appointment: Mapped[Appointment | None] = relationship()


class VoiceAdmissionGate(Base):
    __tablename__ = "voice_admission_gate"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    touched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceRateLimit(Base):
    __tablename__ = "voice_rate_limits"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer, default=0)


class VoiceEventReceipt(Base):
    __tablename__ = "voice_event_receipts"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceRecordingAccess(Base):
    __tablename__ = "voice_recording_access"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("staff_users.id"))
    outcome: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VoiceToolCall(Base):
    __tablename__ = "voice_tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    voice_session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(80), index=True)
    outcome: Mapped[str] = mapped_column(String(24), default="success")
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppContact(Base):
    __tablename__ = "whatsapp_contacts"
    sender_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    service_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    marketing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    stopped_all: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(16), default="en")
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    interests: Mapped[list] = mapped_column(JSON, default=list)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppConsentEvent(Base):
    __tablename__ = "whatsapp_consent_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    sender_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_contacts.sender_id"), index=True)
    source_message_id: Mapped[str] = mapped_column(String(120), unique=True)
    choices: Mapped[dict] = mapped_column(JSON)
    disclosure_version: Mapped[str] = mapped_column(String(40), default="2026-10-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppHandoff(Base):
    __tablename__ = "whatsapp_handoffs"
    sender_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_contacts.sender_id"), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("support_cases.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="waiting", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppCaseMessage(Base):
    __tablename__ = "whatsapp_case_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("support_cases.id"), index=True)
    source_message_id: Mapped[str] = mapped_column(String(120), unique=True)
    direction: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppTemplate(Base):
    __tablename__ = "whatsapp_templates"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    language: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    components: Mapped[list] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppCampaign(Base):
    __tablename__ = "whatsapp_campaigns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(120))
    template_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_templates.id"), index=True)
    template_fingerprint: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[list] = mapped_column(JSON)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True, index=True)
    audience: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rate_paise: Mapped[int] = mapped_column(Integer)
    budget_paise: Mapped[int] = mapped_column(Integer)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppOutbound(Base):
    __tablename__ = "whatsapp_outbound"
    __table_args__ = (Index("ix_whatsapp_outbound_claim", "status", "due_at"),
                     Index("ix_whatsapp_outbound_frequency", "sender_id", "purpose", "sending_at"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_contacts.sender_id"), index=True)
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("whatsapp_campaigns.id"), nullable=True, index=True)
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("support_cases.id"), nullable=True, index=True)
    template_id: Mapped[str | None] = mapped_column(ForeignKey("whatsapp_templates.id"), nullable=True, index=True)
    template_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameters: Mapped[list] = mapped_column(JSON, default=list)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    last_error: Mapped[str | None] = mapped_column(String(240), nullable=True)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    engaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppDeliveryReceipt(Base):
    __tablename__ = "whatsapp_delivery_receipts"
    meta_message_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    status: Mapped[str] = mapped_column(String(24))
    timestamp: Mapped[int] = mapped_column(Integer)


class WhatsAppFollowupRule(Base):
    __tablename__ = "whatsapp_followup_rules"
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("whatsapp_templates.id"), index=True)
    template_fingerprint: Mapped[str] = mapped_column(String(64))
    delay_hours: Mapped[int] = mapped_column(Integer, default=24)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class StaffUser(Base):
    __tablename__ = "staff_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(40))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="staff")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StaffSession(Base):
    __tablename__ = "staff_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("staff_users.id", ondelete="CASCADE"), index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StaffLoginLimit(Base):
    __tablename__ = "staff_login_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoogleBookingLink(Base):
    __tablename__ = "google_booking_links"
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), primary_key=True)
    booking_url: Mapped[str] = mapped_column(String(2048))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GrowthAudit(Base):
    __tablename__ = "growth_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), index=True)
    actor: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(80))
    change: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClientModule(Base):
    """Optional capabilities for this clinic deployment; not a multi-tenant boundary."""
    __tablename__ = "client_modules"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ModuleAudit(Base):
    __tablename__ = "module_audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    module_key: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str] = mapped_column(ForeignKey("staff_users.id"))
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
