"""On-demand file generation: PDF (single documents) and Excel (bulk export).

Single-document exports (one student's note card, one classroom's grade
sheet) are meant to also be generatable directly on-device in Flutter for
true offline use -- this server-side route exists for parity/bulk cases and
for any client that prefers to fetch a ready-made file.

WeasyPrint and openpyxl are both imported lazily inside their handlers (not
at module import time) so the API can still boot even if PDF generation is
ever broken in a given environment -- only that one export fails until it's
fixed. openpyxl itself is already a hard dependency (see requirements.txt,
added for §35's roster import), so its import basically never fails in
practice -- kept lazy anyway for consistency and because there's no reason
to pay the import cost on every app boot for an endpoint most requests
never call.

WeasyPrint 62.3 (unlike much older versions) needs NO native cairo/pango
libraries at all -- it's pure Python (fontTools + Pillow) -- confirmed to
work as-is on Render's free "python" native runtime with no Dockerfile/
apt-get step (see docs/data_model.md §41). The real trap was a *version*
bug, not a missing system dependency: weasyprint==62.3's own metadata
declares "pydyf>=0.10.0" (loose), but it is NOT actually compatible with
pydyf 0.12.x at runtime -- `import weasyprint` succeeds either way, so the
break only surfaces the moment `HTML(...).write_pdf()` is actually called,
as an AttributeError, not an ImportError. requirements.txt now pins
`pydyf==0.11.0` explicitly for exactly this reason -- don't remove that pin
without re-verifying against a real weasyprint release note.

Arabic text needs a font that actually ships Arabic glyphs (WeasyPrint's
default fallback does not) -- app/assets/fonts/Amiri-{Regular,Bold}.ttf
(SIL OFL-licensed, bundled directly in this repo, referenced via
`base_url`/relative @font-face url()s below) is used by every PDF template
in this file for exactly that reason. Do not switch a template back to a
generic font-family without checking Arabic actually renders (it silently
falls back to tofu/missing-glyph boxes, not an error).
"""
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from jinja2 import Environment, select_autoescape
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.assessment import Assessment, AssessmentScore
from app.models.common import AssessmentType, NotebookQuality, SessionEventType
from app.models.identity import Classroom, Subject, Term, User
from app.models.session import ClassSession, SessionEvent
from app.models.student import NotebookCheck, Student
from app.routers.council import _ensure_can_view_council, build_council_report
from app.routers.behavior import compute_behavior_score
from app.routers.students import _ensure_can_manage_student

router = APIRouter(prefix="/export", tags=["export"])

# app/assets/fonts/Amiri-*.ttf -- see module docstring. WeasyPrint resolves
# @font-face url()s in the rendered HTML against this base_url, so every
# PDF-producing endpoint below passes `base_url=str(_ASSETS_DIR) + "/"`.
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# Shared @font-face block -- every PDF template in this file includes this
# verbatim (Jinja2 has no cross-template includes here since each template
# is just a Python string, not a file on a loader path). See module
# docstring for why a bundled font is required at all.
_ARABIC_FONT_FACE = """
  @font-face { font-family: "Amiri"; src: url("fonts/Amiri-Regular.ttf"); font-weight: normal; }
  @font-face { font-family: "Amiri"; src: url("fonts/Amiri-Bold.ttf"); font-weight: bold; }
"""

_STUDENT_CARD_TEMPLATE = """
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8" />
<style>
  __ARABIC_FONT_FACE__
  body { font-family: "Amiri", sans-serif; padding: 24px; }
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
""".replace("__ARABIC_FONT_FACE__", _ARABIC_FONT_FACE)


def _render_html(template: str, **context) -> str:
    """Jinja2-render a template string to plain HTML -- split out from
    _render_pdf below specifically so tests can assert on the HTML directly
    (checking an Arabic name/label appears in the RIGHT student's section,
    say) without going through a PDF text-extraction library. Extracting
    text back out of a WeasyPrint-rendered PDF is NOT a reliable way to
    check Arabic content in a test: Amiri (like most Arabic fonts) shapes
    letters into joined ligature glyphs, and generic PDF text extractors
    (pypdf included) hand back that glyph stream reordered/unjoined rather
    than the original Unicode string -- the PDF renders correctly (verified
    visually, see docs/data_model.md §41) even though `extract_text()` on
    it looks scrambled. Plain-HTML string content has no such problem.
    """
    env = Environment(autoescape=select_autoescape(["html"]))
    return env.from_string(template).render(**context)


