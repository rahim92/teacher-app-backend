"""علامة السلوك -- an auto-computed 0-20 behaviour grade from the taps a
teacher already makes during المراقبة المستمرة, so nobody has to tally them
by hand at term's end.

The category set (conduct, unexcused absence, tardiness, materials brought,
participation, teamwork, notebook care, initiative, homework/task
completion) mirrors the categories named in Algeria's December-2020 report
-card reform. The exact point-value per category has genuinely changed
across ministerial circulars (our research turned up inconsistent totals
across sources), so we deliberately do NOT hardcode one "official" split --
DEFAULT_WEIGHTS below is a reasonable default that sums to 20, and every
weight can be overridden per request via query params (a settings screen in
the app can let a teacher persist their own split locally and pass it every
call). The tap-count -> sub-score conversion (targets like "8 participation
taps = full marks") is likewise a documented, adjustable assumption, not a
ministry formula -- no official per-tap conversion exists to mirror.
"""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.common import NotebookQuality
from app.models.identity import Classroom, Term, User
from app.models.session import ClassSession, SessionEvent
from app.models.student import NotebookCheck, Student
from app.schemas.behavior import BehaviorCategoryScore, BehaviorScore

router = APIRouter(tags=["behavior"])

DEFAULT_WEIGHTS = {
    "conduct": 3.0,
    "absence": 2.0,
    "tardiness": 2.0,
    "materials": 2.0,
    "participation": 2.0,
    "teamwork": 2.0,
    "notebook": 2.0,
    "initiative": 2.0,
    "homework": 3.0,
}
LABELS_AR = {
    "conduct": "السلوك العام",
    "absence": "الغياب غير المبرر",
    "tardiness": "التأخر",
    "materials": "إحضار الأدوات",
    "participation": "المشاركة",
    "teamwork": "العمل الجماعي",
    "notebook": "تنظيم الكراس",
    "initiative": "المبادرة والمساهمة",
    "homework": "الفعالية وإنجاز المهام",
}
# Assumed "full marks" tap counts per term for the categories that have no
# natural done/missing ratio -- adjust here if a term's rhythm differs.
PARTICIPATION_TARGET = 8
INITIATIVE_TARGET = 3


