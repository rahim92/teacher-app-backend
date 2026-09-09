"""On-demand PDF generation.

Single-document exports (one student's note card, one classroom's grade
sheet) are meant to also be generatable directly on-device in Flutter for
true offline use -- this server-side route exists for parity/bulk cases and
for any client that prefers to fetch a ready-made file.

WeasyPrint is imported lazily inside the handler (not at module import time)
so the API can still boot even in an environment where its native
dependencies (cairo/pango) aren't installed -- only PDF export itself fails
until they are.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from jinja2 import Environment, select_autoescape
from sqlmodel import Session

from app.auth import get_current_user
from app.database import get_session
from app.models.identity import User
from app.models.student import Student
from app.routers.students import _ensure_can_manage_student

router = APIRouter(prefix="/export", tags=["export"])

_STUDENT_CARD_TEMPLATE = """
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8" />
<style>
  body { font-family: "DejaVu Sans", sans-serif; padding: 24px; }
  h1 { font-size: 20px; border-bottom: 2px solid #333; padding-bottom: 8px; }
  .row { margin: 6px 0; }
  .label { font-weight: bold; }
</style>
</head>
<body>
  <h1>بطاقة ملاحظة تلميذ</h1>
  <div class="row"><span class="label">الاسم الكامل:</span> {{ student.first_name }} {{ student.last_name }}</div>
  <div class="row"><span class="label">تاريخ الميلاد:</span> {{ student.birth_date or "-" }}</div>
  <div class="row"><span class="label">ملاحظات:</span> {{ student.general_notes or "-" }}</div>
</body>
</html>
"""


@router.get("/students/{student_id}/card.pdf")
def export_student_card(
    student_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")
    # Same relation check as editing this student (see students.py):
    # this endpoint takes a bare student_id with no classroom context, and
    # the card includes the student's name/birth date/notes -- unlike the
    # deliberately open cross-teacher GETs elsewhere (ledger, behavior
    # score), there's no classroom_id the caller had to already know here.
    _ensure_can_manage_student(session, student, current_user)

    try:
        from weasyprint import HTML  # lazy import, see module docstring
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise HTTPException(
            status_code=501,
            detail="توليد PDF على السيرفر يتطلب تثبيت WeasyPrint ومكتباته (cairo/pango).",
        ) from exc

    env = Environment(autoescape=select_autoescape(["html"]))
    html = env.from_string(_STUDENT_CARD_TEMPLATE).render(student=student)
    pdf_bytes = HTML(string=html).write_pdf()

    return Response(content=pdf_bytes, media_type="application/pdf")
