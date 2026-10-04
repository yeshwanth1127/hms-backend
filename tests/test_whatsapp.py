from datetime import date, datetime, timedelta
import io

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from app.main import app
from app.db import SessionLocal
from app.models import ReminderJob, utcnow
from sqlalchemy import select


SERVICE = {"X-Service-Key": "dev-whatsapp-service-key"}
ADMIN = {"X-Admin-Key": "dev-admin-key"}
SENDER = "919811111111"
OTHER = "919822222222"


def _future_weekday():
    day = date.today() + timedelta(days=3)
    while day.weekday() == 6:
        day += timedelta(days=1)
    return day


def _book(client: TestClient, suffix: str, consent: bool = True):
    catalog = client.get("/api/v1/integrations/whatsapp/catalogue", headers=SERVICE).json()
    department = next(value for value in catalog["departments"] if value["slug"] == "cardiology")
    branch = next(value for value in catalog["branches"] if value["slug"] == "indiranagar")
    doctor = client.get("/api/v1/integrations/whatsapp/doctors", headers=SERVICE,
                        params={"department": department["slug"], "branch": branch["slug"]}).json()[0]
    day = _future_weekday()
    slots = client.get("/api/v1/integrations/whatsapp/availability", headers=SERVICE, params={
        "doctor_id": doctor["id"], "branch_id": branch["id"],
        "start_date": day.isoformat(), "end_date": day.isoformat(),
    }).json()["slots"]
    hold = client.post("/api/v1/integrations/whatsapp/slot-holds", headers=SERVICE,
                       json={**slots[0], "sender_id": SENDER, "idempotency_key": f"wa-hold-{suffix}"})
    assert hold.status_code == 201, hold.text
    booking = client.post("/api/v1/integrations/whatsapp/appointments", headers=SERVICE,
                          json={"sender_id": SENDER, "hold_id": hold.json()["id"],
                                "patient_name": "Patient Test", "consent_to_reminders": consent,
                                "idempotency_key": f"wa-book-{suffix}"})
    assert booking.status_code == 201, booking.text
    return booking.json(), slots


def test_whatsapp_booking_ownership_reschedule_cancel_and_reminder():
    with TestClient(app) as client:
        assert client.get("/api/v1/integrations/whatsapp/catalogue").status_code == 422
        assert client.get("/api/v1/integrations/whatsapp/catalogue", headers={"X-Service-Key": "wrong"}).status_code == 401
        booking, slots = _book(client, "lifecycle-1")
        assert booking["status"] == "confirmed"
        assert booking["origin_channel"] == "whatsapp"
        assert booking["doctor_name"]
        reused_key = client.post("/api/v1/integrations/whatsapp/slot-holds", headers=SERVICE,
                                 json={**slots[0], "sender_id": OTHER,
                                       "idempotency_key": "wa-hold-lifecycle-1"})
        assert reused_key.status_code == 409
        assert client.get("/api/v1/integrations/whatsapp/appointments", headers=SERVICE,
                          params={"sender_id": OTHER}).json() == []
        assert client.get(f"/api/v1/integrations/whatsapp/appointments/{booking['id']}", headers=SERVICE,
                          params={"sender_id": OTHER}).status_code == 404
        new_hold = client.post("/api/v1/integrations/whatsapp/slot-holds", headers=SERVICE,
                               json={**slots[1], "sender_id": SENDER,
                                     "idempotency_key": "wa-hold-lifecycle-2"})
        assert new_hold.status_code == 201, new_hold.text
        move = {"sender_id": SENDER, "new_hold_id": new_hold.json()["id"],
                "idempotency_key": "wa-move-lifecycle-1"}
        changed = client.post(f"/api/v1/integrations/whatsapp/appointments/{booking['id']}/reschedule",
                              headers=SERVICE, json=move)
        assert changed.status_code == 200, changed.text
        assert datetime.fromisoformat(changed.json()["reservation"]["starts_at"]) == datetime.fromisoformat(slots[1]["starts_at"])
        replay = client.post(f"/api/v1/integrations/whatsapp/appointments/{booking['id']}/reschedule",
                             headers=SERVICE, json=move)
        assert replay.status_code == 200
        assert client.post(f"/api/v1/integrations/whatsapp/appointments/{booking['id']}/cancel",
                           headers=SERVICE, json={"sender_id": OTHER, "reason": "Plans changed"}).status_code == 404
        cancelled = client.post(f"/api/v1/integrations/whatsapp/appointments/{booking['id']}/cancel",
                                headers=SERVICE, json={"sender_id": SENDER, "reason": "Plans changed"})
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert client.get("/api/v1/integrations/whatsapp/reminders/due", headers=SERVICE).json() == []


