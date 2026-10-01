"""Exercise credentials, revocation, CSRF, real roles and optional-module boundaries."""
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.db import Base, get_db
from app.config import settings
from app.models import StaffUser, StaffSession, ClientModule, ModuleAudit, WhatsAppInbound, utcnow
from app.staff_auth import COOKIE, digest, password_hash

PASSWORD = "a-private-test-password"

@pytest.fixture
def staff(monkeypatch):
    engine = create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine,expire_on_commit=False)
    def override():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(settings,'admin_api_key','test-machine-admin-key')
    monkeypatch.setattr(settings,'whatsapp_service_api_key','test-machine-service-key')
    monkeypatch.setattr(settings,'staff_origin','')
    with factory() as db:
        for name,role in [('clinic.admin','admin'),('reception','staff'),('growth','growth_manager')]:
            db.add(StaffUser(username=name,display_name=name,role=role,password_hash=password_hash(PASSWORD)))
        db.commit()
    try:
        with TestClient(app) as client: yield client,factory
    finally:
        app.dependency_overrides.clear();engine.dispose()


def sign_in(client,name='clinic.admin'):
    r=client.post('/api/v1/staff/login',json={'username':name,'password':PASSWORD})
    assert r.status_code==200,r.text
    return {'X-CSRF-Token':r.json()['csrf_token']}


def test_login_hash_cookie_csrf_origin_logout(staff):
    c,f=staff
    assert c.get('/api/v1/admin/appointments').status_code==401
    failed=c.post('/api/v1/staff/login',json={'username':'missing','password':'wrong'})
    assert failed.status_code==401
    assert c.post('/api/v1/staff/login',headers={'Origin':'https://evil.example'},json={'username':'clinic.admin','password':PASSWORD}).status_code==403
    headers=sign_in(c)
    token=c.cookies.get(COOKIE)
    with f() as db:
        user=db.scalar(select(StaffUser).where(StaffUser.username=='clinic.admin'))
        assert user.password_hash.startswith('$argon2id$') and PASSWORD not in user.password_hash
        session=db.get(StaffSession,digest(token))
        assert session and session.token_hash!=token
    assert c.get('/api/v1/admin/appointments').status_code==200
    body={'enabled':False}
    assert c.put('/api/v1/staff/modules/whatsapp',json=body).status_code==403
    assert c.put('/api/v1/staff/modules/whatsapp',headers={**headers,'Origin':'https://evil.example'},json=body).status_code==403
    assert c.put('/api/v1/staff/modules/whatsapp',headers=headers,json=body).status_code==200
    refreshed=c.get('/api/v1/staff/session').json()
    assert refreshed['csrf_token']==headers['X-CSRF-Token'] # stable across tabs/reloads
    assert c.post('/api/v1/staff/logout',headers=headers).status_code==204
    assert c.get('/api/v1/admin/appointments').status_code==401


def test_idle_absolute_expiry_disabled_user_and_production_cookie(staff,monkeypatch):
    c,f=staff
    sign_in(c)
    with f() as db:
        session=db.get(StaffSession,digest(c.cookies[COOKIE]));session.last_seen_at=utcnow()-timedelta(minutes=31);db.commit()
    assert c.get('/api/v1/staff/session').status_code==401
    sign_in(c)
    with f() as db:
        session=db.get(StaffSession,digest(c.cookies[COOKIE]));session.expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert c.get('/api/v1/admin/doctors').status_code==401
    sign_in(c)
    with f() as db:
        user=db.scalar(select(StaffUser).where(StaffUser.username=='clinic.admin'));user.is_active=False;db.commit()
    assert c.get('/api/v1/admin/doctors').status_code==401
    assert c.post('/api/v1/staff/login',json={'username':'clinic.admin','password':PASSWORD}).status_code==401
    monkeypatch.setattr(settings,'app_env','production')
    response=c.post('/api/v1/staff/login',json={'username':'reception','password':PASSWORD})
    assert 'Secure' in response.headers['set-cookie'] and 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']


