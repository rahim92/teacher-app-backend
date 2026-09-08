from typing import Optional

from sqlmodel import Field, UniqueConstraint

from app.models.common import AssessmentType, MasteryLevel, SyncableModel


class Assessment(SyncableModel, table=True):
    __tablename__ = "assessments"

    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    subject_id: str = Field(foreign_key="subjects.id")
    teacher_id: str = Field(foreign_key="users.id")
    assessment_type: AssessmentType
    title: str
    date: str
    coefficient: float = Field(default=1.0)
    max_score: float = Field(default=20.0)


class AssessmentScore(SyncableModel, table=True):
    """The student's single overall grade on one assessment (out of
    Assessment.max_score) -- this is what subject/term/council averages are
    computed from. Kept separate from AssessmentDetail on purpose: a score is
    always recorded for every graded assessment, while the skill-by-skill
    breakdown (AssessmentDetail) is an optional diagnostic layer a teacher
    adds when they want remediation-grade detail. Neither substitutes for
    the other.
    """

    __tablename__ = "assessment_scores"
    __table_args__ = (UniqueConstraint("assessment_id", "student_id", name="uq_one_score_per_student_per_assessment"),)

    assessment_id: str = Field(foreign_key="assessments.id", index=True)
    student_id: str = Field(foreign_key="students.id", index=True)
    score: float


class AssessmentDetail(SyncableModel, table=True):
    """Per-student, per-skill breakdown of one assessment -- this is what makes
    diagnostic remediation possible: a 12/20 overall grade can still flag a
    specific competency as `not_acquired`. Optional/supplementary to
    AssessmentScore above, not a replacement for it.
    """

    __tablename__ = "assessment_details"

    assessment_id: str = Field(foreign_key="assessments.id", index=True)
    student_id: str = Field(foreign_key="students.id", index=True)
    curriculum_unit_id: str = Field(foreign_key="curriculum_units.id")  # the skill measured
    mastery_level: MasteryLevel
    numeric_score: Optional[float] = None


class RemediationSession(SyncableModel, table=True):
    __tablename__ = "remediation_sessions"

    teacher_id: str = Field(foreign_key="users.id", index=True)
    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    date: str
    targeted_curriculum_unit_id: str = Field(foreign_key="curriculum_units.id")
    notes: Optional[str] = None


class RemediationParticipant(SyncableModel, table=True):
    """Tracks one student's mastery level before/after a remediation session,
    so progress across sessions is measurable rather than anecdotal.
    """

    __tablename__ = "remediation_participants"

    remediation_session_id: str = Field(foreign_key="remediation_sessions.id", index=True)
    student_id: str = Field(foreign_key="students.id", index=True)
    before_level: MasteryLevel
    after_level: Optional[MasteryLevel] = None
