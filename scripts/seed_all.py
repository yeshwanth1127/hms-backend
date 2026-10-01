#!/usr/bin/env python3
"""One-shot production seed: catalogue + specialty guides + doctor photos."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.seed import seed_all  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from app.models import Branch, Department, Doctor, MediaAsset, ScheduleRule  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        result = seed_all(db)
        summary = {
            "seeded": result,
            "totals": {
                "branches": db.scalar(select(func.count()).select_from(Branch)),
                "departments": db.scalar(select(func.count()).select_from(Department)),
                "doctors": db.scalar(select(func.count()).select_from(Doctor)),
                "schedules": db.scalar(select(func.count()).select_from(ScheduleRule)),
                "media_assets": db.scalar(select(func.count()).select_from(MediaAsset)),
                "departments_with_guides": db.scalar(
                    select(func.count()).select_from(Department).where(Department.guide_asset_id.is_not(None))
                ),
                "doctors_with_photos": db.scalar(
                    select(func.count()).select_from(Doctor).where(Doctor.photo_asset_id.is_not(None))
                ),
            },
        }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
