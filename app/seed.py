from datetime import date, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Branch, Department, Doctor, ScheduleRule


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


def seed_catalogue(db: Session) -> None:
    if db.scalar(select(Branch.id).limit(1)):
        return
    branches = [
        Branch(slug="indiranagar", name="Indiranagar Flagship Clinic", area="Indiranagar"),
        Branch(slug="koramangala", name="Koramangala Care Center", area="Koramangala"),
        Branch(slug="whitefield", name="Whitefield Technology Hub", area="Whitefield"),
        Branch(slug="jayanagar", name="Jayanagar Specialty OPD", area="Jayanagar"),
        Branch(slug="virtual", name="Virtual Care (Telehealth)", area="Virtual Care", is_virtual=True),
    ]
    departments = [Department(slug=slug, name=name, tagline=tagline, description=tagline) for slug, name, tagline in DEPARTMENTS]
    db.add_all(branches + departments)
    db.flush()
    department_by_slug = {item.slug: item for item in departments}
    for slug, name, title, dept_slug, years, fee, virtual in DOCTORS:
        doctor = Doctor(slug=slug, name=name, title=title, bio=title, experience_years=years,
                        consultation_fee=fee, accepts_virtual=virtual,
                        departments=[department_by_slug[dept_slug]], branches=branches[:4])
        db.add(doctor)
        db.flush()
        for weekday in range(0, 6):
            db.add(ScheduleRule(doctor_id=doctor.id, branch_id=branches[0].id, weekday=weekday,
                                starts_at_local=time(9), ends_at_local=time(17), slot_minutes=30,
                                consultation_type="in_person", effective_from=date(2026, 1, 1)))
    db.commit()

