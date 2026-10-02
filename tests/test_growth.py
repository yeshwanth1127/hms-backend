from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.growth import GrowthAudit
from app.main import app
from app.models import Appointment, Branch, Doctor, Reservation, StaffUser, StaffSession, ClientModule
from app.staff_auth import password_hash, digest, COOKIE
from app.schemas import AppointmentCreate

HEADERS = {}


@pytest.fixture
def growth_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    def db_override():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    monkeypatch.setattr(settings, "booking_allowed_origins", "https://clinic.example")
    with sessions() as db:
        db.add_all([Branch(id="branch-a", slug="clinic-a", name="Clinic A", area="A", timezone="Asia/Kolkata"),
                    Branch(id="branch-b", slug="clinic-b", name="Clinic B", area="B", timezone="Asia/Kolkata"),
                    Branch(id="virtual", slug="virtual", name="Virtual", area="Online", is_virtual=True),
                    Doctor(id="doctor-a", slug="doctor-a", name="Doctor A", title="Doctor", bio="", experience_years=1,
                           consultation_fee=100, accepts_virtual=False)])
        db.add_all([ClientModule(key="google_business", enabled=True), ClientModule(key="growth_analytics", enabled=True)])
        db.add(StaffUser(username="growth.test", display_name="Growth Test", role="growth_manager", password_hash=password_hash("test-password-strong")))
        db.commit()
        HEADERS.clear()

    try:
        with TestClient(app) as client:
            login = client.post("/api/v1/staff/login", json={"username":"growth.test", "password":"test-password-strong"})
            HEADERS.update({"X-CSRF-Token":login.json()["csrf_token"]})
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def add_booking(db, *, created, visit, branch="branch-a", demo=False, status="confirmed", source="google_business"):
    reservation = Reservation(id=str(uuid4()), doctor_id="doctor-a", branch_id=branch, consultation_type="in_person",
                              starts_at=visit, ends_at=visit + timedelta(minutes=30), owner_key="test-owner",
                              status="booked", idempotency_key=str(uuid4()))
    db.add(reservation)
    db.flush()
    db.add(Appointment(confirmation_code=str(uuid4())[:20], reservation_id=reservation.id,
                       patient_name="PRIVATE PATIENT", patient_phone="PRIVATE PHONE", reason="PRIVATE REASON",
                       status=status, origin_channel="web", acquisition_source=source, is_demo=demo,
                       idempotency_key=str(uuid4()), created_at=created))
    db.commit()


