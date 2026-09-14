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


class SubjectGradeTrendPoint(BaseModel):
    """One term's SubjectTermGrade, reshaped for charting -- same four grade
    fields as SubjectTermGrade plus the term's own label/ordering so a
    frontend can plot them left-to-right without a second lookup.
    """

    term_id: str
    term_label: str
    order_index: int
    continuous_assessment: float
    test_average: Optional[float] = None
    exam_average: Optional[float] = None
    average: Optional[float] = None


class SubjectGradeTrend(BaseModel):
    """مخطط تطور المعدل عبر الفصول -- one student's subject-grade history
    across every term of the classroom's academic year, ordered by
    Term.order_index. Built by calling grades.compute_subject_term_grade
    once per term (never a separate averaging implementation), so a term
    shown here can never disagree with what /students/{id}/subject-grade
    reports for that same term. A term with no فرض/اختبار graded yet simply
    carries `average=None` at its position -- still returned (not skipped),
    so a chart can render a gap rather than silently compressing the axis.
    """

    student_id: str
    classroom_id: str
    subject_id: str
    subject_name: str
    points: list[SubjectGradeTrendPoint]
