"""Independent optional growth modules, disabled until the clinic owner opts in."""
from alembic import op
import sqlalchemy as sa
revision = "0009_client_modules"
down_revision = "0008_google_growth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("client_modules", sa.Column("key", sa.String(40), primary_key=True),
                    sa.Column("enabled", sa.Boolean(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("module_audit", sa.Column("id", sa.String(36), primary_key=True),
                    sa.Column("module_key", sa.String(40), nullable=False),
                    sa.Column("actor", sa.String(36), sa.ForeignKey("staff_users.id"), nullable=False),
                    sa.Column("enabled", sa.Boolean(), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_module_audit_module_key", "module_audit", ["module_key"])


def downgrade():
    op.drop_table("module_audit")
    op.drop_table("client_modules")
