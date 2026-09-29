"""Add a concrete date anchor to every schedule rule."""
from datetime import timedelta

from alembic import op
import sqlalchemy as sa


revision = "0003_schedule_dates"
down_revision = "0002_voice_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schedule_rules", sa.Column("schedule_date", sa.Date(), nullable=True))

    rules = sa.table(
        "schedule_rules",
        sa.column("id", sa.String(36)),
        sa.column("weekday", sa.Integer()),
        sa.column("effective_from", sa.Date()),
        sa.column("schedule_date", sa.Date()),
    )
    connection = op.get_bind()
    for rule in connection.execute(
        sa.select(rules.c.id, rules.c.weekday, rules.c.effective_from)
    ).mappings():
        offset = (rule["weekday"] - rule["effective_from"].weekday()) % 7
        concrete_date = rule["effective_from"] + timedelta(days=offset)
        connection.execute(
            rules.update().where(rules.c.id == rule["id"]).values(schedule_date=concrete_date)
        )

    with op.batch_alter_table("schedule_rules") as batch_op:
        batch_op.alter_column("schedule_date", existing_type=sa.Date(), nullable=False)
        batch_op.create_index("ix_schedule_rules_schedule_date", ["schedule_date"])


def downgrade() -> None:
    with op.batch_alter_table("schedule_rules") as batch_op:
        batch_op.drop_index("ix_schedule_rules_schedule_date")
        batch_op.drop_column("schedule_date")
