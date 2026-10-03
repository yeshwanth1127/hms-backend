"""Clinic-wide audit trail and owner-controlled staff permissions."""
from alembic import op
import sqlalchemy as sa
revision = '0012_audit_trail'
down_revision = '0011_booking_journey'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audit_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('request_id', sa.String(80), nullable=False),
        sa.Column('actor_type', sa.String(20), nullable=False, index=True),
        sa.Column('actor_id', sa.String(80), nullable=False, index=True),
        sa.Column('actor_label', sa.String(160), nullable=False),
        sa.Column('action', sa.String(160), nullable=False, index=True),
        sa.Column('targets', sa.JSON, nullable=False),
        sa.Column('target_text', sa.String(400), nullable=False, index=True),
        sa.Column('change', sa.JSON, nullable=False),
        sa.Column('status_code', sa.Integer, nullable=False),
        sa.Column('client_ip', sa.String(64), nullable=False))
    op.create_index('ix_audit_events_created', 'audit_events', ['created_at'])
    op.create_table('staff_permissions',
        sa.Column('key', sa.String(40), primary_key=True),
        sa.Column('allowed', sa.Boolean, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('staff_permissions')
    op.drop_index('ix_audit_events_created', table_name='audit_events')
    op.drop_table('audit_events')
