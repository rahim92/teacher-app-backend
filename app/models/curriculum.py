from typing import Optional

from sqlmodel import Field

from app.models.common import GradeLevel, SyncableModel, UnitType


class CurriculumUnit(SyncableModel, table=True):
    """Reference tree: sequence -> unit -> skill/competency.

    This is centrally curated (from the official ministry documents) and
    shipped/downloaded per subject+grade, NOT edited freely by individual
    teachers. Teachers only choose their subject/grade and get this pre-filled.
    """

    __tablename__ = "curriculum_units"

    subject_id: str = Field(foreign_key="subjects.id", index=True)
    grade_level: GradeLevel
    parent_unit_id: Optional[str] = Field(default=None, foreign_key="curriculum_units.id")
    title: str
    unit_type: UnitType
    order_index: int = Field(default=0)
    year_version: str  # e.g. "2025-2026" -- curricula get revised over time


class AnnualPlan(SyncableModel, table=True):
    """A teacher's personal pacing plan for one subject+grade+year.

    One plan can serve several parallel classrooms taught by the same teacher.
    """

    __tablename__ = "annual_plans"

    teacher_id: str = Field(foreign_key="users.id", index=True)
    subject_id: str = Field(foreign_key="subjects.id")
    grade_level: GradeLevel
    academic_year_id: str = Field(foreign_key="academic_years.id")


class PlanItem(SyncableModel, table=True):
    __tablename__ = "plan_items"

    annual_plan_id: str = Field(foreign_key="annual_plans.id", index=True)
    curriculum_unit_id: str = Field(foreign_key="curriculum_units.id")
    target_week_number: int
    order_index: int = Field(default=0)
