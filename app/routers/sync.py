"""Generic offline-first sync endpoint.

Design (see docs/data_model.md "آلية المزامنة"):
- The mobile app writes every change locally first with a UUID it generates
  itself, and queues it as a "mutation". This endpoint is where that queue
  gets replayed once the device is back online.
- Because MVP scope is a single teacher, the only possible conflict is the
  same teacher editing the same record from two devices (phone + tablet).
  That's resolved with last-write-wins on `updated_at`.
- Append-only tables (session_events, lesson_logs, assessments, ...) never
  conflict since a create is never followed by a competing update.
"""
from datetime import datetime
from typing import Optional, Type

from fastapi import APIRouter, Depends
from sqlmodel import Session, SQLModel, select

from app.auth import get_current_user
from app.database import get_session
from app.models.assessment import (
    Assessment,
    AssessmentDetail,
    AssessmentScore,
    RemediationParticipant,
    RemediationSession,
)
from app.models.common import UserRole
from app.models.curriculum import AnnualPlan, PlanItem
from app.models.identity import Classroom, ClassDelegate, TeacherClassroomAssignment, User
from app.models.messaging import ParentMessageTemplate
from app.models.session import ClassSession, LessonLog, SessionEvent
from app.models.student import NotebookCheck, SeatAssignment, Student
from app.schemas.sync import (
    SyncMutation,
    SyncMutationResult,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
)

router = APIRouter(prefix="/sync", tags=["sync"])

# Only entities a teacher plausibly creates/edits while offline in the field
# go through generic sync. Setup data (schools/subjects/curriculum) is created
# via its own endpoints during initial (online) configuration.
ENTITY_MODEL_MAP: dict[str, Type[SQLModel]] = {
    "students": Student,
    "seat_assignments": SeatAssignment,
    "annual_plans": AnnualPlan,
    "plan_items": PlanItem,
    "class_sessions": ClassSession,
    "session_events": SessionEvent,
    "lesson_logs": LessonLog,
    "assessments": Assessment,
    "assessment_scores": AssessmentScore,
    "assessment_details": AssessmentDetail,
    "remediation_sessions": RemediationSession,
    "remediation_participants": RemediationParticipant,
    "parent_message_templates": ParentMessageTemplate,
    "notebook_checks": NotebookCheck,
    "class_delegates": ClassDelegate,
    # StudentSpecialNeed is deliberately NOT synced generically -- it's
    # sensitive health/disability data about a minor with its own
    # per-row visibility rule (see routers/students.py), always fetched
    # explicitly per student rather than bulk-pulled like everything else.
}

# Fields the client is never allowed to set directly (server-controlled or
# derived) -- stripped from incoming mutation data before it's applied.
_PROTECTED_FIELDS = {"id"}

# Entities that carry `teacher_id` directly: ownership is a straight match.
# On create the field is always forced to the caller (never trusted from the
# client) so a mutation can't be pushed as authored by a different teacher;
# on update it's stripped so an owner can't reassign a record away either.
_DIRECT_TEACHER_ENTITIES = {
    "seat_assignments",
    "annual_plans",
    "class_sessions",
    "lesson_logs",
    "assessments",
    "remediation_sessions",
    "parent_message_templates",
    "notebook_checks",
}

# Entities that hang off a parent row which itself carries teacher_id --
# maps entity name -> (foreign-key field on this entity, parent model).
_PARENT_TEACHER_ENTITIES: dict[str, tuple[str, Type[SQLModel]]] = {
    "plan_items": ("annual_plan_id", AnnualPlan),
    "session_events": ("session_id", ClassSession),
    "assessment_scores": ("assessment_id", Assessment),
    "assessment_details": ("assessment_id", Assessment),
    "remediation_participants": ("remediation_session_id", RemediationSession),
}

# Entities scoped by classroom relation (creator / homeroom teacher / a live
# TeacherClassroomAssignment) -- same "does this teacher have ANY real
# relation to this classroom" rule as students.py's _ensure_can_manage_student.
_CLASSROOM_RELATION_ENTITIES = {"students", "class_delegates"}


def _classroom_relation_ok(session: Session, classroom_id: Optional[str], current_user: User) -> bool:
    if not classroom_id:
        return False
    classroom = session.get(Classroom, classroom_id)
    if not classroom:
        return False
    if classroom.teacher_id == current_user.id or classroom.homeroom_teacher_id == current_user.id:
        return True
    return (
        session.exec(
            select(TeacherClassroomAssignment).where(
                TeacherClassroomAssignment.classroom_id == classroom_id,
                TeacherClassroomAssignment.teacher_id == current_user.id,
                TeacherClassroomAssignment.is_deleted == False,  # noqa: E712
            )
        ).first()
        is not None
    )


