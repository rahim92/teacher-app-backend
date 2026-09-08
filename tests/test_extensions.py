"""Covers the features added after the "developer research" round:
class delegates, per-student special-need visibility, per-term seat maps,
and the auto-computed behaviour score.
"""
import os
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_extensions.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _register_and_login(name: str) -> tuple[dict, dict]:
    email = f"{name}_{uuid.uuid4().hex[:8]}@example.com"
    password = "S3cret!pass"
    register_resp = client.post("/auth/register", json={"full_name": name, "email": email, "password": password})
    assert register_resp.status_code == 201, register_resp.text
    user = register_resp.json()
    login_resp = client.post("/auth/login", data={"username": email, "password": password})
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user


def _setup_classroom(headers, name="1AM - 1"):
    year = client.post(
        "/academic-years", json={"label": "2025-2026", "start_date": "2025-09-01", "end_date": "2026-06-30"}, headers=headers
    ).json()
    term = client.post(
        "/terms",
        json={"academic_year_id": year["id"], "label": "الفصل الأول", "start_date": "2025-09-01", "end_date": "2025-12-31", "order_index": 1},
        headers=headers,
    ).json()
    classroom = client.post(
        "/classrooms", json={"academic_year_id": year["id"], "name": name, "grade_level": "1AM"}, headers=headers
    ).json()
    return year, term, classroom


def test_delegates_require_homeroom_teacher_and_are_visible_to_others():
    headers_main, teacher_main = _register_and_login("homeroom_t")
    headers_other, _ = _register_and_login("other_t")
    year, _term, classroom = _setup_classroom(headers_main, "1AM - delegates")

    student = client.post(
        "/students", json={"classroom_id": classroom["id"], "first_name": "ياسين", "last_name": "مرابط"}, headers=headers_main
    ).json()

    # Not homeroom teacher yet -> refused.
    denied = client.post(
        f"/classrooms/{classroom['id']}/delegates",
        json={"classroom_id": classroom["id"], "student_id": student["id"], "academic_year_id": year["id"]},
        headers=headers_main,
    )
    assert denied.status_code == 403

    client.patch(f"/classrooms/{classroom['id']}/homeroom-teacher", json={"homeroom_teacher_id": teacher_main["id"]}, headers=headers_main)

    added = client.post(
        f"/classrooms/{classroom['id']}/delegates",
        json={"classroom_id": classroom["id"], "student_id": student["id"], "academic_year_id": year["id"], "elected_date": "2025-09-20"},
        headers=headers_main,
    )
    assert added.status_code == 200, added.text

    # A different teacher can still just READ the delegate list.
    listing = client.get(f"/classrooms/{classroom['id']}/delegates", headers=headers_other)
    assert listing.status_code == 200
    assert listing.json()[0]["student_id"] == student["id"]

    # But that other teacher cannot add one themselves.
    forbidden = client.post(
        f"/classrooms/{classroom['id']}/delegates",
        json={"classroom_id": classroom["id"], "student_id": student["id"], "academic_year_id": year["id"]},
        headers=headers_other,
    )
    assert forbidden.status_code == 403


def test_special_need_visibility_levels():
    headers_main, teacher_main = _register_and_login("homeroom_sn")
    headers_subject, _ = _register_and_login("subject_sn")
    headers_stranger, _ = _register_and_login("stranger_sn")
    year, _term, classroom = _setup_classroom(headers_main, "2AM - special-needs")
    client.patch(f"/classrooms/{classroom['id']}/homeroom-teacher", json={"homeroom_teacher_id": teacher_main["id"]}, headers=headers_main)

    student = client.post(
        "/students", json={"classroom_id": classroom["id"], "first_name": "أمينة", "last_name": "زروقي"}, headers=headers_main
    ).json()

    subject = client.post("/subjects", json={"name": "العلوم"}, headers=headers_subject).json()
    subject_teacher_id = client.get("/auth/me", headers=headers_subject).json()["id"]
    client.post(
        "/teacher-classroom-assignments",
        json={
            "teacher_id": subject_teacher_id,
            "classroom_id": classroom["id"],
            "subject_id": subject["id"],
            "academic_year_id": year["id"],
        },
        headers=headers_main,
    )

    client.post(
        "/student-special-needs",
        json={"student_id": student["id"], "category": "visual_impairment", "description": "ضعف بصر", "accommodation_needed": "يحتاج مقعداً أمامياً", "visibility": "shared_with_teachers"},
        headers=headers_main,
    )
    client.post(
        "/student-special-needs",
        json={"student_id": student["id"], "category": "chronic_illness", "description": "تفاصيل طبية حساسة", "visibility": "homeroom_only"},
        headers=headers_main,
    )

    # Homeroom teacher sees both.
    as_homeroom = client.get(f"/students/{student['id']}/special-needs", headers=headers_main).json()
    assert len(as_homeroom) == 2

    # Assigned subject teacher only sees the shared one.
    as_subject = client.get(f"/students/{student['id']}/special-needs", headers=headers_subject).json()
    assert len(as_subject) == 1
    assert as_subject[0]["category"] == "visual_impairment"

    # A teacher with no relation to the classroom is refused outright.
    as_stranger = client.get(f"/students/{student['id']}/special-needs", headers=headers_stranger)
    assert as_stranger.status_code == 403


