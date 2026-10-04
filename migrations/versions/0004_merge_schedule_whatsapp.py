"""Merge schedule-date and WhatsApp migration heads."""

revision = "0004_merge_schedule_whatsapp"
down_revision = ("0003_schedule_dates", "0003_whatsapp_integration")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