def _html_to_pdf(html: str) -> bytes:
    """WeasyPrint HTML->PDF, with `base_url` set to app/assets/ so a
    template's @font-face url()s (see _ARABIC_FONT_FACE) resolve correctly
    regardless of the server's working directory. Raises HTTPException(501)
    for the "PDF engine is broken in this environment" case -- see module
    docstring for the two distinct ways that can actually happen (missing
    native libs -> OSError; the weasyprint/pydyf version trap ->
    AttributeError at render time, not at import time, which is why this
    wraps write_pdf() too, not just the import).
    """
    try:
        from weasyprint import HTML  # lazy import, see module docstring
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise HTTPException(status_code=501, detail="توليد PDF على السيرفر غير متاح حالياً (فشل تحميل WeasyPrint).") from exc

    try:
        return HTML(string=html, base_url=str(_ASSETS_DIR) + "/").write_pdf()
    except Exception as exc:  # noqa: BLE001 -- see docstring: broken PDF engine can fail here, not just at import
        raise HTTPException(status_code=501, detail="توليد PDF على السيرفر غير متاح حالياً (فشل عند التوليد الفعلي).") from exc


def _render_pdf(template: str, **context) -> bytes:
    """Shared by every PDF endpoint in this file: Jinja2 template string ->
    HTML -> PDF bytes. See _render_html/_html_to_pdf for why this is split
    into two pieces instead of one."""
    return _html_to_pdf(_render_html(template, **context))


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

    pdf_bytes = _render_pdf(_STUDENT_CARD_TEMPLATE, student=student)
    return Response(content=pdf_bytes, media_type="application/pdf")


# كشف نقاط القسم الفصلي -- a native PDF (no browser print dialog) built
# from the exact same council.build_council_report data the "مجلس القسم"
# screen and the browser-print report card in classroom_dashboard.html
# already use, so the numbers here can never disagree with either of those.
# One <div class="rc-page"> per student, each forced onto its own page via
# `page-break-after` (WeasyPrint honors the old-style property; `break-
# after` is the modern equivalent, kept as a second declaration for
# forward-compat) -- the last page must NOT get a trailing blank page, so
# the Jinja2 loop skips the property on the final row instead of relying on
# `:last-child` (WeasyPrint's CSS support for structural pseudo-classes
# combined with forced page breaks is exactly the kind of edge case not
# worth trusting untested -- see module docstring's general caution).
_GRADE_SHEET_TEMPLATE = """
<html dir="rtl" lang="ar">
<head>
<meta charset="utf-8" />
<style>
  __ARABIC_FONT_FACE__
  * { box-sizing: border-box; }
  body { font-family: "Amiri", sans-serif; padding: 28px; color: #1a1a1a; margin: 0; }
  .rc-page { padding: 28px; }
  h1 { font-size: 22px; border-bottom: 2px solid #333; padding-bottom: 8px; margin: 0 0 4px; }
  .meta-line { font-size: 13px; color: #444; margin: 2px 0; }
  .student-line { font-size: 15px; margin-top: 14px; margin-bottom: 6px; }
  table.grades { width: 100%; border-collapse: collapse; margin-top: 6px; }
  table.grades th, table.grades td { border: 1px solid #999; padding: 7px 10px; text-align: right; font-size: 13px; }
  table.grades th { background: #f0f0f0; }
  table.summary { width: 100%; border-collapse: collapse; margin-top: 16px; table-layout: fixed; }
  table.summary td { text-align: center; padding: 8px 4px; border: 1px solid #ccc; font-size: 11.5px; color: #444; }
  table.summary td .big { display: block; font-size: 19px; font-weight: bold; color: #111; margin-bottom: 3px; }
  .sign { margin-top: 26px; font-size: 12px; color: #555; }
  .sign div { margin: 4px 0; }
</style>
</head>
<body>
{% for row in rows %}
  <div class="rc-page" {% if not loop.last %}style="page-break-after: always; break-after: page;"{% endif %}>
    <h1>كشف نقاط — {{ classroom_name }}</h1>
    <div class="meta-line">الأستاذ الرئيسي: {{ teacher_name }}</div>
    <div class="meta-line">{{ term_label }}</div>
    <div class="student-line"><b>التلميذ(ة):</b> {{ row.full_name }} &nbsp;&nbsp;&nbsp; <b>الرتبة:</b> {% if row.rank %}{{ row.rank }} من {{ total_students }}{% else %}—{% endif %}</div>
    <table class="grades">
      <thead><tr><th>المادة</th><th>المعدل</th></tr></thead>
      <tbody>
        {% for s in row.subject_averages %}
        <tr><td>{{ s.subject_name }}</td><td>{% if s.average is not none %}{{ "%.2f"|format(s.average) }} / 20{% else %}لم تُدخَل بعد{% endif %}</td></tr>
        {% endfor %}
      </tbody>
    </table>
    <table class="summary">
      <tr>
        <td><span class="big">{% if row.overall_average is not none %}{{ "%.2f"|format(row.overall_average) }}{% else %}—{% endif %}</span>المعدل العام</td>
        <td><span class="big">{{ row.absences }}</span>الغياب</td>
        <td><span class="big">{{ row.tardiness_count }}</span>التأخر</td>
        <td><span class="big">{{ row.negative_behavior_count }}</span>ملاحظات السلوك</td>
      </tr>
    </table>
    <div class="sign">
      <div>تاريخ الطباعة: {{ print_date }}</div>
      <div>إمضاء الأستاذ الرئيسي: ______________</div>
    </div>
  </div>
{% endfor %}
</body>
</html>
""".replace("__ARABIC_FONT_FACE__", _ARABIC_FONT_FACE)


