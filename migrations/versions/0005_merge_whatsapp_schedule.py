"""Merge the independently published schedule and WhatsApp migration branches."""

revision = "0005_merge_whatsapp_schedule"
down_revision = ("0004_whatsapp_inbound", "0003_schedule_dates")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
