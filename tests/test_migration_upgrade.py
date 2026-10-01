"""Exercise upgrades from both independently published migration branches."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


@pytest.mark.parametrize("initial", ["base", "0003_schedule_dates", "0003_whatsapp_integration"])
def test_upgrade_to_merged_whatsapp_head(tmp_path, initial):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    for revision in (initial, "head"):
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision],
                                cwd=root, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [("0010_voice_module",)]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"whatsapp_inbound", "media_assets", "appointments", "schedule_rules", "whatsapp_contacts", "whatsapp_outbound", "staff_users", "staff_sessions", "client_modules", "growth_audit", "voice_recording_access", "voice_event_receipts", "voice_admission_gate", "voice_rate_limits"} <= tables
        assert "schedule_date" in {row[1] for row in db.execute("PRAGMA table_info(schedule_rules)")}


def test_upgrade_preserves_existing_clinic_and_legacy_reminder_consent(tmp_path):
    database = tmp_path / "existing.db"
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    for revision in ("0005_merge_whatsapp_schedule", "head"):
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        if revision != "0005_merge_whatsapp_schedule":
            break
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO branches (id,slug,name,area,timezone,is_virtual,is_active) VALUES ('branch','legacy','Existing clinic','Area','Asia/Kolkata',0,1)")
            db.execute("INSERT INTO doctors (id,slug,name,title,bio,experience_years,consultation_fee,accepts_virtual,is_active) VALUES ('doctor','legacy','Dr Legacy','Doctor','',5,800,0,1)")
            db.execute("INSERT INTO reservations (id,doctor_id,branch_id,consultation_type,starts_at,ends_at,status,owner_key,created_at) VALUES ('reservation','doctor','branch','in_person','2026-10-04 04:00:00','2026-10-04 04:30:00','booked','owner','2026-10-01 00:00:00')")
            db.execute("INSERT INTO appointments (id,confirmation_code,reservation_id,patient_name,patient_phone,status,origin_channel,consent_to_reminders,idempotency_key,created_at,updated_at) VALUES ('appointment','AVO-LEGACY','reservation','Patient','+919700000001','confirmed','whatsapp',1,'legacy-book','2026-10-01 00:00:00','2026-10-01 00:00:00')")
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT name,address,directions_url FROM branches").fetchone() == ("Existing clinic", "", "")
        assert db.execute("SELECT sender_id,service_messages,marketing FROM whatsapp_contacts").fetchone() == ("919700000001", 1, 0)
        assert db.execute("SELECT disclosure_version FROM whatsapp_consent_events").fetchone()[0] == "legacy-appointment-consent"
        assert db.execute("SELECT confirmation_code,consultation_fee FROM appointments").fetchone() == ("AVO-LEGACY", None)
