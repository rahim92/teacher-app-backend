from typing import Optional

from sqlmodel import Field

from app.models.common import SessionEventType, SessionStatus, SyncableModel


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
    """

    __tablename__ = "lesson_logs"

    session_id: Optional[str] = Field(default=None, foreign_key="class_sessions.id")
    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    teacher_id: str = Field(foreign_key="users.id")
    date: str
    curriculum_unit_id: str = Field(foreign_key="curriculum_units.id")
    observations: Optional[str] = None
