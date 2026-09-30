"""Durable WhatsApp inbound delivery queue."""

from alembic import op
import sqlalchemy as sa

revision = "0004_whatsapp_inbound"
down_revision = "0003_whatsapp_integration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("whatsapp_inbound",
        sa.Column("message_id", sa.String(120), primary_key=True),
        sa.Column("sender_id", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(64), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_whatsapp_inbound_sender_id", "whatsapp_inbound", ["sender_id"])
    op.create_index("ix_whatsapp_inbound_status", "whatsapp_inbound", ["status"])
    op.create_index("ix_whatsapp_inbound_available_at", "whatsapp_inbound", ["available_at"])
    op.create_index("ix_whatsapp_inbound_created_at", "whatsapp_inbound", ["created_at"])


def downgrade() -> None:
    op.drop_table("whatsapp_inbound")
