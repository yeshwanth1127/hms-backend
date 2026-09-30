from datetime import date, datetime, timedelta
import io
import socket
import struct
import threading
import tempfile
from pathlib import Path
import pytest

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from app.main import app
from app.db import SessionLocal
from app.models import Appointment, Branch, Doctor, ReminderJob, Reservation, WhatsAppInbound, utcnow
from app.whatsapp import owner_key
from app.media import scan_bytes
from app.services import DomainError
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
        assert len(booking["confirmation_code"]) == 20
        by_code = client.get(f"/api/v1/integrations/whatsapp/appointments/by-code/{booking['confirmation_code']}",
                             headers=SERVICE, params={"sender_id": SENDER})
        assert by_code.status_code == 200 and by_code.json()["id"] == booking["id"]
        assert client.get(f"/api/v1/integrations/whatsapp/appointments/by-code/{booking['confirmation_code']}",
                          headers=SERVICE, params={"sender_id": OTHER}).status_code == 404
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


def test_stale_claimed_reminder_is_not_resent():
    with TestClient(app) as client:
        booking, _ = _book(client, "reminder-stale")
        with SessionLocal() as db:
            job = db.scalar(select(ReminderJob).where(ReminderJob.appointment_id == booking["id"]))
            job.due_at = utcnow() - timedelta(minutes=1)
            db.commit()
        due = client.get("/api/v1/integrations/whatsapp/reminders/due", headers=SERVICE).json()
        assert len(due) == 1
        with SessionLocal() as db:
            job = db.get(ReminderJob, due[0]["id"])
            job.claimed_at = utcnow() - timedelta(minutes=16)
            db.commit()
        assert client.get("/api/v1/integrations/whatsapp/reminders/due", headers=SERVICE).json() == []
        with SessionLocal() as db:
            assert db.get(ReminderJob, due[0]["id"]).status == "uncertain"


