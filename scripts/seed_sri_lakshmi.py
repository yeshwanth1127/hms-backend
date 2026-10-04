#!/usr/bin/env python3
"""Load the Sri Lakshmi website roster and its booking times into the backend. Idempotent.

The catalogue JSON is exported from the website's src/data (doctors, departments, branches), so
the backend matches what patients browse. Times copy the website's booking calendar:
Sun 4 slots, Sat 6 slots, weekdays 6 slots alternating by even/odd date. The hospital has not
published real consultation hours; replace these with its confirmed schedule before go-live.

Run against a migrated database with APP_ENV other than development (development startup
re-seeds the fictional sample clinic):
    uv run --locked python scripts/seed_sri_lakshmi.py [--days 60]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Branch, Department, Doctor, ScheduleRule  # noqa: E402

CATALOGUE = Path(__file__).with_name("sri_lakshmi_catalogue.json")
SLOT_MINUTES = 30  # Closest website times are 45 minutes apart, so 30-minute visits never overlap.


def website_times(day: date) -> list[str]:
    """Mirror getSlotsForDate in the website's OriginalScheduleAppointmentPage."""
    if day.weekday() == 6:
        return ["10:00", "11:00", "11:45", "13:30"]
    if day.weekday() == 5:
        return ["09:30", "10:15", "11:00", "11:45", "13:30", "14:15"]
    if day.day % 2 == 0:
        return ["09:00", "10:30", "11:45", "14:30", "15:45", "16:30"]
    return ["09:15", "10:00", "11:30", "13:15", "14:45", "16:00"]


def upsert(db, model, slug, **fields):
    row = db.scalar(select(model).where(model.slug == slug))
    if not row:
        row = model(slug=slug, **fields)
        db.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=60, help="Days of availability from today.")
    days = parser.parse_args().days
    data = json.loads(CATALOGUE.read_text())

    with SessionLocal() as db:
        branches = {b["id"]: upsert(db, Branch, b["id"], name=b["name"], area=b["area"],
                                    address=b.get("address", ""), is_virtual=False)
                    for b in data["branches"]}
        departments = {d["id"]: upsert(db, Department, d["id"], name=d["name"],
                                       tagline=d.get("tagline", ""), description=d.get("description", ""))
                       for d in data["departments"]}
        db.flush()

        by_room = {b.name: b for b in branches.values()}
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        added = 0
        for d in data["doctors"]:
            branch = by_room[d["roomNumber"]]
            doctor = upsert(db, Doctor, d["id"], name=d["name"], title=d["title"], bio=d["bio"],
                            experience_years=d["experienceYears"], consultation_fee=d["consultationFee"],
                            accepts_virtual=d["acceptsVirtual"], image_url=d["image"], is_active=True)
            doctor.departments = [departments[d["departmentId"]]]
            doctor.branches = [branch]
            db.flush()
            existing = set(db.execute(select(ScheduleRule.schedule_date, ScheduleRule.starts_at_local)
                                      .where(ScheduleRule.doctor_id == doctor.id)).all())
            for offset in range(days):
                day = today + timedelta(days=offset)
                for text in website_times(day):
                    starts = time.fromisoformat(text)
                    if (day, starts) in existing:
                        continue
                    ends = (datetime.combine(day, starts) + timedelta(minutes=SLOT_MINUTES)).time()
                    # One rule per website time, valid on that date only.
                    db.add(ScheduleRule(doctor_id=doctor.id, branch_id=branch.id, consultation_type="in_person",
                                        schedule_date=day, weekday=day.weekday(), starts_at_local=starts,
                                        ends_at_local=ends, slot_minutes=SLOT_MINUTES,
                                        effective_from=day, effective_until=day))
                    added += 1
        db.commit()
        print(f"{len(branches)} branches, {len(departments)} departments, {len(data['doctors'])} doctors, "
              f"{added} new slots from {today} for {days} days")


if __name__ == "__main__":
    main()
