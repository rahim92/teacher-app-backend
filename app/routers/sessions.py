from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.common import LessonLogType, SessionStatus, UserRole
from app.models.identity import Classroom, TeacherClassroomAssignment, User
from app.models.session import ClassSession, LessonLog, SessionEvent
from app.schemas.session import (
    ClassSessionClose,
    ClassSessionCreate,
    ClassSessionRead,
    LessonLogCreate,
    LessonLogRead,
    LessonLogUpdate,
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


def _ensure_teaches_classroom(session: Session, classroom: Classroom, current_user: User) -> None:
    """Same "creator, homeroom teacher, or subject-teacher assignment"
    relation used by students._ensure_can_manage_student -- LessonLog is
    shared at the classroom level (like the real paper دفتر النصوص/الكراس
    اليومي, which stays in the classroom and every subject teacher writes
    their own lessons into it), so this deliberately isn't narrowed to one
    subject the way grades._ensure_can_view_subject_grades is. Real gap
    found while adding this: create_lesson_log had NO ownership check at
    all -- any authenticated teacher could log a lesson (or a holiday) into
    any classroom in the whole app.
    """
    if current_user.role == UserRole.admin:
        return
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
        raise HTTPException(status_code=403, detail="لا تُدرِّس في هذا القسم، فلا يمكنك الكتابة في كراسه اليومي.")


def _ensure_curriculum_unit_required(lesson_type: LessonLogType, curriculum_unit_id: Optional[str]) -> None:
    """Every lesson_type except `holiday` covers real curriculum content and
    must point at a unit; a holiday/توقف entry has nothing to point at by
    definition. Enforced here (not as a DB constraint) since it depends on
    another field's value, and both create and update need the same check.
    """
    if lesson_type != LessonLogType.holiday and not curriculum_unit_id:
        raise HTTPException(
            status_code=400,
            detail="يجب تحديد الوحدة المدروسة لهذا النوع من الحصص (عدا العطلة/التوقف).",
        )


def _get_owned_lesson_log(session: Session, log_id: str, current_user: User) -> LessonLog:
    log = session.get(LessonLog, log_id)
    if not log or log.is_deleted:
        raise HTTPException(status_code=404, detail="لم يتم العثور على هذا التسجيل في الكراس اليومي")
    if log.teacher_id != current_user.id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="يمكن فقط لصاحب هذا التسجيل أو الإدارة تعديله أو حذفه.")
    return log


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
    """The digital دفتر النصوص/الكراس اليومي entry point, independent of the
    class-session open/close lifecycle. `close_session` above already
    creates a LessonLog when a curriculum_unit_id is supplied, but no
    existing screen in the app drives a teacher through that path with a
    curriculum unit attached -- the continuous-monitoring flow is about
    attendance/behavior taps, not curriculum pacing. Rather than bolting a
    curriculum-unit picker onto that unrelated flow, the annual-plan screen
    calls this endpoint directly to record "this planned unit was delivered
    on this date", and the richer دفتر النصوص screen (lesson_type/resource/
    observations, any lesson_type including non-curriculum ones like a
    holiday) also calls it directly. Both/all paths write the same
    LessonLog table, so `GET /classrooms/{id}/lesson-logs` and the
    pacing-progress indicator see entries from any of them without caring
    which screen created them.
    """
    classroom = session.get(Classroom, payload.classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_teaches_classroom(session, classroom, current_user)
    _ensure_curriculum_unit_required(payload.lesson_type, payload.curriculum_unit_id)

    log = LessonLog(**payload.model_dump(), teacher_id=current_user.id)
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


@router.patch("/lesson-logs/{log_id}", response_model=LessonLogRead)
def update_lesson_log(
    log_id: str,
    payload: LessonLogUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    log = _get_owned_lesson_log(session, log_id, current_user)
    updates = payload.model_dump(exclude_unset=True)
    new_type = updates.get("lesson_type", log.lesson_type)
    new_unit = updates.get("curriculum_unit_id", log.curriculum_unit_id)
    _ensure_curriculum_unit_required(new_type, new_unit)

    for field, value in updates.items():
        setattr(log, field, value)
    log.updated_at = datetime.utcnow()
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


@router.delete("/lesson-logs/{log_id}", status_code=204)
def delete_lesson_log(
    log_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    log = _get_owned_lesson_log(session, log_id, current_user)
    log.is_deleted = True
    log.updated_at = datetime.utcnow()
    session.add(log)
    session.commit()


@router.get("/classrooms/{classroom_id}/lesson-logs", response_model=list[LessonLogRead])
def list_lesson_logs(
    classroom_id: str,
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
    lesson_type: Optional[LessonLogType] = Query(default=None),
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Shared at the classroom level on purpose (no teacher_id filter --
    every subject teacher writes into the same notebook), with the same
    date-range/type search the competitor's دفتر النصوص advertises. Newest
    first, since "what did I log today/yesterday" is the common case."""
    query = select(LessonLog).where(LessonLog.classroom_id == classroom_id, LessonLog.is_deleted == False)  # noqa: E712
    if date_from:
        query = query.where(LessonLog.date >= date_from)
    if date_to:
        query = query.where(LessonLog.date <= date_to)
    if lesson_type:
        query = query.where(LessonLog.lesson_type == lesson_type)
    query = query.order_by(LessonLog.date.desc(), LessonLog.created_at.desc())  # type: ignore[union-attr]
    return session.exec(query).all()


@router.get("/students/{student_id}/ledger", response_model=list[SessionEventRead])
def student_ledger(student_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    """The 'دفتر التلميذ' timeline: every quick-tap event ever logged for one
    student, across all sessions. Aggregation (counts, rates) is computed
    client-side or in a future dedicated report endpoint.
    """
    return session.exec(
        select(SessionEvent).where(SessionEvent.student_id == student_id, SessionEvent.is_deleted == False)  # noqa: E712
    ).all()
