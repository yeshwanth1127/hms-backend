"""Initial catalogue, scheduling, and appointments schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("branches",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("area", sa.String(120), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False), sa.Column("is_virtual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("departments",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("tagline", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("doctors",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("title", sa.String(240), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False), sa.Column("experience_years", sa.Integer(), nullable=False),
        sa.Column("consultation_fee", sa.Integer(), nullable=False), sa.Column("accepts_virtual", sa.Boolean(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("doctor_departments",
        sa.Column("doctor_id", sa.String(36), sa.ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("department_id", sa.String(36), sa.ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True))
    op.create_table("doctor_branches",
        sa.Column("doctor_id", sa.String(36), sa.ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True))
    op.create_table("schedule_rules",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("doctor_id", sa.String(36), sa.ForeignKey("doctors.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("consultation_type", sa.String(32), nullable=False), sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("starts_at_local", sa.Time(), nullable=False), sa.Column("ends_at_local", sa.Time(), nullable=False),
        sa.Column("slot_minutes", sa.Integer(), nullable=False), sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table("schedule_exceptions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("doctor_id", sa.String(36), sa.ForeignKey("doctors.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False))
    op.create_table("reservations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("doctor_id", sa.String(36), sa.ForeignKey("doctors.id"), nullable=False),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("consultation_type", sa.String(32), nullable=False), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("owner_key", sa.String(160), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(120), nullable=True, unique=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("uq_live_doctor_reservation", "reservations", ["doctor_id", "starts_at", "ends_at"], unique=True,
                    postgresql_where=sa.text("status IN ('active','booked')"), sqlite_where=sa.text("status IN ('active','booked')"))
    op.create_table("appointments",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("confirmation_code", sa.String(20), nullable=False, unique=True),
        sa.Column("reservation_id", sa.String(36), sa.ForeignKey("reservations.id"), nullable=False, unique=True),
        sa.Column("patient_name", sa.String(160), nullable=False), sa.Column("patient_phone", sa.String(32), nullable=False),
        sa.Column("patient_email", sa.String(254), nullable=True), sa.Column("reason", sa.String(800), nullable=True),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("origin_channel", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("appointment_status_history",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("appointment_id", sa.String(36), sa.ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True), sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False), sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("reason", sa.String(240), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("outbox_events",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table in ["outbox_events", "appointment_status_history", "appointments", "reservations", "schedule_exceptions", "schedule_rules", "doctor_branches", "doctor_departments", "doctors", "departments", "branches"]:
        op.drop_table(table)