def test_named_roles_accounts_and_password_revokes_all_sessions(staff):
    c,f=staff
    headers=sign_in(c,'reception')
    assert c.get('/api/v1/staff/users').status_code==403
    assert c.put('/api/v1/staff/modules/whatsapp',headers=headers,json={'enabled':False}).status_code==403
    assert c.get('/api/v1/admin/appointments').status_code==200
    sign_in(c,'growth')
    assert c.get('/api/v1/admin/appointments').status_code==403
    assert c.get('/api/v1/admin/whatsapp/templates').status_code==403
    headers=sign_in(c)
    body={'username':'new.staff','name':'New Staff','password':'another-private-password','role':'staff'}
    created=c.post('/api/v1/staff/users',headers=headers,json=body)
    assert created.status_code==201 and 'password' not in created.text
    assert c.post('/api/v1/staff/users',headers=headers,json=body).status_code==409
    assert c.post('/api/v1/staff/users',headers=headers,json={**body,'username':'other','role':'superuser'}).status_code==422
    assert c.post('/api/v1/staff/password',headers=headers,json={'current_password':'wrong','new_password':'changed-private-password'}).status_code==401
    assert c.post('/api/v1/staff/password',headers=headers,json={'current_password':PASSWORD,'new_password':'changed-private-password'}).status_code==204
    with f() as db:
        user=db.scalar(select(StaffUser).where(StaffUser.username=='clinic.admin'))
        assert not db.scalars(select(StaffSession).where(StaffSession.user_id==user.id)).all()
    assert c.get('/api/v1/admin/doctors').status_code==401


def test_persisted_rate_limit(staff):
    c,_=staff
    for _ in range(10):assert c.post('/api/v1/staff/login',json={'username':'missing','password':'incorrect'}).status_code==401
    assert c.post('/api/v1/staff/login',json={'username':'missing','password':'incorrect'}).status_code==429
    assert c.post('/api/v1/staff/login',json={'username':'clinic.admin','password':PASSWORD}).status_code==200


def test_module_disabled_blocks_api_and_workers_but_preserves_intake(staff):
    c,f=staff
    headers=sign_in(c)
    assert c.put('/api/v1/staff/modules/whatsapp',headers=headers,json={'enabled':False}).status_code==200
    assert c.get('/api/v1/admin/whatsapp/templates').status_code==403
    assert c.get('/api/v1/admin/whatsapp-assets',headers={'X-Admin-Key':'test-machine-admin-key'}).status_code==403
    service={'X-Service-Key':'test-machine-service-key'}
    p='/api/v1/integrations/whatsapp'
    assert c.get(p+'/catalogue',headers=service).status_code==403
    inbound={'message_id':'wamid.module-pause','sender_id':'919000000001','payload':{'id':'wamid.module-pause','from':'919000000001','type':'text','text':'hi'}}
    assert c.post(p+'/inbound',headers=service,json=inbound).status_code==202
    assert c.post(p+'/inbound/claim',headers=service).json() is None
    assert c.post(p+'/outreach/claim',headers=service).json() is None
    assert c.get(p+'/reminders/due',headers=service).json()==[]
    assert c.post(p+'/delivery-status',headers=service,json={'meta_message_id':'wamid.closed-receipt','status':'delivered','timestamp':1}).status_code==200
    assert c.get('/api/v1/admin/appointments').status_code==200
    with f() as db:
        assert db.get(WhatsAppInbound,'wamid.module-pause').status=='pending'
        audit=db.scalar(select(ModuleAudit));assert audit.actor==c.get('/api/v1/staff/session').json()['user']['id']
    assert c.put('/api/v1/staff/modules/whatsapp',headers=headers,json={'enabled':True}).status_code==200
    assert c.post(p+'/inbound/claim',headers=service).json()['message_id']=='wamid.module-pause'


def test_actor_is_session_identity_and_password_validation_does_not_echo(staff):
    c,f=staff
    service={'X-Service-Key':'test-machine-service-key'}
    sender='919000000009'
    message_id='wamid.handoff.actor'
    assert c.post('/api/v1/integrations/whatsapp/inbound',headers=service,json={'message_id':message_id,'sender_id':sender,'payload':{'id':message_id,'from':sender,'type':'text','text':'Local test help'}}).status_code==202
    assert c.post('/api/v1/integrations/whatsapp/reception',headers=service,json={'sender_id':sender,'source_message_id':'wamid.handoff.actor','text':'Local test help'}).status_code==200
    h=sign_in(c)
    assert c.patch('/api/v1/admin/whatsapp/reception/'+sender,headers=h,json={'status':'active','assigned_to':'Impersonated'}).status_code==200
    reply=c.post('/api/v1/admin/whatsapp/reception/'+sender+'/reply',headers=h,json={'actor':'Impersonated','text':'Local test reply','idempotency_key':'staff-test-actor'})
    assert reply.status_code==202
    row=c.get('/api/v1/admin/whatsapp/reception').json()[0]
    assert row['assigned_to']=='clinic.admin (@clinic.admin)'
    assert row['messages'][-1]['actor']=='clinic.admin (@clinic.admin)'
    invalid=c.post('/api/v1/staff/users',headers=h,json={'username':'invalid.user','name':'   ','password':'private-short','role':'staff'})
    assert invalid.status_code==422 and 'private-short' not in invalid.text
