from typing import Optional

from pydantic import BaseModel

from app.models.common import GradeLevel, UnitType


class CurriculumUnitRead(BaseModel):
    id: str
    subject_id: str
    grade_level: GradeLevel
    parent_unit_id: Optional[str] = None
    title: str
    unit_type: UnitType
    order_index: int
    year_version: str


class AnnualPlanCreate(BaseModel):
    subject_id: str
    grade_level: GradeLevel
    academic_year_id: str


class AnnualPlanRead(AnnualPlanCreate):
    id: str
    teacher_id: str


class PlanItemCreate(BaseModel):
    annual_plan_id: str
    curriculum_unit_id: str
    target_week_number: int
    order_index: int = 0


class PlanItemRead(PlanItemCreate):
    id: str
