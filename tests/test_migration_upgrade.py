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
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [("0005_merge_whatsapp_schedule",)]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"whatsapp_inbound", "media_assets", "appointments", "schedule_rules"} <= tables
        assert "schedule_date" in {row[1] for row in db.execute("PRAGMA table_info(schedule_rules)")}
