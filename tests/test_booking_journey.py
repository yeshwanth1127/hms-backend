import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.config import settings
from app.db import Base, get_db
from app.models import (Appointment, AppointmentStatusHistory, BookingOperationAudit, Branch, Doctor, OutboxEvent,
                        ReminderJob, Reservation, ScheduleRule, StaffUser, WebBookingSession, WaitlistEntry)
from app.staff_auth import password_hash

ORIGIN={'Origin':'http://testserver'}
SERVICE={'X-Service-Key':'dev-whatsapp-service-key'}

@pytest.fixture
def journey(monkeypatch):
    pg=os.environ.get('HMS_BOOKING_DATABASE_URL')
    raw_engine=None
    schema='booking_test_'+uuid4().hex
    if pg:
        raw_engine=create_engine(pg)
        with raw_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine=raw_engine.execution_options(schema_translate_map={None:schema})
    else:
        engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False)
    def override():
        with sessions() as db:yield db
    app.dependency_overrides[get_db]=override
    monkeypatch.setattr(settings,'web_booking_enabled',True)
    monkeypatch.setattr(settings,'web_booking_origin','http://testserver')
    monkeypatch.setattr(settings,'whatsapp_booking_number','919700000000')
    day=datetime.now(timezone.utc).date()+timedelta(days=3)
    with sessions() as db:
        db.add_all([Branch(id='clinic',slug='clinic',name='Clinic',area='Area',timezone='Asia/Kolkata',address='Test street'),
                    Doctor(id='doctor',slug='doctor',name='Doctor',title='Doctor',bio='',experience_years=1,consultation_fee=800),
                    StaffUser(username='journey.admin',display_name='Journey Admin',role='admin',password_hash=password_hash('strong-test-password'))])
        db.flush()
        db.add(ScheduleRule(doctor_id='doctor',branch_id='clinic',consultation_type='in_person',schedule_date=day,
            weekday=day.weekday(),effective_from=day,effective_until=day,starts_at_local=__import__('datetime').time(9),ends_at_local=__import__('datetime').time(12),slot_minutes=30))
        db.commit()
    try:
        with TestClient(app) as client:
            yield client,sessions,day
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
        if raw_engine:
            with raw_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            raw_engine.dispose()


def verified(client,phone='919811111111'):
    started=client.post('/api/v1/web/booking/session',headers=ORIGIN,json={'phone':phone,'privacy_accepted':True})
    assert started.status_code==201,started.text
    code=parse_qs(urlparse(started.json()['verification_url']).query)['text'][0].split()[-1]
    assert client.post('/api/v1/integrations/whatsapp/web-booking/verify',headers=SERVICE,json={'sender_id':phone,'code':code}).status_code==200
    return {**ORIGIN,'X-Booking-CSRF':started.json()['csrf_token']}


def slots(client,day):
    response=client.get('/api/v1/availability',params={'doctor_id':'doctor','branch_id':'clinic','start_date':str(day),'end_date':str(day)})
    assert response.status_code==200,response.text
    return response.json()['slots']


def book(client,day,headers,consent=True):
    slot=slots(client,day)[0]
    hold=client.post('/api/v1/web/booking/holds',headers=headers,json={**slot,'idempotency_key':str(uuid4())})
    assert hold.status_code==201,hold.text
    body={'hold_id':hold.json()['id'],'patient_name':'Fictional Patient','expected_fee':800,'consent_to_reminders':consent,'acquisition_source':'google_business','idempotency_key':str(uuid4())}
    result=client.post('/api/v1/web/booking/appointments',headers=headers,json=body)
    assert result.status_code==201,result.text
    return result.json(),body


def admin(client):
    result=client.post('/api/v1/staff/login',json={'username':'journey.admin','password':'strong-test-password'})
    assert result.status_code==200,result.text
    return {'X-CSRF-Token':result.json()['csrf_token']}


