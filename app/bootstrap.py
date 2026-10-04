"""One-time named administrator bootstrap. Run after migrations; rotate the bootstrap password."""
from sqlalchemy import select

from .auth import hash_password
from .config import settings
from .db import SessionLocal
from .models import Hospital, HospitalMembership, User


def main() -> None:
    with SessionLocal() as db:
        hospital = db.scalar(select(Hospital).where(Hospital.slug == settings.default_hospital_slug))
        if not hospital:
            raise SystemExit(f"Hospital {settings.default_hospital_slug!r} does not exist; run migrations first.")
        email = settings.bootstrap_admin_email.lower().strip()
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(email=email, display_name="Hospital Administrator",
                        password_hash=hash_password(settings.bootstrap_admin_password))
            db.add(user); db.flush()
        membership = db.scalar(select(HospitalMembership).where(
            HospitalMembership.hospital_id == hospital.id, HospitalMembership.user_id == user.id,
            HospitalMembership.role == "hospital_admin"))
        if not membership:
            db.add(HospitalMembership(hospital_id=hospital.id, user_id=user.id, role="hospital_admin"))
        db.commit()
        print(f"Administrator account ready for {email} at {hospital.slug}. Rotate the bootstrap password now.")


if __name__ == "__main__":
    main()
