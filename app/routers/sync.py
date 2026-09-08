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
from typing import Type

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
from app.models.curriculum import AnnualPlan, PlanItem
from app.models.identity import ClassDelegate, User
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


@router.post("/push", response_model=SyncPushResponse)
def push(
    payload: SyncPushRequest,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
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
            result = _apply_mutation(session, model, mutation)
            results.append(result)
        except Exception as exc:  # noqa: BLE001 -- one bad mutation shouldn't fail the whole batch
            session.rollback()
            results.append(SyncMutationResult(local_id=mutation.local_id, status="error", error=str(exc)))

    session.commit()
    return SyncPushResponse(results=results)


def _apply_mutation(session: Session, model: Type[SQLModel], mutation: SyncMutation) -> SyncMutationResult:
    existing = session.get(model, mutation.local_id)
    clean_data = {k: v for k, v in mutation.data.items() if k not in _PROTECTED_FIELDS}

    if mutation.operation == "delete":
        if existing:
            existing.is_deleted = True
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        return SyncMutationResult(local_id=mutation.local_id, status="applied", server_updated_at=datetime.utcnow())

    if existing:
        # last-write-wins: only apply if the incoming change is newer
        if mutation.client_updated_at <= existing.updated_at:
            return SyncMutationResult(
                local_id=mutation.local_id, status="conflict_kept_server", server_updated_at=existing.updated_at
            )
        for field, value in clean_data.items():
            if hasattr(existing, field):
                setattr(existing, field, value)
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        return SyncMutationResult(local_id=mutation.local_id, status="applied", server_updated_at=existing.updated_at)

    # create with the client-generated id so local_id == server_id (no remap needed)
    record = model(id=mutation.local_id, **clean_data)
    session.add(record)
    return SyncMutationResult(local_id=mutation.local_id, status="applied", server_updated_at=record.updated_at)


@router.get("/pull", response_model=SyncPullResponse)
def pull(
    since: datetime,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Returns everything changed since `since`, scoped to this teacher where
    the entity carries a teacher_id (directly or via ownership chain kept
    simple for MVP: most tables here have teacher_id directly).
    """
    changes: dict[str, list[dict]] = {}

    for name, model in ENTITY_MODEL_MAP.items():
        query = select(model).where(model.updated_at > since)  # type: ignore[attr-defined]
        if hasattr(model, "teacher_id"):
            query = query.where(model.teacher_id == current_user.id)  # type: ignore[attr-defined]
        rows = session.exec(query).all()
        if rows:
            changes[name] = [row.model_dump() for row in rows]

    return SyncPullResponse(server_time=datetime.utcnow(), changes=changes)
