"""لوحة تنبيهات ذكية على الصفحة الرئيسية (§38) -- three read-only,
classroom-wide signals a teacher would otherwise have to notice by memory
or by opening several screens one at a time:

  - غياب/تأخر متكرر: تلاميذ تجاوز عدد نقرات "غائب"+"تأخر" لهم حداً معيَّناً
    هذا الفصل -- نفس العمود الرسمي الموحَّد المستعمل في علامة السلوك
    (attendance_absent + tardiness معاً، انظر routers/behavior.py).
  - كراس لم يُفحص منذ مدة: تلاميذ لم يُفحَص كراسهم إطلاقاً هذا الفصل، أو
    آخر فحص لهم أقدم من عدد أيام معيَّن.
  - فروض/اختبارات ناقصة العلامات: فروض/اختبارات هذا الفصل لم تُدخَل بعد
    علامات كل تلاميذ القسم فيها.

Nothing here is stored -- كل تنبيه يُحسَب مباشرة من بيانات موجودة أصلاً
(SessionEvent، NotebookCheck، AssessmentScore)، بنفس منطق "احسب، لا تكرِّر"
الذي تتبعه compute_behavior_score. العتبات (الحد الأدنى للغياب، وعدد أيام
"الكراس القديم") قابلة للتعديل عبر مُعامِلات استعلام اختيارية، بقيم افتراضية
معقولة، بدل شاشة إعدادات منفصلة -- لا يوجد طلب صريح لتخصيصها حتى الآن.
"""
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.assessment import Assessment, AssessmentScore
from app.models.common import SessionEventType
from app.models.identity import Classroom, Term, User
from app.models.session import ClassSession, SessionEvent
from app.models.student import NotebookCheck, Student
from app.routers.students import _ensure_can_manage_classroom_roster
from app.schemas.alerts import ClassroomAlerts, RepeatedAbsenceAlert, StaleNotebookAlert, UngradedAssessmentAlert

router = APIRouter(tags=["alerts"])

DEFAULT_MIN_ABSENCES = 3
DEFAULT_NOTEBOOK_STALE_DAYS = 21


@router.get("/classrooms/{classroom_id}/alerts", response_model=ClassroomAlerts)
def get_classroom_alerts(
    classroom_id: str,
    term_id: str,
    min_absences: int = Query(default=DEFAULT_MIN_ABSENCES, ge=1),
    notebook_stale_days: int = Query(default=DEFAULT_NOTEBOOK_STALE_DAYS, ge=1),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ClassroomAlerts:
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    # نفس علاقة "منشئ/أستاذ رئيسي/أستاذ مادة مُكلَّف" المستعملة لبقية شاشات
    # القسم -- التنبيهات مفيدة لأي أستاذ له علاقة بالقسم، لا للأستاذ الرئيسي
    # فقط (بعكس تقرير مجلس القسم الذي يبقى أضيق عمداً).
    _ensure_can_manage_classroom_roster(session, classroom, current_user)
    term = session.get(Term, term_id)
    if not term or term.is_deleted:
        raise HTTPException(status_code=404, detail="الفصل الدراسي غير موجود")

    students = session.exec(
        select(Student).where(Student.classroom_id == classroom_id, Student.is_deleted == False)  # noqa: E712
    ).all()
    student_name = {s.id: f"{s.first_name} {s.last_name}" for s in students}

    # -- غياب/تأخر متكرر --
    events_with_sessions = session.exec(
        select(SessionEvent, ClassSession)
        .join(ClassSession, SessionEvent.session_id == ClassSession.id)  # type: ignore[arg-type]
        .where(
            ClassSession.classroom_id == classroom_id,
            ClassSession.date >= term.start_date,
            ClassSession.date <= term.end_date,
            SessionEvent.event_type.in_([SessionEventType.attendance_absent, SessionEventType.tardiness]),
            SessionEvent.is_deleted == False,  # noqa: E712
        )
    ).all()
    absence_counts: dict[str, int] = defaultdict(int)
    for event, _cs in events_with_sessions:
        absence_counts[event.student_id] += 1
    repeated_absence = [
        RepeatedAbsenceAlert(student_id=sid, full_name=student_name[sid], absence_count=count)
        for sid, count in absence_counts.items()
        if count >= min_absences and sid in student_name  # sid in student_name excludes a since-removed/transferred student
    ]
    repeated_absence.sort(key=lambda a: a.absence_count, reverse=True)

    # -- كراس لم يُفحص منذ مدة --
    student_ids = list(student_name.keys())
    checks = (
        session.exec(
            select(NotebookCheck).where(
                NotebookCheck.student_id.in_(student_ids),  # type: ignore[union-attr]
                NotebookCheck.check_date >= term.start_date,
                NotebookCheck.check_date <= term.end_date,
                NotebookCheck.is_deleted == False,  # noqa: E712
            )
        ).all()
        if student_ids
        else []
    )
    last_check_date: dict[str, str] = {}
    for check in checks:
        if check.student_id not in last_check_date or check.check_date > last_check_date[check.student_id]:
            last_check_date[check.student_id] = check.check_date

    today = date.today()
    stale_notebooks: list[StaleNotebookAlert] = []
    for sid, full_name in student_name.items():
        last = last_check_date.get(sid)
        if last is None:
            stale_notebooks.append(
                StaleNotebookAlert(student_id=sid, full_name=full_name, last_check_date=None, days_since_check=None)
            )
            continue
        days_since = (today - date.fromisoformat(last)).days
        if days_since >= notebook_stale_days:
            stale_notebooks.append(
                StaleNotebookAlert(student_id=sid, full_name=full_name, last_check_date=last, days_since_check=days_since)
            )

    def _stale_sort_key(alert: StaleNotebookAlert) -> tuple[int, int]:
        # لم يُفحَص إطلاقاً (الأشد إلحاحاً) أولاً، ثم الأقدم فحصاً فالأحدث.
        if alert.days_since_check is None:
            return (0, 0)
        return (1, -alert.days_since_check)

    stale_notebooks.sort(key=_stale_sort_key)

    # -- فروض/اختبارات ناقصة العلامات --
    assessments = session.exec(
        select(Assessment).where(
            Assessment.classroom_id == classroom_id,
            Assessment.date >= term.start_date,
            Assessment.date <= term.end_date,
            Assessment.is_deleted == False,  # noqa: E712
        )
    ).all()
    total_students = len(students)
    ungraded_assessments: list[UngradedAssessmentAlert] = []
    for assessment in assessments:
        scores = session.exec(
            select(AssessmentScore).where(
                AssessmentScore.assessment_id == assessment.id,
                AssessmentScore.is_deleted == False,  # noqa: E712
            )
        ).all()
        missing = total_students - len(scores)
        if missing > 0:
            ungraded_assessments.append(
                UngradedAssessmentAlert(
                    assessment_id=assessment.id,
                    title=assessment.title,
                    subject_id=assessment.subject_id,
                    date=assessment.date,
                    missing_count=missing,
                    total_students=total_students,
                )
            )
    ungraded_assessments.sort(key=lambda a: a.date, reverse=True)

    return ClassroomAlerts(
        classroom_id=classroom_id,
        term_id=term_id,
        repeated_absence=repeated_absence,
        stale_notebooks=stale_notebooks,
        ungraded_assessments=ungraded_assessments,
    )