def test_request_to_verified_booking_persisted_reminder_checkin_and_replay(journey,monkeypatch):
    client,sessions,day=journey
    h=verified(client)
    # Production website routes work only with verified cookie identity; legacy owner-key routes remain blocked.
    monkeypatch.setattr(settings,'app_env','production')
    monkeypatch.setattr(settings,'web_booking_origin','https://clinic.example')
    h['Origin']='https://clinic.example'
    appointment,body=book(client,day,h)
    assert appointment['is_demo'] is False and appointment['doctor_name']=='Doctor'
    replay=client.post('/api/v1/web/booking/appointments',headers=h,json=body)
    assert replay.status_code==201 and replay.json()['id']==appointment['id']
    with sessions() as db:
        item=db.get(Appointment,appointment['id'])
        assert item.acquisition_source=='google_business' and item.origin_channel=='web'
        assert item.reservation.status=='booked' and item.patient_phone=='+919811111111'
        assert db.scalar(select(func.count()).select_from(Appointment))==1
        assert db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.aggregate_id==item.id,OutboxEvent.event_type=='appointment.confirmed'))==1
        assert db.scalar(select(func.count()).select_from(ReminderJob).where(ReminderJob.appointment_id==item.id))==1
    assert client.post('/api/v1/appointments',json={'hold_id':body['hold_id'],'owner_key':'forged','patient_name':'Test','patient_phone':'919811111111','idempotency_key':'forged-operation'}).status_code==403
    client.base_url='https://testserver'
    ah=admin(client)
    updated=client.patch('/api/v1/admin/appointments/'+appointment['id']+'/status',headers=ah,json={'status':'checked_in','actor_id':'FORGED ACTOR','reason':'Arrived'})
    assert updated.status_code==200,updated.text
    with sessions() as db:
        assert db.get(Appointment,appointment['id']).status=='checked_in'
        history=db.scalars(select(AppointmentStatusHistory).where(AppointmentStatusHistory.appointment_id==appointment['id'])).all()
        assert len(history)==2 and history[-1].actor_id!='FORGED ACTOR'


def test_verification_sender_expiry_csrf_role_and_patient_isolation(journey):
    client,sessions,day=journey
    r=client.post('/api/v1/web/booking/session',headers={'Origin':'https://evil.example'},json={'phone':'919811111111','privacy_accepted':True})
    assert r.status_code==403
    r=client.post('/api/v1/web/booking/session',headers=ORIGIN,json={'phone':'919811111111','privacy_accepted':True})
    code=parse_qs(urlparse(r.json()['verification_url']).query)['text'][0].split()[-1]
    slot=slots(client,day)[0]
    body={**slot,'idempotency_key':str(uuid4())}
    assert client.post('/api/v1/web/booking/holds',headers={**ORIGIN,'X-Booking-CSRF':r.json()['csrf_token']},json=body).status_code==401
    assert client.post('/api/v1/integrations/whatsapp/web-booking/verify',headers=SERVICE,json={'sender_id':'919822222222','code':code}).status_code==404
    assert client.post('/api/v1/integrations/whatsapp/web-booking/verify',json={'sender_id':'919811111111','code':code}).status_code in {401,422}
    assert client.post('/api/v1/integrations/whatsapp/web-booking/verify',headers=SERVICE,json={'sender_id':'919811111111','code':code}).status_code==200
    assert client.post('/api/v1/web/booking/holds',headers=ORIGIN,json=body).status_code==403
    h={**ORIGIN,'X-Booking-CSRF':r.json()['csrf_token']}
    appointment,_=book(client,day,h)
    second=verified(client,'919822222222')
    assert client.get('/api/v1/web/booking/appointments').json()==[]
    assert client.post('/api/v1/web/booking/appointments/'+appointment['id']+'/cancel',headers=second,json={'reason':'Changed plans'}).status_code==404
    with sessions() as db:
        for session in db.scalars(select(WebBookingSession)):
            session.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert client.get('/api/v1/web/booking/session').status_code==401


