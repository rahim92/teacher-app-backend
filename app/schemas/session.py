from typing import Optional

from pydantic import BaseModel

from app.models.common import SessionEventType, SessionStatus


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
    curriculum_unit_id: str
    observations: Optional[str] = None


class LessonLogRead(LessonLogCreate):
    id: str
    teacher_id: str
