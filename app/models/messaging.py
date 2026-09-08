from typing import Optional

from sqlmodel import Field

from app.models.common import MessageCategory, SyncableModel


class ParentMessageTemplate(SyncableModel, table=True):
    """A reusable message template the teacher fills in and copies out to
    WhatsApp/SMS/the correspondence notebook. MVP does not send anything --
    there is no automated delivery channel (no SMS gateway, no parent app).
    """

    __tablename__ = "parent_message_templates"

    teacher_id: str = Field(foreign_key="users.id", index=True)
    title: str
    body_template: str  # e.g. "السيد(ة) ولي أمر {student_name}، نعلمكم بغياب ابنكم/ابنتكم بتاريخ {date}."
    category: MessageCategory = Field(default=MessageCategory.general)
    subject_hint: Optional[str] = None
