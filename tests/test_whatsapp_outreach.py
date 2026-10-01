"""Exercise consent and dispatch gates with a fresh database per test."""
from datetime import date, datetime, timedelta, timezone
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db import Base, get_db
from app.config import settings
from app.seed import seed_catalogue
from app.models import (Appointment, WhatsAppContact, WhatsAppOutbound, WhatsAppTemplate,
                        WhatsAppConsentEvent, WhatsAppDeliveryReceipt, Branch)
import app.whatsapp_outreach as outreach
import app.admin as admin

S = {"X-Service-Key": "dev-whatsapp-service-key"}
A = {"X-Admin-Key": "dev-admin-key"}
P = "/api/v1/integrations/whatsapp"
D = "/api/v1/admin/whatsapp"
PHONE = "919700000001"
TESTER = "919700000002"
NOW = datetime(2026, 10, 1, 5, tzinfo=timezone.utc)  # 10:30 India, outside quiet hours


@pytest.fixture
def setup(monkeypatch):
    pg = os.environ.get("HMS_OUTREACH_DATABASE_URL")
    schema = "wa_test_" + uuid4().hex
    if pg:
        raw_engine = create_engine(pg)
        with raw_engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = raw_engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed_catalogue(db)
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    monkeypatch.setattr(settings, "whatsapp_outreach_enabled", True)
    monkeypatch.setattr(settings, "whatsapp_test_recipients", TESTER)
    monkeypatch.setattr(outreach, "utcnow", lambda: NOW)
    monkeypatch.setattr(admin, "utcnow", lambda: NOW)
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    if pg:
        with raw_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        raw_engine.dispose()
    else:
        engine.dispose()


def put_pref(c, sender=PHONE, **fields):
    return c.put(f"{P}/preferences/{sender}", headers=S, json={"source_message_id": str(uuid4()), **fields})