@router.get("/classrooms/{classroom_id}/grade-sheets.pdf")
def export_grade_sheets(
    classroom_id: str,
    term_id: str,
    student_id: str | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """كشف نقاط القسم الفصلي كملف PDF أصلي حقيقي -- no browser print dialog
    involved. `student_id` omitted returns one PDF with every student in
    the classroom (one page per student, see _GRADE_SHEET_TEMPLATE); passed,
    returns a single-page PDF for just that student. Same gate as the
    council report itself (`_ensure_can_view_council`): this crosses every
    subject teacher's grades into one document, exactly like /council's
    report and §39's full-backup export already do.
    """
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_view_council(classroom, current_user)

    term = session.get(Term, term_id)
    if not term or term.is_deleted:
        raise HTTPException(status_code=404, detail="الفصل الدراسي غير موجود")

    report = build_council_report(session, classroom, term)
    rows = report.rows
    if student_id is not None:
        rows = [r for r in rows if r.student_id == student_id]
        if not rows:
            raise HTTPException(status_code=404, detail="التلميذ غير موجود في هذا القسم")

    from datetime import date

    pdf_bytes = _render_pdf(
        _GRADE_SHEET_TEMPLATE,
        rows=rows,
        classroom_name=report.classroom_name,
        term_label=report.term_label,
        teacher_name=current_user.full_name,
        total_students=len(report.rows),
        print_date=date.today().isoformat(),
    )

    suffix = f"-{student_id}" if student_id else ""
    filename = f"grade-sheet-{classroom_id}-{term_id}{suffix}.pdf"  # ASCII-only, see export_classroom_backup's comment for why
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Arabic labels for the raw/bulk export below -- the frontend owns its own
# copies of these for the screens it renders (TAP_TYPES in
# classroom_dashboard.html, etc.), but this file has no frontend to borrow
# labels from, and the raw session-event log below deliberately includes
# every SessionEventType (not just the 8 that have an active tap button
# today, see behavior.py's module docstring) so a row is never a bare
# English enum value even for older/inactive types.
_ASSESSMENT_TYPE_LABELS = {
    AssessmentType.test: "فرض",
    AssessmentType.exam: "اختبار",
    AssessmentType.homework: "عمل منزلي",
    AssessmentType.oral: "شفوي",
}
_NOTEBOOK_QUALITY_LABELS = {
    NotebookQuality.organized: "منظم",
    NotebookQuality.average: "متوسط",
    NotebookQuality.neglected: "مهمل",
}
_SESSION_EVENT_TYPE_LABELS = {
    SessionEventType.attendance_present: "حاضر",
    SessionEventType.attendance_absent: "غائب",
    SessionEventType.tardiness: "تأخر",
    SessionEventType.behavior_positive: "سلوك إيجابي",
    SessionEventType.behavior_negative: "سلوك سلبي",
    SessionEventType.homework_done: "قام بعمل إضافي",
    SessionEventType.homework_missing: "لم يقم بعمل إضافي",
    SessionEventType.participation: "مشاركة / فعالية",
    SessionEventType.equipment_brought: "أحضر الأدوات",
    SessionEventType.equipment_missing: "نسي الأدوات",
    SessionEventType.teamwork_positive: "عمل جماعي جيد",
    SessionEventType.teamwork_negative: "عمل جماعي ضعيف",
    SessionEventType.initiative_shown: "مبادرة",
}


@router.get("/classrooms/{classroom_id}/full-backup.xlsx")
def export_classroom_backup(
    classroom_id: str,
    term_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """نسخة احتياطية/تصدير شامل (§39): ملف Excel واحد بخمس أوراق (التلاميذ،
    علامة السلوك، الفروض والاختبارات، سجل الحضور والسلوك الخام، فحص الكراس)
    لكل بيانات قسم معيَّن في فصل دراسي معيَّن -- أمان ضد فقدان البيانات،
    وأرشيف نهاية الفصل قابل للفتح خارج التطبيق (Excel/LibreOffice/Google
    Sheets). بنفس بوابة صلاحية تقرير مجلس القسم بالضبط (الأستاذ الرئيسي أو
    الإدارة فقط -- انظر _ensure_can_view_council في routers/council.py)،
    لأن هذا الملف يكشف بيانات كل تلاميذ القسم عبر كل المواد معاً، تماماً
    كتقرير المجلس -- لا يُتاح لأستاذ مادة واحدة فقط.
    """
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_view_council(classroom, current_user)
    term = session.get(Term, term_id)
    if not term or term.is_deleted:
        raise HTTPException(status_code=404, detail="الفصل الدراسي غير موجود")

    from openpyxl import Workbook  # lazy import, see module docstring
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    students = session.exec(
        select(Student)
        .where(Student.classroom_id == classroom_id, Student.is_deleted == False)  # noqa: E712
        .order_by(Student.first_name, Student.last_name)
    ).all()
    student_name = {s.id: f"{s.first_name} {s.last_name}" for s in students}
    student_ids = list(student_name.keys())
    subject_name = {s.id: s.name for s in session.exec(select(Subject)).all()}

    wb = Workbook()
    header_font = Font(bold=True)

    def write_sheet(ws, headers, rows):
        # RTL sheet view + a bold header row + a readable column width --
        # every sheet in this workbook gets the same treatment, so this is
        # factored out instead of repeated five times.
        ws.sheet_view.rightToLeft = True
        ws.append(headers)
        for cell in ws[1]:
            cell.font = header_font
        for row in rows:
            ws.append(row)
        for col_idx, header in enumerate(headers, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = max(12, min(40, len(str(header)) + 6))

    # -- 1) التلاميذ --
    ws_students = wb.active
    ws_students.title = "التلاميذ"
    write_sheet(
        ws_students,
        ["الاسم", "اللقب", "تاريخ الميلاد", "الجنس", "ولي الأمر", "هاتف ولي الأمر", "ملاحظات طبية", "ملاحظات عامة"],
        [
            [s.first_name, s.last_name, s.birth_date or "", s.gender or "",
             s.guardian_name or "", s.guardian_phone or "", s.medical_notes or "", s.general_notes or ""]
            for s in students
        ],
    )

    # -- 2) علامة السلوك -- نفس compute_behavior_score التي تستعملها شاشة
    # المتابعة المستمرة ومعدل المادة الفصلي، لا حساب موازٍ قد يختلف عنها.
    behavior_scores = [compute_behavior_score(session, s.id, classroom_id, term_id) for s in students]
    category_labels = [b.label_ar for b in behavior_scores[0].breakdown] if behavior_scores else []
    ws_behavior = wb.create_sheet("علامة السلوك")
    write_sheet(
        ws_behavior,
        ["التلميذ"] + category_labels + ["المجموع"],
        [
            [student_name[score.student_id]] + [b.points_earned for b in score.breakdown] + [score.total]
            for score in behavior_scores
        ],
    )

    # -- 3) الفروض والاختبارات -- صف واحد لكل (تلميذ × فرض) هذا الفصل، بما
    # في ذلك التلاميذ الذين لم تُدخَل علامتهم بعد (خانة العلامة تبقى فارغة
    # بدل حذف الصف بصمت -- هذا بالضبط ما تُبلِّغ عنه تنبيهات §38).
    assessments = session.exec(
        select(Assessment).where(
            Assessment.classroom_id == classroom_id,
            Assessment.date >= term.start_date,
            Assessment.date <= term.end_date,
            Assessment.is_deleted == False,  # noqa: E712
        ).order_by(Assessment.date)
    ).all()
    assessment_rows = []
    for assessment in assessments:
        scores = session.exec(
            select(AssessmentScore).where(
                AssessmentScore.assessment_id == assessment.id,
                AssessmentScore.is_deleted == False,  # noqa: E712
            )
        ).all()
        score_by_student = {sc.student_id: sc.score for sc in scores}
        for s in students:
            assessment_rows.append([
                student_name[s.id],
                subject_name.get(assessment.subject_id, "—"),
                assessment.title,
                _ASSESSMENT_TYPE_LABELS.get(assessment.assessment_type, assessment.assessment_type),
                assessment.date,
                score_by_student.get(s.id),
                assessment.max_score,
            ])
    ws_assessments = wb.create_sheet("الفروض والاختبارات")
    write_sheet(ws_assessments, ["التلميذ", "المادة", "العنوان", "النوع", "التاريخ", "العلامة", "من"], assessment_rows)

    # -- 4) سجل الحضور والسلوك -- كل نقرة خام هذا الفصل، للأرشفة/التدقيق.
    events_with_sessions = (
        session.exec(
            select(SessionEvent, ClassSession)
            .join(ClassSession, SessionEvent.session_id == ClassSession.id)  # type: ignore[arg-type]
            .where(
                ClassSession.classroom_id == classroom_id,
                ClassSession.date >= term.start_date,
                ClassSession.date <= term.end_date,
                SessionEvent.is_deleted == False,  # noqa: E712
            )
            .order_by(ClassSession.date)
        ).all()
        if student_ids
        else []
    )
    log_rows = [
        [
            class_session.date,
            subject_name.get(class_session.subject_id, "—"),
            student_name.get(event.student_id, "؟"),
            _SESSION_EVENT_TYPE_LABELS.get(event.event_type, event.event_type),
            event.note or "",
        ]
        for event, class_session in events_with_sessions
        if event.student_id in student_name
    ]
    ws_log = wb.create_sheet("سجل الحضور والسلوك")
    write_sheet(ws_log, ["التاريخ", "المادة", "التلميذ", "النوع", "ملاحظة"], log_rows)

    # -- 5) فحص الكراس --
    checks = (
        session.exec(
            select(NotebookCheck).where(
                NotebookCheck.student_id.in_(student_ids),  # type: ignore[union-attr]
                NotebookCheck.check_date >= term.start_date,
                NotebookCheck.check_date <= term.end_date,
                NotebookCheck.is_deleted == False,  # noqa: E712
            ).order_by(NotebookCheck.check_date)
        ).all()
        if student_ids
        else []
    )
    ws_notebook = wb.create_sheet("فحص الكراس")
    write_sheet(
        ws_notebook,
        ["التلميذ", "التاريخ", "تنظيم الكراس", "الكتابة", "ملاحظة"],
        [
            [
                student_name.get(check.student_id, "؟"),
                check.check_date,
                _NOTEBOOK_QUALITY_LABELS.get(check.quality, check.quality),
                _NOTEBOOK_QUALITY_LABELS.get(check.writing_quality, "") if check.writing_quality else "",
                check.note or "",
            ]
            for check in checks
        ],
    )

    buffer = BytesIO()
    wb.save(buffer)
    # Deliberately ASCII-only (no Arabic classroom/term name): a
    # Content-Disposition filename has to be Latin-1-safe or Starlette
    # raises encoding a UnicodeEncodeError building the response headers.
    # The frontend gives the download its real Arabic name itself via the
    # <a download="..."> attribute on the blob URL it builds (see
    # downloadClassroomBackup() in classroom_dashboard.html) -- that name,
    # not this one, is what the teacher actually sees saved to disk.
    filename = f"classroom-backup-{classroom_id}-{term_id}.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
