"""WhatsApp assets, support, reminders, and rescheduling."""

from alembic import op
import sqlalchemy as sa

revision = "0003_whatsapp_integration"
down_revision = "0002_voice_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("media_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("storage_name", sa.String(100), nullable=False, unique=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    with op.batch_alter_table("departments") as batch:
        batch.add_column(sa.Column("guide_asset_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_departments_guide_asset", "media_assets", ["guide_asset_id"], ["id"])
    with op.batch_alter_table("doctors") as batch:
        batch.add_column(sa.Column("photo_asset_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_doctors_photo_asset", "media_assets", ["photo_asset_id"], ["id"])
    op.add_column("appointments", sa.Column("consent_to_reminders", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("support_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_key", sa.String(160), nullable=False),
        sa.Column("sender_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_support_cases_owner_key", "support_cases", ["owner_key"])
    op.create_table("case_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("support_cases.id"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("media_assets.id"), nullable=False, unique=True),
        sa.Column("source_message_id", sa.String(120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_case_attachments_case_id", "case_attachments", ["case_id"])
    op.create_table("reminder_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("appointment_id", sa.String(36), sa.ForeignKey("appointments.id"), nullable=False, unique=True),
        sa.Column("sender_id", sa.String(32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_reminder_jobs_appointment_id", "reminder_jobs", ["appointment_id"], unique=True)
    op.create_index("ix_reminder_jobs_due_at", "reminder_jobs", ["due_at"])
    op.create_index("ix_reminder_jobs_status", "reminder_jobs", ["status"])
    op.create_table("reschedule_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("owner_key", sa.String(160), nullable=False),
        sa.Column("appointment_id", sa.String(36), sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("new_reservation_id", sa.String(36), sa.ForeignKey("reservations.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("whatsapp_conversations",
        sa.Column("sender_id", sa.String(32), primary_key=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("last_message_id", sa.String(120), nullable=True),
        sa.Column("last_reply", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade() -> None:
    op.drop_table("whatsapp_conversations")
    op.drop_table("reschedule_operations")
    op.drop_table("reminder_jobs")
    op.drop_table("case_attachments")
    op.drop_table("support_cases")
    op.drop_column("appointments", "consent_to_reminders")
    with op.batch_alter_table("doctors") as batch:
        batch.drop_constraint("fk_doctors_photo_asset", type_="foreignkey")
        batch.drop_column("photo_asset_id")
    with op.batch_alter_table("departments") as batch:
        batch.drop_constraint("fk_departments_guide_asset", type_="foreignkey")
        batch.drop_column("guide_asset_id")
    op.drop_table("media_assets")
