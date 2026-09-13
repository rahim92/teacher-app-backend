from typing import Optional

from pydantic import BaseModel


class SubjectTermGrade(BaseModel):
    """معدل المادة الفصلي -- one subject's trimester average for one student,
    combining the auto-computed continuous-assessment score (see
    behavior.compute_behavior_score) with فرض/اختبار grades (Assessment /
    AssessmentScore) using the official formula the user specified:

        المعدل = ( (المراقبة المستمرة + معدل الفروض) / 2 + معدل الاختبار × 2 ) / 3

    `continuous_assessment` is always populated (it defaults to full marks
    with zero taps, same as behavior-score). `test_average`/`exam_average`
    are None until at least one AssessmentScore of that type exists for this
    subject/classroom/term/student -- and `average` itself stays None until
    BOTH are available, on purpose: presenting a "final average" built from
    the continuous score alone, before any فرض/اختبار has even been graded,
    would be misleading rather than merely incomplete. The three components
    are still returned individually so a screen can show partial progress.
    """

    student_id: str
    classroom_id: str
    subject_id: str
    term_id: str
    continuous_assessment: float
    test_average: Optional[float] = None
    exam_average: Optional[float] = None
    average: Optional[float] = None
