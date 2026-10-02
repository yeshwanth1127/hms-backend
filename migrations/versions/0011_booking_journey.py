"""Verified web booking, waitlist and operations audit."""
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa
revision = '0011_booking_journey'
down_revision = '0010_voice_module'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('web_booking_sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('code_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('phone', sa.String(20), nullable=False, index=True),
        sa.Column('ip_hash', sa.String(64), nullable=False, index=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('booking_gate', sa.Column('key', sa.String(40), primary_key=True),
        sa.Column('touched_at', sa.DateTime(timezone=True), nullable=False))
    op.bulk_insert(sa.table('booking_gate', sa.column('key', sa.String), sa.column('touched_at', sa.DateTime(timezone=True))),
        [{'key': 'web-verification', 'touched_at': datetime.now(timezone.utc)}])
    op.create_table('booking_operation_audit',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('actor', sa.String(160), nullable=False),
        sa.Column('action', sa.String(60), nullable=False), sa.Column('record_id', sa.String(64), nullable=False),
        sa.Column('change', sa.JSON, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('waitlist_entries',
        sa.Column('id', sa.String(36), primary_key=True), sa.Column('phone', sa.String(20), nullable=False, index=True),
        sa.Column('patient_name', sa.String(160), nullable=False),
        sa.Column('doctor_id', sa.String(36), sa.ForeignKey('doctors.id'), nullable=False),
        sa.Column('branch_id', sa.String(36), sa.ForeignKey('branches.id'), nullable=False),
        sa.Column('consultation_type', sa.String(32), nullable=False),
        sa.Column('start_date', sa.Date, nullable=False), sa.Column('end_date', sa.Date, nullable=False),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('consent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hold_id', sa.String(36), sa.ForeignKey('reservations.id'), nullable=True),
        sa.Column('appointment_id', sa.String(36), sa.ForeignKey('appointments.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ('waitlist_entries', 'booking_operation_audit', 'booking_gate', 'web_booking_sessions'):
        op.drop_table(table)
