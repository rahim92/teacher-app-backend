from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

# Every syncable table is addressed by name here -- keep this list in sync
# with app/models/__init__.py and the sync router's ENTITY_MODEL_MAP.
SyncEntityName = Literal[
    "schools",
    "academic_years",
    "subjects",
    "classrooms",
    "students",
    "seat_assignments",
    "annual_plans",
    "plan_items",
    "class_sessions",
    "session_events",
    "lesson_logs",
    "assessments",
    "assessment_scores",
    "assessment_details",
    "remediation_sessions",
    "remediation_participants",
    "parent_message_templates",
    "notebook_checks",
    "class_delegates",
]


class SyncMutation(BaseModel):
    entity: SyncEntityName
    operation: Literal["create", "update", "delete"]
    local_id: str  # UUID generated on-device; becomes the record's permanent id
    data: dict[str, Any] = {}
    client_updated_at: datetime


class SyncMutationResult(BaseModel):
    local_id: str
    status: Literal["applied", "conflict_kept_server", "error"]
    server_updated_at: Optional[datetime] = None
    error: Optional[str] = None


class SyncPushRequest(BaseModel):
    device_id: str
    mutations: list[SyncMutation]


class SyncPushResponse(BaseModel):
    results: list[SyncMutationResult]


class SyncPullResponse(BaseModel):
    server_time: datetime
    # entity name -> list of raw records changed since `since`
    changes: dict[str, list[dict[str, Any]]]
