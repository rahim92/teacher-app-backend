from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.auth import get_current_user
from app.database import get_session
from app.models.common import UserRole
from app.models.identity import (
    AcademicYear,
    ClassDelegate,
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
    AcademicYearUpdate,
    ClassDelegateCreate,
    ClassDelegateRead,
    ClassroomCreate,
    ClassroomDirectoryEntry,
    ClassroomRead,
    HomeroomTeacherUpdate,
    MyClassroomRead,
    SchoolCreate,
    SchoolRead,
    SubjectCreate,
    SubjectRead,
    TaughtSubjectInfo,
    TeacherClassroomAssignmentCreate,
    TeacherClassroomAssignmentRead,
    TermCreate,
    TermRead,
    TermUpdate,
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


@router.patch("/academic-years/{year_id}", response_model=AcademicYearRead)
def update_academic_year(
    year_id: str,
    payload: AcademicYearUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Corrects a school year's own date range (label/start_date/end_date) --
    most commonly needed when a year was created with a stale default range
    (e.g. rolled over from last year's dates) that no longer brackets the
    real current date. MVP: open to any authenticated teacher, like the rest
    of academic setup.
    """
    year = session.get(AcademicYear, year_id)
    if not year or year.is_deleted:
        raise HTTPException(status_code=404, detail="السنة الدراسية غير موجودة")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(year, field, value)
    year.updated_at = datetime.utcnow()
    session.add(year)
    session.commit()
    session.refresh(year)
    return year


@router.post("/terms", response_model=TermRead)
def create_term(payload: TermCreate, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    """A trimester/semester -- council reports and grade averages are always
    computed for one term (see /council)."""
    term = Term(**payload.model_dump())
    session.add(term)
    session.commit()
    session.refresh(term)
    return term


@router.patch("/terms/{term_id}", response_model=TermRead)
def update_term(
    term_id: str,
    payload: TermUpdate,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Corrects a term's date range after the fact. This matters beyond
    cosmetics: a term's [start_date, end_date] gates whether anything
    recorded for it is ever found again -- grade entry's "افتح فرضاً
    مسجَّلاً" picker and /council both filter assessments by
    `term.start_date <= assessment.date <= term.end_date`, and
    /seat-assignments filters the same way by term_id. A term stuck with a
    stale range (e.g. defaulted to last year's dates) silently hides
    everything dated in the real current year from those views, with no
    error -- so unlike most records here, this one needs to be fixable
    in place, not just re-creatable.
    """
    term = session.get(Term, term_id)
    if not term or term.is_deleted:
        raise HTTPException(status_code=404, detail="الفصل الدراسي غير موجود")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(term, field, value)
    term.updated_at = datetime.utcnow()
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
    """Classrooms THIS teacher created in this app -- kept for backward
    compatibility. To see every classroom a teacher actually teaches in
    (as homeroom teacher, a subject teacher, or the creator), use
    /my-classrooms below -- a teacher in a real متوسط school commonly
    teaches 3-4+ classrooms by subject while creating none of them.
    """
    return session.exec(
        select(Classroom).where(Classroom.teacher_id == current_user.id, Classroom.is_deleted == False)  # noqa: E712
    ).all()


@router.get("/my-classrooms", response_model=list[MyClassroomRead])
def list_my_classrooms(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """Every classroom this teacher has ANY real relation to this year:
    created it, is its homeroom teacher ('الأستاذ الرئيسي' -- at most one),
    or teaches a subject in it (TeacherClassroomAssignment -- commonly
    several). Each result is tagged with that teacher's specific role(s) so
    the app can show, e.g., '🎓 مسؤول' next to the one homeroom classroom and
    a subject badge for every other classroom they teach in.
    """
    assigned_classroom_ids = set(
        session.exec(
            select(TeacherClassroomAssignment.classroom_id).where(
                TeacherClassroomAssignment.teacher_id == current_user.id,
                TeacherClassroomAssignment.is_deleted == False,  # noqa: E712
            )
        ).all()
    )
    classrooms = session.exec(
        select(Classroom).where(
            Classroom.is_deleted == False,  # noqa: E712
            (Classroom.teacher_id == current_user.id)
            | (Classroom.homeroom_teacher_id == current_user.id)
            | (Classroom.id.in_(list(assigned_classroom_ids)) if assigned_classroom_ids else (Classroom.id == None))  # noqa: E711
        )
    ).all()

    results: list[MyClassroomRead] = []
    for classroom in classrooms:
        my_assignments = session.exec(
            select(TeacherClassroomAssignment, Subject)
            .join(Subject, Subject.id == TeacherClassroomAssignment.subject_id)
            .where(
                TeacherClassroomAssignment.classroom_id == classroom.id,
                TeacherClassroomAssignment.teacher_id == current_user.id,
                TeacherClassroomAssignment.is_deleted == False,  # noqa: E712
            )
        ).all()
        homeroom_name = None
        if classroom.homeroom_teacher_id:
            homeroom_user = session.get(User, classroom.homeroom_teacher_id)
            homeroom_name = homeroom_user.full_name if homeroom_user else None
        results.append(
            MyClassroomRead(
                **classroom.model_dump(),
                is_creator=classroom.teacher_id == current_user.id,
                is_homeroom=classroom.homeroom_teacher_id == current_user.id,
                homeroom_teacher_name=homeroom_name,
                taught_subjects=[
                    TaughtSubjectInfo(subject_id=subj.id, subject_name=subj.name) for _assign, subj in my_assignments
                ],
            )
        )
    return results


@router.get("/classrooms/directory", response_model=list[ClassroomDirectoryEntry])
def classroom_directory(
    academic_year_id: Optional[str] = None,
    session: Session = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Every classroom in the school (optionally scoped to one academic
    year), regardless of who created it -- so a subject teacher can find a
    classroom a colleague already set up and request a
    TeacherClassroomAssignment in it, instead of re-creating it. Read-only
    and open to any authenticated teacher, consistent with the rest of the
    app's MVP permission model (see e.g. delegates GET).
    """
    query = select(Classroom).where(Classroom.is_deleted == False)  # noqa: E712
    if academic_year_id:
        query = query.where(Classroom.academic_year_id == academic_year_id)
    classrooms = session.exec(query).all()
    entries = []
    for classroom in classrooms:
        homeroom_name = None
        if classroom.homeroom_teacher_id:
            homeroom_user = session.get(User, classroom.homeroom_teacher_id)
            homeroom_name = homeroom_user.full_name if homeroom_user else None
        entries.append(
            ClassroomDirectoryEntry(
                id=classroom.id,
                name=classroom.name,
                grade_level=classroom.grade_level,
                academic_year_id=classroom.academic_year_id,
                homeroom_teacher_name=homeroom_name,
            )
        )
    return entries


@router.patch("/classrooms/{classroom_id}/homeroom-teacher", response_model=ClassroomRead)
def set_homeroom_teacher(
    classroom_id: str,
    payload: HomeroomTeacherUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """A teacher may be 'الأستاذ الرئيسي' for AT MOST ONE classroom per
    academic year (see the unique constraint on Classroom). We check this
    proactively for a friendly error message, and still rely on the DB
    constraint as the real guarantee against a race between two requests.

    Real authorization gap found during a review pass: this endpoint used to
    accept ANY authenticated teacher's token with no ownership check at
    all -- meaning any teacher could reassign (hijack) another teacher's
    classroom leadership, which also gates who can manage class delegates
    and read the full council report. Restricted to whoever created the
    classroom, whoever already holds the homeroom role on it (so a handoff
    is still possible), or an admin.
    """
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    is_creator = classroom.teacher_id == current_user.id
    is_current_homeroom = classroom.homeroom_teacher_id == current_user.id
    is_admin = current_user.role == UserRole.admin
    if not (is_creator or is_current_homeroom or is_admin):
        raise HTTPException(
            status_code=403,
            detail="تعيين الأستاذ الرئيسي متاح فقط لمنشئ القسم أو الأستاذ الرئيسي الحالي أو الإدارة.",
        )

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


def _ensure_can_manage_delegates(classroom: Classroom, current_user: User) -> None:
    """Recording a delegate is the homeroom teacher's job (per decision
    836/39 they supervise the class election and log the result) -- not a
    thing any subject teacher of the class should be able to overwrite.
    """
    is_homeroom_teacher = classroom.homeroom_teacher_id == current_user.id
    is_admin = current_user.role == UserRole.admin
    if not (is_homeroom_teacher or is_admin):
        raise HTTPException(
            status_code=403,
            detail="تسجيل نتيجة انتخاب مندوبي القسم متاح فقط للأستاذ الرئيسي لهذا القسم أو للإدارة.",
        )


@router.post("/classrooms/{classroom_id}/delegates", response_model=ClassDelegateRead)
def add_class_delegate(
    classroom_id: str,
    payload: ClassDelegateCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Records the outcome of the class delegate election (مندوبو القسم) --
    the app never 'appoints' a delegate; it only stores who the class
    elected, entered by the homeroom teacher who supervised the vote.
    """
    if payload.classroom_id != classroom_id:
        raise HTTPException(status_code=400, detail="معرّف القسم غير متطابق")
    classroom = session.get(Classroom, classroom_id)
    if not classroom or classroom.is_deleted:
        raise HTTPException(status_code=404, detail="القسم غير موجود")
    _ensure_can_manage_delegates(classroom, current_user)

    delegate = ClassDelegate(**payload.model_dump())
    session.add(delegate)
    session.commit()
    session.refresh(delegate)
    return delegate


@router.get("/classrooms/{classroom_id}/delegates", response_model=list[ClassDelegateRead])
def list_class_delegates(classroom_id: str, session: Session = Depends(get_session), _: User = Depends(get_current_user)):
    """Read-only for every teacher assigned to the classroom (and beyond --
    MVP keeps GETs open to any authenticated teacher like the rest of the
    app; only the write side is restricted). This is the whole point of the
    feature: every subject teacher should know who the class's delegates are.
    """
    return session.exec(
        select(ClassDelegate).where(ClassDelegate.classroom_id == classroom_id, ClassDelegate.is_deleted == False)  # noqa: E712
    ).all()


@router.delete("/class-delegates/{delegate_id}", status_code=204)
def remove_class_delegate(delegate_id: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    delegate = session.get(ClassDelegate, delegate_id)
    if not delegate or delegate.is_deleted:
        raise HTTPException(status_code=404, detail="المندوب غير موجود")
    classroom = session.get(Classroom, delegate.classroom_id)
    _ensure_can_manage_delegates(classroom, current_user)
    delegate.is_deleted = True
    delegate.updated_at = datetime.utcnow()
    session.add(delegate)
    session.commit()
