from typing import Optional

from sqlmodel import Field

from app.models.common import LessonLogType, SessionEventType, SessionStatus, SyncableModel


class ClassSession(SyncableModel, table=True):
    """One lesson period. Opened at the start of class, closed at the end --
    closing it is what prompts the teacher to log the LessonLog entry.
    """

    __tablename__ = "class_sessions"

    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    teacher_id: str = Field(foreign_key="users.id", index=True)
    subject_id: str = Field(foreign_key="subjects.id")
    date: str  # ISO date
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    status: SessionStatus = Field(default=SessionStatus.open)


class SessionEvent(SyncableModel, table=True):
    """A single quick-tap event: attendance, tardiness, behavior, homework,
    participation. This one table powers the whole 'continuous monitoring
    notebook' -- the per-student and per-classroom ledgers are just
    read/aggregation views over this table, not separate storage.
    """

    __tablename__ = "session_events"

    session_id: str = Field(foreign_key="class_sessions.id", index=True)
    student_id: str = Field(foreign_key="students.id", index=True)
    event_type: SessionEventType
    value: Optional[float] = None  # e.g. minutes late for `tardiness`
    note: Optional[str] = None
    device_id: Optional[str] = None  # for multi-device conflict diagnostics


class LessonLog(SyncableModel, table=True):
    """The digital 'cahier de textes' -- what was actually taught.

    `domain` (الميدان) and `segment` (المقطع/الوحدة) are free text, typed by
    the teacher on every entry -- NOT derived from the CurriculumUnit tree.
    This was a deliberate reversal of the original design (which tried to
    make CurriculumUnit the single source of truth for these two levels):
    the Algerian middle-school curriculum uses genuinely different
    terminology and structure per subject (e.g. Maths: "ميدان / مقطع تعلمي /
    مورد معرفي"؛ Arabic: "ميدان / مقطع / سند"؛ French: "مشروع (Projet) / مقطع
    (Séquence) / سند (Support)"؛ Civic education: "ميدان / مركبة تعلمية /
    سند" -- confirmed against Algerian "الجيل الثاني" curriculum documents),
    so no single fixed tree can represent all of them, and a subject-specific
    "المورد" in particular has many valid values per مقطع depending on which
    resource the teacher actually used that day. `curriculum_unit_id` stays
    as an OPTIONAL secondary link (not shown as required in the rich journal
    screen) purely for teachers who also want the automatic progress/delay
    indicator that compares this log against the planned pacing
    (AnnualPlan/PlanItem) -- domain/segment/resource carry no such
    comparison, they are descriptive only.

    `lesson_title` (عنوان الدرس) replaces the old `resource` field (kept as a
    dead column in the DB, no longer read/written -- no real data existed in
    it yet so a straight functional replacement was safe): a teacher pointed
    out that what belongs here is the actual lesson's title/topic, not a
    reference to supporting material. `completed_phases` (comma-separated
    keys, e.g. "intro,construction") records which stage(s) of the session
    were actually completed -- its meaning depends on the subject:

    - For subjects following the competency-based "وضعية-مشكلة" model (maths,
      sciences, history-geography, civic/Islamic education), it holds a
      SUBSET of a fixed 4-stage checklist: intro (تمهيد) / construction
      (البناء المعرفي) / investment (الاستثمار) / reinvestment (إعادة
      الاستثمار). Confirmed first-hand ONLY for maths (a teacher described
      the exact structure: 5-minute recall activity -> discovery activity
      from the textbook/worksheet -> teacher-guided conclusion -> 1-2
      consolidation exercises); applied as a best-effort DEFAULT to the
      other subjects in this family pending confirmation from teachers of
      those subjects (research found partial confirmation for history and
      Islamic education with slightly different wording -- see
      docs/data_model.md §33 for sources and confidence levels).
    - For language subjects (Arabic, French, English), research into real
      Algerian lesson-prep documents found this 4-stage model does NOT
      apply at all -- an actual Arabic text-comprehension lesson prep used
      completely different, content-specific headers. Language subjects
      instead get exactly ONE session-type tag from a different set:
      listening / reading / language_activities / oral_expression /
      written_expression / integration (see §33).

    Both cases reuse the same free-text column rather than two separate
    ones, since ultimately it is just "which tag(s) describe what happened
    this session" -- the UI decides which checklist to render based on the
    subject.
    """

    __tablename__ = "lesson_logs"

    session_id: Optional[str] = Field(default=None, foreign_key="class_sessions.id")
    classroom_id: str = Field(foreign_key="classrooms.id", index=True)
    teacher_id: str = Field(foreign_key="users.id")
    date: str
    lesson_type: LessonLogType = Field(default=LessonLogType.lesson)
    curriculum_unit_id: Optional[str] = Field(default=None, foreign_key="curriculum_units.id")
    domain: Optional[str] = None
    segment: Optional[str] = None
    lesson_title: Optional[str] = None
    completed_phases: Optional[str] = None
    observations: Optional[str] = None
