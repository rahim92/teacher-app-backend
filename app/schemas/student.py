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


class StudentImportSkippedRow(BaseModel):
    row_number: int  # 1-based, matching what a teacher sees if they open the file in Excel (row 1 = header)
    reason: str


class StudentImportResult(BaseModel):
    """POST /classrooms/{id}/students/import never fails a whole file over
    one bad row -- a class list of 35 names is exactly the kind of file
    where row 17 has a typo or a blank cell, and refusing the other 34 over
    that would be worse than importing them and flagging row 17. `created`
    lets the roster screen show the new students immediately without a
    second round-trip; `skipped` lists exactly which rows need a manual fix.
    """

    created_count: int
    skipped_count: int
    created: list[StudentRead]
    skipped: list[StudentImportSkippedRow]


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
    # Which of the (at most MAX_STUDENTS_PER_DESK) spots within the desk this
    # is -- server-assigned only, never accepted on SeatAssignmentUpsert; see
    # upsert_seat_assignment/swap_seat_assignments in routers/students.py.
    seat_slot: int = 0


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
    quality: NotebookQuality  # تنظيم الكراس
    writing_quality: Optional[NotebookQuality] = None  # الكتابة (السبورة والكراس)
    note: Optional[str] = None


class NotebookCheckRead(NotebookCheckCreate):
    id: str
    teacher_id: str
