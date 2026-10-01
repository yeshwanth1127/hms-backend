"""Disposable, explicitly isolated local clinic demo. Never a production seed."""
from pathlib import Path
from threading import RLock
from sqlalchemy.engine import make_url
from ..config import settings
from ..services import DomainError

LOCK = RLock()
MARKER = 'avocado-local-demo-v1'


def guard(db=None):
    root = Path(settings.demo_workspace).resolve()
    url = make_url(settings.database_url)
    if (not settings.demo_mode or settings.app_env != 'demo'
            or url.drivername != 'sqlite'
            or not url.database or Path(url.database).resolve() != root / 'clinic.db'
            or Path(settings.media_dir).resolve() != root / 'uploads'
            or not (root / '.demo-workspace').is_file()
            or (root / '.demo-workspace').read_text().strip() != MARKER):
        raise DomainError('DEMO_UNAVAILABLE', 'Demo controls require an isolated local demo workspace.', 403)
    if db is not None and db.get_bind().url != url:
        raise DomainError('DEMO_DATABASE_MISMATCH', 'This database is not the demo workspace.', 403)
    return root


def block_transport():
    if settings.demo_mode:
        guard()
        raise DomainError('DEMO_TRANSPORT_DISABLED', 'Live calls and external messages are disabled in this demo.', 503)
