"""علامة السلوك -- an auto-computed 0-20 continuous-assessment grade
(المراقبة المستمرة) from the taps a teacher already makes during class, so
nobody has to tally them by hand at term's end.

Unlike the earlier version of this file, the category set and every weight
below are NOT a documented-but-adjustable guess -- they're copied directly
from an official كشف تنقيط المراقبة المستمرة (continuous-assessment scoring
sheet) the user provided, which groups its nine /20 columns into three
sections:

  الانضباط والمواظبة (discipline & attendance) -- 7ن
    السلوك (conduct) 2ن، الغيابات والتأخيرات (absence+tardiness, ONE column
    on the official sheet, not two) 2ن، إحضار الأدوات (materials) 2ن،
    تنظيم الكراس (notebook organization) 1ن
  المردود داخل القسم (in-class performance) -- 7ن
    المشاركة (participation) 2ن + الفعالية (مناقشة تحليل..) 3ن -- merged
    into one "participation" category per the user's explicit choice, so
    5ن total -- والكتابة (السبورة والكراس) (writing quality) 2ن
  المردود خارج القسم (out-of-class performance) -- 6ن
    أعمال إضافية (additional work) 3ن، العمل ضمن فريق (teamwork) 2ن،
    المبادرة والمساهمة (initiative) 1ن

7 + 7 + 6 = 20. DEFAULT_WEIGHTS still exists as override points (a settings
screen could let a teacher deviate from the official split), but the
defaults themselves now ARE the official ones, not a placeholder.

Every category is "full marks by default, deducted per negative tap"
(penalty_score) except participation/writing/initiative, which have no
natural negative reading of silence and are earned instead:
participation/initiative from a positive tap count against a per-term
target (target_score), writing/notebook from the average quality recorded
during periodic notebook checks (see NotebookCheck.writing_quality/quality
and models/student.py). A student with zero taps/checks in a category
gets full marks for it automatically -- see the Quick Tap panel in
classroom_dashboard.html, which only offers the exception-side tap for
each penalty_score category for exactly this reason.
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
    "conduct": 2.0,
    "attendance": 2.0,
    "materials": 2.0,
    "notebook": 1.0,
    "participation": 5.0,
    "writing": 2.0,
    "homework": 3.0,
    "teamwork": 2.0,
    "initiative": 1.0,
}
LABELS_AR = {
    "conduct": "السلوك",
    "attendance": "الغيابات والتأخيرات",
    "materials": "إحضار الأدوات",
    "notebook": "تنظيم الكراس",
    "participation": "المشاركة والفعالية",
    "writing": "الكتابة (السبورة والكراس)",
    "homework": "أعمال إضافية",
    "teamwork": "العمل ضمن فريق",
    "initiative": "المبادرة والمساهمة",
}
# Assumed "full marks" tap counts per term for the categories that have no
# natural done/missing ratio -- adjust here if a term's rhythm differs. Not
# part of the official sheet (it has no per-tap conversion to mirror), so
# this stays a documented, adjustable assumption like before.
PARTICIPATION_TARGET = 8
INITIATIVE_TARGET = 3


@router.get("/students/{student_id}/behavior-score", response_model=BehaviorScore)
def get_behavior_score(
    student_id: str,
    classroom_id: str,
    term_id: str,
    w_conduct: float = Query(default=DEFAULT_WEIGHTS["conduct"]),
    w_attendance: float = Query(default=DEFAULT_WEIGHTS["attendance"]),
    w_materials: float = Query(default=DEFAULT_WEIGHTS["materials"]),
    w_notebook: float = Query(default=DEFAULT_WEIGHTS["notebook"]),
    w_participation: float = Query(default=DEFAULT_WEIGHTS["participation"]),
    w_writing: float = Query(default=DEFAULT_WEIGHTS["writing"]),
    w_homework: float = Query(default=DEFAULT_WEIGHTS["homework"]),
    w_teamwork: float = Query(default=DEFAULT_WEIGHTS["teamwork"]),
    w_initiative: float = Query(default=DEFAULT_WEIGHTS["initiative"]),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    weights = {
        "conduct": w_conduct,
        "attendance": w_attendance,
        "materials": w_materials,
        "notebook": w_notebook,
        "participation": w_participation,
        "writing": w_writing,
        "homework": w_homework,
        "teamwork": w_teamwork,
        "initiative": w_initiative,
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

    def penalty_score(negative_keys, max_points: float, penalty_per_tap: float = 0.5) -> float:
        # Accepts one event-type key or several (e.g. attendance combines
        # attendance_absent + tardiness into a single official column) --
        # every matching tap counts toward the same deduction.
        if isinstance(negative_keys, str):
            negative_keys = (negative_keys,)
        taps = sum(counts.get(k, 0) for k in negative_keys)
        return max(0.0, max_points - min(max_points, taps * penalty_per_tap))

    def target_score(key: str, target: int, max_points: float) -> float:
        return max_points * min(1.0, counts.get(key, 0) / target) if target else max_points

    quality_weight = {NotebookQuality.organized: 1.0, NotebookQuality.average: 0.5, NotebookQuality.neglected: 0.0}

    def quality_average_score(quality_of, max_points: float) -> float:
        # Full marks by default (no checks yet this term, or none of them
        # recorded this specific dimension -- e.g. a check made before
        # writing_quality existed) rather than zero; see module docstring.
        rated = [quality_of(c) for c in notebook_checks]
        rated = [q for q in rated if q is not None]
        if not rated:
            return max_points
        return max_points * (sum(quality_weight[q] for q in rated) / len(rated))

    notebook_points = quality_average_score(lambda c: c.quality, weights["notebook"])
    writing_points = quality_average_score(lambda c: c.writing_quality, weights["writing"])

    breakdown = [
        # -- الانضباط والمواظبة --
        BehaviorCategoryScore(
            category="conduct", label_ar=LABELS_AR["conduct"],
            points_earned=round(penalty_score("behavior_negative", weights["conduct"]), 2), points_max=weights["conduct"],
        ),
        BehaviorCategoryScore(
            category="attendance", label_ar=LABELS_AR["attendance"],
            points_earned=round(penalty_score(("attendance_absent", "tardiness"), weights["attendance"]), 2),
            points_max=weights["attendance"],
        ),
        BehaviorCategoryScore(
            category="materials", label_ar=LABELS_AR["materials"],
            points_earned=round(penalty_score("equipment_missing", weights["materials"]), 2),
            points_max=weights["materials"],
        ),
        BehaviorCategoryScore(
            category="notebook", label_ar=LABELS_AR["notebook"],
            points_earned=round(notebook_points, 2), points_max=weights["notebook"],
        ),
        # -- المردود داخل القسم --
        BehaviorCategoryScore(
            category="participation", label_ar=LABELS_AR["participation"],
            points_earned=round(target_score("participation", PARTICIPATION_TARGET, weights["participation"]), 2),
            points_max=weights["participation"],
        ),
        BehaviorCategoryScore(
            category="writing", label_ar=LABELS_AR["writing"],
            points_earned=round(writing_points, 2), points_max=weights["writing"],
        ),
        # -- المردود خارج القسم --
        BehaviorCategoryScore(
            category="homework", label_ar=LABELS_AR["homework"],
            points_earned=round(penalty_score("homework_missing", weights["homework"]), 2),
            points_max=weights["homework"],
        ),
        BehaviorCategoryScore(
            category="teamwork", label_ar=LABELS_AR["teamwork"],
            points_earned=round(penalty_score("teamwork_negative", weights["teamwork"]), 2),
            points_max=weights["teamwork"],
        ),
        BehaviorCategoryScore(
            category="initiative", label_ar=LABELS_AR["initiative"],
            points_earned=round(target_score("initiative_shown", INITIATIVE_TARGET, weights["initiative"]), 2),
            points_max=weights["initiative"],
        ),
    ]

    total = round(sum(b.points_earned for b in breakdown), 2)
    total_max = round(sum(b.points_max for b in breakdown), 2)

    return BehaviorScore(
        student_id=student_id, classroom_id=classroom_id, term_id=term_id,
        total=total, total_max=total_max, breakdown=breakdown,
    )
