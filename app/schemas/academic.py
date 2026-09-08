from typing import Optional

from pydantic import BaseModel

from app.models.common import GradeLevel


class SchoolCreate(BaseModel):
    name: str
    address: Optional[str] = None


class SchoolRead(SchoolCreate):
    id: str


class AcademicYearCreate(BaseModel):
    label: str
    start_date: str
    end_date: str


class AcademicYearRead(AcademicYearCreate):
    id: str


class TermCreate(BaseModel):
    academic_year_id: str
    label: str
    start_date: str
    end_date: str
    order_index: int = 0


class TermRead(TermCreate):
    id: str


class SubjectCreate(BaseModel):
    name: str
    code: Optional[str] = None
    coefficient: float = 1.0


class SubjectRead(SubjectCreate):
    id: str


class ClassroomCreate(BaseModel):
    school_id: Optional[str] = None
    academic_year_id: str
    name: str
    grade_level: GradeLevel


class ClassroomRead(ClassroomCreate):
    id: str
    teacher_id: str
    homeroom_teacher_id: Optional[str] = None


class HomeroomTeacherUpdate(BaseModel):
    homeroom_teacher_id: Optional[str] = None  # None clears the assignment


class TeacherClassroomAssignmentCreate(BaseModel):
    teacher_id: str
    classroom_id: str
    subject_id: str
    academic_year_id: str


class TeacherClassroomAssignmentRead(TeacherClassroomAssignmentCreate):
    id: str


class ClassDelegateCreate(BaseModel):
    classroom_id: str
    student_id: str
    academic_year_id: str
    elected_date: Optional[str] = None
    note: Optional[str] = None


class ClassDelegateRead(ClassDelegateCreate):
    id: str
