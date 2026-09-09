from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.common import SessionStatus, UserRole
from app.models.identity import User
from app.models.session import ClassSession, LessonLog, SessionEvent
from app.schemas.session import (
    ClassSessionClose,
    ClassSessionCreate,
    ClassSessionRead,
    LessonLogCreate,
    LessonLogRead,
    SessionEventCreate,
    SessionEventRead,
)

router = APIRouter(tags=["sessions"])


def _ensure_owns_session(class_session: ClassSession, current_user: User) -> None:
    """A ClassSession is one lesson period run by ONE teacher -- unlike
    Student/Assessment there's no legitimate multi-teacher collaboration
    case for writing into someone else's session (the cross-teacher reads
    elsewhere, e.g. the behaviour score or a student's ledger, are about
    aggregating a classroom's whole history for council purposes, not about
    tapping new events into another teacher's ongoing lesson).
    """
    if class_session.teacher_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="هذه الحصة ليست لك، فلا يمكنك تعديلها أو تسجيل أحداث فيها.")


@router.post("/class-sessions", response_model=ClassSessionRead)
def open_session(
    payload: ClassSessionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    class_session = ClassSession(**payload.model_dump(), teacher_id=current_user.id)
    session.add(class_session)
    session.commit()
    session.refresh(class_session)
    return class_session


@router.post("/class-sessions/{session_id}/events", response_model=SessionEventRead)
def add_session_event(
    session_id: str,
    payload: SessionEventCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """The 'one-tap' endpoint: called once per tap in the seating grid
    (attendance / tardiness / behavior / homework / participation).

    Real gap found in review: this used to accept a tap from ANY
    authenticated teacher for ANY session_id -- not even scoped to a
    teacher of the classroom, just any logged-in account in the whole app
    -- letting a stranger inject attendance/behavior taps into a lesson
    they have nothing to do with. Now requires the session to actually
    exist and belong to the caller.
    """
    if payload.session_id != session_id:
        raise HTTPException(status_code=400, detail="معرّف الحصة غير متطابق")
    class_session = session.get(ClassSession, session_id)
    if not class_session or class_session.is_deleted:
        raise HTTPException(status_code=404, detail="الحصة غير موجودة")
    _ensure_owns_session(class_session, current_user)

    event = SessionEvent(**payload.model_dump())
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("/class-sessions/{session_id}/events", response_model=list[SessionEventRead])
def list_session_events(session_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    return session.exec(
        select(SessionEvent).where(SessionEvent.session_id == session_id, SessionEvent.is_deleted == False)  # noqa: E712
    ).all()


@router.post("/class-sessions/{session_id}/close", response_model=ClassSessionRead)
def close_session(
    session_id: str,
    payload: ClassSessionClose,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Ends the lesson period and, if a curriculum unit was picked, logs it
    as a LessonLog entry (the digital 'cahier de textes' record).
    """
    class_session = session.get(ClassSession, session_id)
    if not class_session or class_session.is_deleted:
        raise HTTPException(status_code=404, detail="الحصة غير موجودة")
    _ensure_owns_session(class_session, current_user)

    class_session.status = SessionStatus.closed
    class_session.end_time = payload.end_time
    class_session.updated_at = datetime.utcnow()
    session.add(class_session)

    if payload.curriculum_unit_id:
        lesson_log = LessonLog(
            session_id=class_session.id,
            classroom_id=class_session.classroom_id,
            teacher_id=current_user.id,
            date=class_session.date,
            curriculum_unit_id=payload.curriculum_unit_id,
            observations=payload.observations,
        )
        session.add(lesson_log)

    session.commit()
    session.refresh(class_session)
    return class_session


@router.post("/lesson-logs", response_model=LessonLogRead)
def create_lesson_log(
    payload: LessonLogCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Direct 'mark this lesson as taught' entry point, independent of the
    class-session open/close lifecycle. `close_session` above already
    creates a LessonLog when a curriculum_unit_id is supplied, but no
    existing screen in the app drives a teacher through that path with a
    curriculum unit attached -- the continuous-monitoring flow is about
    attendance/behavior taps, not curriculum pacing. Rather than bolting a
    curriculum-unit picker onto that unrelated flow, the new annual-plan
    screen calls this endpoint directly to record "this planned unit was
    delivered on this date". Both paths write the same LessonLog table, so
    `GET /classrooms/{id}/lesson-logs` and the pacing-progress indicator see
    entries from either one without caring which path created them.
    """
    log = LessonLog(**payload.model_dump(), teacher_id=current_user.id)
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


@router.get("/classrooms/{classroom_id}/lesson-logs", response_model=list[LessonLogRead])
def list_lesson_logs(classroom_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    return session.exec(
        select(LessonLog).where(LessonLog.classroom_id == classroom_id, LessonLog.is_deleted == False)  # noqa: E712
    ).all()


@router.get("/students/{student_id}/ledger", response_model=list[SessionEventRead])
def student_ledger(student_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    """The 'دفتر التلميذ' timeline: every quick-tap event ever logged for one
    student, across all sessions. Aggregation (counts, rates) is computed
    client-side or in a future dedicated report endpoint.
    """
    return session.exec(
        select(SessionEvent).where(SessionEvent.student_id == student_id, SessionEvent.is_deleted == False)  # noqa: E712
    ).all()
