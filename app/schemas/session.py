from typing import Optional

from pydantic import BaseModel

from app.models.common import LessonLogType, SessionEventType, SessionStatus


class ClassSessionCreate(BaseModel):
    classroom_id: str
    subject_id: str
    date: str
    start_time: Optional[str] = None


class ClassSessionRead(BaseModel):
    id: str
    classroom_id: str
    teacher_id: str
    subject_id: str
    date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: SessionStatus


class ClassSessionClose(BaseModel):
    end_time: Optional[str] = None
    curriculum_unit_id: Optional[str] = None  # what was actually taught -> creates a LessonLog
    observations: Optional[str] = None


class SessionEventCreate(BaseModel):
    session_id: str
    student_id: str
    event_type: SessionEventType
    value: Optional[float] = None
    note: Optional[str] = None
    device_id: Optional[str] = None


class SessionEventRead(SessionEventCreate):
    id: str


class LessonLogCreate(BaseModel):
    session_id: Optional[str] = None
    classroom_id: str
    date: str
    lesson_type: LessonLogType = LessonLogType.lesson
    curriculum_unit_id: Optional[str] = None  # optional secondary link -- powers the pacing indicator only, if set
    domain: Optional[str] = None  # الميدان -- typed freely, terminology differs per subject
    segment: Optional[str] = None  # المقطع/الوحدة -- typed freely, terminology differs per subject
    lesson_title: Optional[str] = None  # عنوان الدرس
    completed_phases: Optional[str] = None  # comma-separated tags -- meaning depends on subject family, see models/session.py
    observations: Optional[str] = None


class LessonLogRead(LessonLogCreate):
    id: str
    teacher_id: str


class LessonLogUpdate(BaseModel):
    """Partial update -- only fields actually sent are changed. A teacher
    fixing a typo in `observations` shouldn't have to resend the whole entry
    (and risk accidentally clearing `curriculum_unit_id` by omission)."""

    date: Optional[str] = None
    lesson_type: Optional[LessonLogType] = None
    curriculum_unit_id: Optional[str] = None
    domain: Optional[str] = None
    segment: Optional[str] = None
    lesson_title: Optional[str] = None
    completed_phases: Optional[str] = None
    observations: Optional[str] = None
