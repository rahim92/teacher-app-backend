from pydantic import BaseModel


class BehaviorCategoryScore(BaseModel):
    category: str  # machine key, e.g. "materials"
    label_ar: str  # e.g. "إحضار الأدوات"
    points_earned: float
    points_max: float


class BehaviorScore(BaseModel):
    student_id: str
    classroom_id: str
    term_id: str
    total: float
    total_max: float
    breakdown: list[BehaviorCategoryScore]
