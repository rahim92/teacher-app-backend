"""مجلس القسم -- the class council report.

The one place in this app that deliberately crosses teacher boundaries: it
combines every subject teacher's grades (AssessmentScore) and every
teacher's attendance/behavior taps (SessionEvent) for one classroom into a
single per-student summary. Because that reveals one teacher's data to
another, access is restricted (see _ensure_can_view_council) to the
classroom's homeroom teacher ("الأستاذ الرئيسي", capped at one classroom per
year -- see the unique constraint on Classroom) or an admin account.

This only produces useful output once several teachers' TeacherClassroomAssignment
rows exist for the classroom -- in a single-teacher MVP install it will
simply show one subject's worth of data. The mobile app is expected to hide
the entry point to this report until more than one teacher is assigned.
"""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.assessment import Assessment, AssessmentScore
from app.models.common import SessionEventType, UserRole
from app.models.identity import Classroom, Subject, TeacherClassroomAssignment, Term, User
from app.models.session import ClassSession, SessionEvent
from app.models.student import Student
from app.schemas.council import CouncilReport, StudentCouncilRow, SubjectAverage

router = APIRouter(prefix="/council", tags=["council"])


def _ensure_can_view_council(classroom: Classroom, current_user: User) -> None:
    is_homeroom_teacher = classroom.homeroom_teacher_id == current_user.id
    is_admin = current_user.role == UserRole.admin
    if not (is_homeroom_teacher or is_admin):
        raise HTTPException(
            status_code=403,
            detail="تقرير مجلس القسم متاح فقط للأستاذ الرئيسي لهذا القسم أو للإدارة.",
        )


@router.get("/classrooms/{classroom_id}/report", response_model=CouncilReport)
def get_council_report(
    classroom_id: str,
    term_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_view_council(classroom, current_user)

    term = session.get(Term, term_id)
    if not term or term.is_deleted:
        raise HTTPException(status_code=404, detail="الفصل الدراسي غير موجود")

    students = session.exec(
        select(Student).where(Student.classroom_id == classroom_id, Student.is_deleted == False)  # noqa: E712
    ).all()

    assignments = session.exec(
        select(TeacherClassroomAssignment).where(
            TeacherClassroomAssignment.classroom_id == classroom_id,
            TeacherClassroomAssignment.is_deleted == False,  # noqa: E712
        )
    ).all()
    subject_ids = list({a.subject_id for a in assignments})
    subjects = (
        {s.id: s for s in session.exec(select(Subject).where(Subject.id.in_(subject_ids))).all()}
        if subject_ids
        else {}
    )

    # subject_id -> student_id -> [(score normalized to /20, assessment coefficient), ...]
    per_subject_scores: dict[str, dict[str, list[tuple[float, float]]]] = defaultdict(lambda: defaultdict(list))

    for subject_id in subject_ids:
        assessments = session.exec(
            select(Assessment).where(
                Assessment.classroom_id == classroom_id,
                Assessment.subject_id == subject_id,
                Assessment.date >= term.start_date,
                Assessment.date <= term.end_date,
                Assessment.is_deleted == False,  # noqa: E712
            )
        ).all()
        for assessment in assessments:
            scores = session.exec(
                select(AssessmentScore).where(
                    AssessmentScore.assessment_id == assessment.id,
                    AssessmentScore.is_deleted == False,  # noqa: E712
                )
            ).all()
            for sc in scores:
                normalized = (sc.score / assessment.max_score) * 20 if assessment.max_score else 0.0
                per_subject_scores[subject_id][sc.student_id].append((normalized, assessment.coefficient))

    # Attendance/behavior aggregated across EVERY subject teacher for this
    # classroom -- this cross-teacher join is exactly why this endpoint is
    # permission-gated above.
    events_with_sessions = session.exec(
        select(SessionEvent, ClassSession)
        .join(ClassSession, SessionEvent.session_id == ClassSession.id)  # type: ignore[arg-type]
        .where(
            ClassSession.classroom_id == classroom_id,
            ClassSession.date >= term.start_date,
            ClassSession.date <= term.end_date,
            SessionEvent.is_deleted == False,  # noqa: E712
        )
    ).all()

    event_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event, _class_session in events_with_sessions:
        event_counts[event.student_id][event.event_type] += 1

    rows: list[StudentCouncilRow] = []
    for student in students:
        subject_averages: list[SubjectAverage] = []
        weighted_sum = 0.0
        weight_total = 0.0

        for subject_id, subject in subjects.items():
            student_scores = per_subject_scores.get(subject_id, {}).get(student.id, [])
            if student_scores:
                numerator = sum(score * coef for score, coef in student_scores)
                denominator = sum(coef for _, coef in student_scores)
                subject_avg = numerator / denominator if denominator else None
            else:
                subject_avg = None

            subject_averages.append(SubjectAverage(subject_id=subject_id, subject_name=subject.name, average=subject_avg))
            if subject_avg is not None:
                weighted_sum += subject_avg * subject.coefficient
                weight_total += subject.coefficient

        overall_average = weighted_sum / weight_total if weight_total else None
        counts = event_counts.get(student.id, {})

        rows.append(
            StudentCouncilRow(
                student_id=student.id,
                full_name=f"{student.first_name} {student.last_name}",
                subject_averages=subject_averages,
                overall_average=overall_average,
                absences=counts.get(SessionEventType.attendance_absent.value, 0),
                tardiness_count=counts.get(SessionEventType.tardiness.value, 0),
                positive_behavior_count=counts.get(SessionEventType.behavior_positive.value, 0),
                negative_behavior_count=counts.get(SessionEventType.behavior_negative.value, 0),
            )
        )

    ranked = sorted((r for r in rows if r.overall_average is not None), key=lambda r: r.overall_average, reverse=True)
    for index, row in enumerate(ranked, start=1):
        row.rank = index
    rows.sort(key=lambda r: (r.rank is None, r.rank if r.rank is not None else 0))

    return CouncilReport(
        classroom_id=classroom_id,
        classroom_name=classroom.name,
        term_id=term_id,
        term_label=term.label,
        rows=rows,
    )
