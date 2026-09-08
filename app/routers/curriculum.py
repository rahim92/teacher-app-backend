from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.common import GradeLevel
from app.models.curriculum import AnnualPlan, CurriculumUnit, PlanItem
from app.models.identity import User
from app.models.session import LessonLog
from app.schemas.curriculum import (
    AnnualPlanCreate,
    AnnualPlanRead,
    CurriculumUnitCreate,
    CurriculumUnitRead,
    PlanItemCreate,
    PlanItemRead,
)

router = APIRouter(tags=["curriculum"])


@router.post("/curriculum-units", response_model=CurriculumUnitRead)
def create_curriculum_unit(
    payload: CurriculumUnitCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """MVP simplification: CurriculumUnit's own docstring describes it as a
    centrally-curated reference tree teachers only download, never author --
    but no ministry-content import pipeline exists yet, so a fresh install's
    database starts with zero units unless `seed.py` was run by hand
    directly against it. That leaves nothing to pick a "skill" from anywhere
    the diagnostic/remediation module needs one. This endpoint lets a
    teacher add their own tracked skill/unit directly until real curated
    content exists; deliberately not admin-only for that reason.
    """
    unit = CurriculumUnit(**payload.model_dump())
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


@router.get("/curriculum-units", response_model=list[CurriculumUnitRead])
def list_curriculum_units(
    subject_id: str,
    grade_level: GradeLevel,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Returns the reference tree (sequence -> unit -> skill) for one
    subject+grade, ordered so the client can render it directly.
    """
    return session.exec(
        select(CurriculumUnit)
        .where(
            CurriculumUnit.subject_id == subject_id,
            CurriculumUnit.grade_level == grade_level,
            CurriculumUnit.is_deleted == False,  # noqa: E712
        )
        .order_by(CurriculumUnit.order_index)
    ).all()


@router.post("/annual-plans", response_model=AnnualPlanRead)
def create_annual_plan(
    payload: AnnualPlanCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    plan = AnnualPlan(**payload.model_dump(), teacher_id=current_user.id)
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


@router.get("/annual-plans", response_model=list[AnnualPlanRead])
def list_annual_plans(
    subject_id: str,
    grade_level: GradeLevel,
    academic_year_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Lets the UI check whether this teacher already has an annual plan for
    one subject+grade+year before offering to create a new one. Nothing in
    the schema enforces at-most-one-plan, so this is a UI-level convention,
    not a hard constraint -- scoped to the current teacher (teacher_id) since
    two teachers of the same subject+grade must never see each other's plan.
    """
    return session.exec(
        select(AnnualPlan).where(
            AnnualPlan.teacher_id == current_user.id,
            AnnualPlan.subject_id == subject_id,
            AnnualPlan.grade_level == grade_level,
            AnnualPlan.academic_year_id == academic_year_id,
            AnnualPlan.is_deleted == False,  # noqa: E712
        )
    ).all()


@router.post("/plan-items", response_model=PlanItemRead)
def create_plan_item(payload: PlanItemCreate, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    item = PlanItem(**payload.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.get("/annual-plans/{plan_id}/items", response_model=list[PlanItemRead])
def list_plan_items(plan_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    """Ordered by target week so the client can render the plan as a
    week-by-week pacing table directly.
    """
    return session.exec(
        select(PlanItem)
        .where(PlanItem.annual_plan_id == plan_id, PlanItem.is_deleted == False)  # noqa: E712
        .order_by(PlanItem.target_week_number, PlanItem.order_index)
    ).all()


@router.delete("/plan-items/{item_id}")
def delete_plan_item(item_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    item = session.get(PlanItem, item_id)
    if not item or item.is_deleted:
        raise HTTPException(status_code=404, detail="عنصر الخطة غير موجود")
    item.is_deleted = True
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    return {"ok": True}


@router.get("/annual-plans/{plan_id}/progress")
def get_plan_progress(
    plan_id: str,
    classroom_id: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Compares planned pacing (PlanItem count) against actually-delivered
    lessons (LessonLog count) for one classroom following this plan, and
    returns a simple delay indicator in number of lessons.

    Also returns `delivered_unit_ids` so the client can mark each individual
    plan item as delivered/pending in the pacing table, instead of only
    showing one aggregate number.
    """
    planned_units = session.exec(
        select(PlanItem).where(PlanItem.annual_plan_id == plan_id, PlanItem.is_deleted == False)  # noqa: E712
    ).all()
    delivered_unit_ids = {
        row.curriculum_unit_id
        for row in session.exec(
            select(LessonLog).where(LessonLog.classroom_id == classroom_id, LessonLog.is_deleted == False)  # noqa: E712
        ).all()
    }
    planned_unit_ids = {p.curriculum_unit_id for p in planned_units}
    delivered_count = len(planned_unit_ids & delivered_unit_ids)
    delay = len(planned_unit_ids) - delivered_count

    return {
        "planned_total": len(planned_unit_ids),
        "delivered_count": delivered_count,
        "delivered_unit_ids": sorted(planned_unit_ids & delivered_unit_ids),
        "delay_in_units": max(delay, 0),
        "status": "on_track" if delay <= 0 else ("slightly_behind" if delay <= 2 else "behind"),
    }
