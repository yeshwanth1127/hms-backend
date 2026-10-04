from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import Appointment, Branch, Doctor, Hospital, Patient, Reservation
from app.teleconsultation_service import ensure_for_appointment


def _login(client: TestClient, email: str, password: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def test_named_admin_session_replaces_browser_admin_key():
    with TestClient(app) as client:
        actor = _login(client, "admin@example.com", "change-me-in-production")
        assert actor["role"] == "hospital_admin"
        assert client.get("/api/v1/admin/analytics").status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.get("/api/v1/admin/analytics").status_code == 401


def test_patient_consent_waiting_room_and_assigned_doctor_lifecycle():
    with TestClient(app):
        with SessionLocal() as db:
            hospital = db.scalar(select(Hospital))
            doctor = db.scalar(select(Doctor).where(Doctor.user_id.is_not(None)))
            patient = db.scalar(select(Patient).where(Patient.user_id.is_not(None)))
            branch = db.scalar(select(Branch).where(Branch.is_virtual.is_(True)))
            now = datetime.now(timezone.utc)
            reservation = Reservation(doctor_id=doctor.id, branch_id=branch.id, consultation_type="virtual",
                                      starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(minutes=25),
                                      status="booked", owner_key="test", idempotency_key="virtual-opd-reservation")
            db.add(reservation); db.flush()
            appointment = Appointment(confirmation_code="AVO-VIRTUAL", reservation_id=reservation.id,
                                      hospital_id=hospital.id, patient_id=patient.id, patient_name=patient.name,
                                      patient_phone=patient.phone or "9999999999", patient_email=patient.email,
                                      status="confirmed", origin_channel="staff", idempotency_key="virtual-opd-appointment")
            db.add(appointment); db.flush(); ensure_for_appointment(db, appointment); db.commit()
            appointment_id = appointment.id

    patient_client = TestClient(app)
    doctor_client = TestClient(app)
    with patient_client, doctor_client:
        _login(patient_client, "patient@example.com", "patient-demo-password")
        patient_view = patient_client.get(f"/api/v1/me/appointments/{appointment_id}/teleconsultation")
        assert patient_view.status_code == 200 and patient_view.json()["consent_accepted"] is False
        assert patient_client.post(f"/api/v1/me/appointments/{appointment_id}/teleconsultation/check-in").status_code == 409
        version = patient_view.json()["consent_version"]
        assert patient_client.post(f"/api/v1/me/appointments/{appointment_id}/teleconsultation/consent",
                                   json={"document_version": version, "accepted": True}).status_code == 201
        waiting = patient_client.post(f"/api/v1/me/appointments/{appointment_id}/teleconsultation/check-in")
        assert waiting.json()["status"] == "waiting"
        assert patient_client.post(f"/api/v1/me/appointments/{appointment_id}/teleconsultation/join-grant").status_code == 409

        _login(doctor_client, "doctor@example.com", "doctor-demo-password")
        started = doctor_client.post(f"/api/v1/doctor/appointments/{appointment_id}/teleconsultation/start")
        assert started.status_code == 200 and started.json()["status"] == "in_progress"
        doctor_grant = doctor_client.post(f"/api/v1/doctor/appointments/{appointment_id}/teleconsultation/join-grant")
        patient_grant = patient_client.post(f"/api/v1/me/appointments/{appointment_id}/teleconsultation/join-grant")
        assert doctor_grant.json()["role"] == "moderator"
        assert patient_grant.json()["role"] == "participant"
        assert patient_grant.json()["room_name"] == doctor_grant.json()["room_name"]
        completed = doctor_client.post(f"/api/v1/doctor/appointments/{appointment_id}/teleconsultation/end", json={})
        assert completed.json()["status"] == "completed"


def test_wrong_patient_cannot_enumerate_an_appointment():
    with TestClient(app) as client:
        _login(client, "patient@example.com", "patient-demo-password")
        response = client.get("/api/v1/me/appointments/not-a-real-appointment/teleconsultation")
        assert response.status_code == 404


def test_admin_creates_virtual_opd_and_doctor_sees_complete_worklist():
    admin = TestClient(app)
    doctor_client = TestClient(app)
    with admin, doctor_client:
        _login(admin, "admin@example.com", "change-me-in-production")
        doctors = admin.get("/api/v1/admin/doctors").json()
        doctor = next(item for item in doctors if item["slug"] == "doc-1")
        starts_at = datetime.now(timezone.utc) + timedelta(days=8)
        created = admin.post("/api/v1/admin/virtual-opd", json={
            "doctor_id": doctor["id"],
            "patient_name": "Portal Test Patient",
            "patient_phone": "+919900001234",
            "patient_email": "portal-test@example.com",
            "reason": "Virtual follow-up",
            "starts_at": starts_at.isoformat(),
            "duration_minutes": 30,
            "idempotency_key": "admin-virtual-opd-test-001",
        })
        assert created.status_code == 201, created.text
        assert created.json()["consultation_type"] == "virtual"
        assert created.json()["teleconsultation_status"] == "scheduled"
        queue = admin.get("/api/v1/admin/virtual-opd")
        assert any(item["id"] == created.json()["id"] for item in queue.json())

        _login(doctor_client, "doctor@example.com", "doctor-demo-password")
        worklist = doctor_client.get("/api/v1/doctor/dashboard/appointments")
        assert worklist.status_code == 200
        assert any(item["id"] == created.json()["id"] and item["consultation_type"] == "virtual"
                   for item in worklist.json())


def test_catalogue_and_admin_queries_are_tenant_scoped():
    with TestClient(app) as client:
        with SessionLocal() as db:
            other = Hospital(slug="other-hospital", name="Other Hospital", virtual_opd_enabled=True)
            db.add(other); db.flush()
            db.add(Branch(hospital_id=other.id, slug="other-branch", name="Other Branch", area="Elsewhere"))
            db.commit()
        default_branches = client.get("/api/v1/branches").json()
        other_branches = client.get("/api/v1/branches", headers={"X-Hospital-Slug": "other-hospital"}).json()
        assert all(item["slug"] != "other-branch" for item in default_branches)
        assert [item["slug"] for item in other_branches] == ["other-branch"]
        _login(client, "admin@example.com", "change-me-in-production")
        admin_catalogue = client.get("/api/v1/admin/catalogue").json()
        assert all(item["slug"] != "other-branch" for item in admin_catalogue["branches"])


def test_production_booking_requires_a_patient_session(monkeypatch):
    from app.config import settings
    with TestClient(app) as anonymous:
        monkeypatch.setattr(settings, "app_env", "production")
        response = anonymous.post("/api/v1/slot-holds", json={})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PATIENT_AUTH_REQUIRED"
    monkeypatch.setattr(settings, "app_env", "test")
    with TestClient(app) as patient:
        _login(patient, "patient@example.com", "patient-demo-password")
        monkeypatch.setattr(settings, "app_env", "production")
        response = patient.post("/api/v1/slot-holds", json={})
        assert response.status_code == 422
