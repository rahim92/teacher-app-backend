from typing import Optional

from pydantic import BaseModel


class SubjectAverage(BaseModel):
    subject_id: str
    subject_name: str
    average: Optional[float] = None  # None until at least one AssessmentScore exists


class StudentCouncilRow(BaseModel):
    student_id: str
    full_name: str
    subject_averages: list[SubjectAverage]
    overall_average: Optional[float] = None
    rank: Optional[int] = None
    absences: int = 0
    tardiness_count: int = 0
    positive_behavior_count: int = 0
    negative_behavior_count: int = 0


class CouncilReport(BaseModel):
    classroom_id: str
    classroom_name: str
    term_id: str
    term_label: str
    rows: list[StudentCouncilRow]
