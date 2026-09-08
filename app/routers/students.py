from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.identity import User
from app.models.student import NotebookCheck, SeatAssignment, Student
from app.schemas.student import (
    NotebookCheckCreate,
    NotebookCheckRead,
    SeatAssignmentRead,
    SeatAssignmentUpsert,
    StudentCreate,
    StudentRead,
    StudentUpdate,
)

router = APIRouter(tags=["students"])


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
    _: User = Depends(get_current_user),
):
    student = session.get(Student, student_id)
    if not student or student.is_deleted:
        raise HTTPException(status_code=404, detail="التلميذ غير موجود")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(student, field, value)
    student.updated_at = datetime.utcnow()

    session.add(student)
    session.commit()
    session.refresh(student)
    return student


@router.put("/seat-assignments", response_model=SeatAssignmentRead)
def upsert_seat_assignment(
    payload: SeatAssignmentUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """One row per (teacher, classroom, student) -- moving a student's seat
    just updates seat_row/seat_col in place rather than creating a new row.
    """
    existing = session.exec(
        select(SeatAssignment).where(
            SeatAssignment.teacher_id == current_user.id,
            SeatAssignment.classroom_id == payload.classroom_id,
            SeatAssignment.student_id == payload.student_id,
            SeatAssignment.is_deleted == False,  # noqa: E712
        )
    ).first()

    if existing:
        existing.seat_row = payload.seat_row
        existing.seat_col = payload.seat_col
        existing.updated_at = datetime.utcnow()
        seat = existing
    else:
        seat = SeatAssignment(teacher_id=current_user.id, **payload.model_dump())

    session.add(seat)
    session.commit()
    session.refresh(seat)
    return seat


@router.get("/classrooms/{classroom_id}/seat-assignments", response_model=list[SeatAssignmentRead])
def list_seat_assignments(
    classroom_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return session.exec(
        select(SeatAssignment).where(
            SeatAssignment.classroom_id == classroom_id,
            SeatAssignment.teacher_id == current_user.id,
            SeatAssignment.is_deleted == False,  # noqa: E712
        )
    ).all()


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


@router.get("/students/{student_id}/notebook-checks", response_model=list[NotebookCheckRead])
def list_notebook_checks(student_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    return session.exec(
        select(NotebookCheck).where(NotebookCheck.student_id == student_id, NotebookCheck.is_deleted == False)  # noqa: E712
    ).all()
