"""Repeatable fictional clinic records through the real database models."""
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from ..models import (Appointment, AppointmentStatusHistory, Branch, Doctor, Reservation,
    VoiceSession, WhatsAppContact, WhatsAppConsentEvent, WhatsAppConversation,
    WhatsAppHandoff, WhatsAppCaseMessage, SupportCase, WhatsAppTemplate,
    WhatsAppCampaign, WhatsAppOutbound, WhatsAppDeliveryReceipt, WhatsAppFollowupRule,
    ReminderJob, ScheduleException, GoogleBookingLink, GrowthAudit, OutboxEvent,
    ClientModule, StaffUser, utcnow)
from ..seed import seed_all
from ..staff_auth import password_hash
from ..client_modules import MODULES
from . import guard

DEMO_PASSWORD = 'DemoClinic2026!'
NAMES = ['Anika Rao', 'Rohan Shah', 'Meera Sen', 'Arjun Das', 'Kavya Kumar',
         'Neel Patel', 'Tara Iyer', 'Dev Menon', 'Riya Kapoor', 'Aarav Nair',
         'Isha Verma', 'Kabir Joshi']


def seed(db):
    guard(db)
    seed_all(db)
    now = utcnow()
    today = now.astimezone(ZoneInfo('Asia/Kolkata')).date()
    branches = db.scalars(select(Branch).order_by(Branch.slug)).all()
    branch = next(b for b in branches if b.slug == 'indiranagar')
    doctors = db.scalars(select(Doctor).order_by(Doctor.slug)).unique().all()
    for username, name, role in [('demo.admin', 'Clinic Administrator', 'admin'),
                                  ('demo.reception', 'Reception Team', 'staff'),
                                  ('demo.growth', 'Growth Manager', 'growth_manager')]:
        if not db.scalar(select(StaffUser).where(StaffUser.username == username)):
            db.add(StaffUser(username=username, display_name=name, role=role,
                             password_hash=password_hash(DEMO_PASSWORD)))
    for key in MODULES:
        item = db.get(ClientModule, key)
        if not item:
            db.add(ClientModule(key=key, enabled=True))
    db.flush()
    admin = db.scalar(select(StaffUser).where(StaffUser.username == 'demo.admin'))
    appointments = []
    physical = [b for b in branches if not b.is_virtual]
    # A month's history and a busy current/future clinic day, without overlapping slots.
    for i in range(84):
        day_offset = -(i // 2 + 1) if i < 56 else (i - 56) // 10
        visit_day = today + timedelta(days=day_offset)
        starts = datetime.combine(visit_day, time(9 + (i % 8), 30 * (i % 2)), ZoneInfo('Asia/Kolkata')).astimezone(timezone.utc)
        doctor = doctors[i % len(doctors)]
        status = (['completed', 'completed', 'no_show', 'cancelled'][i % 4]
                  if starts < now else ['confirmed', 'confirmed', 'confirmed', 'cancelled'][i % 4])
        if i in (56, 57, 58):
            status = 'checked_in' if i == 56 else 'confirmed'
        channel = 'voice' if i in (59, 65, 74) else ['web', 'whatsapp', 'staff'][i % 3]
        visit_branch = branch if i >= 56 else physical[i % len(physical)]
        res = Reservation(doctor_id=doctor.id, branch_id=visit_branch.id, consultation_type='in_person',
                          starts_at=starts, ends_at=starts+timedelta(minutes=30),
                          status='released' if status == 'cancelled' else 'booked', owner_key=f'demo:{i}')
        db.add(res)
        db.flush()
        item = Appointment(confirmation_code=f'DEMO{i+1:05}', reservation_id=res.id,
            patient_name=NAMES[i % len(NAMES)], patient_phone=f'+1555010{i+100:04}',
            patient_email=f'patient{i+1}@example.invalid', reason='Synthetic consultation request',
            consultation_fee=doctor.consultation_fee, status=status, origin_channel=channel,
            acquisition_source=['google_business', 'organic_search', 'referral', 'direct'][i % 4],
            is_demo=True, consent_to_reminders=True, idempotency_key=f'demo-appointment-{i}',
            created_at=starts-timedelta(days=3), updated_at=now)
        db.add(item)
        db.flush()
        appointments.append(item)
        db.add(AppointmentStatusHistory(appointment_id=item.id, from_status=None, to_status='confirmed',
            actor_type='demo', actor_id='fixture', created_at=starts-timedelta(days=3)))
        if status != 'confirmed':
            db.add(AppointmentStatusHistory(appointment_id=item.id, from_status='confirmed', to_status=status,
                actor_type='staff', actor_id=admin.id, reason='Synthetic visit outcome', created_at=min(starts, now)))
        if i >= 56 and status == 'confirmed':
            db.add(ReminderJob(appointment_id=item.id, sender_id=item.patient_phone.lstrip("+"),
                due_at=starts-timedelta(hours=24), status='pending'))
    for i in range(18):
        status = ['completed', 'completed', 'abandoned', 'error', 'completed', 'completed'][i % 6]
        booked = appointments[{0:59, 6:65, 12:74}[i]] if i in (0,6,12) else None
        start = booked.created_at if booked else now-timedelta(hours=i*5, minutes=5)
        db.add(VoiceSession(runtime_session_id=f'demo-call-{i+1:03}',
            provider_reference=f'demo-reference-{i+1:03}', interaction_id=f'demo-interaction-{i+1:03}',
            agent_version=7, status=status, channel='web_voice' if i % 2 else 'phone',
            started_at=start, ended_at=start+timedelta(seconds=90+i*7), turn_count=6+i%9,
            tool_call_count=2+i%4, last_intent=['book_appointment', 'check_availability', 'clinic_hours'][i % 3],
            appointment_id=booked.id if booked else None,
            recording_consent_at=start if i != 4 else None, recording_notice_version='recording-v1',
            recording_available_until=now-timedelta(days=1) if i == 5 else now+timedelta(days=29)))
    for i, name in enumerate(NAMES):
        sender = f'1555010{i+200:04}'
        db.add(WhatsAppContact(sender_id=sender, service_messages=True, marketing=i < 9,
            stopped_all=i == 11, language='en', branch_id=branch.id, interests=['general-medicine'],
            last_inbound_at=now-timedelta(minutes=i*15)))
        db.flush()
        db.add(WhatsAppConsentEvent(sender_id=sender, source_message_id=f'demo-consent-{i}',
            choices={'service_messages': True, 'marketing': i < 9}, disclosure_version='demo-v1'))
        db.add(WhatsAppConversation(sender_id=sender, state={'step': 'menu', 'patient_name': name},
            last_message_id=f'demo-inbound-{i}', last_reply={'text': 'How can we help today?'}))
        case = SupportCase(owner_key=f'demo:{sender}', sender_id=sender, kind='reception',
            description=['Help rescheduling my appointment', 'Question about arrival instructions',
                         'Which reports should I bring?'][i % 3], status='open' if i < 7 else 'resolved',
            idempotency_key=f'demo-case-{i}', created_at=now-timedelta(hours=i))
        db.add(case)
        db.flush()
        db.add(WhatsAppHandoff(sender_id=sender, case_id=case.id,
            status='waiting' if i < 4 else 'assigned' if i < 7 else 'closed',
            assigned_to=None if i < 4 else 'Reception Team'))
        for j, (direction, text) in enumerate([('inbound', f'Hi, I am {name}. {case.description}.'),
                ('outbound', 'Reception can help. Please keep your booking reference ready.'),
                ('inbound', 'Thank you, I have my reference with me.')]):
            db.add(WhatsAppCaseMessage(case_id=case.id, source_message_id=f'demo-case-msg-{i}-{j}',
                direction=direction, text=text, actor='demo.bot' if direction == 'outbound' else None,
                created_at=now-timedelta(minutes=i*15+3-j)))
    components = [{'type': 'BODY', 'text': 'Hello {{1}}, your clinic update: {{2}}.'},
        {'type': 'BUTTONS', 'buttons': [{'type': 'QUICK_REPLY', 'text': 'Book appointment'},
                                       {'type': 'QUICK_REPLY', 'text': 'Contact reception'},
                                       {'type': 'QUICK_REPLY', 'text': 'Stop updates'}]}]
    for i, title in enumerate(['clinic_update', 'visit_reminder', 'visit_feedback']):
        db.add(WhatsAppTemplate(id=f'demo-template-{i}', name=title, language='en', category='MARKETING' if i == 0 else 'UTILITY',
            status='APPROVED', components=components, fingerprint=f'demo-fingerprint-{i}', synced_at=now))
    db.flush()
    for i, (title, status) in enumerate([('October preventive care', 'draft'), ('Clinic hours update', 'completed'),
                                         ('Weekend appointments', 'scheduled')]):
        campaign = WhatsAppCampaign(title=title, template_id='demo-template-0', template_fingerprint='demo-fingerprint-0',
            parameters=['Patient', 'Our October appointments are open'], audience={'branch_id': branch.id},
            status=status, scheduled_at=now+timedelta(days=2) if i != 1 else now-timedelta(days=2),
            rate_paise=90, budget_paise=9000, approved_count=8 if i != 0 else 0,
            approved_by='demo.admin' if i != 0 else None)
        db.add(campaign)
        db.flush()
        if i == 1:
            for j in range(8):
                db.add(WhatsAppOutbound(dedupe_key=f'demo-outbound-{j}', sender_id=f'1555010{j+200:04}',
                    campaign_id=campaign.id, template_id='demo-template-0', template_fingerprint='demo-fingerprint-0',
                    parameters=['Patient', 'Clinic hours update'], purpose='campaign', due_at=now-timedelta(days=2),
                    status=['read', 'delivered', 'accepted', 'failed'][j % 4], meta_message_id=f'demo-meta-{j}',
                    sending_at=now-timedelta(days=2), engaged_at=now-timedelta(days=1) if j < 3 else None,
                    converted_appointment_id=appointments[j].id if j < 2 else None,
                    last_error='Synthetic delivery failure' if j % 4 == 3 else None))
                db.add(WhatsAppDeliveryReceipt(meta_message_id=f'demo-meta-{j}',
                    status=['read', 'delivered', 'accepted', 'failed'][j % 4], timestamp=int(now.timestamp())))
    db.add(WhatsAppFollowupRule(kind='feedback', template_id='demo-template-2', template_fingerprint='demo-fingerprint-2', enabled=True))
    db.add(WhatsAppFollowupRule(kind='no_show', template_id='demo-template-1', template_fingerprint='demo-fingerprint-1', enabled=False))
    db.add(ScheduleException(doctor_id=doctors[0].id, branch_id=branch.id,
        starts_at=now+timedelta(days=3), ends_at=now+timedelta(days=3, hours=2), reason='Teaching session'))
    for b in branches:
        b.address = f'Synthetic {b.area} clinic address'
        b.arrival_instructions = 'Please arrive 10 minutes early with your booking reference.'
        url = f'https://clinic.example/schedule-appointment?branch={b.slug}&source=google_business'
        db.add(GoogleBookingLink(branch_id=b.id, booking_url=url))
        db.add(GrowthAudit(branch_id=b.id, actor=admin.id, action='booking_link_updated',
            change={'before': None, 'after': url}, created_at=now-timedelta(days=3)))
    db.add(Reservation(doctor_id=doctors[0].id, branch_id=branch.id, consultation_type='in_person',
        starts_at=now+timedelta(days=5), ends_at=now+timedelta(days=5, minutes=30), status='active',
        owner_key='demo:active-hold', expires_at=now+timedelta(minutes=7)))
    for i in range(6):
        db.add(OutboxEvent(event_type=['appointment.confirmed', 'appointment.completed', 'appointment.cancelled'][i % 3],
            aggregate_id=appointments[i].id, payload={'appointment_id': appointments[i].id},
            created_at=now-timedelta(minutes=i*5), processed_at=now if i > 2 else None))
    for i in range(30):
        day = today-timedelta(days=i)
        for event, count in [('page_viewed', 120+i*4), ('booking_intent_clicked', 26+i),
                ('booking_flow_started', 18+i), ('booking_preview_completed', 9+i//2),
                ('booking_validation_failed', 2), ('contact_intent_clicked', 12), ('search_used', 34)]:
            db.add(OutboxEvent(event_type='demo.website_activity', aggregate_id='demo',
                payload={'event': event, 'events': count, 'visitors': max(1, count*3//4)},
                created_at=datetime.combine(day, time(12), ZoneInfo('Asia/Kolkata')).astimezone(timezone.utc), processed_at=now))
    db.commit()
