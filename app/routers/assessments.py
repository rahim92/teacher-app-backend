from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
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
from app.models.common import MasteryLevel, UserRole
from app.models.identity import Term, User
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

    Kept as a plain create (fails on a duplicate (assessment_id, student_id)
    via the DB's unique constraint) for backward compatibility with existing
    callers -- the grade-entry screen uses the upsert-friendly PUT below
    instead, so a teacher revising an already-entered mark doesn't hit that.
    """
    score = AssessmentScore(**payload.model_dump())
    session.add(score)
    session.commit()
    session.refresh(score)
    return score


@router.put("/assessment-scores", response_model=AssessmentScoreRead)
def upsert_assessment_score(
    payload: AssessmentScoreCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Create-or-update by (assessment_id, student_id) -- same upsert-by-
    natural-key pattern as /seat-assignments -- so the grade-entry table can
    call this every time a score is entered OR corrected, without needing a
    separate "does a score already exist" lookup or a per-row PATCH id.
    """
    existing = session.exec(
        select(AssessmentScore).where(
            AssessmentScore.assessment_id == payload.assessment_id,
            AssessmentScore.student_id == payload.student_id,
            AssessmentScore.is_deleted == False,  # noqa: E712
        )
    ).first()
    if existing:
        existing.score = payload.score
        existing.updated_at = datetime.utcnow()
        score = existing
    else:
        score = AssessmentScore(**payload.model_dump())
    session.add(score)
    session.commit()
    session.refresh(score)
    return score


@router.get("/classrooms/{classroom_id}/assessments", response_model=list[AssessmentRead])
def list_assessments(
    classroom_id: str,
    subject_id: Optional[str] = None,
    term_id: Optional[str] = None,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Lists the tests/exams/homeworks recorded for a classroom -- what the
    grade-entry screen offers to reopen and re-enter/correct scores for, and
    (indirectly, via non-deleted assessments only) what /council's subject
    averages are computed from. `term_id` narrows by the assessment's date
    falling inside that term's range -- the same convention /council uses,
    kept consistent so "شهدت هذا الفصل الدراسي" means the same thing
    everywhere in the app.
    """
    query = select(Assessment).where(
        Assessment.classroom_id == classroom_id, Assessment.is_deleted == False  # noqa: E712
    )
    if subject_id:
        query = query.where(Assessment.subject_id == subject_id)
    assessments = session.exec(query.order_by(Assessment.date.desc())).all()
    if term_id:
        term = session.get(Term, term_id)
        if term and not term.is_deleted:
            assessments = [a for a in assessments if term.start_date <= a.date <= term.end_date]
    return assessments


@router.delete("/assessments/{assessment_id}", status_code=204)
def delete_assessment(
    assessment_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Soft-deletes a wrongly created test/exam (wrong title, duplicate,
    wrong subject). Its AssessmentScore rows are left in place -- same
    no-cascade choice made for students/delegates elsewhere -- but become
    unreachable in every app view in practice, since both the grade-entry
    list and /council reach scores only through non-deleted assessments.
    """
    assessment = session.get(Assessment, assessment_id)
    if not assessment or assessment.is_deleted:
        raise HTTPException(status_code=404, detail="الفرض/الاختبار غير موجود")
    if assessment.teacher_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="يمكن فقط لصاحب الفرض أو الإدارة حذفه.")
    assessment.is_deleted = True
    assessment.updated_at = datetime.utcnow()
    session.add(assessment)
    session.commit()


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
