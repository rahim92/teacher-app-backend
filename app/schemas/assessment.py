from typing import Optional

from pydantic import BaseModel

from app.models.common import AssessmentType, MasteryLevel


class AssessmentCreate(BaseModel):
    classroom_id: str
    subject_id: str
    assessment_type: AssessmentType
    title: str
    date: str
    coefficient: float = 1.0
    max_score: float = 20.0


class AssessmentRead(AssessmentCreate):
    id: str
    teacher_id: str


class AssessmentScoreCreate(BaseModel):
    assessment_id: str
    student_id: str
    score: float


class AssessmentScoreRead(AssessmentScoreCreate):
    id: str


class AssessmentDetailCreate(BaseModel):
    assessment_id: str
    student_id: str
    curriculum_unit_id: str
    mastery_level: MasteryLevel
    numeric_score: Optional[float] = None


class AssessmentDetailRead(AssessmentDetailCreate):
    id: str


class RemediationSessionCreate(BaseModel):
    classroom_id: str
    date: str
    targeted_curriculum_unit_id: str
    notes: Optional[str] = None


class RemediationSessionRead(RemediationSessionCreate):
    id: str
    teacher_id: str


class RemediationParticipantCreate(BaseModel):
    remediation_session_id: str
    student_id: str
    before_level: MasteryLevel
    after_level: Optional[MasteryLevel] = None


class RemediationParticipantRead(RemediationParticipantCreate):
    id: str


class RemediationParticipantUpdate(BaseModel):
    """Records the follow-up outcome once it's known -- separate from
    creation because `after_level` is by nature knowable only some time
    after the remediation session itself (a later re-test), not at the
    moment the session/group is formed."""

    after_level: MasteryLevel