def test_production_startup_rejects_development_defaults(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(RuntimeError, match="strong production secret"):
        with TestClient(app):
            pass


def test_appointment_pages_include_older_visits_and_preserve_owner_scope():
    sender = "919866666666"
    with TestClient(app) as client:
        with SessionLocal() as db:
            doctor = db.scalar(select(Doctor))
            branch = db.scalar(select(Branch))
            for index in range(11):
                start = utcnow() + timedelta(days=30 + index)
                hold = Reservation(doctor_id=doctor.id, branch_id=branch.id,
                                   consultation_type="in_person", starts_at=start,
                                   ends_at=start + timedelta(minutes=30), status="booked",
                                   owner_key=owner_key(sender))
                db.add(hold)
                db.flush()
                db.add(Appointment(confirmation_code=f"PAGE-{index:04d}", reservation_id=hold.id,
                                   patient_name="Page Test", patient_phone=f"+{sender}", status="confirmed",
                                   origin_channel="whatsapp", idempotency_key=f"page-test-{index}"))
            db.commit()
        url = "/api/v1/integrations/whatsapp/appointments/page"
        first = client.get(url, headers=SERVICE, params={"sender_id": sender, "limit": 8}).json()
        second = client.get(url, headers=SERVICE, params={"sender_id": sender, "limit": 8, "offset": 8}).json()
        assert first["total"] == second["total"] == 11
        assert len(first["items"]) == 8 and len(second["items"]) == 3
        assert set(item["id"] for item in first["items"]).isdisjoint(item["id"] for item in second["items"])
        assert client.get(url, headers=SERVICE, params={"sender_id": OTHER}).json()["total"] == 0


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


def test_inbound_queue_deduplicates_and_quarantines_ambiguous_sends():
    with TestClient(app) as client:
        path = "/api/v1/integrations/whatsapp/inbound"
        message = {"message_id": "wamid.queue-one", "sender_id": SENDER,
                   "payload": {"id": "wamid.queue-one", "from": SENDER, "type": "text", "text": "hi"}}
        assert client.post(path, headers=SERVICE, json=message).status_code == 202
        assert client.post(path, headers=SERVICE, json=message).json()["duplicate"] is True
        assert client.post(path, headers=SERVICE, json={**message, "sender_id": OTHER}).status_code == 422
        claimed = client.post(f"{path}/claim", headers=SERVICE).json()
        assert claimed["message_id"] == message["message_id"]
        token = {"claim_token": claimed["claim_token"]}
        assert client.post(f"{path}/{message['message_id']}/sending", headers=SERVICE, json=token).status_code == 200
        assert client.post(f"{path}/{message['message_id']}/failed", headers=SERVICE,
                           json={**token, "error": "Meta timeout"}).json()["status"] == "uncertain"
        assert client.post(f"{path}/claim", headers=SERVICE).json() is None
        issues = client.get(f"{path}/issues", headers=SERVICE).json()
        assert any(item["message_id"] == message["message_id"] for item in issues)
        assert client.get("/api/v1/admin/whatsapp-delivery-issues").status_code == 422
        staff_issues = client.get("/api/v1/admin/whatsapp-delivery-issues", headers=ADMIN).json()
        assert any(item["message_id"] == message["message_id"] for item in staff_issues["inbound"])
        with SessionLocal() as db:
            stored = db.get(WhatsAppInbound, message["message_id"])
            assert stored.payload == {}


def test_inbound_retry_before_send_and_stale_send_quarantine():
    with TestClient(app) as client:
        path = "/api/v1/integrations/whatsapp/inbound"
        for suffix in ("retry", "stale"):
            body = {"message_id": f"wamid.{suffix}", "sender_id": SENDER,
                    "payload": {"id": f"wamid.{suffix}", "from": SENDER, "type": "text", "text": "hi"}}
            assert client.post(path, headers=SERVICE, json=body).status_code == 202
        first = client.post(f"{path}/claim", headers=SERVICE).json()
        assert first["message_id"] == "wamid.retry"
        failed = client.post(f"{path}/{first['message_id']}/failed", headers=SERVICE,
                             json={"claim_token": first["claim_token"], "error": "Backend unavailable"})
        assert failed.json()["status"] == "pending"
        with SessionLocal() as db:
            item = db.get(WhatsAppInbound, first["message_id"])
            item.available_at = utcnow() - timedelta(seconds=1)
            db.commit()
        replay = client.post(f"{path}/claim", headers=SERVICE).json()
        assert replay["message_id"] == first["message_id"]
        client.post(f"{path}/{replay['message_id']}/sending", headers=SERVICE,
                    json={"claim_token": replay["claim_token"]})
        assert client.post(f"{path}/{replay['message_id']}/sent", headers=SERVICE,
                           json={"claim_token": replay["claim_token"]}).json()["status"] == "sent"
        second = client.post(f"{path}/claim", headers=SERVICE).json()
        assert second["message_id"] == "wamid.stale"
        client.post(f"{path}/{second['message_id']}/sending", headers=SERVICE,
                    json={"claim_token": second["claim_token"]})
        with SessionLocal() as db:
            item = db.get(WhatsAppInbound, second["message_id"])
            item.claimed_at = utcnow() - timedelta(minutes=16)
            db.commit()
        assert client.post(f"{path}/claim", headers=SERVICE).json() is None
        with SessionLocal() as db:
            assert db.get(WhatsAppInbound, second["message_id"]).status == "uncertain"


def test_clamav_stream_scan_accepts_clean_and_rejects_infected():
    def serve(reply: bytes, path):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            listener.listen(1)
            ready.set()
            connection, _ = listener.accept()
            with connection:
                assert connection.recv(10) == b"zINSTREAM\0"
                data = bytearray()
                while True:
                    length = struct.unpack(">I", connection.recv(4))[0]
                    if not length:
                        break
                    while len(data) < length:
                        data.extend(connection.recv(length - len(data)))
                assert data == b"safe-content"
                connection.sendall(reply + b"\0")

    with tempfile.TemporaryDirectory(prefix="clamd-", dir="/tmp") as folder:
        for index, reply in enumerate((b"stream: OK", b"stream: Eicar-Test-Signature FOUND")):
            ready = threading.Event()
            path = Path(folder) / f"scan-{index}.sock"
            thread = threading.Thread(target=serve, args=(reply, path), daemon=True)
            thread.start()
            assert ready.wait(2)
            if index == 0:
                scan_bytes(b"safe-content", str(path))
            else:
                try:
                    scan_bytes(b"safe-content", str(path))
                    assert False, "infected content was accepted"
                except DomainError as exc:
                    assert exc.code == "UNSAFE_MEDIA"
            thread.join(timeout=2)
        try:
            scan_bytes(b"safe-content", str(Path(folder) / "missing.sock"))
            assert False, "missing scanner was accepted"
        except DomainError as exc:
            assert exc.code == "MEDIA_SCAN_UNAVAILABLE"


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
                            headers=SERVICE, json={"status": "resolved"}).status_code == 422
