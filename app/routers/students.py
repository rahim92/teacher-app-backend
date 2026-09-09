from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.common import SpecialNeedVisibility, UserRole
from app.models.identity import Classroom, TeacherClassroomAssignment, User
from app.models.student import NotebookCheck, SeatAssignment, Student, StudentSpecialNeed
from app.schemas.student import (
    NotebookCheckCreate,
    NotebookCheckRead,
    SeatAssignmentRead,
    SeatAssignmentUpsert,
    SeatSwapRequest,
    StudentCreate,
    StudentRead,
    StudentSpecialNeedCreate,
    StudentSpecialNeedRead,
    StudentUpdate,
)

router = APIRouter(tags=["students"])


def _ensure_can_manage_student(session: Session, student: Student, current_user: User) -> None:
    """Real authorization gap found during a review pass: `update_student`/
    `delete_student` used to accept ANY authenticated teacher's token, with
    no check that they have anything to do with the student's classroom --
    unlike /assessments, /seat-assignments and class-delegates, which already
    check this. That mattered more here than almost anywhere else in the
    app: Student carries guardian_phone and medical_notes. Mirrors the same
    "creator, homeroom teacher, or subject-teacher assignment" relation
    /my-classrooms computes to decide who a classroom's teachers even are.
    """
    if current_user.role == UserRole.admin:
        return
    classroom = session.get(Classroom, student.classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    if classroom.teacher_id == current_user.id or classroom.homeroom_teacher_id == current_user.id:
        return
    has_assignment = session.exec(
        select(TeacherClassroomAssignment).where(
            TeacherClassroomAssignment.classroom_id == classroom.id,
            TeacherClassroomAssignment.teacher_id == current_user.id,
            TeacherClassroomAssignment.is_deleted == False,  # noqa: E712
        )
    ).first()
    if not has_assignment:
        raise HTTPException(status_code=403, detail="لا تُدرِّس في هذا القسم، فلا يمكنك تعديل بيانات تلاميذه.")


@router.post("/students", response_model=StudentRead)
def create_student(payload: StudentCreate, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    student = Student(**payload.model_dump())
    session.add(student)
    session.commit()
    session.refresh(student)
    return student


@router.get("/classrooms/{classroom_id}/students", response_model=list[StudentRead])
def list_students(
    classroom_id: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    return session.exec(
        select(Student).where(Student.classroom_id == classroom_id, Student.is_deleted == False)  # noqa: E712
    ).all()


@router.patch("/students/{student_id}", response_model=StudentRead)
def update_student(
    student_id: str,
    payload: StudentUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")
    _ensure_can_manage_student(session, student, current_user)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(student, field, value)
    student.updated_at = datetime.utcnow()

    session.add(student)
    session.commit()
    session.refresh(student)
    return student


@router.delete("/students/{student_id}", status_code=204)
def delete_student(
    student_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Soft-deletes a student added by mistake (duplicate entry, wrong
    classroom, typo the teacher would rather re-enter than fix). Related
    rows (special needs, seat assignments, delegate record...) are left in
    place with is_deleted left as-is on THEM -- same "don't cascade" choice
    already made for class delegates -- so a teacher's own history isn't
    silently wiped if a student is restored later via direct DB access.
    """
    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")
    _ensure_can_manage_student(session, student, current_user)
    student.is_deleted = True
    student.updated_at = datetime.utcnow()
    session.add(student)
    session.commit()


# Two students may deliberately share one desk (seat_row/seat_col) -- there's
# no DB uniqueness on that pair, only this per-endpoint cap, so a teacher who
# wants a 3-per-bench arrangement isn't blocked by a schema-level constraint,
# just this documented product decision (matches how the "at most one
# homeroom" rule lives at the DB layer while this lives at the endpoint).
MAX_STUDENTS_PER_DESK = 2


@router.put("/seat-assignments", response_model=SeatAssignmentRead)
def upsert_seat_assignment(
    payload: SeatAssignmentUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """One row per (teacher, classroom, student) -- moving a student's seat
    just updates seat_row/seat_col in place rather than creating a new row.

    A desk (one seat_row/seat_col pair) may hold up to MAX_STUDENTS_PER_DESK
    students -- e.g. a shared two-person table -- enforced here rather than
    with a DB unique constraint, since it's a capacity rule, not an identity
    one.
    """
    existing = session.exec(
        select(SeatAssignment).where(
            SeatAssignment.teacher_id == current_user.id,
            SeatAssignment.classroom_id == payload.classroom_id,
            SeatAssignment.student_id == payload.student_id,
            SeatAssignment.term_id == payload.term_id,
            SeatAssignment.is_deleted == False,  # noqa: E712
        )
    ).first()

    occupants = session.exec(
        select(SeatAssignment).where(
            SeatAssignment.teacher_id == current_user.id,
            SeatAssignment.classroom_id == payload.classroom_id,
            SeatAssignment.term_id == payload.term_id,
            SeatAssignment.seat_row == payload.seat_row,
            SeatAssignment.seat_col == payload.seat_col,
            SeatAssignment.is_deleted == False,  # noqa: E712
            SeatAssignment.student_id != payload.student_id,
        )
    ).all()
    if len(occupants) >= MAX_STUDENTS_PER_DESK:
        raise HTTPException(status_code=400, detail=f"هذا المقعد ممتلئ (الحد الأقصى {MAX_STUDENTS_PER_DESK} تلميذين في الطاولة الواحدة).")

    if existing:
        existing.seat_row = payload.seat_row
        existing.seat_col = payload.seat_col
        existing.reason = payload.reason
        existing.updated_at = datetime.utcnow()
        seat = existing
    else:
        seat = SeatAssignment(teacher_id=current_user.id, **payload.model_dump())

    session.add(seat)
    session.commit()
    session.refresh(seat)
    return seat


@router.post("/seat-assignments/swap", response_model=list[SeatAssignmentRead])
def swap_seat_assignments(
    payload: SeatSwapRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Exchanges the (seat_row, seat_col) of two existing seat assignments
    in one transaction -- e.g. dragging one student's seat icon onto another
    student's to swap their places.

    This is deliberately its own endpoint rather than two sequential calls
    to `upsert_seat_assignment` above: a plain swap never changes how many
    students occupy either desk (it's still at most the same two people,
    just relabeled), but two separate upserts would transiently try to add
    the dragged student to the target desk BEFORE the target student has
    left it -- which the MAX_STUDENTS_PER_DESK check above would reject
    whenever the target desk is already at capacity (the common case, since
    desks are meant to seat two). Swapping the two rows' coordinates
    directly sidesteps that entirely.
    """
    a = session.get(SeatAssignment, payload.seat_id_a)
    b = session.get(SeatAssignment, payload.seat_id_b)
    if not a or a.is_deleted or not b or b.is_deleted:
        raise HTTPException(status_code=404, detail="أحد تعييني المقعد غير موجود")
    if a.teacher_id != current_user.id or b.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="يمكن فقط تبديل مقاعد ضمن خريطتك أنت")
    if a.id == b.id:
        return [a, b]

    a.seat_row, b.seat_row = b.seat_row, a.seat_row
    a.seat_col, b.seat_col = b.seat_col, a.seat_col
    a.updated_at = datetime.utcnow()
    b.updated_at = datetime.utcnow()
    session.add(a)
    session.add(b)
    session.commit()
    session.refresh(a)
    session.refresh(b)
    return [a, b]


@router.delete("/seat-assignments/{seat_id}", status_code=204)
def delete_seat_assignment(
    seat_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Un-seats one student -- e.g. to free a shared desk, or when a student
    leaves seating entirely. Scoped to the calling teacher's own map, same as
    every other seat-assignment operation.
    """
    seat = session.get(SeatAssignment, seat_id)
    if not seat or seat.is_deleted or seat.teacher_id != current_user.id:
        raise HTTPException(status_code=404, detail="لا يوجد تعيين مقعد بهذا المعرّف")
    seat.is_deleted = True
    seat.updated_at = datetime.utcnow()
    session.add(seat)
    session.commit()


@router.get("/classrooms/{classroom_id}/seat-assignments", response_model=list[SeatAssignmentRead])
def list_seat_assignments(
    classroom_id: str,
    term_id: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(SeatAssignment).where(
        SeatAssignment.classroom_id == classroom_id,
        SeatAssignment.teacher_id == current_user.id,
        SeatAssignment.is_deleted == False,  # noqa: E712
    )
    # term_id omitted -> every map this teacher has for the classroom
    # (standing + any per-term ones); pass it to scope to one term/standing.
    if term_id is not None:
        query = query.where(SeatAssignment.term_id == term_id)
    return session.exec(query).all()


@router.post("/notebook-checks", response_model=NotebookCheckRead)
def create_notebook_check(
    payload: NotebookCheckCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """A periodic check of a student's own notebooks (كراس الدروس/الأنشطة) --
    a spot check, not a per-tap event. See docs/data_model.md.
    """
    check = NotebookCheck(**payload.model_dump(), teacher_id=current_user.id)
    session.add(check)
    session.commit()
    session.refresh(check)
    return check


def _teacher_relation_to_classroom(classroom: Classroom, current_user: User, session: Session) -> str:
    """Returns 'homeroom' (or admin), 'assigned', or 'none' -- what
    StudentSpecialNeed visibility filtering keys off. Kept separate from
    council's stricter all-or-nothing check because special-need entries
    have their own per-row visibility instead of an endpoint-wide gate.
    """
    if current_user.role == UserRole.admin or classroom.homeroom_teacher_id == current_user.id:
        return "homeroom"
    assigned = session.exec(
        select(TeacherClassroomAssignment).where(
            TeacherClassroomAssignment.classroom_id == classroom.id,
            TeacherClassroomAssignment.teacher_id == current_user.id,
            TeacherClassroomAssignment.is_deleted == False,  # noqa: E712
        )
    ).first()
    return "assigned" if assigned else "none"


@router.post("/student-special-needs", response_model=StudentSpecialNeedRead)
def add_special_need(
    payload: StudentSpecialNeedCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Records a condition the teacher must be considerate of. `visibility`
    defaults to homeroom_only (see the schema) -- a teacher must
    deliberately widen it to shared_with_teachers for the classroom-wide
    accommodation notice (e.g. front-row seating) to reach every subject
    teacher. This is sensitive health/disability data about a minor: kept
    out of the generic /sync entity map on purpose so it's never silently
    bulk-pulled -- always fetched explicitly per student.
    """
    need = StudentSpecialNeed(**payload.model_dump(), created_by=current_user.id)
    session.add(need)
    session.commit()
    session.refresh(need)
    return need


@router.get("/students/{student_id}/special-needs", response_model=list[StudentSpecialNeedRead])
def list_special_needs(student_id: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")
    classroom = session.get(Classroom, student.classroom_id)
    relation = _teacher_relation_to_classroom(classroom, current_user, session)
    if relation == "none":
        raise HTTPException(
            status_code=403,
            detail="لا يمكن الاطلاع على الحالات الخاصة لتلميذ في قسم لست أستاذاً فيه.",
        )

    rows = session.exec(
        select(StudentSpecialNeed).where(
            StudentSpecialNeed.student_id == student_id, StudentSpecialNeed.is_deleted == False  # noqa: E712
        )
    ).all()
    if relation == "homeroom":
        return rows
    # a subject teacher who isn't homeroom only sees the deliberately-shared,
    # actionable entries -- never the fuller clinical picture.
    return [r for r in rows if r.visibility == SpecialNeedVisibility.shared_with_teachers]


@router.get("/students/{student_id}/notebook-checks", response_model=list[NotebookCheckRead])
def list_notebook_checks(student_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    return session.exec(
        select(NotebookCheck).where(NotebookCheck.student_id == student_id, NotebookCheck.is_deleted == False)  # noqa: E712
    ).all()