def sync(c, category="MARKETING", text="Hello {{1}}. Visit our clinic.", header=None):
    template = {"id": "1001", "name": "clinic_offer", "language": "en", "category": category,
                "status": "APPROVED", "components": [{"type": "BODY", "text": text},
                {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Book a visit"}, {"type": "QUICK_REPLY", "text": "Stop offers"}]}]}
    if header:
        template["components"].insert(0, {"type": "HEADER", "format": header})
    r = c.post(P + "/templates/sync", headers=S, json={"templates": [template]})
    assert r.status_code == 200, r.text
    return template


def campaign(c, **overrides):
    data = {"title": "Clinic news", "template_id": "1001", "parameters": ["friend"],
            "scheduled_at": NOW.isoformat(), "rate_paise": 100, "budget_paise": 10000, **overrides}
    r = c.post(D + "/campaigns", headers=A, json=data)
    assert r.status_code == 201, r.text
    return r.json()


def claim(c):
    r = c.post(P + "/outreach/claim", headers=S)
    assert r.status_code == 200, r.text
    return r.json()


def sending(c, job):
    return c.post(f"{P}/outreach/{job['id']}/sending", headers=S, json={"claim_token": job["claim_token"]})


def accepted(c, job, mid="wamid.outreach-test"):
    r = c.post(f"{P}/outreach/{job['id']}/sent", headers=S,
               json={"claim_token": job["claim_token"], "meta_message_id": mid})
    assert r.status_code == 200, r.text
    return r


def approve(c, item):
    r = c.post(f"{D}/campaigns/{item['id']}/test", headers=A, json={"sender_id": TESTER, "actor": "Reception"})
    assert r.status_code == 202, r.text
    job = claim(c)
    assert job["purpose"] == "test"
    assert sending(c, job).json()["send"]
    accepted(c, job, "wamid.test-" + item["id"])
    preview = c.get(f"{D}/campaigns/{item['id']}/preview", headers=A).json()
    return c.post(f"{D}/campaigns/{item['id']}/approve", headers=A,
                  json={"actor": "Reception", "test_received": True, "expected_count": preview["recipients"], "audience_hash": preview["audience_hash"]})


def test_preferences_require_auth_record_consent_and_do_not_replay_old_optin(setup):
    c, factory = setup
    assert c.get(P + "/preferences/" + PHONE).status_code == 422
    assert c.get(D + "/campaigns", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert c.get(P + "/preferences/" + PHONE, headers=S).json()["marketing"] is False
    data = {"source_message_id": "wamid.consent-event", "service_messages": True, "marketing": True, "stopped_all": False}
    assert c.put(P + "/preferences/" + PHONE, headers=S, json=data).status_code == 200
    assert put_pref(c, stopped_all=True).json()["service_messages"] is False
    replay = c.put(P + "/preferences/" + PHONE, headers=S, json=data)
    assert replay.json()["stopped_all"] is True
    assert replay.json()["marketing"] is False
    assert c.put(P + "/preferences/" + TESTER, headers=S, json=data).status_code == 409
    with factory() as db:
        assert len(db.scalars(select(WhatsAppConsentEvent)).all()) == 2
    assert put_pref(c, marketing=True, stopped_all=False).json()["marketing"]
    assert not put_pref(c, marketing=False).json()["marketing"]
    assert put_pref(c, branch_id="").json()["branch_id"] is None
    assert put_pref(c, interests=["made-up-specialty"]).status_code == 422


def test_campaign_needs_fresh_approved_template_test_audience_and_budget(setup):
    c, factory = setup
    put_pref(c, marketing=True)
    template = sync(c)
    item = campaign(c)
    path = f"{D}/campaigns/{item['id']}"
    assert c.post(path + "/test", headers=A, json={"sender_id": PHONE, "actor": "Staff"}).status_code == 422
    preview = c.get(path + "/preview", headers=A).json()
    body = {"actor": "Staff", "test_received": True, "expected_count": 1, "audience_hash": preview["audience_hash"]}
    assert c.post(path + "/approve", headers=A, json=body).status_code == 409
    assert approve(c, item).status_code == 200
    job = claim(c)
    assert job["sender_id"] == PHONE
    # Withdraw consent after claim. Authorization must refuse even that claimed job.
    assert put_pref(c, marketing=False).status_code == 200
    assert sending(c, job).status_code == 409  # claim was cancelled by preference update
    assert claim(c) is None
    put_pref(c, marketing=True)
    changed = campaign(c)
    template["components"][0]["text"] = "Changed {{1}}"
    assert c.post(P + "/templates/sync", headers=S, json={"templates": [template]}).status_code == 200
    assert c.get(f"{D}/campaigns/{changed['id']}/preview", headers=A).status_code == 409
    tiny = campaign(c, budget_paise=1)
    assert not c.get(f"{D}/campaigns/{tiny['id']}/preview", headers=A).json()["within_budget"]
    with factory() as db:
        t = db.get(WhatsAppTemplate, "1001"); t.synced_at = NOW - timedelta(hours=3); db.commit()
    assert c.get(f"{D}/campaigns/{tiny['id']}/preview", headers=A).status_code == 409


def test_audience_snapshot_detects_changed_preferences_and_filters_language_interest(setup):
    c, _ = setup
    put_pref(c, marketing=True, language="en", interests=["cardiology"])
    put_pref(c, sender="919700000003", marketing=True, language="kn")
    put_pref(c, sender="919700000004", marketing=True, interests=["dermatology"])
    sync(c)
    item = campaign(c, audience={"interest": "cardiology"})
    assert c.get(f"{D}/campaigns/{item['id']}/preview", headers=A).json()["recipients"] == 1
    assert approve(c, item).status_code == 200
    # Editing a opted-in person's interests also changes the audience hash.
    item2 = campaign(c)
    preview = c.get(f"{D}/campaigns/{item2['id']}/preview", headers=A).json()
    c.post(f"{D}/campaigns/{item2['id']}/test", headers=A, json={"sender_id": TESTER, "actor": "Staff"})
    while (job := claim(c)) and job["purpose"] != "test":
        sending(c, job); accepted(c, job, "wamid.skip-" + job["id"])
    sending(c, job); accepted(c, job, "wamid.new-test")
    put_pref(c, marketing=False)
    assert c.post(f"{D}/campaigns/{item2['id']}/approve", headers=A, json={"actor": "Staff", "test_received": True, "expected_count": preview["recipients"], "audience_hash": preview["audience_hash"]}).status_code == 409


def test_quiet_hours_frequency_and_ambiguous_sends_are_not_retried(setup, monkeypatch):
    c, factory = setup
    put_pref(c, marketing=True); sync(c)
    item = campaign(c); assert approve(c, item).status_code == 200
    monkeypatch.setattr(outreach, "utcnow", lambda: NOW + timedelta(hours=10))
    sync(c)
    job = claim(c)
    assert sending(c, job).json()["reason"] == "quiet_hours"
    monkeypatch.setattr(outreach, "utcnow", lambda: NOW + timedelta(days=1))
    # Fresh sync is mandatory after the overnight delay.
    sync(c)
    job = claim(c); assert sending(c, job).json()["send"]
    r = c.post(f"{P}/outreach/{job['id']}/failed", headers=S, json={"claim_token": job["claim_token"], "error": "network timeout"})
    assert r.json()["status"] == "uncertain"
    assert claim(c) is None
    second = campaign(c); assert approve(c, second).status_code == 200
    next_job = claim(c)
    assert sending(c, next_job).json()["reason"] == "frequency_limit"
    with factory() as db:
        assert db.get(WhatsAppOutbound, job["id"]).status == "uncertain"


def test_delivery_callbacks_are_monotonic_even_before_send_completion(setup):
    c, factory = setup
    put_pref(c, marketing=True); sync(c)
    item = campaign(c); assert approve(c, item).status_code == 200
    job = claim(c); sending(c, job)
    for status, timestamp in [("read", 100), ("sent", 101), ("failed", 102), ("delivered", 99)]:
        assert c.post(P + "/delivery-status", headers=S, json={"meta_message_id": "wamid.early-receipt", "status": status, "timestamp": timestamp}).status_code == 200
    assert accepted(c, job, "wamid.early-receipt").json()["status"] == "read"
    assert c.post(f"{P}/outreach/{job['id']}/engage", headers=S, json={"sender_id": TESTER}).status_code == 404
    assert c.post(f"{P}/outreach/{job['id']}/engage", headers=S, json={"sender_id": PHONE, "action": "stop"}).status_code == 200
    with factory() as db:
        assert db.get(WhatsAppDeliveryReceipt, "wamid.early-receipt").status == "read"
        assert db.get(WhatsAppOutbound, job["id"]).opted_out_at is not None
    assert c.get(D + "/campaigns", headers=A).json()[0]["unsubscribes_from_buttons"] == 1


def test_reception_pauses_bot_and_staff_reply_requires_open_window(setup):
    c, factory = setup
    put_pref(c)
    r = c.post(P + "/reception", headers=S, json={"sender_id": PHONE, "source_message_id": "wamid.handoff-1", "text": "Need help"})
    assert r.status_code == 200
    assert c.get(P + "/preferences/" + PHONE, headers=S).json()["handoff"]["status"] == "waiting"
    reply = {"actor": "Reception", "text": "How can I help?", "idempotency_key": "staff.hello-1"}
    assert c.post(D + f"/reception/{PHONE}/reply", headers=A, json=reply).status_code == 409
    with factory() as db:
        db.get(WhatsAppContact, PHONE).last_inbound_at = NOW; db.commit()
    assert c.post(D + f"/reception/{PHONE}/reply", headers=A, json=reply).status_code == 202
    assert c.post(D + f"/reception/{PHONE}/reply", headers=A, json=reply).status_code == 202
    job = claim(c)
    assert job["purpose"] == "staff"
    c.post(P + f"/reception/{PHONE}/resume", headers=S)
    assert sending(c, job).json()["send"] is False
    assert c.get(P + "/preferences/" + PHONE, headers=S).json()["handoff"] is None


def test_disabled_outreach_only_claims_configured_tests_and_rejects_wrong_claims(setup, monkeypatch):
    c, _ = setup
    put_pref(c, marketing=True); sync(c)
    item = campaign(c); assert approve(c, item).status_code == 200
    monkeypatch.setattr(settings, "whatsapp_outreach_enabled", False)
    assert claim(c) is None
    second = campaign(c)
    c.post(f"{D}/campaigns/{second['id']}/test", headers=A, json={"sender_id": TESTER, "actor": "Staff"})
    job = claim(c)
    assert job["purpose"] == "test"
    assert c.post(f"{P}/outreach/{job['id']}/sending", headers=S, json={"claim_token": "0" * 64}).status_code == 409
    assert sending(c, job).json()["send"]


def test_media_required_and_template_layouts_fail_closed(setup):
    c, _ = setup
    sync(c, header="IMAGE")
    r = c.post(D + "/campaigns", headers=A, json={"title": "Missing header", "template_id": "1001", "parameters": ["hello"], "scheduled_at": NOW.isoformat(), "rate_paise": 100, "budget_paise": 10000})
    assert r.status_code == 422
    template = sync(c)
    template["components"][1]["buttons"] = ["invalid"]
    assert c.post(P + "/templates/sync", headers=S, json={"templates": [template]}).status_code == 200
    assert c.get(D + "/templates", headers=A).json()[0]["spec"] is None
    assert c.get("/whatsapp-operations.js").status_code == 200


def book(c, suffix, consent=True, expected_fee=None):
    catalogue = c.get(P + "/catalogue", headers=S).json()
    branch = next(b for b in catalogue["branches"] if b["slug"] == "indiranagar")
    doctor = c.get(P + "/doctors?department=cardiology&branch=indiranagar", headers=S).json()[0]
    day = date.today() + timedelta(days=10)
    while day.weekday() == 6:
        day += timedelta(days=1)
    slots = c.get(P + "/availability", headers=S, params={"doctor_id": doctor["id"], "branch_id": branch["id"], "start_date": day.isoformat(), "end_date": day.isoformat()}).json()["slots"]
    hold = c.post(P + "/slot-holds", headers=S, json={**slots[0], "sender_id": PHONE, "idempotency_key": "hold-" + suffix})
    assert hold.status_code == 201, hold.text
    body = {"sender_id": PHONE, "hold_id": hold.json()["id"], "patient_name": "Test Patient", "consent_to_reminders": consent, "idempotency_key": "book-" + suffix}
    if expected_fee is not None:
        body["expected_fee"] = expected_fee
    return c.post(P + "/appointments", headers=S, json=body), doctor, branch


def test_fee_snapshot_and_consent_survive_booking_replays_without_reopting_stop(setup):
    c, factory = setup
    rejected, doctor, branch = book(c, "fee-mismatch", expected_fee=1)
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "PRICE_CHANGED"
    response, _, _ = book(c, "fee-correct", expected_fee=doctor["consultation_fee"])
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["consultation_fee"] == doctor["consultation_fee"]
    assert c.get(P + "/preferences/" + PHONE, headers=S).json()["service_messages"] is True
    assert c.get(P + "/preferences/" + PHONE, headers=S).json()["marketing"] is False
    put_pref(c, stopped_all=True)
    replay = c.post(P + "/appointments", headers=S, json={"sender_id": PHONE, "hold_id": item["reservation"]["id"], "patient_name": "Test Patient", "consent_to_reminders": True, "idempotency_key": "book-fee-correct", "expected_fee": doctor["consultation_fee"]})
    assert replay.status_code == 201, replay.text
    assert c.get(P + "/preferences/" + PHONE, headers=S).json()["stopped_all"] is True
    assert c.patch(D + f"/branches/{branch['id']}", headers=A, json={"address": "Clinic address", "directions_url": "javascript:alert(1)"}).status_code == 422
    assert c.patch(D + f"/branches/{branch['id']}", headers=A, json={"address": "Clinic address", "directions_url": "https://maps.google.com/maps?q=clinic", "arrival_instructions": "Arrive ten minutes early."}).status_code == 200
    assert c.get(P + f"/appointments/{item['id']}", headers=S, params={"sender_id": PHONE}).json()["address"] == "Clinic address"


def test_care_followups_use_staff_recorded_status_and_disabled_rule_blocks_claim(setup):
    c, factory = setup
    sync(c, category="UTILITY", text="Visit {{1}} with {{2}} on {{3}}. How was your visit?")
    rule = {"template_id": "1001", "delay_hours": 0, "enabled": True}
    assert c.put(D + "/followup-rules/feedback", headers=A, json=rule).status_code == 200
    response, _, _ = book(c, "feedback")
    item = response.json()
    assert c.patch(f"/api/v1/admin/appointments/{item['id']}/status", headers=A, json={"status": "no_show"}).status_code == 409
    assert claim(c) is None  # booking alone must not trigger a completed-visit survey
    with factory() as db:
        appointment = db.get(Appointment, item["id"])
        appointment.reservation.starts_at = NOW - timedelta(hours=3)
        appointment.reservation.ends_at = NOW - timedelta(hours=2)
        db.commit()
    assert c.patch(f"/api/v1/admin/appointments/{item['id']}/status", headers=A, json={"status": "checked_in"}).status_code == 200
    assert c.patch(f"/api/v1/admin/appointments/{item['id']}/status", headers=A, json={"status": "completed"}).status_code == 200
    job = claim(c)
    assert job["purpose"] == "feedback"
    assert job["parameters"][0] == item["confirmation_code"]
    assert len(job["parameters"]) == 3
    # Disable after claim; dispatch must recheck the rule.
    assert c.put(D + "/followup-rules/feedback", headers=A, json={**rule, "enabled": False}).status_code == 200
    assert sending(c, job).json()["send"] is False
    assert c.put(D + "/followup-rules/followup", headers=A, json=rule).status_code == 200
    due = NOW + timedelta(days=10)
    r = c.post(D + f"/appointments/{item['id']}/followup", headers=A, json={"due_at": due.isoformat(), "actor": "Dr Test"})
    assert r.status_code == 202, r.text
    with factory() as db:
        scheduled = db.scalar(select(WhatsAppOutbound).where(WhatsAppOutbound.purpose == "followup"))
        assert outreach.utc(scheduled.due_at) == due
        assert scheduled.approved_actor == "Dr Test"
    assert c.post(D + f"/appointments/{item['id']}/followup", headers=A, json={"due_at": (due + timedelta(days=1)).isoformat(), "actor": "Dr Test"}).status_code == 409


def test_no_show_care_requires_service_consent_and_cannot_be_triggered_by_patient(setup):
    c, factory = setup
    sync(c, category="UTILITY", text="Visit {{1}} with {{2}} on {{3}} was missed. Rebook if needed.")
    assert c.put(D + "/followup-rules/no_show", headers=A, json={"template_id": "1001", "delay_hours": 0, "enabled": True}).status_code == 200
    response, _, _ = book(c, "no-show", consent=False)
    item = response.json()
    with factory() as db:
        appt = db.get(Appointment, item["id"]); appt.reservation.starts_at = NOW - timedelta(hours=3); appt.reservation.ends_at = NOW - timedelta(hours=2); db.commit()
    assert c.patch(f"/api/v1/admin/appointments/{item['id']}/status", headers=S, json={"status": "no_show"}).status_code == 422
    assert c.patch(f"/api/v1/admin/appointments/{item['id']}/status", headers=A, json={"status": "no_show"}).status_code == 200
    assert claim(c) is None


def test_booking_and_visit_consent_commit_atomically(setup, monkeypatch):
    c, factory = setup
    def unavailable(*args):
        from app.services import DomainError
        raise DomainError("CONSENT_UNAVAILABLE", "Could not record consent.", 503)
    monkeypatch.setattr(outreach, "change_preferences", unavailable)
    response, _, _ = book(c, "atomic-consent")
    assert response.status_code == 503
    with factory() as db:
        assert db.scalar(select(Appointment.id).where(Appointment.idempotency_key == "book-atomic-consent")) is None
        from app.models import Reservation, ReminderJob
        hold = db.scalar(select(Reservation).where(Reservation.idempotency_key == "hold-atomic-consent"))
        assert hold.status == "active"
        assert db.scalar(select(ReminderJob.id)) is None


def test_campaign_pdf_upload_stays_private_and_patient_assets_cannot_be_reused(setup, tmp_path, monkeypatch):
    import io
    from pypdf import PdfWriter
    from app.models import MediaAsset
    c, factory = setup
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    writer = PdfWriter(); writer.add_blank_page(width=200, height=200)
    document = io.BytesIO(); writer.write(document)
    upload = c.post(D + "/campaign-assets", headers=A, files={"file": ("approved-guide.pdf", document.getvalue(), "application/pdf")})
    assert upload.status_code == 201, upload.text
    asset = upload.json()
    assert c.get(D + f"/assets/{asset['id']}").status_code == 422
    assert c.get(D + f"/assets/{asset['id']}", headers=A).content == document.getvalue()
    assert c.get(P + f"/assets/{asset['id']}", headers=S).status_code == 404
    sync(c, header="DOCUMENT")
    item = campaign(c, asset_id=asset["id"])
    queued = c.post(f"{D}/campaigns/{item['id']}/test", headers=A, json={"sender_id": TESTER, "actor": "Staff"})
    assert queued.status_code == 202
    job = claim(c)
    assert job["asset_id"] == asset["id"] and job["header_type"] == "DOCUMENT"
    assert c.get(P + f"/assets/{asset['id']}", headers=S).content == document.getvalue()
    with factory() as db:
        db.get(MediaAsset, asset["id"]).kind = "attachment"; db.commit()
    assert c.get(P + f"/assets/{asset['id']}", headers=S).status_code == 404
    rejected = c.post(D + "/campaigns", headers=A, json={"title": "Patient attachment reuse", "template_id": "1001", "parameters": ["friend"], "asset_id": asset["id"], "scheduled_at": NOW.isoformat(), "rate_paise": 100, "budget_paise": 10000})
    assert rejected.status_code == 422


def test_reminders_wait_until_morning_and_stop_is_rechecked_before_send(setup, monkeypatch):
    from app.models import ReminderJob
    c, factory = setup
    response, _, _ = book(c, "quiet-reminder")
    assert response.status_code == 201
    with factory() as db:
        job = db.scalar(select(ReminderJob).where(ReminderJob.appointment_id == response.json()["id"]))
        job.status, job.claimed_at = "claimed", NOW
        job_id = job.id
        db.commit()
    monkeypatch.setattr(outreach, "utcnow", lambda: NOW + timedelta(hours=10))
    authorization = c.post(f"{P}/reminders/{job_id}/authorize", headers=S)
    assert authorization.json()["reason"] == "quiet_hours"
    with factory() as db:
        job = db.get(ReminderJob, job_id)
        assert job.status == "pending"
        assert outreach.utc(job.due_at).hour == 3  # 09:00 India
        assert outreach.utc(job.due_at).minute == 30
        job.status = "claimed"; db.commit()
    put_pref(c, stopped_all=True)
    assert c.post(f"{P}/reminders/{job_id}/authorize", headers=S).json()["send"] is False


@pytest.mark.skipif(not os.environ.get("HMS_OUTREACH_DATABASE_URL"), reason="PostgreSQL row-lock concurrency check")
def test_delivery_callback_racing_send_completion_is_not_lost(setup, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    c, factory = setup
    put_pref(c, marketing=True); sync(c)
    item = campaign(c); assert approve(c, item).status_code == 200
    job = claim(c); assert sending(c, job).json()["send"]
    inserted, release = threading.Event(), threading.Event()
    original = outreach.lock_receipt
    def instrumented(db, mid, status, timestamp):
        row = original(db, mid, status, timestamp)
        if status == "accepted" and mid == "wamid.racing-callback":
            inserted.set()
            assert release.wait(5)
        return row
    monkeypatch.setattr(outreach, "lock_receipt", instrumented)
    with ThreadPoolExecutor(max_workers=2) as threads:
        sent = threads.submit(accepted, c, job, "wamid.racing-callback")
        assert inserted.wait(5)
        callback = threads.submit(c.post, P + "/delivery-status", headers=S,
                                  json={"meta_message_id": "wamid.racing-callback", "status": "read", "timestamp": 100})
        release.set()
        assert sent.result(timeout=10).status_code == 200
        assert callback.result(timeout=10).status_code == 200
    with factory() as db:
        assert db.get(WhatsAppOutbound, job["id"]).status == "read"