def test_summary_timezone_demo_branch_and_privacy(growth_client):
    client, sessions = growth_client
    # 18:30 UTC is local midnight; immediately before belongs to the previous local day.
    boundary = datetime(2026, 1, 1, 18, 30, tzinfo=timezone.utc)
    with sessions() as db:
        for offset, branch, demo, status in [(0, "branch-a", False, "completed"),
                                            (-1, "branch-a", False, "confirmed"),
                                            (1, "branch-a", True, "confirmed"),
                                            (2, "branch-b", False, "confirmed")]:
            add_booking(db, created=boundary+timedelta(seconds=offset), visit=boundary-timedelta(days=1)+timedelta(hours=offset),
                        branch=branch, demo=demo, status=status)
    params = {"start_date": "2026-01-02", "end_date": "2026-01-02", "branch_id": "branch-a"}
    response = client.get("/api/v1/admin/growth/summary", params=params, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["appointments_in_cohort"] == 1
    assert body["summary"]["attendance_rate_resolved"] == 100
    assert body["by_acquisition_source"] == {"google_business": 1}
    assert body["by_channel"] == {"web": 1}
    assert "PRIVATE" not in response.text
    assert "patient_phone" not in response.text
    assert body["sources"]["google"] == "not_connected"
    assert client.get("/api/v1/admin/growth/summary", params={**params, "include_demo": True},
                      headers=HEADERS).json()["summary"]["appointments_in_cohort"] == 2
    assert client.get("/api/v1/admin/growth/summary", params={**params, "cohort": "visit"},
                      headers=HEADERS).json()["summary"]["appointments_in_cohort"] == 0


def test_unknown_outcomes_and_empty_denominators(growth_client):
    client, sessions = growth_client
    day = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with sessions() as db:
        for offset, status in enumerate(["completed", "no_show", "confirmed", "cancelled"]):
            add_booking(db, created=day, visit=day+timedelta(hours=offset), status=status)
    params = {"start_date": "2026-01-02", "end_date": "2026-01-02"}
    summary = client.get("/api/v1/admin/growth/summary", params=params, headers=HEADERS).json()["summary"]
    assert summary["attendance_rate_resolved"] == 50
    assert summary["attendance_denominator"] == 2
    assert summary["past_outcome_unknown"] == 1
    assert summary["past_cancelled"] == 1
    empty = client.get("/api/v1/admin/growth/summary", params={**params, "branch_id": "branch-b"},
                       headers=HEADERS).json()["summary"]
    assert empty["retained_confirmation_share"] is None
    assert empty["attendance_rate_resolved"] is None


def test_growth_auth_and_invalid_filters(growth_client):
    client, _ = growth_client
    for path in ["/growth/summary", "/google/booking-links", "/google/changes"]:
        with TestClient(app) as unauthenticated:
            assert unauthenticated.get("/api/v1/admin"+path, headers={"X-Admin-Key": "bad"}).status_code == 401
    for params, expected in [({"branch_id": "missing"}, 404), ({"reporting_timezone": "bad"}, 422),
                             ({"start_date": "2026-02-01", "end_date": "2026-01-01"}, 422),
                             ({"start_date": "2024-01-01", "end_date": "2026-01-01"}, 422),
                             ({"end_date": "9999-12-31"}, 422)]:
        assert client.get("/api/v1/admin/growth/summary", params=params, headers=HEADERS).status_code == expected


def test_manual_link_validation_idempotent_audit_and_no_publish(growth_client, monkeypatch):
    client, sessions = growth_client
    path = "/api/v1/admin/google/booking-links/branch-a"
    for url in ["http://clinic.example/book", "https://other.example/book", "https://user:pass@clinic.example/book",
                "https://clinic.example/book#secret", "https://clinic.example/book?patient=secret"]:
        assert client.put(path, json={"booking_url": url}, headers=HEADERS).status_code == 422
    body = {"booking_url": "https://clinic.example/book"}
    assert client.put(path, json=body, headers={"X-Admin-Key": "bad"}).status_code == 403
    first = client.put(path, json=body, headers=HEADERS)
    assert first.status_code == 200
    assert first.json()["booking_url"] == "https://clinic.example/book?branch=clinic-a&source=google_business"
    assert first.json()["google_publish_state"] == "not_published_by_this_app"
    assert client.put(path, json=body, headers=HEADERS).json() == first.json()
    with sessions() as db:
        assert len(db.scalars(select(GrowthAudit)).all()) == 1
    assert client.put("/api/v1/admin/google/booking-links/virtual", json=body, headers=HEADERS).status_code == 422
    monkeypatch.setattr(settings, "booking_allowed_origins", "")
    assert client.put(path, json=body, headers=HEADERS).status_code == 503


def test_acquisition_contract_rejects_free_text():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AppointmentCreate(hold_id="hold", owner_key="owner", patient_name="Patient", patient_phone="1234567",
                          idempotency_key="booking-123", acquisition_source="patient symptom text")


def test_confirmation_persists_source_and_demo_state_without_replay_reclassification(growth_client, monkeypatch):
    from app.services import confirm_appointment
    _, sessions = growth_client
    with sessions() as db:
        from app.models import ScheduleRule
        from datetime import time
        from zoneinfo import ZoneInfo
        day = (datetime.now(timezone.utc)+timedelta(days=1)).astimezone(ZoneInfo('Asia/Kolkata')).date()
        begins = datetime.combine(day, time(9), tzinfo=ZoneInfo('Asia/Kolkata')).astimezone(timezone.utc)
        db.add(ScheduleRule(doctor_id='doctor-a', branch_id='branch-a', consultation_type='in_person',
            schedule_date=day, weekday=day.weekday(), effective_from=day, effective_until=day,
            starts_at_local=time(9), ends_at_local=time(10), slot_minutes=30))
        now = datetime.now(timezone.utc)
        hold = Reservation(id=str(uuid4()), doctor_id="doctor-a", branch_id="branch-a", consultation_type="in_person",
                           starts_at=begins, ends_at=begins+timedelta(minutes=30),
                           status="active", owner_key="owner", expires_at=now+timedelta(minutes=5),
                           idempotency_key=str(uuid4()))
        db.add(hold)
        db.commit()
        body = AppointmentCreate(hold_id=hold.id, owner_key="owner", patient_name="Test Patient",
                                 patient_phone="123456789", idempotency_key=str(uuid4()),
                                 acquisition_source="google_business")
        item = confirm_appointment(db, body)
        assert item.acquisition_source == "google_business"
        assert item.origin_channel == "web"
        assert item.is_demo is True
        monkeypatch.setattr(settings, "app_env", "production")
        replay = confirm_appointment(db, body.model_copy(update={"acquisition_source": "direct"}))
        assert replay.id == item.id
        assert replay.is_demo is True
        assert replay.acquisition_source == "google_business"


def test_receptionist_cannot_read_or_manage_growth_and_shared_key_has_no_access(growth_client):
    client, sessions = growth_client
    with sessions() as db:
        db.add(StaffUser(username="reception.test", display_name="Reception Test", role="staff", password_hash=password_hash("test-password-strong")))
        db.commit()
    login = client.post("/api/v1/staff/login", json={"username":"reception.test", "password":"test-password-strong"})
    reception = {"X-CSRF-Token": login.json()["csrf_token"]}
    for path in ["/growth/summary", "/growth/catalogue", "/google/setup", "/google/capabilities", "/google/booking-links", "/google/changes"]:
        assert client.get("/api/v1/admin"+path, headers=reception).status_code == 403
        with TestClient(app) as unauthenticated:
            assert unauthenticated.get("/api/v1/admin"+path, headers={"X-Admin-Key": "dev-admin-key"}).status_code == 401
    assert client.put("/api/v1/admin/google/booking-links/branch-a", headers=reception,
                      json={"booking_url": "https://clinic.example/book"}).status_code == 403
    # Cookie identity, not an old CSRF header, determines patient-data permissions.
    assert client.get("/api/v1/admin/appointments").status_code == 200
    client.post("/api/v1/staff/login", json={"username":"growth.test", "password":"test-password-strong"})
    assert client.get("/api/v1/admin/appointments").status_code == 403


def test_role_changes_disable_expiry_and_logout_are_checked_on_each_request(growth_client):
    client, sessions = growth_client
    def get():
        return client.get("/api/v1/admin/growth/summary", headers=HEADERS)
    token = client.cookies.get(COOKIE)
    with sessions() as db:
        staff = db.scalar(select(StaffUser).where(StaffUser.display_name == "Growth Test"))
        staff.role = "staff"
        db.commit()
    assert get().status_code == 403
    with sessions() as db:
        staff = db.scalar(select(StaffUser).where(StaffUser.display_name == "Growth Test"))
        staff.role = "growth_manager"
        staff.is_active = False
        db.commit()
    assert get().status_code == 401
    with sessions() as db:
        staff = db.scalar(select(StaffUser).where(StaffUser.display_name == "Growth Test"))
        staff.is_active = True
        session = db.get(StaffSession, digest(token))
        session.expires_at = datetime.now(timezone.utc)-timedelta(seconds=1)
        db.commit()
    assert get().status_code == 401
    with sessions() as db:
        session = db.get(StaffSession, digest(token))
        session.expires_at = datetime.now(timezone.utc)+timedelta(hours=1)
        db.commit()
    assert get().status_code == 200
    assert client.post("/api/v1/staff/logout", headers=HEADERS).status_code == 204
    assert get().status_code == 401


def test_named_audit_and_new_profile_setup(growth_client):
    client, sessions = growth_client
    setup = client.get("/api/v1/admin/google/setup", headers=HEADERS).json()
    assert setup["profile_status"] == "not_connected"
    assert setup["preview_mode"] == "draft_only"
    assert client.put("/api/v1/admin/google/booking-links/branch-a", headers=HEADERS,
                      json={"booking_url": "https://clinic.example/book"}).status_code == 200
    history = client.get("/api/v1/admin/google/changes", headers=HEADERS).json()
    assert history[0]["actor_name"] == "Growth Test"
    assert history[0]["actor"] == client.get("/api/v1/staff/session", headers=HEADERS).json()["user"]["id"]
    with sessions() as db:
        assert db.get(StaffSession, digest(client.cookies.get(COOKIE))) is not None


def test_preview_is_illustrative_and_capabilities_require_growth_role(growth_client):
    client, _ = growth_client
    page = client.get("/growth", follow_redirects=False)
    assert page.status_code == 307
    assert page.headers["location"] == "/staff/google_business/overview"
    result = client.get("/api/v1/admin/google/capabilities", headers=HEADERS)
    assert result.status_code == 200
    body = result.json()
    assert body["google_connected"] is False
    assert body["mode"] == "planning_only"
    assert len(body["capabilities"]) == 10
    with TestClient(app) as unauthenticated:
        assert unauthenticated.get("/api/v1/admin/google/capabilities").status_code == 401


def test_modules_independent_default_off_role_and_direct_api_enforcement(growth_client):
    client, sessions = growth_client
    with sessions() as db:
        db.get(ClientModule, "google_business").enabled = False
        db.commit()
    assert client.get("/api/v1/admin/google/setup").status_code == 403
    assert client.get("/api/v1/admin/growth/summary").status_code == 200
    assert client.put("/api/v1/staff/modules/google_business", headers=HEADERS, json={"enabled":True}).status_code == 403
    with sessions() as db:
        staff = db.scalar(select(StaffUser).where(StaffUser.username == "growth.test"))
        staff.role = "admin"
        db.commit()
    assert client.put("/api/v1/staff/modules/google_business", json={"enabled":True}).status_code == 403
    assert client.put("/api/v1/staff/modules/google_business", headers=HEADERS, json={"enabled":True}).status_code == 200
    assert client.get("/api/v1/admin/google/setup").status_code == 200
    assert client.put("/api/v1/staff/modules/growth_analytics", headers=HEADERS, json={"enabled":False}).status_code == 200
    assert client.get("/api/v1/admin/growth/summary").status_code == 403
    assert client.get("/api/v1/admin/google/setup").status_code == 200
    assert client.get("/api/v1/admin/growth/catalogue").status_code == 200
    assert client.put("/api/v1/staff/modules/appointments", headers=HEADERS, json={"enabled":False}).status_code == 404
    assert client.put("/api/v1/staff/modules/google_business", headers=HEADERS, json={"enabled":"false"}).status_code == 422
    with sessions() as db:
        db.delete(db.get(ClientModule, "google_business"))
        db.commit()
    assert client.get("/api/v1/admin/google/setup").status_code == 403
    assert client.get("/api/v1/admin/growth/catalogue").status_code == 403


def test_login_failures_logout_and_no_plaintext_password(growth_client):
    client, sessions = growth_client
    assert client.post("/api/v1/staff/login", json={"username":"growth.test","password":"wrong"}).status_code == 401
    with sessions() as db:
        user = db.scalar(select(StaffUser).where(StaffUser.username == "growth.test"))
        assert user.password_hash.startswith("$argon2")
        assert "test-password-strong" not in user.password_hash
    assert client.post("/api/v1/staff/logout", headers=HEADERS).status_code == 204
    assert client.get("/api/v1/staff/session").status_code == 401


def test_module_disable_preserves_links_and_audits_named_changes(growth_client):
    from app.models import ModuleAudit
    client, sessions = growth_client
    assert client.put('/api/v1/admin/google/booking-links/branch-a', headers=HEADERS,
                      json={'booking_url':'https://clinic.example/book'}).status_code == 200
    with sessions() as db:
        staff = db.scalar(select(StaffUser).where(StaffUser.username == 'growth.test'))
        staff.role = 'admin'
        actor = staff.id
        db.commit()
    path='/api/v1/staff/modules/google_business'
    for enabled in (False, False, True):
        response=client.put(path, headers=HEADERS, json={'enabled':enabled})
        assert response.status_code == 200
        assert response.json()['data_retained'] is True
    assert len(client.get('/api/v1/admin/google/booking-links').json()['links']) == 1
    with sessions() as db:
        rows=db.scalars(select(ModuleAudit).where(ModuleAudit.module_key=='google_business').order_by(ModuleAudit.created_at)).all()
        assert [row.enabled for row in rows] == [False, True]
        assert all(row.actor == actor for row in rows)
    # Backwards compatibility does not override an explicit clinic opt-out.
    modules=client.get('/api/v1/staff/modules').json()['modules']
    assert next(m for m in modules if m['key']=='whatsapp')['enabled'] is True
    assert client.put('/api/v1/staff/modules/whatsapp',headers=HEADERS,json={'enabled':False}).status_code == 200
    assert next(m for m in client.get('/api/v1/staff/modules').json()['modules'] if m['key']=='whatsapp')['enabled'] is False
