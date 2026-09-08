"""Shared base classes and enums used across every model.

Every syncable entity (i.e. everything created on a teacher's phone that later
syncs to the server) inherits SyncableModel so it carries a consistent set of
fields the sync engine relies on:

  id          - UUID generated client-side (so a record is valid before it
                ever reaches the server; this is what makes offline-first work)
  created_at  - when the record was first created (on whichever device)
  updated_at  - last-write-wins conflict resolution key
  is_deleted  - soft delete, so deletions replicate through sync just like edits
"""
import uuid
from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel


def new_uuid() -> str:
    return str(uuid.uuid4())


class SyncableModel(SQLModel):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_deleted: bool = Field(default=False)


class UserRole(str, Enum):
    teacher = "teacher"
    admin = "admin"
    inspector = "inspector"


class GradeLevel(str, Enum):
    am1 = "1AM"
    am2 = "2AM"
    am3 = "3AM"
    am4 = "4AM"


class UnitType(str, Enum):
    sequence = "sequence"
    unit = "unit"
    skill = "skill"


class AssessmentType(str, Enum):
    test = "test"
    exam = "exam"
    homework = "homework"
    oral = "oral"


class MasteryLevel(str, Enum):
    not_acquired = "not_acquired"
    in_progress = "in_progress"
    acquired = "acquired"


class SessionStatus(str, Enum):
    open = "open"
    closed = "closed"


class SessionEventType(str, Enum):
    attendance_present = "attendance_present"
    attendance_absent = "attendance_absent"
    tardiness = "tardiness"
    behavior_positive = "behavior_positive"
    behavior_negative = "behavior_negative"
    homework_done = "homework_done"
    homework_missing = "homework_missing"
    participation = "participation"


class MessageCategory(str, Enum):
    absence = "absence"
    behavior = "behavior"
    general = "general"


class NotebookQuality(str, Enum):
    """Periodic check of a student's own notebooks (كراس الدروس / الأنشطة) --
    a distinct, lower-frequency observation from the moment-to-moment
    SessionEvent taps: this is 'how well kept is the notebook today', not an
    in-class event.
    """

    organized = "organized"  # منظم
    average = "average"  # متوسط
    neglected = "neglected"  # مهمل
