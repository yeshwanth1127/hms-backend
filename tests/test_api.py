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
        live = client.get("/api/health/live")
        ready = client.get("/api/health/ready")
        assert live.status_code == 200
        assert ready.status_code == 200
        assert ready.json() == {
            "ready": True, "service": "exora-hospital-backend", "api_version": "v1",
        }
        assert len(client.get("/api/v1/departments").json()) >= 8
        assert len(client.get("/api/v1/doctors").json()) == 10


def test_schedules_have_concrete_dates_and_accept_date_only_input():
    with TestClient(app) as client:
        headers = {"X-Admin-Key": "dev-admin-key"}
        schedules = client.get("/api/v1/admin/schedules", headers=headers)
        assert schedules.status_code == 200
        assert schedules.json()
        assert all(item["schedule_date"] for item in schedules.json())

        doctor, branch = catalogue(client)
        schedule_day = future_weekday(6)
        created = client.post("/api/v1/admin/schedules", headers=headers, json={
            "doctor_id": doctor["id"], "branch_id": branch["id"],
            "consultation_type": "in_person", "schedule_date": schedule_day.isoformat(),
            "starts_at_local": "18:00:00", "ends_at_local": "19:00:00",
            "slot_minutes": 30, "effective_until": schedule_day.isoformat(),
        })
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["schedule_date"] == schedule_day.isoformat()
        assert body["weekday"] == schedule_day.weekday()
        assert body["effective_from"] == schedule_day.isoformat()

        slots = client.get("/api/v1/availability", params={
            "doctor_id": doctor["id"], "branch_id": branch["id"],
            "start_date": schedule_day.isoformat(), "end_date": schedule_day.isoformat(),
        })
        assert slots.status_code == 200
        assert any(item["starts_at"].startswith(schedule_day.isoformat()) for item in slots.json()["slots"])


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
            "patient_email": "new.booking.patient@example.com", "reason": "Annual checkup",
            "origin_channel": "web", "idempotency_key": "booking-test-0001",
        }
        booked = client.post("/api/v1/appointments", json=booking_body)
        assert booked.status_code == 201
        appointment = booked.json()
        assert appointment["status"] == "confirmed"
        assert appointment["confirmation_code"].startswith("AVO-")
        assert appointment["patient_code"].startswith("EXO-P-")
        assert len(appointment["patient_access_code"]) == 8
        assert appointment["patient_account_created"] is True
        replay_booking = client.post("/api/v1/appointments", json=booking_body)
        assert replay_booking.json()["id"] == appointment["id"]
        assert replay_booking.json()["patient_access_code"] is None
        login = client.post("/api/v1/auth/login", json={
            "email": booking_body["patient_email"], "password": appointment["patient_access_code"],
        })
        assert login.status_code == 200
        assert login.json()["role"] == "patient"
        code_login = client.post("/api/v1/auth/patient-code-login", json={
            "patient_code": appointment["patient_code"],
            "access_code": appointment["patient_access_code"],
        })
        assert code_login.status_code == 200
        assert code_login.json()["patient_id"]

        hidden = client.get(f"/api/v1/appointments/{appointment['id']}", headers={"X-Owner-Key": "wrong"})
        assert hidden.status_code == 404
        cancelled = client.patch(
            f"/api/v1/appointments/{appointment['id']}/cancel",
            headers={"X-Owner-Key": "browser-session-1"},
            json={"actor_id": "patient-test", "reason": "Plans changed"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"


def test_every_seeded_doctor_has_a_demo_login():
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={
            "email": "doctor.doc-2@example.com", "password": "doctor-demo-password",
        })
        assert response.status_code == 200
        assert response.json()["role"] == "doctor"

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
        assert client.get("/api/v1/admin/analytics").status_code == 401
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
        assert [item["slug"] for item in doctor["branches"]] == ["indiranagar"]
        assert [item["slug"] for item in doctor["in_person_branches"]] == ["indiranagar"]
        assert doctor["virtual_branches"] == []
        assert doctor["accepts_virtual"] is False
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

        looked_up = client.get(
            "/api/v1/integrations/voice/appointments",
            headers=service_headers,
            params={"patient_phone": "+919888888888"},
        )
        assert looked_up.status_code == 200
        assert [item["id"] for item in looked_up.json()] == [appointment["id"]]
        assert looked_up.json()[0]["reservation"]["starts_at"].removesuffix("Z") == slot["starts_at"].removesuffix("Z")

        verified_lookup = client.get(
            "/api/v1/integrations/voice/appointments",
            headers=service_headers,
            params={
                "patient_phone": "+919888888888",
                "confirmation_code": appointment["confirmation_code"].lower(),
            },
        )
        assert verified_lookup.status_code == 200
        assert [item["id"] for item in verified_lookup.json()] == [appointment["id"]]

        assert client.get(
            "/api/v1/integrations/voice/appointments",
            headers=service_headers,
        ).status_code == 422
        assert client.get(
            "/api/v1/integrations/voice/appointments",
            params={"patient_phone": "+919888888888"},
        ).status_code == 422
        assert client.get(
            "/api/v1/integrations/voice/appointments",
            headers=service_headers,
            params={"patient_phone": "+919888888888", "confirmation_code": "WRONG-CODE"},
        ).json() == []

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


def test_voice_doctor_modes_come_from_schedules_not_profile_branches():
    with TestClient(app) as client:
        admin_headers = {"X-Admin-Key": "dev-admin-key"}
        service_headers = {"X-Service-Key": "dev-voice-service-key"}
        doctors = client.get("/api/v1/doctors").json()
        doctor = next(item for item in doctors if any(
            department["slug"] == "cardiology" for department in item["departments"]
        ))
        virtual_branch = next(
            item for item in client.get("/api/v1/branches").json()
            if item["slug"] == "virtual"
        )
        schedule_day = date.today() + timedelta(days=45)
        created = client.post("/api/v1/admin/schedules", headers=admin_headers, json={
            "doctor_id": doctor["id"], "branch_id": virtual_branch["id"],
            "consultation_type": "virtual", "schedule_date": schedule_day.isoformat(),
            "starts_at_local": "10:00:00", "ends_at_local": "11:00:00",
            "slot_minutes": 30, "effective_until": schedule_day.isoformat(),
        })
        assert created.status_code == 201, created.text
        try:
            voice_doctors = client.get(
                "/api/v1/integrations/voice/doctors", headers=service_headers,
                params={"department": "cardiology"},
            ).json()
            voice_doctor = next(item for item in voice_doctors if item["id"] == doctor["id"])
            assert [item["slug"] for item in voice_doctor["virtual_branches"]] == ["virtual"]
            assert voice_doctor["accepts_virtual"] is True
        finally:
            deleted = client.delete(
                f"/api/v1/admin/schedules/{created.json()['id']}", headers=admin_headers,
            )
            assert deleted.status_code == 204


def test_voice_catalogue_filters_are_forgiving_and_discoverable():
    with TestClient(app) as client:
        headers = {"X-Service-Key": "dev-voice-service-key"}

        all_doctors = client.get(
            "/api/v1/integrations/voice/doctors", headers=headers,
        ).json()
        cardiologists = client.get(
            "/api/v1/integrations/voice/doctors", headers=headers,
            params={"department": "cardiology"},
        ).json()
        assert cardiologists
        assert all(any(value["slug"] == "cardiology" for value in item["departments"])
                   for item in cardiologists)

        for natural_value in ("Heart", "heart doctor", "cardiolgy"):
            response = client.get(
                "/api/v1/integrations/voice/doctors", headers=headers,
                params={"department": natural_value},
            )
            assert response.status_code == 200
            assert [item["id"] for item in response.json()] == [item["id"] for item in cardiologists]

        primary_care = client.get(
            "/api/v1/integrations/voice/doctors", headers=headers,
            params={"department": "general medicine"},
        )
        assert primary_care.status_code == 200
        assert primary_care.json()
        assert all(any(value["slug"] == "general-medicine" for value in item["departments"])
                   for item in primary_care.json())

        for unknown in ("eye", "ophthalmology", "space medicine"):
            response = client.get(
                "/api/v1/integrations/voice/doctors", headers=headers,
                params={"department": unknown},
            )
            assert response.status_code == 200
            assert [item["id"] for item in response.json()] == [item["id"] for item in all_doctors]

        indiranagar = client.get(
            "/api/v1/integrations/voice/doctors", headers=headers,
            params={"branch": "the branch near INDIRANAGAR"},
        )
        assert indiranagar.status_code == 200
        assert indiranagar.json()
        assert all(any(branch["slug"] == "indiranagar" for branch in item["in_person_branches"])
                   for item in indiranagar.json())

        unknown_branch = client.get(
            "/api/v1/integrations/voice/doctors", headers=headers,
            params={"branch": "a location this hospital does not have"},
        )
        assert unknown_branch.status_code == 200
        assert [item["id"] for item in unknown_branch.json()] == [item["id"] for item in all_doctors]

        departments = client.get(
            "/api/v1/integrations/voice/meta/departments", headers=headers,
        )
        assert departments.status_code == 200
        cardiology = next(item for item in departments.json() if item["slug"] == "cardiology")
        assert cardiology["name"] == "Cardiology & Heart Health"
        assert "heart" in cardiology["synonyms"]

        branches = client.get(
            "/api/v1/integrations/voice/meta/branches", headers=headers,
        )
        assert branches.status_code == 200
        branch = next(item for item in branches.json() if item["slug"] == "indiranagar")
        assert branch["area"] == "Indiranagar"
        assert "Indiranagar" in branch["synonyms"]

        assert client.get("/api/v1/integrations/voice/meta/departments").status_code == 422
