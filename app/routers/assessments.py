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
from app.models.student import Student
from app.schemas.assessment import (
    AssessmentCreate,
    AssessmentDetailCreate,
    AssessmentDetailRead,
    AssessmentRead,
    AssessmentScoreCreate,
    AssessmentScoreRead,
    RemediationParticipantCreate,
    RemediationParticipantRead,
    RemediationParticipantUpdate,
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


@router.put("/assessment-details", response_model=AssessmentDetailRead)
def upsert_assessment_detail(
    payload: AssessmentDetailCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Create-or-update by (assessment_id, student_id, curriculum_unit_id) --
    same upsert pattern as /assessment-scores -- so the diagnostic-marking
    screen can call this every time a mastery level is set OR corrected for
    one student on one skill, without a separate existence check first.
    """
    existing = session.exec(
        select(AssessmentDetail).where(
            AssessmentDetail.assessment_id == payload.assessment_id,
            AssessmentDetail.student_id == payload.student_id,
            AssessmentDetail.curriculum_unit_id == payload.curriculum_unit_id,
            AssessmentDetail.is_deleted == False,  # noqa: E712
        )
    ).first()
    if existing:
        existing.mastery_level = payload.mastery_level
        existing.numeric_score = payload.numeric_score
        existing.updated_at = datetime.utcnow()
        detail = existing
    else:
        detail = AssessmentDetail(**payload.model_dump())
    session.add(detail)
    session.commit()
    session.refresh(detail)
    return detail


@router.get("/assessments/{assessment_id}/details", response_model=list[AssessmentDetailRead])
def list_assessment_details(
    assessment_id: str,
    curriculum_unit_id: Optional[str] = None,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """What the diagnostic-marking screen loads to prefill mastery levels
    already set for this assessment, so re-opening it doesn't start blank.
    """
    query = select(AssessmentDetail).where(
        AssessmentDetail.assessment_id == assessment_id, AssessmentDetail.is_deleted == False  # noqa: E712
    )
    if curriculum_unit_id:
        query = query.where(AssessmentDetail.curriculum_unit_id == curriculum_unit_id)
    return session.exec(query).all()


@router.get("/curriculum-units/{unit_id}/struggling-students")
def struggling_students(
    unit_id: str,
    classroom_id: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """The diagnostic alert: students (of THIS classroom specifically) whose
    most recent mark on this skill/unit is `not_acquired`. Feeds directly
    into forming a remediation group (Module 3's core value proposition).

    `classroom_id` used to be accepted but silently ignored -- a real bug,
    since CurriculumUnit is scoped by subject+grade, not by classroom, so
    without this filter two different classrooms sharing the same skill
    would leak each other's struggling students into one list.
    """
    classroom_student_ids = set(
        session.exec(
            select(Student.id).where(Student.classroom_id == classroom_id, Student.is_deleted == False)  # noqa: E712
        ).all()
    )
    if not classroom_student_ids:
        return {"unit_id": unit_id, "student_ids": []}

    details = session.exec(
        select(AssessmentDetail)
        .where(
            AssessmentDetail.curriculum_unit_id == unit_id,
            AssessmentDetail.student_id.in_(classroom_student_ids),
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


@router.get("/classrooms/{classroom_id}/remediation-sessions", response_model=list[RemediationSessionRead])
def list_remediation_sessions(
    classroom_id: str,
    curriculum_unit_id: Optional[str] = None,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    query = select(RemediationSession).where(
        RemediationSession.classroom_id == classroom_id, RemediationSession.is_deleted == False  # noqa: E712
    )
    if curriculum_unit_id:
        query = query.where(RemediationSession.targeted_curriculum_unit_id == curriculum_unit_id)
    return session.exec(query.order_by(RemediationSession.date.desc())).all()


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


@router.get("/remediation-sessions/{session_id}/participants", response_model=list[RemediationParticipantRead])
def list_remediation_participants(
    session_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)
):
    return session.exec(
        select(RemediationParticipant).where(
            RemediationParticipant.remediation_session_id == session_id,
            RemediationParticipant.is_deleted == False,  # noqa: E712
        )
    ).all()


@router.patch("/remediation-participants/{participant_id}", response_model=RemediationParticipantRead)
def update_remediation_participant(
    participant_id: str,
    payload: RemediationParticipantUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Records the follow-up outcome (a later re-check) for one student in
    one remediation group -- this is what turns the group from an anecdotal
    "we did a support session" into a measurable before/after.

    Ownership check added during a review pass -- previously any
    authenticated teacher's token could record a follow-up outcome for any
    other teacher's remediation group.
    """
    participant = session.get(RemediationParticipant, participant_id)
    if not participant or participant.is_deleted:
        raise HTTPException(status_code=404, detail="المشارك غير موجود")
    remediation_session = session.get(RemediationSession, participant.remediation_session_id)
    if remediation_session and remediation_session.teacher_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="يمكن فقط لصاحب حصة المعالجة أو الإدارة تسجيل نتيجة المتابعة.")
    participant.after_level = payload.after_level
    participant.updated_at = datetime.utcnow()
    session.add(participant)
    session.commit()
    session.refresh(participant)
    return participant