def test_patient_reschedule_cancel_and_free_capacity(journey):
    client,sessions,day=journey
    h=verified(client)
    appointment,_=book(client,day,h)
    old=appointment['reservation']['starts_at']
    replacement=slots(client,day)[0]
    hold=client.post('/api/v1/web/booking/holds',headers=h,json={**replacement,'idempotency_key':str(uuid4())}).json()
    body={'new_hold_id':hold['id'],'idempotency_key':str(uuid4())}
    url='/api/v1/web/booking/appointments/'+appointment['id']+'/reschedule'
    moved=client.post(url,headers=h,json=body)
    assert moved.status_code==200,moved.text
    assert moved.json()['reservation']['id']==hold['id']
    assert client.post(url,headers=h,json=body).status_code==200
    assert any(datetime.fromisoformat(s['starts_at'])==datetime.fromisoformat(old) for s in slots(client,day))
    cancel=client.post('/api/v1/web/booking/appointments/'+appointment['id']+'/cancel',headers=h,json={'reason':'Changed plans'})
    assert cancel.status_code==200 and cancel.json()['status']=='cancelled'
    with sessions() as db:
        assert db.get(Reservation,hold['id']).status=='released'
        assert db.scalar(select(ReminderJob)).status=='cancelled'
        assert db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_type=='appointment.rescheduled'))==1


def test_block_preview_acknowledgement_invalidation_and_staff_move(journey):
    client,sessions,day=journey
    h=verified(client)
    appointment,_=book(client,day,h)
    ah=admin(client)
    reservation=appointment['reservation']
    block={'doctor_id':'doctor','branch_id':'clinic','starts_at':reservation['starts_at'],'ends_at':reservation['ends_at'],'reason':'Doctor unavailable'}
    preview=client.post('/api/v1/admin/schedule-exceptions/preview',headers=ah,json=block)
    assert preview.status_code==200,preview.text
    assert [a['id'] for a in preview.json()['affected_appointments']]==[appointment['id']]
    assert client.post('/api/v1/admin/schedule-exceptions',headers=ah,json=block).status_code==409
    created=client.post('/api/v1/admin/schedule-exceptions',headers=ah,json={**block,'acknowledged_appointments':[appointment['id']]})
    assert created.status_code==201 and created.json()['notification_state']=='staff_review_required'
    assert datetime.fromisoformat(created.json()['starts_at']).utcoffset() == timedelta(0)
    replacement=slots(client,day)[0]
    request={'starts_at':replacement['starts_at'],'ends_at':replacement['ends_at'],'reason':'Agreed new time','idempotency_key':str(uuid4())}
    url='/api/v1/admin/appointments/'+appointment['id']+'/reschedule'
    moved=client.post(url,headers=ah,json=request)
    assert moved.status_code==200,moved.text
    assert client.post(url,headers=ah,json=request).status_code==200
    assert datetime.fromisoformat(moved.json()['starts_at'])==datetime.fromisoformat(replacement['starts_at'])
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(BookingOperationAudit))==2
        assert db.get(Appointment,appointment['id']).consultation_fee==800
    assert not any(datetime.fromisoformat(s['starts_at'])==datetime.fromisoformat(reservation['starts_at']) for s in slots(client,day))
    assert client.delete('/api/v1/admin/schedule-exceptions/'+created.json()['id'],headers=ah).status_code==204
    assert any(datetime.fromisoformat(s['starts_at'])==datetime.fromisoformat(reservation['starts_at']) for s in slots(client,day))


def test_waitlist_consent_offer_allocation_acceptance_replay_and_withdraw(journey):
    client,sessions,day=journey
    h=verified(client)
    request={'doctor_id':'doctor','branch_id':'clinic','consultation_type':'in_person','patient_name':'Fictional Patient','start_date':str(day),'end_date':str(day),'consent_to_waitlist':False}
    assert client.post('/api/v1/web/booking/waitlist',headers=h,json=request).status_code==422
    request['consent_to_waitlist']=True
    entry=client.post('/api/v1/web/booking/waitlist',headers=h,json=request).json()
    assert client.post('/api/v1/web/booking/waitlist',headers=h,json=request).json()['id']==entry['id']
    ah=admin(client)
    slot=slots(client,day)[0]
    offer=client.post('/api/v1/admin/waitlist/'+entry['id']+'/offer',headers=ah,json={'starts_at':slot['starts_at'],'ends_at':slot['ends_at'],'idempotency_key':str(uuid4())})
    assert offer.status_code==200,offer.text
    assert not any(s['starts_at']==slot['starts_at'] for s in slots(client,day))
    accept={'expected_fee':800,'consent_to_reminders':True,'idempotency_key':str(uuid4())}
    url='/api/v1/web/booking/waitlist/'+entry['id']+'/accept'
    response=client.post(url,headers=h,json=accept)
    assert response.status_code==200,response.text
    assert client.post(url,headers=h,json=accept).json()['id']==response.json()['id']
    with sessions() as db:
        assert db.get(WaitlistEntry,entry['id']).status=='booked'
        assert db.scalar(select(func.count()).select_from(Appointment))==1
        assert db.scalar(select(func.count()).select_from(ReminderJob))==1
    assert client.delete('/api/v1/web/booking/waitlist/'+entry['id'],headers=h).status_code==409


