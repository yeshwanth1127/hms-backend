"""First-party identity, tenant ownership, and Virtual OPD lifecycle."""
from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = "0005_identity_virtual_opd"
down_revision = "0004_merge_schedule_whatsapp"
branch_labels = None
depends_on = None
DEFAULT_HOSPITAL_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table("hospitals",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("virtual_opd_enabled", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug"))
    op.create_index("ix_hospitals_slug", "hospitals", ["slug"])
    hospitals = sa.table("hospitals", sa.column("id", sa.String), sa.column("slug", sa.String),
                         sa.column("name", sa.String), sa.column("timezone", sa.String),
                         sa.column("virtual_opd_enabled", sa.Boolean), sa.column("created_at", sa.DateTime(timezone=True)))
    op.bulk_insert(hospitals, [{"id": DEFAULT_HOSPITAL_ID, "slug": "exora-demo", "name": "Exora Hospital",
                               "timezone": "Asia/Kolkata", "virtual_opd_enabled": False,
                               "created_at": datetime.now(timezone.utc)}])
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("email", sa.String(254), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False), sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email"))
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table("hospital_memberships",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("hospital_id", sa.String(36), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(32), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("hospital_id", "user_id", "role", name="uq_membership_role"))
    op.create_index("ix_hospital_memberships_hospital_id", "hospital_memberships", ["hospital_id"])
    op.create_index("ix_hospital_memberships_user_id", "hospital_memberships", ["user_id"])
    op.create_index("ix_hospital_memberships_role", "hospital_memberships", ["role"])
    op.create_table("user_sessions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("membership_id", sa.String(36), sa.ForeignKey("hospital_memberships.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash"))
    for name in ("token_hash", "user_id", "membership_id", "expires_at"):
        op.create_index(f"ix_user_sessions_{name}", "user_sessions", [name])
    op.create_table("patients",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("hospital_id", sa.String(36), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id")), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("phone", sa.String(32)), sa.Column("email", sa.String(254)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("hospital_id", "user_id", name="uq_patient_user_hospital"))
    op.create_index("ix_patients_hospital_id", "patients", ["hospital_id"])
    op.create_index("ix_patients_user_id", "patients", ["user_id"])
    for table in ("branches", "departments", "schedule_rules", "reservations"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("hospital_id", sa.String(36)))
            batch.create_foreign_key(f"fk_{table}_hospital_id", "hospitals", ["hospital_id"], ["id"])
        op.create_index(f"ix_{table}_hospital_id", table, ["hospital_id"])
        op.execute(sa.text(f"UPDATE {table} SET hospital_id = :hospital_id").bindparams(hospital_id=DEFAULT_HOSPITAL_ID))
    with op.batch_alter_table("doctors") as batch:
        batch.add_column(sa.Column("hospital_id", sa.String(36)))
        batch.add_column(sa.Column("user_id", sa.String(36)))
        batch.create_foreign_key("fk_doctors_hospital_id", "hospitals", ["hospital_id"], ["id"])
        batch.create_foreign_key("fk_doctors_user_id", "users", ["user_id"], ["id"])
        batch.create_unique_constraint("uq_doctors_user_id", ["user_id"])
    op.create_index("ix_doctors_hospital_id", "doctors", ["hospital_id"])
    op.execute(sa.text("UPDATE doctors SET hospital_id = :hospital_id").bindparams(hospital_id=DEFAULT_HOSPITAL_ID))
    with op.batch_alter_table("appointments") as batch:
        batch.add_column(sa.Column("hospital_id", sa.String(36)))
        batch.add_column(sa.Column("patient_id", sa.String(36)))
        batch.create_foreign_key("fk_appointments_hospital_id", "hospitals", ["hospital_id"], ["id"])
        batch.create_foreign_key("fk_appointments_patient_id", "patients", ["patient_id"], ["id"])
    op.create_index("ix_appointments_hospital_id", "appointments", ["hospital_id"])
    op.create_index("ix_appointments_patient_id", "appointments", ["patient_id"])
    op.execute(sa.text("UPDATE appointments SET hospital_id = :hospital_id").bindparams(hospital_id=DEFAULT_HOSPITAL_ID))
    op.create_table("teleconsultations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("hospital_id", sa.String(36), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("appointment_id", sa.String(36), sa.ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("room_key", sa.String(80), nullable=False, unique=True), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("doctor_started_at", sa.DateTime(timezone=True)), sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)), sa.Column("last_activity_at", sa.DateTime(timezone=True)),
        sa.Column("ended_by_actor_type", sa.String(32)), sa.Column("ended_by_actor_id", sa.String(36)),
        sa.Column("end_reason", sa.String(240)), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    for name in ("hospital_id", "appointment_id", "status"):
        op.create_index(f"ix_teleconsultations_{name}", "teleconsultations", [name])
    op.create_table("teleconsultation_consents",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("hospital_id", sa.String(36), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("teleconsultation_id", sa.String(36), sa.ForeignKey("teleconsultations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False), sa.Column("document_version", sa.String(40), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False), sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("captured_by_actor_type", sa.String(32), nullable=False), sa.Column("captured_by_actor_id", sa.String(36), nullable=False))
    for name in ("hospital_id", "teleconsultation_id", "patient_id"):
        op.create_index(f"ix_teleconsultation_consents_{name}", "teleconsultation_consents", [name])
    op.create_table("teleconsultation_events",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("hospital_id", sa.String(36), sa.ForeignKey("hospitals.id"), nullable=False),
        sa.Column("teleconsultation_id", sa.String(36), sa.ForeignKey("teleconsultations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False), sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False), sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(80)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    for name in ("hospital_id", "teleconsultation_id", "event_type"):
        op.create_index(f"ix_teleconsultation_events_{name}", "teleconsultation_events", [name])


def downgrade() -> None:
    for table in ("teleconsultation_events", "teleconsultation_consents", "teleconsultations"):
        op.drop_table(table)
    op.drop_index("ix_appointments_patient_id", table_name="appointments")
    op.drop_index("ix_appointments_hospital_id", table_name="appointments")
    with op.batch_alter_table("appointments") as batch:
        batch.drop_column("patient_id"); batch.drop_column("hospital_id")
    op.drop_index("ix_doctors_hospital_id", table_name="doctors")
    with op.batch_alter_table("doctors") as batch:
        batch.drop_constraint("uq_doctors_user_id", type_="unique")
        batch.drop_column("user_id"); batch.drop_column("hospital_id")
    for table in ("reservations", "schedule_rules", "departments", "branches"):
        op.drop_index(f"ix_{table}_hospital_id", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_column("hospital_id")
    for table in ("patients", "user_sessions", "hospital_memberships", "users", "hospitals"):
        op.drop_table(table)
