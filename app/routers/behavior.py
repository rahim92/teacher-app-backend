"""علامة السلوك -- an auto-computed 0-20 continuous-assessment grade
(المراقبة المستمرة) from the taps a teacher already makes during class, so
nobody has to tally them by hand at term's end. This is the same score the
"المتابعة المستمرة" screen shows (the two used to be two separate home-screen
tiles pointing at the exact same view -- one has since been removed as a
pure duplicate, see docs/data_model.md §34).

The category set and every weight below are NOT a documented-but-adjustable
guess -- they're copied directly from an official كشف تنقيط المراقبة
المستمرة (continuous-assessment scoring sheet) the user provided, which
groups its nine /20 columns into three sections:

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

Every category falls into exactly one of three scoring shapes:

  - penalty_score (conduct, attendance, materials): full marks by default,
    -0.5 per negative/exception tap, floored at 0. A student with zero taps
    gets full marks automatically -- see the Quick Tap panel in
    classroom_dashboard.html, which only offers the exception-side tap for
    these categories for exactly this reason.
  - bonus_score (participation, homework/"أعمال إضافية", teamwork,
    initiative): the mirror image -- ZERO by default, +0.5 per positive tap,
    capped at the category max. These four used to be a mix of inconsistent
    shapes (participation/initiative computed as a ratio against an assumed
    per-term tap target; homework/teamwork were actually penalty categories
    reading the *missing*/*negative* tap) -- a teacher's explicit
    instruction unified all four to the same flat "+0.5 per positive tap,
    capped" rule, which also flips which SessionEventType each of
    homework/teamwork reads: homework now reads `homework_done` (not
    `homework_missing`) and teamwork now reads `teamwork_positive` (not
    `teamwork_negative`). See docs/data_model.md §34.
  - quality_latest_score (notebook only, تنظيم الكراس): the quality rating
    from the MOST RECENT notebook check this term (NotebookCheck.quality,
    see models/student.py), not an average -- this category reflects the
    notebook's current state, so an old weaker check must not keep dragging
    the score down after a later check found it organized. Explicit
    correction requested by the teacher (§43) after the opposite
    (term-wide-average) behaviour misrepresented an already-fixed notebook.
  - quality_average_score (writing/الكتابة only): the average quality
    rating across every periodic check this term (NotebookCheck.
    writing_quality) -- deliberately still cumulative, unlike notebook
    organization above: "الكتابة" tracks accumulated board/notebook work
    over the whole term, not a single current state.
  Both default to full marks with zero checks this term (no evidence
  against the student yet), same rationale as penalty_score's default.
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
from app.routers.students import _ensure_can_manage_classroom_roster
from app.schemas.behavior import BehaviorCategoryScore, BehaviorScore, BehaviorWeights, BehaviorWeightsRead

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
# Not part of the official sheet (it has no per-tap conversion to mirror),
# so this stays a documented, adjustable constant: how many points one
# positive/negative tap is worth, shared by every tap-based category
# (bonus and penalty alike) -- the same 0.5/tap the official sheet's own
# +٥/-٥ half-point granularity already implies for "الغيابات والتأخيرات".
POINTS_PER_TAP = 0.5

# Classroom.weight_* column name for each DEFAULT_WEIGHTS/BehaviorWeights key.
_WEIGHT_COLUMNS = {
    "conduct": "weight_conduct",
    "attendance": "weight_attendance",
    "materials": "weight_materials",
    "notebook": "weight_notebook",
    "participation": "weight_participation",
    "writing": "weight_writing",
    "homework": "weight_homework",
    "teamwork": "weight_teamwork",
    "initiative": "weight_initiative",
}


def _classroom_custom_weights(classroom: Classroom) -> dict | None:
    """A classroom's saved weight override (§37), or None if it has never
    saved one. All nine columns are written together by the PUT endpoint
    below and never partially (see Classroom.weight_* docstring), so any one
    of them being unset means "no override at all", not a partial one.
    """
    values = {key: getattr(classroom, column) for key, column in _WEIGHT_COLUMNS.items()}
    if any(v is None for v in values.values()):
        return None
    return values


def compute_behavior_score(
    session: Session,
    student_id: str,
    classroom_id: str,
    term_id: str,
    weights: dict | None = None,
) -> BehaviorScore:
    """The actual computation behind GET /students/{id}/behavior-score,
    factored out so other modules (grades.py, for the new subject-term
    average; council.py) can get a student's continuous-assessment total
    without an HTTP round-trip. `weights` is resolved in priority order when
    not passed explicitly: an explicit override (the query-params on the
    standalone endpoint below) beats the classroom's saved settings (§37,
    `PUT /classrooms/{id}/behavior-weights`) beats DEFAULT_WEIGHTS (the
    official split) -- so grades.py/council.py, which never pass `weights`
    at all, automatically honor whatever a classroom has saved, exactly like
    the standalone endpoint does when called with no query params.
    """
    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    term = session.get(Term, term_id)
    if not term or term.is_deleted:
        raise HTTPException(status_code=404, detail="الفصل الدراسي غير موجود")

    weights = weights or _classroom_custom_weights(classroom) or DEFAULT_WEIGHTS

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

    def penalty_score(negative_keys, max_points: float, penalty_per_tap: float = POINTS_PER_TAP) -> float:
        # Accepts one event-type key or several (e.g. attendance combines
        # attendance_absent + tardiness into a single official column) --
        # every matching tap counts toward the same deduction. Full marks
        # by default (zero taps), floored at 0 how ever many taps pile up.
        if isinstance(negative_keys, str):
            negative_keys = (negative_keys,)
        taps = sum(counts.get(k, 0) for k in negative_keys)
        return max(0.0, max_points - min(max_points, taps * penalty_per_tap))

    def bonus_score(positive_key: str, max_points: float, bonus_per_tap: float = POINTS_PER_TAP) -> float:
        # The mirror image of penalty_score: ZERO by default (no evidence of
        # the positive behaviour yet), +0.5 per tap, capped at max_points
        # how ever many taps pile up. Used for every category that used to
        # be either penalty-shaped on the wrong (missing/negative) tap, or a
        # per-term-target ratio -- both replaced by this single flat rule
        # per the teacher's explicit instruction (see module docstring).
        taps = counts.get(positive_key, 0)
        return min(max_points, taps * bonus_per_tap)

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

    def quality_latest_score(quality_of, max_points: float) -> float:
        # "تنظيم الكراس" reflects the notebook's CURRENT state -- only the
        # most recent check this term, not an average of every check made
        # so far. Explicit correction requested by the teacher: an earlier,
        # weaker check was dragging the score down even after the notebook
        # had since become "منظَّم", which misrepresents its present state
        # (unlike "الكتابة", a genuinely cumulative dorsal-work rubric that
        # intentionally stays averaged via quality_average_score above).
        # Ties on check_date (two checks logged the same calendar day) break
        # on created_at -- the one entered later wins, same "most current
        # information available" rule.
        dated = [(c.check_date, c.created_at, quality_of(c)) for c in notebook_checks if quality_of(c) is not None]
        if not dated:
            return max_points  # no evidence yet this term -- same full-marks-by-default rule as every other category
        dated.sort(key=lambda row: (row[0], row[1]))
        latest_quality = dated[-1][2]
        return max_points * quality_weight[latest_quality]

    notebook_points = quality_latest_score(lambda c: c.quality, weights["notebook"])
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
            points_earned=round(bonus_score("participation", weights["participation"]), 2),
            points_max=weights["participation"],
        ),
        BehaviorCategoryScore(
            category="writing", label_ar=LABELS_AR["writing"],
            points_earned=round(writing_points, 2), points_max=weights["writing"],
        ),
        # -- المردود خارج القسم --
        BehaviorCategoryScore(
            category="homework", label_ar=LABELS_AR["homework"],
            points_earned=round(bonus_score("homework_done", weights["homework"]), 2),
            points_max=weights["homework"],
        ),
        BehaviorCategoryScore(
            category="teamwork", label_ar=LABELS_AR["teamwork"],
            points_earned=round(bonus_score("teamwork_positive", weights["teamwork"]), 2),
            points_max=weights["teamwork"],
        ),
        BehaviorCategoryScore(
            category="initiative", label_ar=LABELS_AR["initiative"],
            points_earned=round(bonus_score("initiative_shown", weights["initiative"]), 2),
            points_max=weights["initiative"],
        ),
    ]

    total = round(sum(b.points_earned for b in breakdown), 2)
    total_max = round(sum(b.points_max for b in breakdown), 2)

    return BehaviorScore(
        student_id=student_id, classroom_id=classroom_id, term_id=term_id,
        total=total, total_max=total_max, breakdown=breakdown,
    )


@router.get("/students/{student_id}/behavior-score", response_model=BehaviorScore)
def get_behavior_score(
    student_id: str,
    classroom_id: str,
    term_id: str,
    # None (not DEFAULT_WEIGHTS) by default -- so we can tell "caller didn't
    # ask for an override" apart from "caller explicitly wants the official
    # default", and let a classroom's saved §37 settings apply in the first
    # case exactly like every other caller of compute_behavior_score. A
    # caller may still override just one or two categories; the rest fall
    # back to the classroom's saved weights (or DEFAULT_WEIGHTS), not to a
    # silently-reset official value for the categories it didn't mention.
    w_conduct: float | None = Query(default=None),
    w_attendance: float | None = Query(default=None),
    w_materials: float | None = Query(default=None),
    w_notebook: float | None = Query(default=None),
    w_participation: float | None = Query(default=None),
    w_writing: float | None = Query(default=None),
    w_homework: float | None = Query(default=None),
    w_teamwork: float | None = Query(default=None),
    w_initiative: float | None = Query(default=None),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
) -> BehaviorScore:
    overrides = {
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
    overrides = {k: v for k, v in overrides.items() if v is not None}
    weights = None
    if overrides:
        classroom = session.get(Classroom, classroom_id)
        base = (_classroom_custom_weights(classroom) if classroom else None) or DEFAULT_WEIGHTS
        weights = {**base, **overrides}
    return compute_behavior_score(session, student_id, classroom_id, term_id, weights)


@router.get("/classrooms/{classroom_id}/behavior-weights", response_model=BehaviorWeightsRead)
def get_behavior_weights(
    classroom_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BehaviorWeightsRead:
    """§37: the settings screen reads this to show either the classroom's
    saved override or the official defaults (with is_custom telling it
    which, so it can show a "قيم افتراضية" vs "قيم مخصَّصة" indicator)."""
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_manage_classroom_roster(session, classroom, current_user)
    custom = _classroom_custom_weights(classroom)
    return BehaviorWeightsRead(is_custom=custom is not None, **(custom or DEFAULT_WEIGHTS))


@router.put("/classrooms/{classroom_id}/behavior-weights", response_model=BehaviorWeightsRead)
def update_behavior_weights(
    classroom_id: str,
    payload: BehaviorWeights,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> BehaviorWeightsRead:
    """Saves all nine category maxima together (never a partial update --
    see Classroom.weight_* docstring). Every future behavior-score
    computation for this classroom (the standalone endpoint with no query
    overrides, grades.py, council.py) picks this up automatically through
    compute_behavior_score's fallback chain."""
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_manage_classroom_roster(session, classroom, current_user)

    values = payload.model_dump()
    if any(v < 0 for v in values.values()):
        raise HTTPException(status_code=400, detail="لا يمكن أن تكون علامة أي خانة سالبة")
    total = sum(values.values())
    if abs(total - 20.0) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"مجموع الخانات التسع يجب أن يساوي 20 تماماً (المجموع الحالي: {round(total, 2)})",
        )

    for key, column in _WEIGHT_COLUMNS.items():
        setattr(classroom, column, values[key])
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return BehaviorWeightsRead(is_custom=True, **values)


@router.delete("/classrooms/{classroom_id}/behavior-weights", status_code=204)
def reset_behavior_weights(
    classroom_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Reverts to the official split -- e.g. after experimenting with a
    custom split that turned out not to fit. Soft-reset (NULLs all nine
    columns) rather than deleting the Classroom row, obviously."""
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_manage_classroom_roster(session, classroom, current_user)
    for column in _WEIGHT_COLUMNS.values():
        setattr(classroom, column, None)
    session.add(classroom)
    session.commit()
