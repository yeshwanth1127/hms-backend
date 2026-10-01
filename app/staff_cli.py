"""Operator-only account provisioning/recovery. Never creates default credentials."""
import argparse
import getpass
from sqlalchemy import delete, select
from .db import SessionLocal
from .models import StaffUser, StaffSession
from .staff_auth import password_hash, username


def main():
    parser = argparse.ArgumentParser(description="Create a staff account or reset its password; run migrations first.")
    parser.add_argument("command", choices=("create", "reset", "disable"))
    parser.add_argument("--username", required=True)
    parser.add_argument("--name", default="Clinic administrator")
    parser.add_argument("--role", choices=("admin", "staff", "growth_manager"), default="admin")
    args = parser.parse_args()
    name = username(args.username)
    with SessionLocal() as db:
        user = db.scalar(select(StaffUser).where(StaffUser.username == name))
        if args.command == "create" and user:
            parser.error("Username already exists; use reset for recovery.")
        if args.command != "create" and not user:
            parser.error("Staff account does not exist.")
        if args.command == "disable":
            user.is_active = False
        else:
            password = getpass.getpass("New password (12–128 characters): ")
            if password != getpass.getpass("Confirm password: "):
                parser.error("Passwords do not match.")
            encoded = password_hash(password)
            if user:
                user.password_hash = encoded
            else:
                if not 2 <= len(args.name.strip()) <= 40:
                    parser.error("Name must have 2–40 characters.")
                user = StaffUser(username=name, display_name=args.name.strip(), role=args.role, password_hash=encoded)
                db.add(user)
        if user.id:
            db.execute(delete(StaffSession).where(StaffSession.user_id == user.id))
        db.commit()
    print(f"Staff account {name}: {args.command} completed.")


if __name__ == "__main__":
    main()
