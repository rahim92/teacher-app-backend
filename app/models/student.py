from typing import Optional

from sqlmodel import Field

from app.models.common import NotebookQuality, SyncableModel


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
    """

    __tablename__ = "seat_assignments"

    teacher_id: str = Field(foreign_key="users.id", index=True)
    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    student_id: str = Field(foreign_key="students.id", index=True)
    seat_row: int
    seat_col: int


class NotebookCheck(SyncableModel, table=True):
    """A periodic check of a student's own notebooks (كراس الدروس /
    الأنشطة) -- how organized their writing/record-keeping is. Distinct from
    SessionEvent: this is a low-frequency spot check, not a per-tap moment.
    """

    __tablename__ = "notebook_checks"

    student_id: str = Field(foreign_key="students.id", index=True)
    teacher_id: str = Field(foreign_key="users.id", index=True)
    check_date: str
    quality: NotebookQuality
    note: Optional[str] = None
