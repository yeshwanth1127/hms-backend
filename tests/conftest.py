import os
from pathlib import Path

DB_PATH = Path("/tmp/avocado-health-tests.db")
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

