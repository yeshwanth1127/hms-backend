"""Appointment attribution, demo isolation and manually prepared Google links."""
from alembic import op
import sqlalchemy as sa

revision = "0008_google_growth"
down_revision = "6b67db09e83a"
branch_labels = None
depends_on = None


def upgrade():
    # Existing records have unverified provenance; exclude them from production reporting.
    op.add_column("appointments", sa.Column("acquisition_source", sa.String(32), nullable=False, server_default="unknown"))
    op.add_column("appointments", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_appointments_acquisition_source", "appointments", ["acquisition_source"])
    op.create_index("ix_appointments_is_demo", "appointments", ["is_demo"])
    op.create_table("google_booking_links",
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), primary_key=True),
        sa.Column("booking_url", sa.String(2048), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("growth_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("actor", sa.String(160), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("change", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_growth_audit_branch_id", "growth_audit", ["branch_id"])


def downgrade():
    op.drop_table("growth_audit")
    op.drop_table("google_booking_links")
    op.drop_index("ix_appointments_is_demo", table_name="appointments")
    op.drop_index("ix_appointments_acquisition_source", table_name="appointments")
    op.drop_column("appointments", "is_demo")
    op.drop_column("appointments", "acquisition_source")
