import os
import tempfile
from pathlib import Path

_database_dir = tempfile.TemporaryDirectory(prefix="hms-tests-")
DB_PATH = Path(_database_dir.name) / "test.db"
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
