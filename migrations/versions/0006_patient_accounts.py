"""Add stable patient codes and booking-created access credentials."""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "0006_patient_accounts"
down_revision = "0005_identity_virtual_opd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("patient_code", sa.String(24), nullable=True))
    op.add_column("patients", sa.Column("access_code_hash", sa.Text(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id FROM patients")).fetchall()
    for row in rows:
        code = f"EXO-P-{uuid.uuid4().hex[:8].upper()}"
        connection.execute(sa.text("UPDATE patients SET patient_code = :code WHERE id = :id"),
                           {"code": code, "id": row[0]})
    with op.batch_alter_table("patients") as batch:
        batch.alter_column("patient_code", existing_type=sa.String(24), nullable=False)
        batch.create_unique_constraint("uq_patients_patient_code", ["patient_code"])
    op.create_index("ix_patients_patient_code", "patients", ["patient_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_patients_patient_code", table_name="patients")
    with op.batch_alter_table("patients") as batch:
        batch.drop_constraint("uq_patients_patient_code", type_="unique")
        batch.drop_column("access_code_hash")
        batch.drop_column("patient_code")
