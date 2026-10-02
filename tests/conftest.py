import os
import tempfile
from pathlib import Path

_database_dir = tempfile.TemporaryDirectory(prefix="hms-tests-")
DB_PATH = Path(_database_dir.name) / "test.db"
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
# Tests use these fixture credentials. A copied deployment .env must not alter
# service authentication before app.config constructs its cached settings.
os.environ["ADMIN_API_KEY"] = "dev-admin-key"
os.environ["VOICE_SERVICE_API_KEY"] = "dev-voice-service-key"
os.environ["WHATSAPP_SERVICE_API_KEY"] = "dev-whatsapp-service-key"
os.environ["WHATSAPP_OWNER_SECRET"] = "dev-whatsapp-owner-secret"
