from fastapi import APIRouter, Depends
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
    CurriculumUnitRead,
    PlanItemCreate,
    PlanItemRead,
)

router = APIRouter(tags=["curriculum"])


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


@router.post("/plan-items", response_model=PlanItemRead)
def create_plan_item(payload: PlanItemCreate, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    item = PlanItem(**payload.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


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
        "delay_in_units": max(delay, 0),
        "status": "on_track" if delay <= 0 else ("slightly_behind" if delay <= 2 else "behind"),
    }