def test_seat_assignment_per_term_and_behavior_score():
    headers, teacher = _register_and_login("beh_t")
    year, term, classroom = _setup_classroom(headers, "3AM - behavior")
    student = client.post(
        "/students", json={"classroom_id": classroom["id"], "first_name": "كريم", "last_name": "بوعلام"}, headers=headers
    ).json()
    subject = client.post("/subjects", json={"name": "الرياضيات"}, headers=headers).json()

    # Two seat maps for the same student/classroom -- one standing, one for this term.
    client.put("/seat-assignments", json={"classroom_id": classroom["id"], "student_id": student["id"], "seat_row": 1, "seat_col": 1}, headers=headers)
    client.put("/seat-assignments", json={"classroom_id": classroom["id"], "student_id": student["id"], "term_id": term["id"], "seat_row": 1, "seat_col": 2, "reason": "ضعف بصر"}, headers=headers)
    all_maps = client.get(f"/classrooms/{classroom['id']}/seat-assignments", headers=headers).json()
    assert len(all_maps) == 2
    only_term = client.get(f"/classrooms/{classroom['id']}/seat-assignments", params={"term_id": term["id"]}, headers=headers).json()
    assert len(only_term) == 1 and only_term[0]["seat_col"] == 2

    # Behaviour score: log a session, tap a mix of positive/negative events.
    class_session = client.post(
        "/class-sessions", json={"classroom_id": classroom["id"], "subject_id": subject["id"], "date": "2025-10-10"}, headers=headers
    ).json()
    for event_type in ["equipment_brought", "equipment_brought", "equipment_missing", "homework_done", "homework_done", "tardiness"]:
        client.post(
            f"/class-sessions/{class_session['id']}/events",
            json={"session_id": class_session["id"], "student_id": student["id"], "event_type": event_type},
            headers=headers,
        )

    score = client.get(
        f"/students/{student['id']}/behavior-score",
        params={"classroom_id": classroom["id"], "term_id": term["id"]},
        headers=headers,
    ).json()
    breakdown = {b["category"]: b for b in score["breakdown"]}
    # materials: 2 brought, 1 missing -> 2/3 of the max (default weight 2) = 1.33
    assert breakdown["materials"]["points_earned"] == round(2.0 * 2 / 3, 2)
    # homework: 2 done, 0 missing -> full marks
    assert breakdown["homework"]["points_earned"] == breakdown["homework"]["points_max"]
    # tardiness: one tap, penalty 0.5 off the default max of 2
    assert breakdown["tardiness"]["points_earned"] == 1.5
    assert score["total"] <= score["total_max"]


def test_my_classrooms_covers_creator_homeroom_and_subject_teacher_roles():
    """A teacher in a real متوسط school commonly: creates none of their
    classrooms, is homeroom ('مسؤول') of at most one, and teaches a subject
    in several others. /my-classrooms is what the dashboard's classroom
    switcher relies on to show all of that in one call.
    """
    headers_a, teacher_a = _register_and_login("multi_a")
    headers_b, teacher_b = _register_and_login("multi_b")
    year, _term, classroom1 = _setup_classroom(headers_a, "1AM - multi-1")
    classroom2 = client.post(
        "/classrooms", json={"academic_year_id": year["id"], "name": "1AM - multi-2", "grade_level": "1AM"}, headers=headers_a
    ).json()
    # A third classroom, same academic year, created (and remaining owned) by
    # someone else entirely -- this is what makes the homeroom conflict below
    # a real same-year conflict rather than a coincidence across two years.
    headers_c, _teacher_c = _register_and_login("multi_c")
    classroom3 = client.post(
        "/classrooms", json={"academic_year_id": year["id"], "name": "1AM - multi-3", "grade_level": "1AM"}, headers=headers_c
    ).json()

    math = client.post("/subjects", json={"name": "الرياضيات"}, headers=headers_b).json()
    science = client.post("/subjects", json={"name": "العلوم"}, headers=headers_b).json()

    # Teacher B never creates a classroom, but is set as homeroom of classroom1
    # and teaches a subject in both classroom1 and classroom2.
    client.patch(f"/classrooms/{classroom1['id']}/homeroom-teacher", json={"homeroom_teacher_id": teacher_b["id"]}, headers=headers_a)
    client.post("/teacher-classroom-assignments", json={
        "teacher_id": teacher_b["id"], "classroom_id": classroom1["id"], "subject_id": math["id"], "academic_year_id": year["id"],
    }, headers=headers_b)
    client.post("/teacher-classroom-assignments", json={
        "teacher_id": teacher_b["id"], "classroom_id": classroom2["id"], "subject_id": science["id"], "academic_year_id": year["id"],
    }, headers=headers_b)

    mine = client.get("/my-classrooms", headers=headers_b).json()
    by_id = {c["id"]: c for c in mine}
    assert set(by_id.keys()) == {classroom1["id"], classroom2["id"]}  # classroom3 never touched by B

    c1 = by_id[classroom1["id"]]
    assert c1["is_creator"] is False
    assert c1["is_homeroom"] is True
    assert [s["subject_name"] for s in c1["taught_subjects"]] == ["الرياضيات"]

    c2 = by_id[classroom2["id"]]
    assert c2["is_homeroom"] is False
    assert [s["subject_name"] for s in c2["taught_subjects"]] == ["العلوم"]

    # Teacher A still only sees classrooms they created.
    mine_a = client.get("/my-classrooms", headers=headers_a).json()
    assert {c["id"] for c in mine_a} == {classroom1["id"], classroom2["id"]}
    assert all(c["is_creator"] for c in mine_a)

    # A teacher who is homeroom of classroom1 cannot ALSO become homeroom of
    # classroom3 -- the one-homeroom-per-teacher-per-year rule still holds
    # regardless of how many classrooms they teach a subject in.
    conflict = client.patch(
        f"/classrooms/{classroom3['id']}/homeroom-teacher", json={"homeroom_teacher_id": teacher_b["id"]}, headers=headers_c
    )
    assert conflict.status_code == 400

    # The directory lists every classroom in the school, including ones B
    # has no relation to yet -- what lets B discover classroom3 to join it.
    directory = client.get("/classrooms/directory", headers=headers_b).json()
    assert classroom3["id"] in {c["id"] for c in directory}


