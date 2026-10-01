"""The reset boundary, persistence, roles and transport blocks matter beyond UI smoke."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func, event
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.demo import MARKER, guard
from app.demo.fixtures import seed, DEMO_PASSWORD
from app.models import Appointment, StaffUser, VoiceSession, MediaAsset
from app.voice import provider
from app.services import DomainError


@pytest.fixture
def demo(tmp_path, monkeypatch):
    (tmp_path / '.demo-workspace').write_text(MARKER)
    url = 'sqlite:///' + str(tmp_path / 'clinic.db')
    for name, value in dict(demo_mode=True, app_env='demo', demo_workspace=str(tmp_path),
                           database_url=url, media_dir=str(tmp_path / 'uploads'), staff_origin='http://testserver').items():
        monkeypatch.setattr(settings, name, value)
    engine = create_engine(url, connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def fk(c, _):
        c.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed(db)
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    client = TestClient(app)
    yield client, factory, tmp_path
    app.dependency_overrides.clear()
    engine.dispose()


def login(client, username='demo.admin'):
    response = client.post('/api/v1/staff/login', json={'username': username, 'password': DEMO_PASSWORD})
    assert response.status_code == 200
    return {'X-CSRF-Token': response.json()['csrf_token']}


def test_real_modules_clear_and_reload(demo):
    c, factory, root = demo
    headers = login(c)
    redirect = c.get('/admin', follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers['location'] == '/staff/appointments'
    modules = c.get('/api/v1/staff/modules').json()['modules']
    assert len(modules) == 4 and all(m['enabled'] and m['accessible'] for m in modules)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Appointment)) == 84
        assert all(a.is_demo for a in db.scalars(select(Appointment)))
        call = db.scalar(select(VoiceSession).where(VoiceSession.runtime_session_id == 'demo-call-001'))
    voice = c.get('/api/v1/staff/voice').json()
    assert voice['total'] == 18 and voice['summary']['bookings'] > 0
    response = c.post(f'/api/v1/staff/voice/sessions/{call.id}/recording', headers=headers)
    assert response.status_code == 200 and response.content.startswith(b'RIFF')
    assert c.get('/api/v1/admin/growth/summary?include_demo=true').json()['summary']['appointments_created'] > 0
    assert c.get('/api/v1/admin/growth/summary').json()['summary']['appointments_created'] == 0
    activity = c.get('/api/v1/admin/growth/website-activity?traffic=demo').json()
    assert activity['synthetic'] and sum(r['events'] for r in activity['rows']) > 0
    assert c.post('/api/v1/staff/demo/clear').status_code == 403
    result = c.post('/api/v1/staff/demo/clear', headers=headers)
    assert result.status_code == 200, result.text
    assert all(value == 0 for value in result.json()['counts'].values())
    assert not list((root / 'uploads').iterdir())
    assert c.get('/api/v1/staff/session').status_code == 200
    assert c.get('/api/v1/staff/voice').json()['total'] == 0
    assert sum(r['events'] for r in c.get('/api/v1/admin/growth/website-activity?traffic=demo').json()['rows']) == 0
    assert all(m['enabled'] for m in c.get('/api/v1/staff/modules').json()['modules'])
    assert c.post('/api/v1/staff/demo/reload', headers=headers).status_code == 200
    assert c.post('/api/v1/staff/demo/reload', headers=headers).status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Appointment)) == 84
        assert db.scalar(select(func.count()).select_from(MediaAsset)) == 19
    assert c.put('/api/v1/staff/modules/voice', headers=headers, json={'enabled': False}).status_code == 200
    assert c.post('/api/v1/staff/demo/reload', headers=headers).status_code == 200
    voice_module = next(m for m in c.get('/api/v1/staff/modules').json()['modules'] if m['key'] == 'voice')
    assert not voice_module['enabled']


def test_guard_roles_and_no_provider_network(demo, monkeypatch):
    c, factory, root = demo
    headers = login(c, 'demo.reception')
    assert c.post('/api/v1/staff/demo/clear', headers=headers).status_code == 403
    def no_http(*a, **k):
        pytest.fail('Demo made a provider HTTP request')
    monkeypatch.setattr(provider.httpx, 'Client', no_http)
    with pytest.raises(DomainError, match='Live calls'):
        provider.mint()
    assert c.post('/api/v1/web/voice/sessions', json={'recording_consent': True, 'notice_version': 'recording-v1'}).status_code == 503
    assert c.post('/api/v1/integrations/whatsapp/outreach/claim', headers={'X-Service-Key': settings.whatsapp_service_api_key}).status_code == 503
    assert c.get('/api/v1/integrations/voice/branches', headers={'X-Service-Key': settings.voice_service_api_key}).status_code == 503
    monkeypatch.setattr(settings, 'app_env', 'production')
    with factory() as db, pytest.raises(DomainError):
        guard(db)
    monkeypatch.setattr(settings, 'app_env', 'demo')
    (root / '.demo-workspace').unlink()
    with factory() as db, pytest.raises(DomainError):
        guard(db)
