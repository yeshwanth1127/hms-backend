"""Add voice runtime operational metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0002_voice_operations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("runtime_session_id", sa.String(80), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("last_intent", sa.String(120), nullable=True),
        sa.Column("appointment_id", sa.String(36), sa.ForeignKey("appointments.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_voice_sessions_runtime_session_id", "voice_sessions", ["runtime_session_id"], unique=True)
    op.create_index("ix_voice_sessions_status", "voice_sessions", ["status"])
    op.create_index("ix_voice_sessions_appointment_id", "voice_sessions", ["appointment_id"])
    op.create_table(
        "voice_tool_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("voice_session_id", sa.String(36), sa.ForeignKey("voice_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(80), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("appointment_id", sa.String(36), sa.ForeignKey("appointments.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_voice_tool_calls_voice_session_id", "voice_tool_calls", ["voice_session_id"])
    op.create_index("ix_voice_tool_calls_tool_name", "voice_tool_calls", ["tool_name"])


def downgrade() -> None:
    op.drop_table("voice_tool_calls")
    op.drop_table("voice_sessions")
