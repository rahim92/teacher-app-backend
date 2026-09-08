"""Import every model module here so SQLModel.metadata.create_all() (and
Alembic's autogenerate) can see all tables from a single import of `app.models`.
"""
from app.models.assessment import (  # noqa: F401
    Assessment,
    AssessmentDetail,
    AssessmentScore,
    RemediationParticipant,
    RemediationSession,
)
from app.models.curriculum import AnnualPlan, CurriculumUnit, PlanItem  # noqa: F401
from app.models.identity import (  # noqa: F401
    AcademicYear,
    Classroom,
    School,
    Subject,
    TeacherClassroomAssignment,
    Term,
    User,
)
from app.models.messaging import ParentMessageTemplate  # noqa: F401
from app.models.session import ClassSession, LessonLog, SessionEvent  # noqa: F401
from app.models.student import NotebookCheck, SeatAssignment, Student  # noqa: F401
