from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.identity import (
    AcademicYear,
    Classroom,
    School,
    Subject,
    TeacherClassroomAssignment,
    Term,
    User,
)
from app.schemas.academic import (
    AcademicYearCreate,
    AcademicYearRead,
    ClassroomCreate,
    ClassroomRead,
    HomeroomTeacherUpdate,
    SchoolCreate,
    SchoolRead,
    SubjectCreate,
    SubjectRead,
    TeacherClassroomAssignmentCreate,
    TeacherClassroomAssignmentRead,
    TermCreate,
    TermRead,
)

router = APIRouter(tags=["academic"])


@router.post("/schools", response_model=SchoolRead)
def create_school(payload: SchoolCreate, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    school = School(**payload.model_dump())
    session.add(school)
    session.commit()
    session.refresh(school)
    return school


@router.get("/schools", response_model=list[SchoolRead])
def list_schools(session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    return session.exec(select(School).where(School.is_deleted == False)).all()  # noqa: E712


@router.post("/academic-years", response_model=AcademicYearRead)
def create_academic_year(
    payload: AcademicYearCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    year = AcademicYear(**payload.model_dump())
    session.add(year)
    session.commit()
    session.refresh(year)
    return year


@router.get("/academic-years", response_model=list[AcademicYearRead])
def list_academic_years(session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    return session.exec(select(AcademicYear).where(AcademicYear.is_deleted == False)).all()  # noqa: E712


@router.post("/terms", response_model=TermRead)
def create_term(payload: TermCreate, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    """A trimester/semester -- council reports and grade averages are always
    computed for one term (see /council)."""
    term = Term(**payload.model_dump())
    session.add(term)
    session.commit()
    session.refresh(term)
    return term


@router.get("/terms", response_model=list[TermRead])
def list_terms(
    academic_year_id: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    return session.exec(
        select(Term)
        .where(Term.academic_year_id == academic_year_id, Term.is_deleted == False)  # noqa: E712
        .order_by(Term.order_index)
    ).all()


@router.post("/subjects", response_model=SubjectRead)
def create_subject(payload: SubjectCreate, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    subject = Subject(**payload.model_dump())
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


@router.get("/subjects", response_model=list[SubjectRead])
def list_subjects(session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    return session.exec(select(Subject).where(Subject.is_deleted == False)).all()  # noqa: E712


@router.post("/classrooms", response_model=ClassroomRead)
def create_classroom(
    payload: ClassroomCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    classroom = Classroom(**payload.model_dump(), teacher_id=current_user.id)
    session.add(classroom)
    session.commit()
    session.refresh(classroom)
    return classroom


@router.get("/classrooms", response_model=list[ClassroomRead])
def list_classrooms(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return session.exec(
        select(Classroom).where(Classroom.teacher_id == current_user.id, Classroom.is_deleted == False)  # noqa: E712
    ).all()


@router.patch("/classrooms/{classroom_id}/homeroom-teacher", response_model=ClassroomRead)
def set_homeroom_teacher(
    classroom_id: str,
    payload: HomeroomTeacherUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """A teacher may be 'الأستاذ الرئيسي' for AT MOST ONE classroom per
    academic year (see the unique constraint on Classroom). We check this
    proactively for a friendly error message, and still rely on the DB
    constraint as the real guarantee against a race between two requests.
    """
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")

    if payload.homeroom_teacher_id:
        conflict = session.exec(
            select(Classroom).where(
                Classroom.homeroom_teacher_id == payload.homeroom_teacher_id,
                Classroom.academic_year_id == classroom.academic_year_id,
                Classroom.id != classroom_id,
                Classroom.is_deleted == False,  # noqa: E712
            )
        ).first()
        if conflict:
            raise HTTPException(
                status_code=400,
                detail=f"هذا الأستاذ مسؤول بالفعل عن القسم '{conflict.name}' هذه السنة الدراسية — لا يمكن أن يكون أستاذاً رئيسياً لأكثر من قسم واحد.",
            )

    classroom.homeroom_teacher_id = payload.homeroom_teacher_id
    classroom.updated_at = datetime.utcnow()
    session.add(classroom)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail="هذا الأستاذ مسؤول بالفعل عن قسم آخر هذه السنة الدراسية.",
        )
    session.refresh(classroom)
    return classroom


@router.post("/teacher-classroom-assignments", response_model=TeacherClassroomAssignmentRead)
def assign_teacher_to_classroom(
    payload: TeacherClassroomAssignmentCreate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Records 'this teacher teaches this subject in this classroom, this
    year' -- a teacher naturally accumulates many of these (they teach
    several classrooms); nothing limits that. Only the homeroom-teacher role
    above is capped at one.
    """
    assignment = TeacherClassroomAssignment(**payload.model_dump())
    session.add(assignment)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="هذا التعيين موجود بالفعل")
    session.refresh(assignment)
    return assignment


@router.get("/classrooms/{classroom_id}/teacher-assignments", response_model=list[TeacherClassroomAssignmentRead])
def list_teacher_assignments(
    classroom_id: str,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Every subject teacher assigned to this classroom -- what a council
    report joins across to gather each subject's grades.
    """
    return session.exec(
        select(TeacherClassroomAssignment).where(
            TeacherClassroomAssignment.classroom_id == classroom_id,
            TeacherClassroomAssignment.is_deleted == False,  # noqa: E712
        )
    ).all()