@router.get("/students/{student_id}/behavior-score", response_model=BehaviorScore)
def get_behavior_score(
    student_id: str,
    classroom_id: str,
    term_id: str,
    w_conduct: float = Query(default=DEFAULT_WEIGHTS["conduct"]),
    w_absence: float = Query(default=DEFAULT_WEIGHTS["absence"]),
    w_tardiness: float = Query(default=DEFAULT_WEIGHTS["tardiness"]),
    w_materials: float = Query(default=DEFAULT_WEIGHTS["materials"]),
    w_participation: float = Query(default=DEFAULT_WEIGHTS["participation"]),
    w_teamwork: float = Query(default=DEFAULT_WEIGHTS["teamwork"]),
    w_notebook: float = Query(default=DEFAULT_WEIGHTS["notebook"]),
    w_initiative: float = Query(default=DEFAULT_WEIGHTS["initiative"]),
    w_homework: float = Query(default=DEFAULT_WEIGHTS["homework"]),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    weights = {
        "conduct": w_conduct,
        "absence": w_absence,
        "tardiness": w_tardiness,
        "materials": w_materials,
        "participation": w_participation,
        "teamwork": w_teamwork,
        "notebook": w_notebook,
        "initiative": w_initiative,
        "homework": w_homework,
    }

    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    term = session.get(Term, term_id)
    if not term or term.is_deleted:
        raise HTTPException(status_code=404, detail="الفصل الدراسي غير موجود")

    # Cross-teacher taps by design: like the council report, "السلوك" is a
    # single combined grade covering the student's whole classroom conduct,
    # not one subject's -- and /students/{id}/ledger already exposes every
    # teacher's taps for a student with no extra gate, so this follows the
    # same MVP permission shape rather than introducing a new one.
    events_with_sessions = session.exec(
        select(SessionEvent, ClassSession)
        .join(ClassSession, SessionEvent.session_id == ClassSession.id)  # type: ignore[arg-type]
        .where(
            ClassSession.classroom_id == classroom_id,
            SessionEvent.student_id == student_id,
            ClassSession.date >= term.start_date,
            ClassSession.date <= term.end_date,
            SessionEvent.is_deleted == False,  # noqa: E712
        )
    ).all()

    counts: dict[str, int] = defaultdict(int)
    for event, _cs in events_with_sessions:
        counts[event.event_type] += 1

    notebook_checks = session.exec(
        select(NotebookCheck).where(
            NotebookCheck.student_id == student_id,
            NotebookCheck.check_date >= term.start_date,
            NotebookCheck.check_date <= term.end_date,
            NotebookCheck.is_deleted == False,  # noqa: E712
        )
    ).all()

    def ratio_score(done_key: str, missing_key: str, max_points: float) -> float:
        done, missing = counts.get(done_key, 0), counts.get(missing_key, 0)
        total = done + missing
        return max_points if total == 0 else max_points * done / total

    def penalty_score(negative_key: str, max_points: float, penalty_per_tap: float = 0.5) -> float:
        return max(0.0, max_points - min(max_points, counts.get(negative_key, 0) * penalty_per_tap))

    def target_score(key: str, target: int, max_points: float) -> float:
        return max_points * min(1.0, counts.get(key, 0) / target) if target else max_points

    notebook_points = weights["notebook"]
    if notebook_checks:
        quality_weight = {NotebookQuality.organized: 1.0, NotebookQuality.average: 0.5, NotebookQuality.neglected: 0.0}
        notebook_points = weights["notebook"] * (
            sum(quality_weight[c.quality] for c in notebook_checks) / len(notebook_checks)
        )

    breakdown = [
        BehaviorCategoryScore(
            category="conduct", label_ar=LABELS_AR["conduct"],
            points_earned=round(penalty_score("behavior_negative", weights["conduct"]), 2), points_max=weights["conduct"],
        ),
        BehaviorCategoryScore(
            category="absence", label_ar=LABELS_AR["absence"],
            points_earned=round(penalty_score("attendance_absent", weights["absence"]), 2), points_max=weights["absence"],
        ),
        BehaviorCategoryScore(
            category="tardiness", label_ar=LABELS_AR["tardiness"],
            points_earned=round(penalty_score("tardiness", weights["tardiness"]), 2), points_max=weights["tardiness"],
        ),
        BehaviorCategoryScore(
            category="materials", label_ar=LABELS_AR["materials"],
            points_earned=round(ratio_score("equipment_brought", "equipment_missing", weights["materials"]), 2),
            points_max=weights["materials"],
        ),
        BehaviorCategoryScore(
            category="participation", label_ar=LABELS_AR["participation"],
            points_earned=round(target_score("participation", PARTICIPATION_TARGET, weights["participation"]), 2),
            points_max=weights["participation"],
        ),
        BehaviorCategoryScore(
            category="teamwork", label_ar=LABELS_AR["teamwork"],
            points_earned=round(ratio_score("teamwork_positive", "teamwork_negative", weights["teamwork"]), 2),
            points_max=weights["teamwork"],
        ),
        BehaviorCategoryScore(
            category="notebook", label_ar=LABELS_AR["notebook"],
            points_earned=round(notebook_points, 2), points_max=weights["notebook"],
        ),
        BehaviorCategoryScore(
            category="initiative", label_ar=LABELS_AR["initiative"],
            points_earned=round(target_score("initiative_shown", INITIATIVE_TARGET, weights["initiative"]), 2),
            points_max=weights["initiative"],
        ),
        BehaviorCategoryScore(
            category="homework", label_ar=LABELS_AR["homework"],
            points_earned=round(ratio_score("homework_done", "homework_missing", weights["homework"]), 2),
            points_max=weights["homework"],
        ),
    ]

    total = round(sum(b.points_earned for b in breakdown), 2)
    total_max = round(sum(b.points_max for b in breakdown), 2)

    return BehaviorScore(
        student_id=student_id, classroom_id=classroom_id, term_id=term_id,
        total=total, total_max=total_max, breakdown=breakdown,
    )
