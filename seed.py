"""Seeds a minimal but coherent dataset so the app is usable immediately after
a fresh install: one subject, one academic year, and a small curriculum tree
(sequence -> unit -> skill) for grade 1AM math, matching the reference-bank
design in docs/data_model.md.

Run with: python seed.py
"""
from sqlmodel import Session, select

from app.database import engine, init_db
from app.models.common import GradeLevel, UnitType
from app.models.curriculum import CurriculumUnit
from app.models.identity import AcademicYear, Subject


def main() -> None:
    init_db()
    with Session(engine) as session:
        subject = session.exec(select(Subject).where(Subject.name == "الرياضيات")).first()
        if not subject:
            subject = Subject(name="الرياضيات", code="MATH")
            session.add(subject)
            session.commit()
            session.refresh(subject)

        year = session.exec(select(AcademicYear).where(AcademicYear.label == "2025-2026")).first()
        if not year:
            year = AcademicYear(label="2025-2026", start_date="2025-09-01", end_date="2026-06-30")
            session.add(year)
            session.commit()
            session.refresh(year)

        existing_tree = session.exec(
            select(CurriculumUnit).where(
                CurriculumUnit.subject_id == subject.id,
                CurriculumUnit.grade_level == GradeLevel.am1,
            )
        ).first()
        if existing_tree:
            print("Seed data already present, skipping curriculum tree.")
            return

        sequence = CurriculumUnit(
            subject_id=subject.id,
            grade_level=GradeLevel.am1,
            title="المقطع 1: الأعداد الطبيعية",
            unit_type=UnitType.sequence,
            order_index=1,
            year_version="2025-2026",
        )
        session.add(sequence)
        session.commit()
        session.refresh(sequence)

        unit = CurriculumUnit(
            subject_id=subject.id,
            grade_level=GradeLevel.am1,
            parent_unit_id=sequence.id,
            title="الوحدة 1.1: كتابة وقراءة الأعداد",
            unit_type=UnitType.unit,
            order_index=1,
            year_version="2025-2026",
        )
        session.add(unit)
        session.commit()
        session.refresh(unit)

        skill = CurriculumUnit(
            subject_id=subject.id,
            grade_level=GradeLevel.am1,
            parent_unit_id=unit.id,
            title="يقارن ويرتب الأعداد الطبيعية",
            unit_type=UnitType.skill,
            order_index=1,
            year_version="2025-2026",
        )
        session.add(skill)
        session.commit()
        print("Seeded: subject, academic year, and a 3-level curriculum tree.")


if __name__ == "__main__":
    main()