def test_reminder_claim_and_completion():
    with TestClient(app) as client:
        booking, _ = _book(client, "reminder-1")
        with SessionLocal() as db:
            job = db.scalar(select(ReminderJob).where(ReminderJob.appointment_id == booking["id"]))
            assert job is not None
            job.due_at = utcnow() - timedelta(minutes=1)
            db.commit()
        due = client.get("/api/v1/integrations/whatsapp/reminders/due", headers=SERVICE).json()
        assert len(due) == 1
        assert due[0]["confirmation_code"] == booking["confirmation_code"]
        assert datetime.fromisoformat(due[0]["starts_at"]).utcoffset() == timedelta(0)
        completed = client.post(f"/api/v1/integrations/whatsapp/reminders/{due[0]['id']}/complete",
                                headers=SERVICE, json={"status": "sent"})
        assert completed.status_code == 200
        assert completed.json()["status"] == "sent"
        assert client.get("/api/v1/integrations/whatsapp/reminders/due", headers=SERVICE).json() == []


def test_conversation_state_survives_requests():
    with TestClient(app) as client:
        path = f"/api/v1/integrations/whatsapp/conversations/{SENDER}"
        initial = client.get(path, headers=SERVICE)
        assert initial.status_code == 200
        assert initial.json()["state"]["step"] == "menu"
        saved = client.put(path, headers=SERVICE, json={
            "state": {"step": "doctor", "draft": {"department": "cardiology"}},
            "last_message_id": "wamid.conversation-test-1",
            "last_reply": {"kind": "text", "text": "Choose a doctor"},
        })
        assert saved.status_code == 200
        restored = client.get(path, headers=SERVICE).json()
        assert restored["state"]["draft"]["department"] == "cardiology"
        assert restored["last_reply"]["text"] == "Choose a doctor"
        assert client.get(path, headers={"X-Service-Key": "wrong"}).status_code == 401


def test_uploads_cases_and_validation(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(pdf)
    png = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(png, format="PNG")
    with TestClient(app) as client:
        inventory = client.get("/api/v1/admin/whatsapp-assets", headers=ADMIN).json()
        dept = next(value for value in inventory["departments"] if value["slug"] == "cardiology")
        doctor = inventory["doctors"][0]
        bad = client.post(f"/api/v1/admin/departments/{dept['id']}/guide", headers=ADMIN,
                          files={"file": ("bad.pdf", b"not-a-pdf", "application/pdf")})
        assert bad.status_code == 415
        guide = client.post(f"/api/v1/admin/departments/{dept['id']}/guide", headers=ADMIN,
                            files={"file": ("cardiology.pdf", pdf.getvalue(), "application/pdf")})
        assert guide.status_code == 201, guide.text
        replacement = client.post(f"/api/v1/admin/departments/{dept['id']}/guide", headers=ADMIN,
                                  files={"file": ("updated.pdf", pdf.getvalue(), "application/pdf")})
        assert replacement.status_code == 201
        assert replacement.json()["id"] != guide.json()["id"]
        image = client.post(f"/api/v1/admin/doctors/{doctor['id']}/photo", headers=ADMIN,
                            files={"file": ("doctor.png", png.getvalue(), "image/png")})
        assert image.status_code == 201
        asset = client.get(f"/api/v1/integrations/whatsapp/assets/{replacement.json()['id']}", headers=SERVICE)
        assert asset.status_code == 200 and asset.content.startswith(b"%PDF-")
        assert client.get(f"/api/v1/integrations/whatsapp/assets/{guide.json()['id']}", headers=SERVICE).status_code == 404
        case = client.post("/api/v1/integrations/whatsapp/cases", headers=SERVICE,
                           json={"sender_id": SENDER, "kind": "issue", "description": "Please call me",
                                 "idempotency_key": "wa-case-upload-1"})
        assert case.status_code == 201
        attached = client.post(f"/api/v1/integrations/whatsapp/cases/{case.json()['id']}/attachments",
                               headers=SERVICE, data={"sender_id": SENDER, "source_message_id": "wamid.upload-test-1"},
                               files={"file": ("photo.png", png.getvalue(), "image/png")})
        assert attached.status_code == 201, attached.text
        cases = client.get("/api/v1/admin/whatsapp-cases", headers=ADMIN).json()
        assert len(cases) >= 1
        assert any(item["sender_id"] == SENDER for item in cases)
        changed = client.patch(f"/api/v1/admin/whatsapp-cases/{case.json()['id']}",
                               headers=ADMIN, json={"status": "in_progress"})
        assert changed.status_code == 200
        assert changed.json()["status"] == "in_progress"
        assert client.patch(f"/api/v1/admin/whatsapp-cases/{case.json()['id']}",
                            headers=SERVICE, json={"status": "resolved"}).status_code == 401