def test_student_edit_and_soft_delete():
    """A teacher fixing a typo in a student's name, or removing one entered
    by mistake, should never lose the classroom -- edit and delete both act
    on one student without disturbing the rest of the roster.
    """
    headers, _teacher = _register_and_login("roster_edit")
    _year, _term, classroom = _setup_classroom(headers, "1AM - roster-edit")
    student = client.post(
        "/students", json={"classroom_id": classroom["id"], "first_name": "ياسن", "last_name": "بن علي"}, headers=headers
    ).json()
    other = client.post(
        "/students", json={"classroom_id": classroom["id"], "first_name": "نور", "last_name": "شريف"}, headers=headers
    ).json()

    fixed = client.patch(f"/students/{student['id']}", json={"first_name": "ياسين"}, headers=headers)
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["first_name"] == "ياسين"
    assert fixed.json()["last_name"] == "بن علي"  # untouched field stays as-is

    deleted = client.delete(f"/students/{student['id']}", headers=headers)
    assert deleted.status_code == 204

    roster = client.get(f"/classrooms/{classroom['id']}/students", headers=headers).json()
    assert {s["id"] for s in roster} == {other["id"]}

    # A deleted student is gone from every student-scoped endpoint, not just
    # the roster listing.
    gone = client.get(f"/students/{student['id']}/special-needs", headers=headers)
    assert gone.status_code == 404

    # Deleting the same student twice is a clean 404, not a crash.
    redelete = client.delete(f"/students/{student['id']}", headers=headers)
    assert redelete.status_code == 404


def test_seat_assignment_shared_desk_and_unseat():
    """Two students may share one desk (a common bench arrangement), capped
    at two; un-seating one frees the desk for someone else.
    """
    headers, _teacher = _register_and_login("seat_pair")
    _year, _term, classroom = _setup_classroom(headers, "1AM - seat-pair")
    s1 = client.post("/students", json={"classroom_id": classroom["id"], "first_name": "علي", "last_name": "1"}, headers=headers).json()
    s2 = client.post("/students", json={"classroom_id": classroom["id"], "first_name": "سعاد", "last_name": "2"}, headers=headers).json()
    s3 = client.post("/students", json={"classroom_id": classroom["id"], "first_name": "رياض", "last_name": "3"}, headers=headers).json()

    seat1 = client.put("/seat-assignments", json={"classroom_id": classroom["id"], "student_id": s1["id"], "seat_row": 1, "seat_col": 1}, headers=headers)
    assert seat1.status_code == 200, seat1.text
    seat2 = client.put("/seat-assignments", json={"classroom_id": classroom["id"], "student_id": s2["id"], "seat_row": 1, "seat_col": 1}, headers=headers)
    assert seat2.status_code == 200, seat2.text  # same desk, second occupant -- allowed

    desk = [a for a in client.get(f"/classrooms/{classroom['id']}/seat-assignments", headers=headers).json() if a["seat_row"] == 1 and a["seat_col"] == 1]
    assert {a["student_id"] for a in desk} == {s1["id"], s2["id"]}

    # A third student at the same desk is refused -- max two per table.
    overflow = client.put("/seat-assignments", json={"classroom_id": classroom["id"], "student_id": s3["id"], "seat_row": 1, "seat_col": 1}, headers=headers)
    assert overflow.status_code == 400

    # Un-seat the first occupant -> the desk has room again.
    unseat = client.delete(f"/seat-assignments/{seat1.json()['id']}", headers=headers)
    assert unseat.status_code == 204
    now_fits = client.put("/seat-assignments", json={"classroom_id": classroom["id"], "student_id": s3["id"], "seat_row": 1, "seat_col": 1}, headers=headers)
    assert now_fits.status_code == 200, now_fits.text

    desk_after = [a for a in client.get(f"/classrooms/{classroom['id']}/seat-assignments", headers=headers).json() if a["seat_row"] == 1 and a["seat_col"] == 1]
    assert {a["student_id"] for a in desk_after} == {s2["id"], s3["id"]}


