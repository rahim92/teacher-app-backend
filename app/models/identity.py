from typing import Optional

from sqlmodel import Field, UniqueConstraint

from app.models.common import GradeLevel, SyncableModel, UserRole


class User(SyncableModel, table=True):
    """A teacher (or, in a future version, an admin/inspector)."""

    __tablename__ = "users"

    full_name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    role: UserRole = Field(default=UserRole.teacher)
    default_subject_id: Optional[str] = Field(default=None, foreign_key="subjects.id")


class School(SyncableModel, table=True):
    __tablename__ = "schools"

    name: str
    address: Optional[str] = None


class AcademicYear(SyncableModel, table=True):
    __tablename__ = "academic_years"

    label: str  # e.g. "2025-2026"
    start_date: str  # ISO date; kept as string to stay timezone/locale agnostic
    end_date: str


class Term(SyncableModel, table=True):
    """A trimester/semester within an academic year -- council reports and
    grade averages are always computed for one term, never the whole year.
    """

    __tablename__ = "terms"

    academic_year_id: str = Field(foreign_key="academic_years.id", index=True)
    label: str  # e.g. "الفصل الأول"
    start_date: str
    end_date: str
    order_index: int = Field(default=0)


class Subject(SyncableModel, table=True):
    __tablename__ = "subjects"

    name: str  # e.g. "الرياضيات"
    code: Optional[str] = None
    # The subject's own official weight when combining every subject's term
    # average into one overall average (e.g. math=4, PE=1) -- distinct from
    # Assessment.coefficient, which only weighs tests *within* one subject.
    coefficient: float = Field(default=1.0)


class Classroom(SyncableModel, table=True):
    """The physical classroom (a group of students). `teacher_id` is who
    created it in this app (kept for MVP's single-teacher filtering);
    `homeroom_teacher_id` is the "أستاذ رئيسي" -- a distinct, optional role a
    teacher holds for AT MOST ONE classroom per academic year (enforced by
    the unique constraint below). Which teacher teaches which SUBJECT in
    this classroom is a separate many-to-many concern -- see
    TeacherClassroomAssignment.
    """

    __tablename__ = "classrooms"
    __table_args__ = (
        # A plain UNIQUE constraint treats every NULL as distinct (both in
        # SQLite and PostgreSQL), so classrooms with no homeroom teacher set
        # never collide with each other -- only two real assignments of the
        # same teacher in the same year would.
        UniqueConstraint("homeroom_teacher_id", "academic_year_id", name="uq_one_homeroom_per_teacher_per_year"),
    )

    teacher_id: str = Field(foreign_key="users.id", index=True)
    homeroom_teacher_id: Optional[str] = Field(default=None, foreign_key="users.id", index=True)
    school_id: Optional[str] = Field(default=None, foreign_key="schools.id")
    academic_year_id: str = Field(foreign_key="academic_years.id")
    name: str  # e.g. "3AM - 2"
    grade_level: GradeLevel


class TeacherClassroomAssignment(SyncableModel, table=True):
    """Which teacher teaches which subject in which classroom, this year.
    A teacher commonly holds many of these (they teach several classrooms);
    a classroom commonly has one per subject taught in it. This is what a
    council report joins across to find every subject teacher for a class.
    """

    __tablename__ = "teacher_classroom_assignments"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id", "classroom_id", "subject_id", "academic_year_id", name="uq_teacher_classroom_subject_year"
        ),
    )

    teacher_id: str = Field(foreign_key="users.id", index=True)
    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    subject_id: str = Field(foreign_key="subjects.id")
    academic_year_id: str = Field(foreign_key="academic_years.id")
