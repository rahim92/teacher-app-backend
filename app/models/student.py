from typing import Optional

from sqlmodel import Field

from app.models.common import NotebookQuality, SpecialNeedCategory, SpecialNeedVisibility, SyncableModel


class Student(SyncableModel, table=True):
    __tablename__ = "students"

    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    first_name: str
    last_name: str
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    medical_notes: Optional[str] = None  # sensitive: encrypt at rest on-device
    general_notes: Optional[str] = None


class SeatAssignment(SyncableModel, table=True):
    """Seating position is per-teacher, not a fixed student attribute --
    different subject teachers commonly arrange the same classroom differently.

    `term_id` is optional (None = "the standing arrangement") so a teacher
    who never bothers with per-term seating still gets simple single-map
    behaviour, while one who rotates seats each term (a documented real
    practice -- front-row rotation, vision/hearing needs, behaviour-based
    regrouping) can hold one map per term without them overwriting each
    other. `reason` records *why*, mostly to justify the arrangement later
    (a recurring friction point -- see docs/data_model.md).
    """

    __tablename__ = "seat_assignments"

    teacher_id: str = Field(foreign_key="users.id", index=True)
    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    student_id: str = Field(foreign_key="students.id", index=True)
    term_id: Optional[str] = Field(default=None, foreign_key="terms.id", index=True)
    seat_row: int
    seat_col: int
    # Which of the up-to-MAX_STUDENTS_PER_DESK spots within the desk this is
    # (0 or 1 today) -- without this, two students sharing one desk have no
    # persisted left/right identity, so swapping their places at the SAME
    # desk had nothing to actually exchange. Server-assigned, never accepted
    # from the client -- see upsert_seat_assignment/swap_seat_assignments.
    seat_slot: int = Field(default=0)
    reason: Optional[str] = None


class NotebookCheck(SyncableModel, table=True):
    """A periodic check of a student's own notebooks (كراس الدروس /
    الأنشطة) -- how organized their writing/record-keeping is. Distinct from
    SessionEvent: this is a low-frequency spot check, not a per-tap moment.

    Two independent dimensions per check, matching the official المراقبة
    المستمرة rubric's two separate notebook-related columns (see
    docs/data_model.md): `quality` is "تنظيم الكراس" (organization/tidiness,
    under الانضباط والمواظبة), `writing_quality` is "الكتابة (السبورة
    والكراس)" (how completely the board work/exercises were copied, under
    المردود داخل القسم) -- a well-organized notebook and a thoroughly
    written one are not the same thing, so a check rates both, not one.
    `writing_quality` is optional/nullable so a check made before this field
    existed doesn't need backfilling; see database.py's additive-column
    migration and routers/behavior.py for how a missing value is handled.
    """

    __tablename__ = "notebook_checks"

    student_id: str = Field(foreign_key="students.id", index=True)
    teacher_id: str = Field(foreign_key="users.id", index=True)
    check_date: str
    quality: NotebookQuality
    writing_quality: Optional[NotebookQuality] = Field(default=None)
    note: Optional[str] = None


class StudentSpecialNeed(SyncableModel, table=True):
    """A student condition the teacher must be considerate of -- chronic
    illness, sensory/physical/intellectual disability, or a specific
    learning difficulty. Deliberately NOT folded into Student.medical_notes
    free text: `visibility` is what lets the app share the *actionable*
    part (accommodation_needed) with every teacher of the classroom while
    keeping the fuller clinical picture restricted to the homeroom teacher
    and admin by default -- see docs/data_model.md and the router's
    permission check for the exact rule.
    """

    __tablename__ = "student_special_needs"

    student_id: str = Field(foreign_key="students.id", index=True)
    category: SpecialNeedCategory
    description: Optional[str] = None
    accommodation_needed: Optional[str] = None  # e.g. "يحتاج مقعداً أمامياً"
    emergency_protocol: Optional[str] = None  # e.g. "يحمل جهاز استنشاق للربو"
    visibility: SpecialNeedVisibility = Field(default=SpecialNeedVisibility.homeroom_only)
    created_by: str = Field(foreign_key="users.id")