def test_held_slot_blocked_price_changed_and_idempotency_cannot_leak(journey):
    client,sessions,day=journey
    h=verified(client)
    slot=slots(client,day)[0]
    request={**slot,'idempotency_key':'protected-hold-key'}
    hold=client.post('/api/v1/web/booking/holds',headers=h,json=request).json()
    # Shared legacy service also rejects another owner reusing a key.
    legacy={**slot,'owner_key':'first-owner','idempotency_key':'shared-key-ownership'}
    second_slot=slots(client,day)[1]
    legacy.update(second_slot)
    assert client.post('/api/v1/slot-holds',json=legacy).status_code==201
    assert client.post('/api/v1/slot-holds',json={**legacy,'owner_key':'other-owner'}).status_code==409
    ah=admin(client)
    block={**{k:slot[k] for k in ['doctor_id','branch_id','starts_at','ends_at']},'reason':'Unavailable'}
    assert client.post('/api/v1/admin/schedule-exceptions',headers=ah,json=block).status_code==201
    confirm={'hold_id':hold['id'],'patient_name':'Fictional Patient','expected_fee':800,'idempotency_key':'blocked-booking-key'}
    assert client.post('/api/v1/web/booking/appointments',headers=h,json=confirm).status_code==409
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Appointment))==0
        assert db.get(Reservation,hold['id']).status=='released'
    third=slots(client,day)[0]
    replacement=client.post('/api/v1/web/booking/holds',headers=h,json={**third,'idempotency_key':'price-change-hold'}).json()
    with sessions() as db:
        db.get(Doctor,'doctor').consultation_fee=900
        db.commit()
    confirm.update(hold_id=replacement['id'],idempotency_key='price-change-booking')
    assert client.post('/api/v1/web/booking/appointments',headers=h,json=confirm).json()['error']['code']=='PRICE_CHANGED'
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(OutboxEvent))==0


def test_expired_challenge_rate_limit_and_no_verification_consent(journey):
    client,sessions,_=journey
    assert client.post('/api/v1/web/booking/session',headers=ORIGIN,json={'phone':'919811111111','privacy_accepted':False}).status_code==422
    r=client.post('/api/v1/web/booking/session',headers=ORIGIN,json={'phone':'919811111111','privacy_accepted':True})
    code=parse_qs(urlparse(r.json()['verification_url']).query)['text'][0].split()[-1]
    with sessions() as db:
        from app.models import WhatsAppContact
        assert db.scalar(select(func.count()).select_from(WhatsAppContact))==0
        item=db.scalar(select(WebBookingSession))
        assert code not in item.code_hash
        item.expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert client.post('/api/v1/integrations/whatsapp/web-booking/verify',headers=SERVICE,json={'sender_id':'919811111111','code':code}).status_code==404
    for _ in range(4):
        assert client.post('/api/v1/web/booking/session',headers=ORIGIN,json={'phone':'919811111111','privacy_accepted':True}).status_code==201
    assert client.post('/api/v1/web/booking/session',headers=ORIGIN,json={'phone':'919811111111','privacy_accepted':True}).status_code==429


