from typing import Optional

from pydantic import BaseModel


class RepeatedAbsenceAlert(BaseModel):
    student_id: str
    full_name: str
    absence_count: int  # attendance_absent + tardiness taps combined, this term


class StaleNotebookAlert(BaseModel):
    student_id: str
    full_name: str
    last_check_date: Optional[str]  # None => never checked this term
    days_since_check: Optional[int]  # None whenever last_check_date is None


class UngradedAssessmentAlert(BaseModel):
    assessment_id: str
    title: str
    subject_id: str
    date: str
    missing_count: int
    total_students: int


class ClassroomAlerts(BaseModel):
    classroom_id: str
    term_id: str
    repeated_absence: list[RepeatedAbsenceAlert]
    stale_notebooks: list[StaleNotebookAlert]
    ungraded_assessments: list[UngradedAssessmentAlert]
