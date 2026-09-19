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


class AcademicYearUpdate(BaseModel):
    """Partial update -- e.g. correcting a year created with a stale default
    date range (only fields actually sent are changed)."""

    label: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class TermCreate(BaseModel):
    academic_year_id: str
    label: str
    start_date: str
    end_date: str
    order_index: int = 0


class TermRead(TermCreate):
    id: str


class TermUpdate(BaseModel):
    """Partial update -- same rationale as AcademicYearUpdate above."""

    label: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    order_index: Optional[int] = None


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


class TaughtSubjectInfo(BaseModel):
    subject_id: str
    subject_name: str


class MyClassroomRead(ClassroomRead):
    """Enriched view used by /my-classrooms: what role(s) THIS teacher holds
    in this classroom. A teacher commonly teaches several classrooms (one
    TeacherClassroomAssignment per subject/classroom); they can be the
    homeroom teacher ('الأستاذ الرئيسي') of at most one, per the unique
    constraint on Classroom.
    """

    is_creator: bool
    is_homeroom: bool
    homeroom_teacher_name: Optional[str] = None
    taught_subjects: list[TaughtSubjectInfo] = []


class ClassroomDirectoryEntry(BaseModel):
    """Lightweight listing so a teacher can find a classroom created by a
    colleague and request to teach a subject in it -- without exposing the
    full ClassroomRead (roster counts, etc.) of a classroom they're not yet
    related to.
    """

    id: str
    name: str
    grade_level: GradeLevel
    academic_year_id: str
    homeroom_teacher_name: Optional[str] = None


class HomeroomTeacherUpdate(BaseModel):
    homeroom_teacher_id: Optional[str] = None  # None clears the assignment


class TeacherClassroomAssignmentCreate(BaseModel):
    teacher_id: str
    classroom_id: str
    subject_id: str
    academic_year_id: str


class TeacherClassroomAssignmentRead(TeacherClassroomAssignmentCreate):
    id: str


class TeacherAssignmentDisplay(BaseModel):
    """Enriched view used only by GET /classrooms/{id}/teacher-assignments
    (§74 mobile gap-analysis) -- the raw TeacherClassroomAssignmentRead above
    (still returned as-is by POST /teacher-classroom-assignments, unchanged)
    carries only teacher_id/subject_id foreign keys, which is fine for a
    create response the caller already knows the names for, but useless for
    a listing screen: no client (web or mobile) mirrors a Users/Teachers
    table locally (identity data is deliberately excluded from
    ENTITY_MODEL_MAP in sync.py -- see its own comment), so a bare
    teacher_id UUID has no name to resolve against on-device. Same shape/
    naming convention as the existing TaughtSubjectInfo (subject_id +
    subject_name pairing) above, extended with the equivalent teacher pair.
    """

    id: str
    teacher_id: str
    teacher_name: str
    subject_id: str
    subject_name: str
    academic_year_id: str


class ClassDelegateCreate(BaseModel):
    classroom_id: str
    student_id: str
    academic_year_id: str
    elected_date: Optional[str] = None
    note: Optional[str] = None


class ClassDelegateRead(ClassDelegateCreate):
    id: str
