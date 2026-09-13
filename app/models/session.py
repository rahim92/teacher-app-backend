from typing import Optional

from sqlmodel import Field

from app.models.common import LessonLogType, SessionEventType, SessionStatus, SyncableModel


class ClassSession(SyncableModel, table=True):
    """One lesson period. Opened at the start of class, closed at the end --
    closing it is what prompts the teacher to log the LessonLog entry.
    """

    __tablename__ = "class_sessions"

    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    teacher_id: str = Field(foreign_key="users.id", index=True)
    subject_id: str = Field(foreign_key="subjects.id")
    date: str  # ISO date
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: SessionStatus = Field(default=SessionStatus.open)


class SessionEvent(SyncableModel, table=True):
    """A single quick-tap event: attendance, tardiness, behavior, homework,
    participation. This one table powers the whole 'continuous monitoring
    notebook' -- the per-student and per-classroom ledgers are just
    read/aggregation views over this table, not separate storage.
    """

    __tablename__ = "session_events"

    session_id: str = Field(foreign_key="class_sessions.id", index=True)
    student_id: str = Field(foreign_key="students.id", index=True)
    event_type: SessionEventType
    value: Optional[float] = None  # e.g. minutes late for `tardiness`
    note: Optional[str] = None
    device_id: Optional[str] = None  # for multi-device conflict diagnostics


class LessonLog(SyncableModel, table=True):
    """The digital 'cahier de textes' -- what was actually taught, tied to the
    curriculum reference tree so it can be compared against the planned pacing
    (AnnualPlan/PlanItem) to compute an automatic progress/delay indicator.

    `curriculum_unit_id` used to be required, which made it impossible to
    log anything but a real lesson -- a holiday, a general support/
    remediation slot, or guided work with no single competency attached all
    need an entry in the same notebook with no unit to point at. It is now
    optional and required only for `lesson_type`s that actually cover
    curriculum content (enforced in the router, not here, since that rule
    depends on `lesson_type`'s value). `resource` (السند) is the reference
    material used -- a textbook page, a worksheet, a document -- distinct
    from `observations` (free-form notes on how the session actually went).
    """

    __tablename__ = "lesson_logs"

    session_id: Optional[str] = Field(default=None, foreign_key="class_sessions.id")
    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    teacher_id: str = Field(foreign_key="users.id")
    date: str
    lesson_type: LessonLogType = Field(default=LessonLogType.lesson)
    curriculum_unit_id: Optional[str] = Field(default=None, foreign_key="curriculum_units.id")
    resource: Optional[str] = None
    observations: Optional[str] = None
