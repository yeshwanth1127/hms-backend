"""Catalogue + media seed for Avocado Health.

Safe to re-run: skips existing rows by slug / already-attached assets.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import date, time, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .media import media_path
from .models import Branch, Department, Doctor, MediaAsset, ScheduleRule


DEPARTMENTS = [
    (
        "general-medicine",
        "Primary Care",
        "Everyday and preventive care",
        "Comprehensive primary care for fever, infections, lifestyle counselling, "
        "chronic disease follow-up, and annual health checks across Avocado Health clinics.",
    ),
    (
        "cardiology",
        "Cardiology & Heart Health",
        "Comprehensive cardiovascular care",
        "Evaluation and management of chest pain, hypertension, arrhythmias, "
        "heart-failure risk, and interventional cardiology referrals.",
    ),
    (
        "metabolic",
        "Weight Management & Metabolic Health",
        "Evidence-based metabolic care",
        "Diabetes, thyroid, and weight-management programmes with nutrition and "
        "endocrine follow-up tailored to each patient.",
    ),
    (
        "orthopedics",
        "Orthopedics & Joint Care",
        "Joint, sports injury, and spine care",
        "Sports injuries, joint pain, fracture follow-up, and pre/post joint-replacement counselling.",
    ),
    (
        "dermatology",
        "Skin Care",
        "Clinical dermatology and skin wellness",
        "Acne, eczema, pigmentary disorders, mole checks, and minor cutaneous procedures.",
    ),
    (
        "neurology",
        "Mental Health & Neurology",
        "Neurological and psychiatric care",
        "Headache, seizure evaluation, sleep concerns, anxiety, and depression support "
        "with coordinated neurology and psychiatry.",
    ),
    (
        "pediatrics",
        "Pediatrics & Child Health",
        "Care for children and adolescents",
        "Well-child visits, immunisation counselling, growth tracking, and adolescent medicine.",
    ),
    (
        "ent",
        "Ear, Nose & Throat (ENT)",
        "ENT and head-neck care",
        "Sinusitis, hearing concerns, tonsillitis, vertigo, and common head-and-neck complaints.",
    ),
    (
        "dental",
        "Dental & Oral Maxillofacial",
        "Dental and oral health",
        "Preventive dentistry, restorative care, implants, and oral-surgery consultations.",
    ),
]

DOCTORS = [
    ("doc-1", "Dr. Vikram Rao", "Senior Consultant, Interventional Cardiology", "cardiology", 18, 1200, True,
     "Interventional cardiologist focused on chest-pain pathways, hypertension clinics, "
     "and clear next-step counselling for patients and families."),
    ("doc-2", "Dr. Ananya Sharma", "Consultant, Internal Medicine & Preventive Care", "general-medicine", 12, 800, True,
     "Internal medicine physician for fever workups, lifestyle disease follow-up, "
     "and preventive health packages."),
    ("doc-3", "Dr. Siddharth Mukherjee", "Consultant Orthopaedic & Joint Replacement Surgeon", "orthopedics", 14, 1000, False,
     "Orthopaedic surgeon for sports injuries, knee/hip pain, and joint-replacement counselling."),
    ("doc-4", "Dr. Radhika Iyer", "Consultant, Obstetrics, Gynecology & Women's Health", "general-medicine", 11, 900, True,
     "Women's health consultations covering menstrual concerns, preventive screening, "
     "and coordinated specialty referrals."),
    ("doc-5", "Dr. Meera Krishnan", "Consultant Endocrinologist", "metabolic", 10, 1000, True,
     "Endocrinology for diabetes, thyroid disorders, and structured weight-management programmes."),
    ("doc-6", "Dr. Arjun Nair", "Consultant Dermatologist & Cutaneous Surgeon", "dermatology", 9, 900, True,
     "Clinical dermatology for acne, eczema, pigment concerns, and minor skin procedures."),
    ("doc-7", "Dr. Kavya Reddy", "Consultant Psychiatrist & Neurologist", "neurology", 13, 1200, True,
     "Integrated mental-health and neurology care for headache, sleep, anxiety, and mood concerns."),
    ("doc-8", "Dr. Rohan Desai", "Consultant Paediatrician & Adolescent Medicine", "pediatrics", 15, 800, True,
     "Paediatric and adolescent care including growth reviews, fever, and parental guidance."),
    ("doc-9", "Dr. Priya Nair", "Senior Consultant, Ear, Nose & Throat", "ent", 14, 950, True,
     "ENT consultant for sinus, ear, throat, and balance-related complaints."),
    ("doc-10", "Dr. Rajesh Kulkarni", "Senior Consultant, Dental Surgery & Implantology", "dental", 16, 750, False,
     "Dental surgery and implantology with emphasis on restorative and preventive oral care."),
]

CLINIC_INFO = {
    "brand": "Avocado Health",
    "tagline": "Multispecialty care across Bengaluru, plus virtual consults.",
    "hours": "OPD: Mon–Sat 09:00–17:00 IST · Virtual: Mon–Fri 14:00–18:00 IST",
    "support": "Book via website, voice assistant, or WhatsApp. Bring prior reports to the visit.",
    "note": "Illustrative clinic content for platform testing. Replace with approved clinic copy before go-live.",
}

# Accent colours for placeholder doctor portraits (RGB).
PORTRAIT_COLORS = [
    (46, 125, 90),
    (56, 102, 140),
    (140, 84, 56),
    (90, 70, 130),
    (70, 120, 110),
    (130, 70, 90),
    (80, 100, 70),
    (100, 80, 60),
    (60, 90, 120),
    (120, 95, 55),
]


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_guide_pdf(department_name: str, tagline: str, description: str) -> bytes:
    """Minimal single-page PDF specialty guide (no external PDF libs required)."""
    lines = [
        CLINIC_INFO["brand"],
        department_name,
        tagline,
        "",
        "About this specialty",
        description,
        "",
        "Clinic hours",
        CLINIC_INFO["hours"],
        "",
        "How to book",
        CLINIC_INFO["support"],
        "",
        CLINIC_INFO["note"],
    ]

    content_cmds: list[str] = ["BT", "/F1 11 Tf", "50 760 Td", "16 TL"]
    for i, raw in enumerate(lines):
        text = " ".join(raw.split())
        if i == 0:
            content_cmds += ["/F1 20 Tf", f"({_pdf_escape(text)}) Tj", "T*", "/F1 11 Tf"]
            continue
        if i == 1:
            content_cmds += ["/F1 16 Tf", f"({_pdf_escape(text)}) Tj", "T*", "/F1 11 Tf"]
            continue
        if not text:
            content_cmds.append("T*")
            continue
        while text:
            chunk, text = text[:90], text[90:]
            content_cmds.append(f"({_pdf_escape(chunk)}) Tj")
            content_cmds.append("T*")
    content_cmds.append("ET")
    stream = "\n".join(content_cmds).encode("latin-1", errors="replace")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def _store_bytes(db: Session, *, kind: str, filename: str, mime: str, data: bytes) -> MediaAsset:
    storage_name = uuid.uuid4().hex
    path = media_path(storage_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    asset = MediaAsset(
        kind=kind,
        original_name=filename[:255],
        mime_type=mime,
        storage_name=storage_name,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    db.add(asset)
    db.flush()
    return asset


def _portrait_png(name: str, color: tuple[int, int, int]) -> bytes:
    size = 512
    image = Image.new("RGB", (size, size), color)
    draw = ImageDraw.Draw(image)
    # Soft circle vignette
    draw.ellipse((36, 36, size - 36, size - 36), fill=tuple(min(255, c + 28) for c in color))
    initials = "".join(part[0] for part in name.replace("Dr.", "").split() if part)[:2].upper() or "AH"
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 140)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), initials, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 10), initials, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _add_schedule(
    db: Session,
    *,
    doctor_id: str,
    branch_id: str,
    weekdays: range | list[int],
    starts: time,
    ends: time,
    consultation_type: str,
    slot_minutes: int = 30,
    effective_from: date | None = None,
) -> int:
    effective_from = effective_from or date(2026, 1, 1)
    created = 0
    for weekday in weekdays:
        exists = db.scalar(
            select(ScheduleRule.id).where(
                ScheduleRule.doctor_id == doctor_id,
                ScheduleRule.branch_id == branch_id,
                ScheduleRule.weekday == weekday,
                ScheduleRule.consultation_type == consultation_type,
                ScheduleRule.starts_at_local == starts,
                ScheduleRule.ends_at_local == ends,
                ScheduleRule.is_active.is_(True),
            ).limit(1)
        )
        if exists:
            continue
        schedule_date = effective_from + timedelta(days=(weekday - effective_from.weekday()) % 7)
        db.add(
            ScheduleRule(
                doctor_id=doctor_id,
                branch_id=branch_id,
                weekday=weekday,
                starts_at_local=starts,
                ends_at_local=ends,
                slot_minutes=slot_minutes,
                consultation_type=consultation_type,
                schedule_date=schedule_date,
                effective_from=effective_from,
            )
        )
        created += 1
    return created


def seed_catalogue(db: Session) -> dict[str, int]:
    """Seed branches, departments, doctors, and baseline schedules. Idempotent."""
    stats = {"branches": 0, "departments": 0, "doctors": 0, "schedules": 0}

    branch_specs = [
        ("indiranagar", "Indiranagar Flagship Clinic", "Indiranagar", False),
        ("koramangala", "Koramangala Care Center", "Koramangala", False),
        ("whitefield", "Whitefield Technology Hub", "Whitefield", False),
        ("jayanagar", "Jayanagar Specialty OPD", "Jayanagar", False),
        ("virtual", "Virtual Care (Telehealth)", "Virtual Care", True),
    ]
    branches: list[Branch] = []
    for slug, name, area, is_virtual in branch_specs:
        existing = db.scalar(select(Branch).where(Branch.slug == slug))
        if existing:
            branches.append(existing)
            continue
        branch = Branch(slug=slug, name=name, area=area, is_virtual=is_virtual)
        db.add(branch)
        branches.append(branch)
        stats["branches"] += 1
    db.flush()
    branch_by_slug = {b.slug: b for b in branches}
    physical = [branch_by_slug[s] for s in ("indiranagar", "koramangala", "whitefield", "jayanagar")]

    departments: list[Department] = []
    for slug, name, tagline, description in DEPARTMENTS:
        existing = db.scalar(select(Department).where(Department.slug == slug))
        if existing:
            if not existing.description or existing.description == existing.tagline:
                existing.description = description
            if not existing.tagline:
                existing.tagline = tagline
            departments.append(existing)
            continue
        dept = Department(slug=slug, name=name, tagline=tagline, description=description)
        db.add(dept)
        departments.append(dept)
        stats["departments"] += 1
    db.flush()
    department_by_slug = {d.slug: d for d in departments}

    for index, (slug, name, title, dept_slug, years, fee, virtual, bio) in enumerate(DOCTORS):
        existing = db.scalar(select(Doctor).where(Doctor.slug == slug))
        if existing:
            if not existing.bio or existing.bio == existing.title:
                existing.bio = bio
            doctor = existing
        else:
            doctor = Doctor(
                slug=slug,
                name=name,
                title=title,
                bio=bio,
                experience_years=years,
                consultation_fee=fee,
                accepts_virtual=virtual,
                departments=[department_by_slug[dept_slug]],
                branches=physical,
            )
            db.add(doctor)
            db.flush()
            stats["doctors"] += 1

        # Primary OPD: Indiranagar Mon–Sat 09:00–17:00
        stats["schedules"] += _add_schedule(
            db,
            doctor_id=doctor.id,
            branch_id=branch_by_slug["indiranagar"].id,
            weekdays=range(0, 6),
            starts=time(9),
            ends=time(17),
            consultation_type="in_person",
        )
        # Second physical clinic half-day for coverage variety
        alt = physical[(index % (len(physical) - 1)) + 1]  # skip indiranagar rotation
        stats["schedules"] += _add_schedule(
            db,
            doctor_id=doctor.id,
            branch_id=alt.id,
            weekdays=[1, 3],  # Tue / Thu
            starts=time(10),
            ends=time(13),
            consultation_type="in_person",
        )
        if doctor.accepts_virtual:
            stats["schedules"] += _add_schedule(
                db,
                doctor_id=doctor.id,
                branch_id=branch_by_slug["virtual"].id,
                weekdays=range(0, 5),
                starts=time(14),
                ends=time(18),
                consultation_type="virtual",
            )

    db.commit()
    return stats


def seed_media_assets(db: Session) -> dict[str, int]:
    """Attach specialty PDF guides and doctor portrait PNGs when missing."""
    Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
    stats = {"guides": 0, "photos": 0}

    departments = db.scalars(select(Department).order_by(Department.name)).all()
    for dept in departments:
        if dept.guide_asset_id:
            continue
        pdf = _build_guide_pdf(dept.name, dept.tagline, dept.description or dept.tagline)
        # Validate with the same PDF sniff the API uses.
        if not pdf.startswith(b"%PDF-"):
            raise RuntimeError(f"Failed to build PDF for {dept.slug}")
        asset = _store_bytes(
            db,
            kind="guide",
            filename=f"avocado-{dept.slug}-guide.pdf",
            mime="application/pdf",
            data=pdf,
        )
        dept.guide_asset_id = asset.id
        stats["guides"] += 1

    doctors = db.scalars(select(Doctor).order_by(Doctor.name)).unique().all()
    for index, doctor in enumerate(doctors):
        if doctor.photo_asset_id:
            continue
        color = PORTRAIT_COLORS[index % len(PORTRAIT_COLORS)]
        png = _portrait_png(doctor.name, color)
        asset = _store_bytes(
            db,
            kind="photo",
            filename=f"{doctor.slug}.png",
            mime="image/png",
            data=png,
        )
        doctor.photo_asset_id = asset.id
        doctor.image_url = f"/api/v1/integrations/whatsapp/assets/{asset.id}"
        stats["photos"] += 1

    db.commit()
    return stats


def seed_all(db: Session) -> dict[str, dict[str, int]]:
    catalogue = seed_catalogue(db)
    media = seed_media_assets(db)
    return {"catalogue": catalogue, "media": media}
