from typing import Optional

from pydantic import BaseModel

from app.models.common import MessageCategory


class ParentMessageTemplateCreate(BaseModel):
    title: str
    body_template: str
    category: MessageCategory = MessageCategory.general
    subject_hint: Optional[str] = None


class ParentMessageTemplateRead(ParentMessageTemplateCreate):
    id: str
    teacher_id: str


class RenderMessageRequest(BaseModel):
    template_id: str
    variables: dict[str, str]  # e.g. {"student_name": "...", "date": "..."}


class RenderMessageResponse(BaseModel):
    text: str
