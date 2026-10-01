from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Appointment, Reservation, Doctor, Branch
from sqlalchemy import select


def test_nurse_list_ist_date_search_and_pagination(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "admin_api_key", "test-nurse-desk-admin-key")
    with TestClient(app) as client:
        with SessionLocal() as db:
            doctor = db.scalars(select(Doctor)).first()
            branch = db.scalars(select(Branch)).first()
            for index, start in enumerate([datetime(2031, 1, 1, 18, 29, tzinfo=timezone.utc), datetime(2031, 1, 1, 18, 30, tzinfo=timezone.utc), datetime(2031, 1, 2, 18, 29, tzinfo=timezone.utc), datetime(2031, 1, 2, 18, 30, tzinfo=timezone.utc)]):
                reservation = Reservation(doctor_id=doctor.id, branch_id=branch.id, starts_at=start, ends_at=start + timedelta(minutes=1), consultation_type='in_person', status='confirmed', owner_key=f'nurse-test-{index}')
                db.add(reservation)
                db.flush()
                db.add(Appointment(reservation_id=reservation.id, confirmation_code=f'NURSE-{index}', patient_name='Nurse Search Patient', patient_phone='+919999999999', status='confirmed', origin_channel='web', idempotency_key=f'nurse-book-{index}'))
            db.commit()
            doctor_id, branch_id, doctor_name = doctor.id, branch.id, doctor.name
        headers = {'X-Admin-Key': 'test-nurse-desk-admin-key'}
        params = {'day': '2031-01-02', 'doctor_id': doctor_id, 'branch_id': branch_id, 'query': 'Nurse Search', 'limit': 1}
        first = client.get('/api/v1/admin/appointments', headers=headers, params=params)
        assert first.status_code == 200
        assert [row['confirmation_code'] for row in first.json()] == ['NURSE-1']
        second = client.get('/api/v1/admin/appointments', headers=headers, params={**params, 'offset': 1})
        assert [row['confirmation_code'] for row in second.json()] == ['NURSE-2']
        by_doctor = client.get('/api/v1/admin/appointments', headers=headers, params={**params, 'query': doctor_name, 'limit': 50})
        assert [row['confirmation_code'] for row in by_doctor.json()] == ['NURSE-1', 'NURSE-2']