def test_waitlist_offer_expiry_withdraw_stop_and_claimed_reminder_preserved(journey):
    client,sessions,day=journey
    h=verified(client)
    a,_=book(client,day,h)
    ah=admin(client)
    with sessions() as db:
        reminder=db.scalar(select(ReminderJob))
        reminder.status='uncertain'
        db.commit()
    slot=slots(client,day)[0]
    result=client.post('/api/v1/admin/appointments/'+a['id']+'/reschedule',headers=ah,json={'starts_at':slot['starts_at'],'ends_at':slot['ends_at'],'reason':'Agreed time','idempotency_key':'uncertain-move-key'})
    assert result.status_code==200,result.text
    with sessions() as db:
        assert db.scalar(select(ReminderJob)).status=='uncertain'
    joined=client.post('/api/v1/web/booking/waitlist',headers=h,json={'doctor_id':'doctor','branch_id':'clinic','consultation_type':'in_person','patient_name':'Fictional Patient','start_date':str(day),'end_date':str(day),'consent_to_waitlist':True}).json()
    slot=slots(client,day)[0]
    offer={'starts_at':slot['starts_at'],'ends_at':slot['ends_at'],'idempotency_key':'waitlist-expiry-key'}
    url='/api/v1/admin/waitlist/'+joined['id']+'/offer'
    assert client.post(url,headers=ah,json=offer).status_code==200
    with sessions() as db:
        entry=db.get(WaitlistEntry,joined['id'])
        db.get(Reservation,entry.hold_id).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert client.post('/api/v1/web/booking/waitlist/'+joined['id']+'/accept',headers=h,json={'expected_fee':800,'idempotency_key':'expired-accept-key'}).status_code==409
    assert client.get('/api/v1/web/booking/waitlist').json()[0]['status']=='waiting'
    from app.models import WhatsAppContact
    with sessions() as db:
        contact=db.get(WhatsAppContact,'919811111111')
        contact.stopped_all=True
        db.commit()
    offer['idempotency_key']='stopped-offer-key'
    assert client.post(url,headers=ah,json=offer).status_code==409
    assert client.delete('/api/v1/web/booking/waitlist/'+joined['id'],headers=h).status_code==204
    assert client.get('/api/v1/web/booking/waitlist').json()[0]['status']=='withdrawn'


@pytest.mark.skipif(not os.environ.get('HMS_BOOKING_DATABASE_URL'),reason='Independent PostgreSQL connections are required')
def test_postgres_overlapping_holds_and_identical_retry_are_serialized(journey):
    client,sessions,day=journey
    from datetime import time
    from app.services import create_hold,DomainError
    from app.schemas import HoldCreate
    with sessions() as db:
        db.add(ScheduleRule(doctor_id='doctor',branch_id='clinic',consultation_type='in_person',schedule_date=day,
            weekday=day.weekday(),effective_from=day,effective_until=day,starts_at_local=time(9),ends_at_local=time(12),slot_minutes=20))
        db.commit()
    available=slots(client,day)
    first=next(s for s in available if datetime.fromisoformat(s['starts_at']).minute==30 and (datetime.fromisoformat(s['ends_at'])-datetime.fromisoformat(s['starts_at'])).total_seconds()==1800)
    second=next(s for s in available if datetime.fromisoformat(s['starts_at']).minute==50 and (datetime.fromisoformat(s['ends_at'])-datetime.fromisoformat(s['starts_at'])).total_seconds()==1200)
    barrier=Barrier(2)
    def reserve(slot,owner,operation):
        with sessions() as db:
            barrier.wait(timeout=5)
            try:return create_hold(db,HoldCreate(**slot,owner_key=owner,idempotency_key=operation)).id
            except DomainError as error:return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(reserve,first,'owner-one','overlap-operation-one'),pool.submit(reserve,second,'owner-two','overlap-operation-two')]
        results=[f.result(timeout=10) for f in futures]
    assert results.count('SLOT_NO_LONGER_AVAILABLE')==1
    with sessions() as db:
        for hold in db.scalars(select(Reservation)):hold.status='released'
        db.commit()
    barrier=Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(reserve,first,'same-owner','same-operation-key') for _ in range(2)]
        results=[f.result(timeout=10) for f in futures]
    assert results[0]==results[1] and results[0]!='SLOT_NO_LONGER_AVAILABLE'
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Reservation).where(Reservation.idempotency_key=='same-operation-key'))==1
