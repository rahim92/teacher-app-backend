from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.identity import User
from app.models.messaging import ParentMessageTemplate
from app.schemas.messaging import (
    ParentMessageTemplateCreate,
    ParentMessageTemplateRead,
    RenderMessageRequest,
    RenderMessageResponse,
)

router = APIRouter(tags=["messaging"])


class _SafeDict(dict):
    """Lets a template render even if the caller forgot a variable --
    missing placeholders are left visible (e.g. '{parent_name}') instead of
    raising, since this is a manual copy/paste flow, not a critical pipeline.
    """

    def __missing__(self, key):
        return "{" + key + "}"


@router.post("/message-templates", response_model=ParentMessageTemplateRead)
def create_template(
    payload: ParentMessageTemplateCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    template = ParentMessageTemplate(**payload.model_dump(), teacher_id=current_user.id)
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.get("/message-templates", response_model=list[ParentMessageTemplateRead])
def list_templates(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return session.exec(
        select(ParentMessageTemplate).where(
            ParentMessageTemplate.teacher_id == current_user.id,
            ParentMessageTemplate.is_deleted == False,  # noqa: E712
        )
    ).all()


@router.delete("/message-templates/{template_id}", status_code=204)
def delete_template(
    template_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Removes a wrongly-worded or no-longer-needed template. Only its own
    author may delete it -- templates aren't shared between teachers (see
    list_templates, scoped to the caller), so there's no admin-override case
    to mirror /assessments' delete here.
    """
    template = session.get(ParentMessageTemplate, template_id)
    if not template or template.is_deleted:
        raise HTTPException(status_code=404, detail="النموذج غير موجود")
    if template.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="يمكن فقط لصاحب النموذج حذفه.")
    template.is_deleted = True
    template.updated_at = datetime.utcnow()
    session.add(template)
    session.commit()


@router.post("/message-templates/render", response_model=RenderMessageResponse)
def render_template(
    payload: RenderMessageRequest,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    template = session.get(ParentMessageTemplate, payload.template_id)
    if not template or template.is_deleted:
        raise HTTPException(status_code=404, detail="النموذج غير موجود")

    text = template.body_template.format_map(_SafeDict(payload.variables))
    return RenderMessageResponse(text=text)