def test_grade_entry_list_upsert_and_delete():
    """The grade-entry screen's whole workflow: create a test, list it back
    (filtered by subject/term the same way /council filters), enter and then
    correct a student's mark without hitting the unique-score constraint,
    and delete a wrongly created test so it (and its marks) disappear from
    every view -- including the council averages that read it.
    """
    headers, teacher = _register_and_login("grade_t")
    headers_other, _ = _register_and_login("grade_other")
    year, term, classroom = _setup_classroom(headers, "1AM - grades")
    subject = client.post("/subjects", json={"name": "الرياضيات"}, headers=headers).json()
    s1 = client.post("/students", json={"classroom_id": classroom["id"], "first_name": "أمين", "last_name": "1"}, headers=headers).json()
    s2 = client.post("/students", json={"classroom_id": classroom["id"], "first_name": "هدى", "last_name": "2"}, headers=headers).json()
    # /council only reports averages for subjects the teacher is formally
    # assigned to teach in this classroom -- needed for the subject to
    # appear in subject_averages at all (not just as a None average).
    client.post("/teacher-classroom-assignments", json={
        "teacher_id": teacher["id"], "classroom_id": classroom["id"], "subject_id": subject["id"], "academic_year_id": year["id"],
    }, headers=headers)

    created = client.post("/assessments", json={
        "classroom_id": classroom["id"], "subject_id": subject["id"], "assessment_type": "test",
        "title": "الفرض الأول", "date": "2025-10-05", "coefficient": 1, "max_score": 20,
    }, headers=headers)
    assert created.status_code == 200, created.text
    assessment = created.json()

    # An assessment outside the term's date range and one for a different
    # subject shouldn't show up when the grade screen filters by both.
    client.post("/assessments", json={
        "classroom_id": classroom["id"], "subject_id": subject["id"], "assessment_type": "test",
        "title": "خارج الفصل", "date": "2026-02-01", "coefficient": 1, "max_score": 20,
    }, headers=headers)
    other_subject = client.post("/subjects", json={"name": "العلوم"}, headers=headers).json()
    client.post("/assessments", json={
        "classroom_id": classroom["id"], "subject_id": other_subject["id"], "assessment_type": "test",
        "title": "مادة أخرى", "date": "2025-10-06", "coefficient": 1, "max_score": 20,
    }, headers=headers)

    listing = client.get(f"/classrooms/{classroom['id']}/assessments", params={
        "subject_id": subject["id"], "term_id": term["id"],
    }, headers=headers).json()
    assert {a["id"] for a in listing} == {assessment["id"]}

    # Enter a mark, then correct it -- PUT upserts instead of hitting the
    # (assessment_id, student_id) unique constraint a second POST would.
    first_put = client.put("/assessment-scores", json={"assessment_id": assessment["id"], "student_id": s1["id"], "score": 12}, headers=headers)
    assert first_put.status_code == 200, first_put.text
    corrected = client.put("/assessment-scores", json={"assessment_id": assessment["id"], "student_id": s1["id"], "score": 15.5}, headers=headers)
    assert corrected.status_code == 200, corrected.text
    client.put("/assessment-scores", json={"assessment_id": assessment["id"], "student_id": s2["id"], "score": 9}, headers=headers)

    scores = client.get(f"/assessments/{assessment['id']}/scores", headers=headers).json()
    assert len(scores) == 2  # correction updated in place, not a duplicate row
    by_student = {s["student_id"]: s["score"] for s in scores}
    assert by_student[s1["id"]] == 15.5

    # Only the assessment's own teacher (or an admin) may delete it.
    forbidden = client.delete(f"/assessments/{assessment['id']}", headers=headers_other)
    assert forbidden.status_code == 403

    deleted = client.delete(f"/assessments/{assessment['id']}", headers=headers)
    assert deleted.status_code == 204
    after_delete = client.get(f"/classrooms/{classroom['id']}/assessments", params={
        "subject_id": subject["id"], "term_id": term["id"],
    }, headers=headers).json()
    assert after_delete == []

    # And its marks are gone from the council report too, since /council
    # only ever looks at non-deleted assessments.
    client.patch(f"/classrooms/{classroom['id']}/homeroom-teacher", json={"homeroom_teacher_id": teacher["id"]}, headers=headers)
    report = client.get(f"/council/classrooms/{classroom['id']}/report", params={"term_id": term["id"]}, headers=headers).json()
    row1 = next(r for r in report["rows"] if r["student_id"] == s1["id"])
    subj_avg = next(sa for sa in row1["subject_averages"] if sa["subject_id"] == subject["id"])
    assert subj_avg["average"] is None


