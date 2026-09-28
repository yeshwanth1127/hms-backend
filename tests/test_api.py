from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


def future_weekday(target_weekday: int) -> date:
    cursor = datetime.now(timezone.utc).date() + timedelta(days=1)
    while cursor.weekday() != target_weekday:
        cursor += timedelta(days=1)
    return cursor


def catalogue(client: TestClient):
    doctors = client.get("/api/v1/doctors").json()
    branches = client.get("/api/v1/branches").json()
    return doctors[0], next(item for item in branches if item["slug"] == "indiranagar")


def test_health_and_catalogue():
    with TestClient(app) as client:
        assert client.get("/api/health/live").status_code == 200
        assert client.get("/api/health/ready").status_code == 200
        assert len(client.get("/api/v1/departments").json()) >= 8
        assert len(client.get("/api/v1/doctors").json()) == 10


def test_hold_confirm_cancel_and_idempotency():
    with TestClient(app) as client:
        doctor, branch = catalogue(client)
        day = future_weekday(0)
        response = client.get("/api/v1/availability", params={
            "doctor_id": doctor["id"], "branch_id": branch["id"],
            "start_date": day.isoformat(), "end_date": day.isoformat(),
        })
        assert response.status_code == 200
        slot = response.json()["slots"][0]
        hold_body = {**slot, "owner_key": "browser-session-1", "idempotency_key": "hold-test-0001"}
        hold_response = client.post("/api/v1/slot-holds", json=hold_body)
        assert hold_response.status_code == 201
        hold = hold_response.json()
        replay = client.post("/api/v1/slot-holds", json=hold_body)
        assert replay.json()["id"] == hold["id"]

        booking_body = {
            "hold_id": hold["id"], "owner_key": "browser-session-1",
            "patient_name": "Test Patient", "patient_phone": "+919999999999",
            "patient_email": "patient@example.com", "reason": "Annual checkup",
            "origin_channel": "web", "idempotency_key": "booking-test-0001",
        }
        booked = client.post("/api/v1/appointments", json=booking_body)
        assert booked.status_code == 201
        appointment = booked.json()
        assert appointment["status"] == "confirmed"
        assert appointment["confirmation_code"].startswith("AVO-")
        replay_booking = client.post("/api/v1/appointments", json=booking_body)
        assert replay_booking.json()["id"] == appointment["id"]

        hidden = client.get(f"/api/v1/appointments/{appointment['id']}", headers={"X-Owner-Key": "wrong"})
        assert hidden.status_code == 404
        cancelled = client.patch(
            f"/api/v1/appointments/{appointment['id']}/cancel",
            headers={"X-Owner-Key": "browser-session-1"},
            json={"actor_id": "patient-test", "reason": "Plans changed"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"


def test_second_hold_cannot_take_same_slot():
    with TestClient(app) as client:
        doctor, branch = catalogue(client)
        day = future_weekday(1)
        slots = client.get("/api/v1/availability", params={
            "doctor_id": doctor["id"], "branch_id": branch["id"],
            "start_date": day.isoformat(), "end_date": day.isoformat(),
        }).json()["slots"]
        slot = slots[0]
        first = client.post("/api/v1/slot-holds", json={
            **slot, "owner_key": "caller-one", "idempotency_key": "hold-conflict-0001",
        })
        assert first.status_code == 201
        second = client.post("/api/v1/slot-holds", json={
            **slot, "owner_key": "caller-two", "idempotency_key": "hold-conflict-0002",
        })
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "SLOT_NO_LONGER_AVAILABLE"


def test_admin_requires_key_and_manages_catalogue():
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/analytics").status_code == 422
        assert client.get("/api/v1/admin/analytics", headers={"X-Admin-Key": "wrong-key"}).status_code == 401
        headers = {"X-Admin-Key": "dev-admin-key"}
        analytics = client.get("/api/v1/admin/analytics", headers=headers)
        assert analytics.status_code == 200
        assert analytics.json()["summary"]["active_doctors"] == 10
        doctors = client.get("/api/v1/admin/doctors", headers=headers).json()
        doctor = doctors[0]
        updated = client.patch(f"/api/v1/admin/doctors/{doctor['id']}", headers=headers,
                               json={"accepts_virtual": not doctor["accepts_virtual"]})
        assert updated.status_code == 200
        assert updated.json()["accepts_virtual"] is (not doctor["accepts_virtual"])
        catalogue = client.get("/api/v1/admin/catalogue", headers=headers)
        assert len(catalogue.json()["branches"]) == 5


def test_voice_service_books_and_is_visible_to_admin():
    with TestClient(app) as client:
        service_headers = {"X-Service-Key": "dev-voice-service-key"}
        assert client.get("/api/v1/integrations/voice/doctors").status_code == 422
        assert client.get("/api/v1/integrations/voice/doctors", headers={"X-Service-Key": "wrong"}).status_code == 401

        session_id = "runtime-test-session-0001"
        started = client.post("/api/v1/integrations/voice/sessions", headers=service_headers,
                              json={"runtime_session_id": session_id, "channel": "web_voice"})
        assert started.status_code == 201

        doctors = client.get("/api/v1/integrations/voice/doctors", headers=service_headers,
                             params={"department": "cardiology"}).json()
        doctor = doctors[0]
        branch = next(item for item in doctor["branches"] if item["slug"] == "indiranagar")
        day = future_weekday(2)
        slot = client.get("/api/v1/integrations/voice/availability", headers=service_headers, params={
            "doctor_id": doctor["id"], "branch_id": branch["id"],
            "start_date": day.isoformat(), "end_date": day.isoformat(),
        }).json()["slots"][0]
        owner_key = f"voice:{session_id}"
        hold = client.post("/api/v1/integrations/voice/slot-holds", headers=service_headers,
                           json={**slot, "owner_key": owner_key, "idempotency_key": "voice-hold-test-0001"})
        assert hold.status_code == 201
        booking = client.post("/api/v1/integrations/voice/appointments", headers=service_headers, json={
            "hold_id": hold.json()["id"], "owner_key": owner_key,
            "patient_name": "Voice Patient", "patient_phone": "+919888888888",
            "reason": "Cardiology consultation", "origin_channel": "voice",
            "idempotency_key": "voice-booking-test-0001",
        })
        assert booking.status_code == 201
        appointment = booking.json()
        client.post(f"/api/v1/integrations/voice/sessions/{session_id}/events", headers=service_headers,
                    json={"tool_name": "confirm_appointment", "intent": "book_appointment",
                          "appointment_id": appointment["id"]})
        client.patch(f"/api/v1/integrations/voice/sessions/{session_id}", headers=service_headers,
                     json={"status": "completed"})

        admin_headers = {"X-Admin-Key": "dev-admin-key"}
        appointments = client.get("/api/v1/admin/appointments", headers=admin_headers).json()
        assert any(item["id"] == appointment["id"] and item["origin_channel"] == "voice" for item in appointments)
        sessions = client.get("/api/v1/admin/voice-sessions", headers=admin_headers).json()
        assert any(item["runtime_session_id"] == session_id and item["appointment_id"] == appointment["id"] for item in sessions)
