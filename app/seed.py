from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (Branch, Department, Doctor, Hospital, HospitalMembership, Patient,
                     ScheduleRule, User)
from .config import settings


DEPARTMENTS = [
    ("general-medicine", "Primary Care", "Everyday and preventive care"),
    ("cardiology", "Cardiology & Heart Health", "Comprehensive cardiovascular care"),
    ("metabolic", "Weight Management & Metabolic Health", "Evidence-based metabolic care"),
    ("orthopedics", "Orthopedics & Joint Care", "Joint, sports injury, and spine care"),
    ("dermatology", "Skin Care", "Clinical dermatology and skin wellness"),
    ("neurology", "Mental Health & Neurology", "Neurological and psychiatric care"),
    ("pediatrics", "Pediatrics & Child Health", "Care for children and adolescents"),
    ("ent", "Ear, Nose & Throat (ENT)", "ENT and head-neck care"),
    ("dental", "Dental & Oral Maxillofacial", "Dental and oral health"),
]

DOCTORS = [
    ("doc-1", "Dr. Vikram Rao", "Senior Consultant, Interventional Cardiology", "cardiology", 18, 1200, True),
    ("doc-2", "Dr. Ananya Sharma", "Consultant, Internal Medicine & Preventive Care", "general-medicine", 12, 800, True),
    ("doc-3", "Dr. Siddharth Mukherjee", "Consultant Orthopaedic & Joint Replacement Surgeon", "orthopedics", 14, 1000, False),
    ("doc-4", "Dr. Radhika Iyer", "Consultant, Obstetrics, Gynecology & Women's Health", "general-medicine", 11, 900, True),
    ("doc-5", "Dr. Meera Krishnan", "Consultant Endocrinologist", "metabolic", 10, 1000, True),
    ("doc-6", "Dr. Arjun Nair", "Consultant Dermatologist & Cutaneous Surgeon", "dermatology", 9, 900, True),
    ("doc-7", "Dr. Kavya Reddy", "Consultant Psychiatrist & Neurologist", "neurology", 13, 1200, True),
    ("doc-8", "Dr. Rohan Desai", "Consultant Paediatrician & Adolescent Medicine", "pediatrics", 15, 800, True),
    ("doc-9", "Dr. Priya Nair", "Senior Consultant, Ear, Nose & Throat", "ent", 14, 950, True),
    ("doc-10", "Dr. Rajesh Kulkarni", "Senior Consultant, Dental Surgery & Implantology", "dental", 16, 750, False),
]


def ensure_demo_doctor_accounts(db: Session, hospital: Hospital) -> None:
    """Give every seeded clinician a usable account in local demo environments."""
    from .auth import hash_password
    doctors = db.scalars(select(Doctor).where(Doctor.hospital_id == hospital.id)).all()
    for doctor in doctors:
        if doctor.user_id:
            continue
        email = f"doctor.{doctor.slug}@example.com"
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, display_name=doctor.name,
                        password_hash=hash_password("doctor-demo-password"))
            db.add(user)
            db.flush()
        membership = db.scalar(select(HospitalMembership).where(
            HospitalMembership.hospital_id == hospital.id,
            HospitalMembership.user_id == user.id,
            HospitalMembership.role == "doctor",
        ))
        if membership is None:
            db.add(HospitalMembership(hospital_id=hospital.id, user_id=user.id, role="doctor"))
        doctor.user_id = user.id


def seed_catalogue(db: Session) -> None:
    from .auth import hash_password
    hospital = db.scalar(select(Hospital).where(Hospital.slug == "exora-demo"))
    if db.scalar(select(Branch.id).limit(1)):
        if hospital:
            hospital.virtual_opd_enabled = True
            ensure_demo_doctor_accounts(db, hospital)
            db.commit()
        return
    if hospital is None:
        hospital = Hospital(slug="exora-demo", name="Exora Demo Hospital", virtual_opd_enabled=True)
        db.add(hospital)
        db.flush()
    admin = User(email=settings.bootstrap_admin_email.lower(), display_name="Exora Administrator",
                 password_hash=hash_password(settings.bootstrap_admin_password))
    patient_user = User(email="patient@example.com", display_name="Demo Patient",
                        password_hash=hash_password("patient-demo-password"))
    doctor_user = User(email="doctor@example.com", display_name="Dr. Vikram Rao",
                       password_hash=hash_password("doctor-demo-password"))
    db.add_all([admin, patient_user, doctor_user]); db.flush()
    db.add_all([
        HospitalMembership(hospital_id=hospital.id, user_id=admin.id, role="hospital_admin"),
        HospitalMembership(hospital_id=hospital.id, user_id=patient_user.id, role="patient"),
        HospitalMembership(hospital_id=hospital.id, user_id=doctor_user.id, role="doctor"),
    ])
    db.add(Patient(hospital_id=hospital.id, user_id=patient_user.id, name="Demo Patient",
                   phone="+919900000001", email=patient_user.email))
    branches = [
        Branch(hospital_id=hospital.id, slug="indiranagar", name="Indiranagar Flagship Clinic", area="Indiranagar"),
        Branch(hospital_id=hospital.id, slug="koramangala", name="Koramangala Care Center", area="Koramangala"),
        Branch(hospital_id=hospital.id, slug="whitefield", name="Whitefield Technology Hub", area="Whitefield"),
        Branch(hospital_id=hospital.id, slug="jayanagar", name="Jayanagar Specialty OPD", area="Jayanagar"),
        Branch(hospital_id=hospital.id, slug="virtual", name="Virtual Care (Telehealth)", area="Virtual Care", is_virtual=True),
    ]
    departments = [Department(hospital_id=hospital.id, slug=slug, name=name, tagline=tagline, description=tagline) for slug, name, tagline in DEPARTMENTS]
    db.add_all(branches + departments)
    db.flush()
    department_by_slug = {item.slug: item for item in departments}
    for slug, name, title, dept_slug, years, fee, virtual in DOCTORS:
        doctor = Doctor(slug=slug, name=name, title=title, bio=title, experience_years=years,
                        consultation_fee=fee, accepts_virtual=virtual,
                        hospital_id=hospital.id, user_id=doctor_user.id if slug == "doc-1" else None,
                        departments=[department_by_slug[dept_slug]],
                        branches=branches[:4] + ([branches[4]] if virtual else []))
        db.add(doctor)
        db.flush()
        for weekday in range(0, 6):
            effective_from = date(2026, 1, 1)
            schedule_date = effective_from + timedelta(
                days=(weekday - effective_from.weekday()) % 7)
            db.add(ScheduleRule(hospital_id=hospital.id, doctor_id=doctor.id, branch_id=branches[0].id, weekday=weekday,
                                starts_at_local=time(9), ends_at_local=time(17), slot_minutes=30,
                                consultation_type="in_person", schedule_date=schedule_date,
                                effective_from=effective_from))
    ensure_demo_doctor_accounts(db, hospital)
    db.commit()
