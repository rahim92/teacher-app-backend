"""معدل المادة الفصلي -- one subject's trimester average, combining علامة
السلوك (المراقبة المستمرة, see behavior.py) with الفرض/الاختبار grades
(Assessment/AssessmentScore, see assessments.py) using the official formula:

    المعدل = ( (المراقبة المستمرة + معدل الفروض) / 2 + معدل الاختبار × 2 ) / 3

Exposed two ways, per the user's request: a per-teacher endpoint below
(GET /students/{id}/subject-grade), and reused by council.py so مجلس القسم
shows the same formula instead of its old "average every graded item
together" shortcut. `compute_subject_term_grade` is the single shared
implementation both call, so the two views can never silently disagree.

Only test-type and exam-type assessments feed this formula, matching
exactly what the user described -- homework/oral Assessment entries (a
teacher can still record those) are not part of it. "Extra work" already
has its own punitive category inside the continuous-assessment score (see
behavior.py's "homework" category, "أعمال إضافية") from the official-sheet
rebuild, so this isn't a gap, just a boundary between the two systems.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.assessment import Assessment, AssessmentScore
from app.models.common import AssessmentType, UserRole
from app.models.identity import Classroom, Subject, TeacherClassroomAssignment, Term, User
from app.models.student import Student
from app.routers.behavior import compute_behavior_score
from app.schemas.grades import SubjectGradeTrend, SubjectGradeTrendPoint, SubjectTermGrade

router = APIRouter(tags=["grades"])


def _ensure_can_view_subject_grades(session: Session, classroom: Classroom, subject_id: str, current_user: User) -> None:
    """Stricter than students._ensure_can_manage_student on purpose: that one
    only checks "do you teach ANY subject in this classroom", which is right
    for roster/seating data but too broad for another teacher's grades. Here
    a subject-assignment match is required -- the homeroom teacher/admin are
    the only ones allowed to see every subject (same as /council), since
    they already see all of it there.
    """
    if current_user.role == UserRole.admin:
        return
    if classroom.homeroom_teacher_id == current_user.id:
        return
    if classroom.teacher_id == current_user.id:
        return
    has_assignment = session.exec(
        select(TeacherClassroomAssignment).where(
            TeacherClassroomAssignment.classroom_id == classroom.id,
            TeacherClassroomAssignment.teacher_id == current_user.id,
            TeacherClassroomAssignment.subject_id == subject_id,
            TeacherClassroomAssignment.is_deleted == False,  # noqa: E712
        )
    ).first()
    if not has_assignment:
        raise HTTPException(status_code=403, detail="لا تُدرِّس هذه المادة في هذا القسم، فلا يمكنك الاطلاع على معدلها.")


def _type_average(
    session: Session,
    classroom_id: str,
    subject_id: str,
    student_id: str,
    term: Term,
    assessment_type: AssessmentType,
) -> Optional[float]:
    """Weighted average (by Assessment.coefficient, same weighting council.py
    already used) of one student's scores across every assessment of one
    type (test, or exam) for this subject/classroom/term -- normalized to
    /20 first, so a 15/25 فرض and a 9/20 فرض combine correctly. None if the
    student has no recorded score of that type yet (not 0 -- a missing
    grade isn't a zero).
    """
    assessments = session.exec(
        select(Assessment).where(
            Assessment.classroom_id == classroom_id,
            Assessment.subject_id == subject_id,
            Assessment.assessment_type == assessment_type,
            Assessment.date >= term.start_date,
            Assessment.date <= term.end_date,
            Assessment.is_deleted == False,  # noqa: E712
        )
    ).all()
    if not assessments:
        return None

    weighted_pairs: list[tuple[float, float]] = []
    for assessment in assessments:
        score = session.exec(
            select(AssessmentScore).where(
                AssessmentScore.assessment_id == assessment.id,
                AssessmentScore.student_id == student_id,
                AssessmentScore.is_deleted == False,  # noqa: E712
            )
        ).first()
        if score is None:
            continue
        normalized = (score.score / assessment.max_score) * 20 if assessment.max_score else 0.0
        weighted_pairs.append((normalized, assessment.coefficient))

    if not weighted_pairs:
        return None
    numerator = sum(value * weight for value, weight in weighted_pairs)
    denominator = sum(weight for _, weight in weighted_pairs)
    return numerator / denominator if denominator else None


def compute_subject_term_grade(
    session: Session,
    student_id: str,
    classroom_id: str,
    subject_id: str,
    term_id: str,
) -> SubjectTermGrade:
    term = session.get(Term, term_id)
    if not term or term.is_deleted:
        raise HTTPException(status_code=404, detail="الفصل الدراسي غير موجود")

    continuous = compute_behavior_score(session, student_id, classroom_id, term_id).total
    test_avg = _type_average(session, classroom_id, subject_id, student_id, term, AssessmentType.test)
    exam_avg = _type_average(session, classroom_id, subject_id, student_id, term, AssessmentType.exam)

    average = None
    if test_avg is not None and exam_avg is not None:
        midpoint = (continuous + test_avg) / 2
        average = (midpoint + exam_avg * 2) / 3

    return SubjectTermGrade(
        student_id=student_id,
        classroom_id=classroom_id,
        subject_id=subject_id,
        term_id=term_id,
        continuous_assessment=round(continuous, 2),
        test_average=round(test_avg, 2) if test_avg is not None else None,
        exam_average=round(exam_avg, 2) if exam_avg is not None else None,
        average=round(average, 2) if average is not None else None,
    )


@router.get("/students/{student_id}/subject-grade", response_model=SubjectTermGrade)
def get_subject_term_grade(
    student_id: str,
    classroom_id: str,
    subject_id: str,
    term_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_view_subject_grades(session, classroom, subject_id, current_user)

    return compute_subject_term_grade(session, student_id, classroom_id, subject_id, term_id)


@router.get("/students/{student_id}/subject-grade-trend", response_model=SubjectGradeTrend)
def get_subject_grade_trend(
    student_id: str,
    classroom_id: str,
    subject_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """مخطط تطور المعدل عبر الفصول -- the same subject-grade formula as
    /students/{id}/subject-grade, computed once per term of the classroom's
    academic year instead of just the current one, so a teacher can see
    whether a student is improving or slipping over the year rather than a
    single snapshot. Gated exactly like the single-term endpoint above: a
    subject teacher sees their own subject's trend, the homeroom
    teacher/admin can see any subject's (see _ensure_can_view_subject_grades).
    """
    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_view_subject_grades(session, classroom, subject_id, current_user)
    subject = session.get(Subject, subject_id)
    if not subject or subject.is_deleted:
        raise HTTPException(status_code=404, detail="المادة غير موجودة")

    terms = session.exec(
        select(Term)
        .where(
            Term.academic_year_id == classroom.academic_year_id,
            Term.is_deleted == False,  # noqa: E712
        )
        .order_by(Term.order_index)
    ).all()

    points: list[SubjectGradeTrendPoint] = []
    for term in terms:
        grade = compute_subject_term_grade(session, student_id, classroom_id, subject_id, term.id)
        points.append(
            SubjectGradeTrendPoint(
                term_id=term.id,
                term_label=term.label,
                order_index=term.order_index,
                continuous_assessment=grade.continuous_assessment,
                test_average=grade.test_average,
                exam_average=grade.exam_average,
                average=grade.average,
            )
        )

    return SubjectGradeTrend(
        student_id=student_id,
        classroom_id=classroom_id,
        subject_id=subject_id,
        subject_name=subject.name,
        points=points,
    )
