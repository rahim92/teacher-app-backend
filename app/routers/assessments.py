from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.assessment import (
    Assessment,
    AssessmentDetail,
    AssessmentScore,
    RemediationParticipant,
    RemediationSession,
)
from app.models.common import MasteryLevel
from app.models.identity import User
from app.schemas.assessment import (
    AssessmentCreate,
    AssessmentDetailCreate,
    AssessmentDetailRead,
    AssessmentRead,
    AssessmentScoreCreate,
    AssessmentScoreRead,
    RemediationParticipantCreate,
    RemediationParticipantRead,
    RemediationSessionCreate,
    RemediationSessionRead,
)

router = APIRouter(tags=["assessments"])


@router.post("/assessments", response_model=AssessmentRead)
def create_assessment(
    payload: AssessmentCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    assessment = Assessment(**payload.model_dump(), teacher_id=current_user.id)
    session.add(assessment)
    session.commit()
    session.refresh(assessment)
    return assessment


@router.post("/assessment-scores", response_model=AssessmentScoreRead)
def add_assessment_score(
    payload: AssessmentScoreCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """The student's overall grade on this assessment -- what subject/term/
    council averages are computed from (see /council). Separate from the
    optional skill-by-skill AssessmentDetail below.
    """
    score = AssessmentScore(**payload.model_dump())
    session.add(score)
    session.commit()
    session.refresh(score)
    return score


@router.get("/assessments/{assessment_id}/scores", response_model=list[AssessmentScoreRead])
def list_assessment_scores(assessment_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    return session.exec(
        select(AssessmentScore).where(
            AssessmentScore.assessment_id == assessment_id, AssessmentScore.is_deleted == False  # noqa: E712
        )
    ).all()


@router.post("/assessment-details", response_model=AssessmentDetailRead)
def add_assessment_detail(
    payload: AssessmentDetailCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    detail = AssessmentDetail(**payload.model_dump())
    session.add(detail)
    session.commit()
    session.refresh(detail)
    return detail


@router.get("/curriculum-units/{unit_id}/struggling-students")
def struggling_students(
    unit_id: str,
    classroom_id: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """The diagnostic alert: students whose most recent assessment on this
    skill/unit is `not_acquired`. Feeds directly into forming a remediation
    group (Module 3's core value proposition).
    """
    details = session.exec(
        select(AssessmentDetail)
        .where(
            AssessmentDetail.curriculum_unit_id == unit_id,
            AssessmentDetail.is_deleted == False,  # noqa: E712
        )
        .order_by(AssessmentDetail.created_at.desc())
    ).all()

    latest_per_student: dict[str, AssessmentDetail] = {}
    for detail in details:
        if detail.student_id not in latest_per_student:
            latest_per_student[detail.student_id] = detail

    struggling = [
        d.student_id for d in latest_per_student.values() if d.mastery_level == MasteryLevel.not_acquired
    ]
    return {"unit_id": unit_id, "student_ids": struggling}


@router.post("/remediation-sessions", response_model=RemediationSessionRead)
def create_remediation_session(
    payload: RemediationSessionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    remediation = RemediationSession(**payload.model_dump(), teacher_id=current_user.id)
    session.add(remediation)
    session.commit()
    session.refresh(remediation)
    return remediation


@router.post("/remediation-participants", response_model=RemediationParticipantRead)
def add_remediation_participant(
    payload: RemediationParticipantCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    participant = RemediationParticipant(**payload.model_dump())
    session.add(participant)
    session.commit()
    session.refresh(participant)
    return participant
