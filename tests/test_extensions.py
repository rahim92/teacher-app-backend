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
