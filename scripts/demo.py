#!/usr/bin/env python3
"""Start one loopback-only demo; repeated starts never refill cleared records."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORKSPACE = ROOT / '.local' / 'clinic-demo'
WORKSPACE.mkdir(parents=True, exist_ok=True)
marker = WORKSPACE / '.demo-workspace'
first = not marker.exists()
if first:
    if any(WORKSPACE.iterdir()):
        raise SystemExit('Refusing to initialize a non-empty unmarked demo directory.')
    marker.write_text('avocado-local-demo-v1\n')
os.environ.update(APP_ENV='demo', DEMO_MODE='true', DEMO_WORKSPACE=str(WORKSPACE),
    DATABASE_URL='sqlite:///' + str(WORKSPACE / 'clinic.db'), MEDIA_DIR=str(WORKSPACE / 'uploads'),
    STAFF_ORIGIN='http://localhost:5173', ALLOWED_ORIGINS='http://localhost:5173',
    BOOKING_ALLOWED_ORIGINS='https://clinic.example', WHATSAPP_OUTREACH_ENABLED='true',
    SARVAM_API_KEY='', POSTHOG_READ_KEY='', POSTHOG_GROWTH_ENABLED='false',
    SARVAM_ORG_ID='demo-org', SARVAM_WORKSPACE_ID='demo-workspace', SARVAM_APP_ID='demo-app',
    SARVAM_APP_VERSION='7', SARVAM_RECORDING_URL_FIELD='', VOICE_RECORDING_HOSTS='',
    VOICE_WEBSITE_BOOKING_URL='/schedule-appointment')
from app.db import Base, SessionLocal, engine
from app.main import app
from app.demo import guard
from app.demo.fixtures import seed
from sqlalchemy import event

@event.listens_for(engine, 'connect')
def foreign_keys(connection, _):
    connection.execute('PRAGMA foreign_keys=ON')

guard()
Base.metadata.create_all(engine)
initialized = WORKSPACE / '.initialized'
if not initialized.exists():
    with SessionLocal() as db:
        from app.demo.router import clear
        clear(db)
        seed(db)
    initialized.write_text('Seeded once. Reload only on explicit request.\n')
if __name__ == '__main__':
    import uvicorn
    print('Demo: http://localhost:5173/admin · demo.admin / DemoClinic2026!')
    uvicorn.run(app, host='127.0.0.1', port=8014)
