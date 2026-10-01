"""named staff accounts and sessions

Revision ID: 6b67db09e83a
Revises: 0006_whatsapp_outreach
Create Date: 2026-10-01 13:44:53.087633
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '6b67db09e83a'
down_revision: Union[str, None] = '0006_whatsapp_outreach'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('staff_login_limits',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('staff_users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('display_name', sa.String(length=40), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_staff_users_username'), 'staff_users', ['username'], unique=True)
    op.create_table('staff_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('csrf_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['staff_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index(op.f('ix_staff_sessions_expires_at'), 'staff_sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_staff_sessions_user_id'), 'staff_sessions', ['user_id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_staff_sessions_user_id'), table_name='staff_sessions')
    op.drop_index(op.f('ix_staff_sessions_expires_at'), table_name='staff_sessions')
    op.drop_table('staff_sessions')
    op.drop_index(op.f('ix_staff_users_username'), table_name='staff_users')
    op.drop_table('staff_users')
    op.drop_table('staff_login_limits')
