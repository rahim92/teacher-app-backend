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


class BehaviorWeights(BaseModel):
    """The nine official-sheet category maxima, always all nine together --
    see Classroom.weight_* in app/models/identity.py for why there is no
    partial-override shape."""

    conduct: float
    attendance: float
    materials: float
    notebook: float
    participation: float
    writing: float
    homework: float
    teamwork: float
    initiative: float


class BehaviorWeightsRead(BehaviorWeights):
    is_custom: bool  # False => these are DEFAULT_WEIGHTS, not a saved override