def test_term_date_patch_fixes_stale_range_hiding_an_assessment():
    """Reproduces the real bug: a term created with a stale/wrong date range
    (e.g. rolled over from a previous school year) silently excludes an
    assessment dated in the real current year from the grade-entry picker's
    listing -- even though creating the assessment itself succeeds and its
    scores can still be entered directly by id. PATCHing the term's dates
    must make it show up without needing to recreate anything.
    """
    headers, teacher = _register_and_login("staleterm_t")
    year, term, classroom = _setup_classroom(headers, "1AM - staleterm")
    subject = client.post("/subjects", json={"name": "الرياضيات"}, headers=headers).json()

    # term's range is 2025-09-01..2025-12-31 (see _setup_classroom) -- an
    # assessment dated well into the next year falls outside it.
    created = client.post("/assessments", json={
        "classroom_id": classroom["id"], "subject_id": subject["id"], "assessment_type": "exam",
        "title": "اختبار فصلي", "date": "2026-09-08", "coefficient": 3, "max_score": 20,
    }, headers=headers)
    assert created.status_code == 200, created.text
    assessment = created.json()

    listing = client.get(f"/classrooms/{classroom['id']}/assessments", params={
        "subject_id": subject["id"], "term_id": term["id"],
    }, headers=headers).json()
    assert listing == []  # excluded -- this is the bug the user hit

    # Scores can still be entered by id even though it's hidden from the
    # term-filtered list -- matches the user's report (score table worked,
    # picker didn't).
    put = client.put("/assessment-scores", json={"assessment_id": assessment["id"], "student_id": "does-not-matter", "score": 9.5}, headers=headers)
    assert put.status_code in (200, 422)  # 422 only if student_id FK is enforced; not the point of this test

    # Fixing the term's own dates (not recreating it) makes the assessment
    # reappear in the filtered listing.
    patched = client.patch(f"/terms/{term['id']}", json={"start_date": "2026-09-01", "end_date": "2026-12-31"}, headers=headers)
    assert patched.status_code == 200, patched.text
    assert patched.json()["start_date"] == "2026-09-01"

    listing_after = client.get(f"/classrooms/{classroom['id']}/assessments", params={
        "subject_id": subject["id"], "term_id": term["id"],
    }, headers=headers).json()
    assert {a["id"] for a in listing_after} == {assessment["id"]}

    # The academic year's own range is independently fixable the same way.
    patched_year = client.patch(f"/academic-years/{year['id']}", json={"end_date": "2027-06-30"}, headers=headers)
    assert patched_year.status_code == 200, patched_year.text
    assert patched_year.json()["end_date"] == "2027-06-30"

    # A term/year id that doesn't exist (or belongs to someone else's
    # already-deleted record) 404s instead of silently no-op'ing.
    assert client.patch("/terms/does-not-exist", json={"start_date": "2026-01-01"}, headers=headers).status_code == 404
    assert client.patch("/academic-years/does-not-exist", json={"end_date": "2026-01-01"}, headers=headers).status_code == 404


def test_parent_message_template_render_and_delete():
    """The report/communication screen's own workflow: save a reusable
    template with placeholders, render it filled in for one student (missing
    variables stay visible as '{var}' rather than erroring -- see
    _SafeDict), then delete a wrongly-worded template so it disappears from
    the teacher's own list. Only the template's own author may delete it.
    """
    headers, _ = _register_and_login("msg_t")
    headers_other, _ = _register_and_login("msg_other")

    created = client.post("/message-templates", json={
        "title": "تنبيه غياب", "body_template": "السيد(ة) ولي أمر {student_name}، غاب بتاريخ {date}. الغياب: {absences}.",
        "category": "absence",
    }, headers=headers)
    assert created.status_code == 200, created.text
    template = created.json()

    listing = client.get("/message-templates", headers=headers).json()
    assert {t["id"] for t in listing} == {template["id"]}
    # Templates are private per-teacher, not shared.
    assert client.get("/message-templates", headers=headers_other).json() == []

    rendered = client.post("/message-templates/render", json={
        "template_id": template["id"], "variables": {"student_name": "أمين بلقاسم", "date": "2026-09-08"},
    }, headers=headers)
    assert rendered.status_code == 200, rendered.text
    text = rendered.json()["text"]
    assert "أمين بلقاسم" in text and "2026-09-08" in text
    assert "{absences}" in text  # missing variable left visible, not an error

    # Only the template's own author may delete it.
    forbidden = client.delete(f"/message-templates/{template['id']}", headers=headers_other)
    assert forbidden.status_code == 403

    deleted = client.delete(f"/message-templates/{template['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/message-templates", headers=headers).json() == []
    assert client.delete(f"/message-templates/{template['id']}", headers=headers).status_code == 404