def _ensure_mutation_allowed(session: Session, entity: str, existing, incoming_data: dict, current_user: User) -> None:
    """Mirror the ownership rule the matching REST endpoint already enforces
    for this entity, so /sync/push can't be used as a back door around it.
    `existing` is the current row for update/delete, or None for create (in
    which case ownership is resolved from the incoming mutation data).
    Raises PermissionError -- caught by push() and turned into a per-mutation
    'error' result, matching how an unsupported entity is already reported,
    rather than failing the whole batch.
    """
    if current_user.role == UserRole.admin:
        return

    if entity in _DIRECT_TEACHER_ENTITIES:
        owner_id = existing.teacher_id if existing is not None else None
        if owner_id is not None and owner_id != current_user.id:
            raise PermissionError("لا يمكنك تعديل سجل يخص أستاذاً آخر.")
        return

    if entity in _PARENT_TEACHER_ENTITIES:
        fk_field, parent_model = _PARENT_TEACHER_ENTITIES[entity]
        parent_id = getattr(existing, fk_field, None) if existing is not None else incoming_data.get(fk_field)
        parent = session.get(parent_model, parent_id) if parent_id else None
        if parent is None or parent.teacher_id != current_user.id:
            raise PermissionError("لا يمكنك تعديل سجل تابع لمورد لا تملكه.")
        return

    if entity == "class_delegates":
        classroom_id = existing.classroom_id if existing is not None else incoming_data.get("classroom_id")
        classroom = session.get(Classroom, classroom_id) if classroom_id else None
        if not classroom or classroom.homeroom_teacher_id != current_user.id:
            raise PermissionError("تسجيل/حذف مندوبي القسم متاح فقط للأستاذ الرئيسي أو الإدارة.")
        return

    if entity in _CLASSROOM_RELATION_ENTITIES:
        classroom_id = existing.classroom_id if existing is not None else incoming_data.get("classroom_id")
        if not _classroom_relation_ok(session, classroom_id, current_user):
            raise PermissionError("لا تُدرِّس في هذا القسم، فلا يمكنك تعديل بيانات تلاميذه.")
        return


@router.post("/push", response_model=SyncPushResponse)
def push(
    payload: SyncPushRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    results: list[SyncMutationResult] = []

    for mutation in payload.mutations:
        model = ENTITY_MODEL_MAP.get(mutation.entity)
        if model is None:
            results.append(
                SyncMutationResult(local_id=mutation.local_id, status="error", error="نوع كيان غير مدعوم")
            )
            continue

        try:
            result = _apply_mutation(session, model, mutation.entity, mutation, current_user)
            results.append(result)
        except Exception as exc:  # noqa: BLE001 -- one bad mutation shouldn't fail the whole batch
            session.rollback()
            results.append(SyncMutationResult(local_id=mutation.local_id, status="error", error=str(exc)))

    session.commit()
    return SyncPushResponse(results=results)


def _apply_mutation(
    session: Session, model: Type[SQLModel], entity: str, mutation: SyncMutation, current_user: User
) -> SyncMutationResult:
    existing = session.get(model, mutation.local_id)
    clean_data = {k: v for k, v in mutation.data.items() if k not in _PROTECTED_FIELDS}

    if mutation.operation == "delete":
        if existing:
            _ensure_mutation_allowed(session, entity, existing, {}, current_user)
            existing.is_deleted = True
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        return SyncMutationResult(local_id=mutation.local_id, status="applied", server_updated_at=datetime.utcnow())

    if existing:
        _ensure_mutation_allowed(session, entity, existing, clean_data, current_user)
        # last-write-wins: only apply if the incoming change is newer
        if mutation.client_updated_at <= existing.updated_at:
            return SyncMutationResult(
                local_id=mutation.local_id, status="conflict_kept_server", server_updated_at=existing.updated_at
            )
        clean_data.pop("teacher_id", None)  # ownership is never reassignable via sync
        for field, value in clean_data.items():
            if hasattr(existing, field):
                setattr(existing, field, value)
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        return SyncMutationResult(local_id=mutation.local_id, status="applied", server_updated_at=existing.updated_at)

    # create with the client-generated id so local_id == server_id (no remap needed)
    if entity in _DIRECT_TEACHER_ENTITIES:
        clean_data["teacher_id"] = current_user.id  # never trust the client's own teacher_id on create
    _ensure_mutation_allowed(session, entity, None, clean_data, current_user)
    record = model(id=mutation.local_id, **clean_data)
    session.add(record)
    return SyncMutationResult(local_id=mutation.local_id, status="applied", server_updated_at=record.updated_at)


def _row_visible_to(session: Session, entity: str, row, current_user: User) -> bool:
    """Same ownership/relation rule as _ensure_mutation_allowed, applied to
    an already-fetched row -- so a teacher can only pull records they could
    also legitimately push to."""
    if entity in _PARENT_TEACHER_ENTITIES:
        fk_field, parent_model = _PARENT_TEACHER_ENTITIES[entity]
        parent = session.get(parent_model, getattr(row, fk_field, None))
        return bool(parent and parent.teacher_id == current_user.id)
    if entity == "class_delegates":
        classroom = session.get(Classroom, row.classroom_id)
        return bool(classroom and classroom.homeroom_teacher_id == current_user.id)
    if entity in _CLASSROOM_RELATION_ENTITIES:
        return _classroom_relation_ok(session, row.classroom_id, current_user)
    return False


@router.get("/pull", response_model=SyncPullResponse)
def pull(
    since: datetime,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Returns everything changed since `since`, scoped to this teacher.

    Entities with a direct `teacher_id` column are filtered in SQL. Every
    other entity used to be pulled back completely unscoped -- e.g. every
    student (with guardian phone numbers and medical notes), every grade,
    and every behaviour/attendance tap in the whole database, regardless of
    who taught them -- because the only check here was `hasattr(model,
    "teacher_id")`, which is false for chain-owned entities. Those are now
    filtered with the same relation rules /sync/push enforces on writes.
    """
    is_admin = current_user.role == UserRole.admin
    changes: dict[str, list[dict]] = {}

    for name, model in ENTITY_MODEL_MAP.items():
        query = select(model).where(model.updated_at > since)  # type: ignore[attr-defined]
        if name in _DIRECT_TEACHER_ENTITIES:
            if not is_admin:
                query = query.where(model.teacher_id == current_user.id)  # type: ignore[attr-defined]
            rows = session.exec(query).all()
        else:
            rows = session.exec(query).all()
            if not is_admin:
                rows = [row for row in rows if _row_visible_to(session, name, row, current_user)]
        if rows:
            changes[name] = [row.model_dump() for row in rows]

    return SyncPullResponse(server_time=datetime.utcnow(), changes=changes)
