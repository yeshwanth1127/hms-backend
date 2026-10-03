"""Every state-changing request leaves exactly one explainable audit record."""
import logging
import re

from sqlalchemy import func, select

from app import audit
from app.main import app
from app.models import AuditEvent
from tests.test_staff_auth import PASSWORD, sign_in, staff  # noqa: F401  (fixture)

WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def mutating_routes(routes=None):
    for route in app.routes if routes is None else routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from mutating_routes(nested.routes)
        elif getattr(route, "endpoint", None) is not None:
            for method in sorted((getattr(route, "methods", None) or set()) & WRITES):
                yield method, route.path


def events(factory):
    with factory() as db:
        return db.scalars(select(AuditEvent).order_by(AuditEvent.created_at)).all()


def test_every_mutating_route_writes_exactly_one_record(staff):
    client, factory = staff
    routes = sorted(set(mutating_routes()))
    assert len(routes) > 60
    for method, template in routes:
        path = re.sub(r"\{[^}]+\}", "audit-probe", template)
        with factory() as db:
            before = db.scalar(select(func.count()).select_from(AuditEvent))
        response = client.request(method, path, json={})
        with factory() as db:
            new = db.scalars(select(AuditEvent).offset(before)).all()
        assert [e.action for e in new] == [f"{method} {template}"], (method, template, response.status_code)
        assert new[0].status_code == response.status_code


def test_sign_in_records_person_and_never_the_password(staff):
    client, factory = staff
    assert client.post("/api/v1/staff/login", json={"username": "reception", "password": "wrong-password-123"}).status_code == 401
    sign_in(client, "reception")
    failed, ok = events(factory)[-2:]
    assert (failed.actor_type, failed.status_code, failed.change) == ("anonymous", 401, {"username": "reception"})
    assert (ok.actor_type, ok.actor_label, ok.status_code) == ("staff", "reception (@reception)", 200)
    assert all(PASSWORD not in str(e.change) and "wrong-password" not in str(e.change) for e in events(factory))


def test_staff_changes_are_named_and_only_admins_read_the_log(staff):
    client, factory = staff
    headers = sign_in(client, "reception")
    assert client.put("/api/v1/staff/modules/whatsapp", headers=headers, json={"enabled": False}).status_code == 403
    denied = events(factory)[-1]
    assert (denied.actor_label, denied.status_code, denied.targets) == ("reception (@reception)", 403, {"key": "whatsapp"})
    assert client.get("/api/v1/staff/audit").status_code == 403
    assert client.get("/api/v1/staff/audit.csv").status_code == 403

    sign_in(client, "clinic.admin")
    log = client.get("/api/v1/staff/audit", params={"actor": "reception", "outcome": "rejected"}).json()
    assert [item["action"] for item in log["items"]] == ["PUT /api/v1/staff/modules/{key}"]
    assert client.get("/api/v1/staff/audit", params={"target": "whatsapp"}).json()["items"][0]["targets"] == {"key": "whatsapp"}
    exported = client.get("/api/v1/staff/audit.csv")
    assert exported.status_code == 200 and "reception (@reception)" in exported.text


def test_services_are_labelled(staff):
    client, factory = staff
    client.post("/api/v1/integrations/whatsapp/inbound", headers={"X-Service-Key": "test-machine-service-key"}, json={})
    assert (events(factory)[-1].actor_type, events(factory)[-1].actor_id) == ("service", "whatsapp")


def test_audit_store_failure_does_not_fail_the_action(staff, monkeypatch, caplog):
    client, factory = staff
    monkeypatch.setattr(audit, "AuditEvent", None)  # any write now raises
    with caplog.at_level(logging.ERROR, logger="hms.audit"):
        assert client.post("/api/v1/staff/login", json={"username": "clinic.admin", "password": PASSWORD}).status_code == 200
    assert "AUDIT_WRITE_FAILED" in caplog.text and "clinic.admin" in caplog.text and PASSWORD not in caplog.text


def test_owner_decides_what_staff_change_and_fees_stay_with_admins(staff):
    from app.models import Doctor
    client, factory = staff
    with factory() as db:
        db.add(Doctor(id="doc-audit", slug="doc-audit", name="Dr Audit", title="GP", experience_years=5, consultation_fee=800))
        db.commit()
    headers = sign_in(client, "reception")
    assert client.get("/api/v1/staff/permissions").json()["allowed"]["doctors.manage"] is True
    assert client.patch("/api/v1/admin/doctors/doc-audit", headers=headers, json={"accepts_virtual": True}).status_code == 200
    fee = client.patch("/api/v1/admin/doctors/doc-audit", headers=headers, json={"consultation_fee": 1})
    assert fee.status_code == 403 and fee.json()["error"]["code"] == "FEE_ADMIN_ONLY"
    assert client.put("/api/v1/staff/permissions/doctors.manage", headers=headers, json={"allowed": False}).status_code == 403

    admin = sign_in(client, "clinic.admin")
    assert client.put("/api/v1/staff/permissions/doctors.manage", headers=admin, json={"allowed": False}).status_code == 200
    assert events(factory)[-1].change == {"allowed": {"from": True, "to": False}}
    assert client.patch("/api/v1/admin/doctors/doc-audit", headers=admin, json={"consultation_fee": 900}).status_code == 200
    assert events(factory)[-1].change == {"consultation_fee": {"from": 800, "to": 900}}
    assert events(factory)[-1].actor_label == "clinic.admin (@clinic.admin)"

    headers = sign_in(client, "reception")
    denied = client.patch("/api/v1/admin/doctors/doc-audit", headers=headers, json={"accepts_virtual": False})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "STAFF_PERMISSION_DENIED"
    assert client.get("/api/v1/staff/permissions").json()["allowed"]["doctors.manage"] is False
