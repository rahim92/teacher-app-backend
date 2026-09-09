from typing import Optional

from pydantic import BaseModel

from app.models.common import NotebookQuality, SpecialNeedCategory, SpecialNeedVisibility


class StudentCreate(BaseModel):
    classroom_id: str
    first_name: str
    last_name: str
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    medical_notes: Optional[str] = None
    general_notes: Optional[str] = None


class StudentUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    medical_notes: Optional[str] = None
    general_notes: Optional[str] = None


class StudentRead(BaseModel):
    id: str
    classroom_id: str
    first_name: str
    last_name: str
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    medical_notes: Optional[str] = None
    general_notes: Optional[str] = None


class SeatAssignmentUpsert(BaseModel):
    classroom_id: str
    student_id: str
    term_id: Optional[str] = None
    seat_row: int
    seat_col: int
    reason: Optional[str] = None


class SeatAssignmentRead(SeatAssignmentUpsert):
    id: str
    teacher_id: str


class SeatSwapRequest(BaseModel):
    seat_id_a: str
    seat_id_b: str


class StudentSpecialNeedCreate(BaseModel):
    student_id: str
    category: SpecialNeedCategory
    description: Optional[str] = None
    accommodation_needed: Optional[str] = None
    emergency_protocol: Optional[str] = None
    visibility: SpecialNeedVisibility = SpecialNeedVisibility.homeroom_only


class StudentSpecialNeedRead(StudentSpecialNeedCreate):
    id: str
    created_by: str


class NotebookCheckCreate(BaseModel):
    student_id: str
    check_date: str
    quality: NotebookQuality
    note: Optional[str] = None


class NotebookCheckRead(NotebookCheckCreate):
    id: str
    teacher_id: str
