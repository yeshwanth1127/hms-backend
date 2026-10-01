"""Voice admission, provider correlation and audited recording access."""

from alembic import op
import sqlalchemy as sa

revision = "0010_voice_module"
down_revision = "0009_client_modules"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("voice_sessions") as table:
        for name, type_ in [
            ("provider_reference", sa.String(160)),
            ("interaction_id", sa.String(160)),
            ("agent_version", sa.Integer()),
            ("admission_hash", sa.String(64)),
            ("expires_at", sa.DateTime(timezone=True)),
            ("recording_consent_at", sa.DateTime(timezone=True)),
            ("recording_notice_version", sa.String(40)),
            ("recording_available_until", sa.DateTime(timezone=True)),
        ]:
            table.add_column(sa.Column(name, type_, nullable=True))
        table.add_column(
            sa.Column(
                "mint_claimed", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        for name in ["provider_reference", "interaction_id", "admission_hash"]:
            table.create_unique_constraint("uq_voice_sessions_" + name, [name])
    op.create_table(
        "voice_admission_gate",
        sa.Column("key", sa.String(40), primary_key=True),
        sa.Column("touched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO voice_admission_gate (key, touched_at) VALUES ('clinic', CURRENT_TIMESTAMP)"
        )
    )
    op.create_table(
        "voice_rate_limits",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "voice_event_receipts",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("voice_sessions.id"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_voice_event_receipts_session_id", "voice_event_receipts", ["session_id"]
    )
    op.create_table(
        "voice_recording_access",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("voice_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.String(36), sa.ForeignKey("staff_users.id"), nullable=False
        ),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_voice_recording_access_session_id", "voice_recording_access", ["session_id"]
    )


def downgrade():
    for table in [
        "voice_recording_access",
        "voice_event_receipts",
        "voice_rate_limits",
        "voice_admission_gate",
    ]:
        op.drop_table(table)
    with op.batch_alter_table("voice_sessions") as table:
        for name in ["provider_reference", "interaction_id", "admission_hash"]:
            table.drop_constraint("uq_voice_sessions_" + name, type_="unique")
        for name in [
            "provider_reference",
            "interaction_id",
            "agent_version",
            "admission_hash",
            "expires_at",
            "mint_claimed",
            "recording_consent_at",
            "recording_notice_version",
            "recording_available_until",
        ]:
            table.drop_column(name)
