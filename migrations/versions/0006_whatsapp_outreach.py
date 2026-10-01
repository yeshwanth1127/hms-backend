"""WhatsApp preferences reception and outreach

Revision ID: 0006_whatsapp_outreach
Revises: 0005_merge_whatsapp_schedule
Create Date: 2026-10-01 01:18:32.807059
"""
from typing import Sequence, Union
from datetime import datetime, timezone
import uuid
from alembic import op
import sqlalchemy as sa


revision: str = '0006_whatsapp_outreach'
down_revision: Union[str, None] = '0005_merge_whatsapp_schedule'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('whatsapp_delivery_receipts',
    sa.Column('meta_message_id', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('timestamp', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('meta_message_id')
    )
    op.create_table('whatsapp_templates',
    sa.Column('id', sa.String(length=80), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('category', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('components', sa.JSON(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_whatsapp_templates_name'), 'whatsapp_templates', ['name'], unique=False)
    op.create_table('whatsapp_campaigns',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=120), nullable=False),
    sa.Column('template_id', sa.String(length=80), nullable=False),
    sa.Column('template_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('parameters', sa.JSON(), nullable=False),
    sa.Column('asset_id', sa.String(length=36), nullable=True),
    sa.Column('audience', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rate_paise', sa.Integer(), nullable=False),
    sa.Column('budget_paise', sa.Integer(), nullable=False),
    sa.Column('approved_count', sa.Integer(), nullable=False),
    sa.Column('approved_by', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], ),
    sa.ForeignKeyConstraint(['template_id'], ['whatsapp_templates.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_whatsapp_campaigns_asset_id'), 'whatsapp_campaigns', ['asset_id'], unique=False)
    op.create_index(op.f('ix_whatsapp_campaigns_status'), 'whatsapp_campaigns', ['status'], unique=False)
    op.create_index(op.f('ix_whatsapp_campaigns_template_id'), 'whatsapp_campaigns', ['template_id'], unique=False)
    op.create_table('whatsapp_case_messages',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.Column('source_message_id', sa.String(length=120), nullable=False),
    sa.Column('direction', sa.String(length=16), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('actor', sa.String(length=100), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['support_cases.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_message_id')
    )
    op.create_index(op.f('ix_whatsapp_case_messages_case_id'), 'whatsapp_case_messages', ['case_id'], unique=False)
    op.create_table('whatsapp_contacts',
    sa.Column('sender_id', sa.String(length=32), nullable=False),
    sa.Column('service_messages', sa.Boolean(), nullable=False),
    sa.Column('marketing', sa.Boolean(), nullable=False),
    sa.Column('stopped_all', sa.Boolean(), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('branch_id', sa.String(length=36), nullable=True),
    sa.Column('interests', sa.JSON(), nullable=False),
    sa.Column('last_inbound_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
    sa.PrimaryKeyConstraint('sender_id')
    )
    op.create_index(op.f('ix_whatsapp_contacts_branch_id'), 'whatsapp_contacts', ['branch_id'], unique=False)
    op.create_index(op.f('ix_whatsapp_contacts_marketing'), 'whatsapp_contacts', ['marketing'], unique=False)
    op.create_table('whatsapp_followup_rules',
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('template_id', sa.String(length=80), nullable=False),
    sa.Column('template_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('delay_hours', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['template_id'], ['whatsapp_templates.id'], ),
    sa.PrimaryKeyConstraint('kind')
    )
    op.create_index(op.f('ix_whatsapp_followup_rules_template_id'), 'whatsapp_followup_rules', ['template_id'], unique=False)
    op.create_table('whatsapp_consent_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('sender_id', sa.String(length=32), nullable=False),
    sa.Column('source_message_id', sa.String(length=120), nullable=False),
    sa.Column('choices', sa.JSON(), nullable=False),
    sa.Column('disclosure_version', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['sender_id'], ['whatsapp_contacts.sender_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_message_id')
    )
    op.create_index(op.f('ix_whatsapp_consent_events_sender_id'), 'whatsapp_consent_events', ['sender_id'], unique=False)
    op.create_table('whatsapp_handoffs',
    sa.Column('sender_id', sa.String(length=32), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('assigned_to', sa.String(length=100), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['support_cases.id'], ),
    sa.ForeignKeyConstraint(['sender_id'], ['whatsapp_contacts.sender_id'], ),
    sa.PrimaryKeyConstraint('sender_id')
    )
    op.create_index(op.f('ix_whatsapp_handoffs_case_id'), 'whatsapp_handoffs', ['case_id'], unique=False)
    op.create_index(op.f('ix_whatsapp_handoffs_status'), 'whatsapp_handoffs', ['status'], unique=False)
    op.create_table('whatsapp_outbound',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('dedupe_key', sa.String(length=160), nullable=False),
    sa.Column('sender_id', sa.String(length=32), nullable=False),
    sa.Column('campaign_id', sa.String(length=36), nullable=True),
    sa.Column('appointment_id', sa.String(length=36), nullable=True),
    sa.Column('case_id', sa.String(length=36), nullable=True),
    sa.Column('template_id', sa.String(length=80), nullable=True),
    sa.Column('template_fingerprint', sa.String(length=64), nullable=True),
    sa.Column('parameters', sa.JSON(), nullable=False),
    sa.Column('asset_id', sa.String(length=36), nullable=True),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('claim_token', sa.String(length=64), nullable=True),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sending_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('meta_message_id', sa.String(length=120), nullable=True),
    sa.Column('last_error', sa.String(length=240), nullable=True),
    sa.Column('opted_out_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_actor', sa.String(length=100), nullable=True),
    sa.Column('engaged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('converted_appointment_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ),
    sa.ForeignKeyConstraint(['asset_id'], ['media_assets.id'], ),
    sa.ForeignKeyConstraint(['campaign_id'], ['whatsapp_campaigns.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['support_cases.id'], ),
    sa.ForeignKeyConstraint(['converted_appointment_id'], ['appointments.id'], ),
    sa.ForeignKeyConstraint(['sender_id'], ['whatsapp_contacts.sender_id'], ),
    sa.ForeignKeyConstraint(['template_id'], ['whatsapp_templates.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key'),
    sa.UniqueConstraint('meta_message_id')
    )
    op.create_index(op.f('ix_whatsapp_outbound_appointment_id'), 'whatsapp_outbound', ['appointment_id'], unique=False)
    op.create_index(op.f('ix_whatsapp_outbound_asset_id'), 'whatsapp_outbound', ['asset_id'], unique=False)
    op.create_index(op.f('ix_whatsapp_outbound_campaign_id'), 'whatsapp_outbound', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_whatsapp_outbound_case_id'), 'whatsapp_outbound', ['case_id'], unique=False)
    op.create_index('ix_whatsapp_outbound_claim', 'whatsapp_outbound', ['status', 'due_at'], unique=False)
    op.create_index(op.f('ix_whatsapp_outbound_converted_appointment_id'), 'whatsapp_outbound', ['converted_appointment_id'], unique=False)
    op.create_index('ix_whatsapp_outbound_frequency', 'whatsapp_outbound', ['sender_id', 'purpose', 'sending_at'], unique=False)
    op.create_index(op.f('ix_whatsapp_outbound_sender_id'), 'whatsapp_outbound', ['sender_id'], unique=False)
    op.create_index(op.f('ix_whatsapp_outbound_template_id'), 'whatsapp_outbound', ['template_id'], unique=False)
    op.add_column('appointments', sa.Column('consultation_fee', sa.Integer(), nullable=True))
    op.add_column('branches', sa.Column('address', sa.String(length=500), server_default='', nullable=False))
    op.add_column('branches', sa.Column('directions_url', sa.String(length=500), server_default='', nullable=False))
    op.add_column('branches', sa.Column('arrival_instructions', sa.String(length=500), server_default='', nullable=False))
    # Preserve previously recorded visit-reminder choices. Never infer marketing
    # consent, language or clinic preferences from appointment data.
    contacts = sa.table('whatsapp_contacts',
        sa.column('sender_id', sa.String), sa.column('service_messages', sa.Boolean),
        sa.column('marketing', sa.Boolean), sa.column('stopped_all', sa.Boolean),
        sa.column('language', sa.String), sa.column('interests', sa.JSON),
        sa.column('updated_at', sa.DateTime(timezone=True)))
    events = sa.table('whatsapp_consent_events',
        sa.column('id', sa.String), sa.column('sender_id', sa.String),
        sa.column('source_message_id', sa.String), sa.column('choices', sa.JSON),
        sa.column('disclosure_version', sa.String), sa.column('created_at', sa.DateTime(timezone=True)))
    connection = op.get_bind()
    legacy = connection.execute(sa.text("SELECT LTRIM(patient_phone, '+') AS sender_id, MAX(CASE WHEN consent_to_reminders THEN 1 ELSE 0 END) AS consent FROM appointments WHERE origin_channel = 'whatsapp' GROUP BY LTRIM(patient_phone, '+')")).mappings()
    stamp = datetime.now(timezone.utc)
    for row in legacy:
        sender = row['sender_id']
        if not sender.isascii() or not sender.isdecimal() or not 7 <= len(sender) <= 20:
            continue
        consent = bool(row['consent'])
        connection.execute(contacts.insert().values(sender_id=sender, service_messages=consent,
            marketing=False, stopped_all=False, language='en', interests=[], updated_at=stamp))
        connection.execute(events.insert().values(id=str(uuid.uuid4()), sender_id=sender,
            source_message_id=f'legacy-v6:{sender}', choices={'service_messages': consent},
            disclosure_version='legacy-appointment-consent', created_at=stamp))


def downgrade() -> None:
    op.drop_column('branches', 'arrival_instructions')
    op.drop_column('branches', 'directions_url')
    op.drop_column('branches', 'address')
    op.drop_column('appointments', 'consultation_fee')
    op.drop_index(op.f('ix_whatsapp_outbound_template_id'), table_name='whatsapp_outbound')
    op.drop_index(op.f('ix_whatsapp_outbound_sender_id'), table_name='whatsapp_outbound')
    op.drop_index('ix_whatsapp_outbound_frequency', table_name='whatsapp_outbound')
    op.drop_index(op.f('ix_whatsapp_outbound_converted_appointment_id'), table_name='whatsapp_outbound')
    op.drop_index('ix_whatsapp_outbound_claim', table_name='whatsapp_outbound')
    op.drop_index(op.f('ix_whatsapp_outbound_case_id'), table_name='whatsapp_outbound')
    op.drop_index(op.f('ix_whatsapp_outbound_campaign_id'), table_name='whatsapp_outbound')
    op.drop_index(op.f('ix_whatsapp_outbound_asset_id'), table_name='whatsapp_outbound')
    op.drop_index(op.f('ix_whatsapp_outbound_appointment_id'), table_name='whatsapp_outbound')
    op.drop_table('whatsapp_outbound')
    op.drop_index(op.f('ix_whatsapp_handoffs_status'), table_name='whatsapp_handoffs')
    op.drop_index(op.f('ix_whatsapp_handoffs_case_id'), table_name='whatsapp_handoffs')
    op.drop_table('whatsapp_handoffs')
    op.drop_index(op.f('ix_whatsapp_consent_events_sender_id'), table_name='whatsapp_consent_events')
    op.drop_table('whatsapp_consent_events')
    op.drop_index(op.f('ix_whatsapp_followup_rules_template_id'), table_name='whatsapp_followup_rules')
    op.drop_table('whatsapp_followup_rules')
    op.drop_index(op.f('ix_whatsapp_contacts_marketing'), table_name='whatsapp_contacts')
    op.drop_index(op.f('ix_whatsapp_contacts_branch_id'), table_name='whatsapp_contacts')
    op.drop_table('whatsapp_contacts')
    op.drop_index(op.f('ix_whatsapp_case_messages_case_id'), table_name='whatsapp_case_messages')
    op.drop_table('whatsapp_case_messages')
    op.drop_index(op.f('ix_whatsapp_campaigns_template_id'), table_name='whatsapp_campaigns')
    op.drop_index(op.f('ix_whatsapp_campaigns_status'), table_name='whatsapp_campaigns')
    op.drop_index(op.f('ix_whatsapp_campaigns_asset_id'), table_name='whatsapp_campaigns')
    op.drop_table('whatsapp_campaigns')
    op.drop_index(op.f('ix_whatsapp_templates_name'), table_name='whatsapp_templates')
    op.drop_table('whatsapp_templates')
    op.drop_table('whatsapp_delivery_receipts')