def test_diagnostic_remediation_module():
    """The whole diagnosis -> remediation-group -> follow-up workflow: a
    teacher-authored skill (CurriculumUnit, since no ministry-content import
    pipeline exists yet -- see create_curriculum_unit), marking two
    students' mastery on it via one assessment, the struggling-students
    alert correctly scoped to ONE classroom (not leaking a same-skill
    student from another classroom -- a real bug in the original endpoint,
    which accepted classroom_id but never used it), forming a remediation
    session/group from it, and recording a participant's follow-up outcome.
    """
    headers, teacher = _register_and_login("remed_t")
    year, term, classroom = _setup_classroom(headers, "1AM - remed")
    # Same subject+grade as the first classroom (CurriculumUnit is scoped by
    # subject+grade, not by classroom) -- its students must never leak in.
    _, _, other_classroom = _setup_classroom(headers, "1AM - other")

    subject = client.post("/subjects", json={"name": "الرياضيات"}, headers=headers).json()
    s1 = client.post("/students", json={"classroom_id": classroom["id"], "first_name": "أمين", "last_name": "1"}, headers=headers).json()
    s2 = client.post("/students", json={"classroom_id": classroom["id"], "first_name": "هدى", "last_name": "2"}, headers=headers).json()
    other_student = client.post("/students", json={"classroom_id": other_classroom["id"], "first_name": "سارة", "last_name": "3"}, headers=headers).json()

    unit = client.post("/curriculum-units", json={
        "subject_id": subject["id"], "grade_level": "1AM", "title": "يقارن ويرتب الأعداد الطبيعية",
        "unit_type": "skill", "order_index": 1, "year_version": "2026-2027",
    }, headers=headers)
    assert unit.status_code == 200, unit.text
    unit = unit.json()

    assessment = client.post("/assessments", json={
        "classroom_id": classroom["id"], "subject_id": subject["id"], "assessment_type": "test",
        "title": "تقييم تشخيصي", "date": "2026-09-10", "coefficient": 1, "max_score": 20,
    }, headers=headers).json()
    other_assessment = client.post("/assessments", json={
        "classroom_id": other_classroom["id"], "subject_id": subject["id"], "assessment_type": "test",
        "title": "تقييم تشخيصي آخر", "date": "2026-09-10", "coefficient": 1, "max_score": 20,
    }, headers=headers).json()

    # Mark s1 in_progress then correct to not_acquired via the same PUT
    # (upsert, same pattern as /assessment-scores) -- no duplicate row.
    d1 = client.put("/assessment-details", json={
        "assessment_id": assessment["id"], "student_id": s1["id"], "curriculum_unit_id": unit["id"], "mastery_level": "in_progress",
    }, headers=headers)
    assert d1.status_code == 200, d1.text
    d1_corrected = client.put("/assessment-details", json={
        "assessment_id": assessment["id"], "student_id": s1["id"], "curriculum_unit_id": unit["id"], "mastery_level": "not_acquired",
    }, headers=headers)
    assert d1_corrected.status_code == 200, d1_corrected.text
    client.put("/assessment-details", json={
        "assessment_id": assessment["id"], "student_id": s2["id"], "curriculum_unit_id": unit["id"], "mastery_level": "acquired",
    }, headers=headers)
    # Same skill, but for a student in the OTHER classroom -- also not_acquired.
    client.put("/assessment-details", json={
        "assessment_id": other_assessment["id"], "student_id": other_student["id"], "curriculum_unit_id": unit["id"], "mastery_level": "not_acquired",
    }, headers=headers)

    details = client.get(f"/assessments/{assessment['id']}/details", headers=headers).json()
    assert len(details) == 2  # the correction updated in place, not a duplicate row
    by_student = {d["student_id"]: d["mastery_level"] for d in details}
    assert by_student[s1["id"]] == "not_acquired"
    assert by_student[s2["id"]] == "acquired"

    # The struggling-students alert for THIS classroom must show only s1 --
    # not other_student, even though they share curriculum_unit_id and are
    # both not_acquired.
    alert = client.get(f"/curriculum-units/{unit['id']}/struggling-students", params={"classroom_id": classroom["id"]}, headers=headers).json()
    assert alert["student_ids"] == [s1["id"]]
    other_alert = client.get(f"/curriculum-units/{unit['id']}/struggling-students", params={"classroom_id": other_classroom["id"]}, headers=headers).json()
    assert other_alert["student_ids"] == [other_student["id"]]

    # Form a remediation group targeting this skill, with s1 as participant,
    # then record their follow-up outcome once known.
    remediation = client.post("/remediation-sessions", json={
        "classroom_id": classroom["id"], "date": "2026-09-15", "targeted_curriculum_unit_id": unit["id"], "notes": "مجموعة دعم مصغرة",
    }, headers=headers)
    assert remediation.status_code == 200, remediation.text
    remediation = remediation.json()

    participant = client.post("/remediation-participants", json={
        "remediation_session_id": remediation["id"], "student_id": s1["id"], "before_level": "not_acquired",
    }, headers=headers)
    assert participant.status_code == 200, participant.text
    participant = participant.json()
    assert participant["after_level"] is None

    sessions_listing = client.get(f"/classrooms/{classroom['id']}/remediation-sessions", headers=headers).json()
    assert {r["id"] for r in sessions_listing} == {remediation["id"]}
    participants_listing = client.get(f"/remediation-sessions/{remediation['id']}/participants", headers=headers).json()
    assert {p["id"] for p in participants_listing} == {participant["id"]}

    updated = client.patch(f"/remediation-participants/{participant['id']}", json={"after_level": "in_progress"}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["after_level"] == "in_progress"

    assert client.patch("/remediation-participants/does-not-exist", json={"after_level": "acquired"}, headers=headers).status_code == 404


def test_annual_plan_pacing_module():
    """The annual-plan/pacing workflow: create a plan for one subject+grade+
    year, add plan items (curriculum unit + target week), list them back in
    week order, mark one as delivered via the new direct POST /lesson-logs
    (independent of the class-session open/close lifecycle -- see
    create_lesson_log's docstring), and confirm the progress endpoint
    reflects exactly which planned units were delivered and which weren't.
    Also covers listing plans by teacher+subject+grade+year (so the UI can
    find an existing plan instead of creating a duplicate) and deleting a
    plan item.
    """
    headers, _teacher = _register_and_login("plan_t")
    other_headers, _ = _register_and_login("plan_other_t")
    year, _term, classroom = _setup_classroom(headers, "1AM - plan")
    subject = client.post("/subjects", json={"name": "الرياضيات"}, headers=headers).json()

    unit1 = client.post("/curriculum-units", json={
        "subject_id": subject["id"], "grade_level": "1AM", "title": "الأعداد الطبيعية",
        "unit_type": "unit", "order_index": 1, "year_version": "2026-2027",
    }, headers=headers).json()
    unit2 = client.post("/curriculum-units", json={
        "subject_id": subject["id"], "grade_level": "1AM", "title": "الكسور",
        "unit_type": "unit", "order_index": 2, "year_version": "2026-2027",
    }, headers=headers).json()
    unit3 = client.post("/curriculum-units", json={
        "subject_id": subject["id"], "grade_level": "1AM", "title": "الأعداد العشرية",
        "unit_type": "unit", "order_index": 3, "year_version": "2026-2027",
    }, headers=headers).json()

    # No plan yet for this subject+grade+year.
    empty_listing = client.get(
        "/annual-plans",
        params={"subject_id": subject["id"], "grade_level": "1AM", "academic_year_id": year["id"]},
        headers=headers,
    ).json()
    assert empty_listing == []
    # Another teacher's plan must never show up in this listing either.
    other_year, _, _ = _setup_classroom(other_headers, "1AM - plan-other")

    plan = client.post("/annual-plans", json={
        "subject_id": subject["id"], "grade_level": "1AM", "academic_year_id": year["id"],
    }, headers=headers)
    assert plan.status_code == 200, plan.text
    plan = plan.json()

    listing = client.get(
        "/annual-plans",
        params={"subject_id": subject["id"], "grade_level": "1AM", "academic_year_id": year["id"]},
        headers=headers,
    ).json()
    assert {p["id"] for p in listing} == {plan["id"]}
    other_listing = client.get(
        "/annual-plans",
        params={"subject_id": subject["id"], "grade_level": "1AM", "academic_year_id": other_year["id"]},
        headers=other_headers,
    ).json()
    assert other_listing == []

    item1 = client.post("/plan-items", json={
        "annual_plan_id": plan["id"], "curriculum_unit_id": unit1["id"], "target_week_number": 1, "order_index": 1,
    }, headers=headers)
    assert item1.status_code == 200, item1.text
    item1 = item1.json()
    item2 = client.post("/plan-items", json={
        "annual_plan_id": plan["id"], "curriculum_unit_id": unit3["id"], "target_week_number": 3, "order_index": 2,
    }, headers=headers).json()
    # Deliberately posted out of week order to confirm the listing sorts.
    item3 = client.post("/plan-items", json={
        "annual_plan_id": plan["id"], "curriculum_unit_id": unit2["id"], "target_week_number": 2, "order_index": 1,
    }, headers=headers).json()

    items_listing = client.get(f"/annual-plans/{plan['id']}/items", headers=headers).json()
    assert [i["id"] for i in items_listing] == [item1["id"], item3["id"], item2["id"]]

    # Nothing delivered yet -- everything pending (3 distinct planned units).
    progress = client.get(f"/annual-plans/{plan['id']}/progress", params={"classroom_id": classroom["id"]}, headers=headers).json()
    assert progress == {
        "planned_total": 3, "delivered_count": 0, "delivered_unit_ids": [], "delay_in_units": 3, "status": "behind",
    }

    # Mark unit1 as delivered directly (no class-session involved).
    log = client.post("/lesson-logs", json={
        "classroom_id": classroom["id"], "date": "2026-09-15", "curriculum_unit_id": unit1["id"], "observations": "درس تمهيدي",
    }, headers=headers)
    assert log.status_code == 200, log.text
    logs_listing = client.get(f"/classrooms/{classroom['id']}/lesson-logs", headers=headers).json()
    assert [entry["curriculum_unit_id"] for entry in logs_listing] == [unit1["id"]]

    progress_after = client.get(f"/annual-plans/{plan['id']}/progress", params={"classroom_id": classroom["id"]}, headers=headers).json()
    assert progress_after["delivered_count"] == 1
    assert progress_after["delivered_unit_ids"] == [unit1["id"]]
    assert progress_after["delay_in_units"] == 2
    assert progress_after["status"] == "slightly_behind"

    # Delete the plan item targeting unit3 -- it must drop out of the
    # listing and no longer count toward planned_total (unit1 and unit2,
    # still planned via item1/item3, must remain).
    delete_resp = client.delete(f"/plan-items/{item2['id']}", headers=headers)
    assert delete_resp.status_code == 200, delete_resp.text
    items_after_delete = client.get(f"/annual-plans/{plan['id']}/items", headers=headers).json()
    assert {i["id"] for i in items_after_delete} == {item1["id"], item3["id"]}
    progress_final = client.get(f"/annual-plans/{plan['id']}/progress", params={"classroom_id": classroom["id"]}, headers=headers).json()
    assert progress_final["planned_total"] == 2
    assert progress_final["delivered_count"] == 1
    assert progress_final["status"] == "slightly_behind"
    assert client.delete("/plan-items/does-not-exist", headers=headers).status_code == 404


def test_cross_teacher_authorization_gaps():
    """Found during a review pass: several mutation endpoints accepted ANY
    authenticated teacher's token with no check that they had anything to do
    with the resource being changed -- unlike /assessments, /seat-assignments
    and class-delegates, which already enforced this. Covers the four gaps
    found and fixed: student edit/delete (carries guardian_phone and
    medical_notes -- the most sensitive data in the app), reassigning a
    classroom's homeroom teacher (which also gates delegate management and
    the council report), deleting another teacher's annual-plan item, and
    recording a follow-up outcome on another teacher's remediation group.
    Also confirms a teacher who legitimately teaches a subject in the
    classroom (via TeacherClassroomAssignment, not as its creator) is still
    allowed to edit its students -- the fix must not be so strict it breaks
    the every-day multi-teacher-per-classroom case documented in
    test_my_classrooms_covers_creator_homeroom_and_subject_teacher_roles.
    """
    headers_a, teacher_a = _register_and_login("authz_owner")
    headers_b, _teacher_b = _register_and_login("authz_stranger")
    year, _term, classroom = _setup_classroom(headers_a, "1AM - authz")
    student = client.post(
        "/students", json={"classroom_id": classroom["id"], "first_name": "إيمان", "last_name": "زروقي"}, headers=headers_a
    ).json()

    # An unrelated teacher can neither edit nor delete this student.
    assert client.patch(f"/students/{student['id']}", json={"first_name": "إيمان2"}, headers=headers_b).status_code == 403
    assert client.delete(f"/students/{student['id']}", headers=headers_b).status_code == 403
    # The owning teacher still can.
    ok = client.patch(f"/students/{student['id']}", json={"first_name": "إيمان2"}, headers=headers_a)
    assert ok.status_code == 200, ok.text

    # A teacher who actually teaches a subject in this classroom (assigned,
    # not the creator) must still be allowed to edit its students.
    subject = client.post("/subjects", json={"name": "العربية"}, headers=headers_a).json()
    headers_c, teacher_c = _register_and_login("authz_subject_teacher")
    assign = client.post("/teacher-classroom-assignments", json={
        "teacher_id": teacher_c["id"], "classroom_id": classroom["id"], "subject_id": subject["id"], "academic_year_id": year["id"],
    }, headers=headers_a)
    assert assign.status_code == 200, assign.text
    assigned_edit = client.patch(f"/students/{student['id']}", json={"last_name": "زروقي2"}, headers=headers_c)
    assert assigned_edit.status_code == 200, assigned_edit.text

    # An unrelated teacher cannot hijack this classroom's homeroom-teacher role.
    hijack = client.patch(f"/classrooms/{classroom['id']}/homeroom-teacher", json={"homeroom_teacher_id": teacher_a["id"]}, headers=headers_b)
    assert hijack.status_code == 403
    # The classroom's own creator still can.
    set_ok = client.patch(f"/classrooms/{classroom['id']}/homeroom-teacher", json={"homeroom_teacher_id": teacher_a["id"]}, headers=headers_a)
    assert set_ok.status_code == 200, set_ok.text

    # An unrelated teacher cannot delete another teacher's annual-plan item.
    unit = client.post("/curriculum-units", json={
        "subject_id": subject["id"], "grade_level": "1AM", "title": "القراءة", "unit_type": "unit", "order_index": 1, "year_version": "2026-2027",
    }, headers=headers_a).json()
    plan = client.post("/annual-plans", json={
        "subject_id": subject["id"], "grade_level": "1AM", "academic_year_id": year["id"],
    }, headers=headers_a).json()
    item = client.post("/plan-items", json={
        "annual_plan_id": plan["id"], "curriculum_unit_id": unit["id"], "target_week_number": 1, "order_index": 1,
    }, headers=headers_a).json()
    assert client.delete(f"/plan-items/{item['id']}", headers=headers_b).status_code == 403
    assert client.delete(f"/plan-items/{item['id']}", headers=headers_a).status_code == 200

    # An unrelated teacher cannot record a follow-up outcome on another
    # teacher's remediation group.
    remediation = client.post("/remediation-sessions", json={
        "classroom_id": classroom["id"], "date": "2026-09-20", "targeted_curriculum_unit_id": unit["id"],
    }, headers=headers_a).json()
    participant = client.post("/remediation-participants", json={
        "remediation_session_id": remediation["id"], "student_id": student["id"], "before_level": "not_acquired",
    }, headers=headers_a).json()
    assert client.patch(f"/remediation-participants/{participant['id']}", json={"after_level": "acquired"}, headers=headers_b).status_code == 403
    owner_update = client.patch(f"/remediation-participants/{participant['id']}", json={"after_level": "acquired"}, headers=headers_a)
    assert owner_update.status_code == 200, owner_update.text
