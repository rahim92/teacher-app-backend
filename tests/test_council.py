"""Covers the multi-teacher pieces added on top of the single-teacher MVP:
- a teacher can be homeroom teacher ("الأستاذ الرئيسي") of at most one
  classroom per academic year
- the council report is only visible to that classroom's homeroom teacher
  (or an admin), and correctly combines grades logged by OTHER teachers
"""
import os
import uuid
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:///./test_council.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _register_and_login(name: str) -> dict:
    email = f"{name}_{uuid.uuid4().hex[:8]}@example.com"
    password = "S3cret!pass"
    register_resp = client.post("/auth/register", json={"full_name": name, "email": email, "password": password})
    assert register_resp.status_code == 201, register_resp.text
    user = register_resp.json()

    login_resp = client.post("/auth/login", data={"username": email, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, user


def _setup_year_and_term(headers):
    year = client.post(
        "/academic-years",
        json={"label": "2025-2026", "start_date": "2025-09-01", "end_date": "2026-06-30"},
        headers=headers,
    ).json()
    term = client.post(
        "/terms",
        json={
            "academic_year_id": year["id"],
            "label": "الفصل الأول",
            "start_date": "2025-09-01",
            "end_date": "2025-12-31",
            "order_index": 1,
        },
        headers=headers,
    ).json()
    return year, term


def test_homeroom_teacher_capped_at_one_classroom_per_year():
    headers_a, _ = _register_and_login("teacher_a")
    year, _term = _setup_year_and_term(headers_a)

    classroom1 = client.post(
        "/classrooms",
        json={"academic_year_id": year["id"], "name": "1AM - 1", "grade_level": "1AM"},
        headers=headers_a,
    ).json()
    classroom2 = client.post(
        "/classrooms",
        json={"academic_year_id": year["id"], "name": "1AM - 2", "grade_level": "1AM"},
        headers=headers_a,
    ).json()

    # Need the teacher's own id -- /auth/me returns it.
    me = client.get("/auth/me", headers=headers_a).json()

    first = client.patch(
        f"/classrooms/{classroom1['id']}/homeroom-teacher",
        json={"homeroom_teacher_id": me["id"]},
        headers=headers_a,
    )
    assert first.status_code == 200, first.text
    assert first.json()["homeroom_teacher_id"] == me["id"]

    second = client.patch(
        f"/classrooms/{classroom2['id']}/homeroom-teacher",
        json={"homeroom_teacher_id": me["id"]},
        headers=headers_a,
    )
    assert second.status_code == 400, second.text
    assert "قسم" in second.json()["detail"]


def test_council_report_requires_homeroom_teacher_or_admin():
    headers_math, teacher_math = _register_and_login("teacher_math")
    headers_arabic, _teacher_arabic = _register_and_login("teacher_arabic")
    year, term = _setup_year_and_term(headers_math)

    classroom = client.post(
        "/classrooms",
        json={"academic_year_id": year["id"], "name": "2AM - 1", "grade_level": "2AM"},
        headers=headers_math,
    ).json()

    # A regular subject teacher (not homeroom, not admin) must be refused.
    denied = client.get(
        f"/council/classrooms/{classroom['id']}/report",
        params={"term_id": term["id"]},
        headers=headers_arabic,
    )
    assert denied.status_code == 403

    # Make teacher_math the homeroom teacher -- now they can view it.
    client.patch(
        f"/classrooms/{classroom['id']}/homeroom-teacher",
        json={"homeroom_teacher_id": teacher_math["id"]},
        headers=headers_math,
    )
    allowed = client.get(
        f"/council/classrooms/{classroom['id']}/report",
        params={"term_id": term["id"]},
        headers=headers_math,
    )
    assert allowed.status_code == 200, allowed.text


def test_council_report_combines_grades_across_subjects():
    headers_math, teacher_math = _register_and_login("teacher_math2")
    headers_arabic, teacher_arabic = _register_and_login("teacher_arabic2")
    year, term = _setup_year_and_term(headers_math)

    classroom = client.post(
        "/classrooms",
        json={"academic_year_id": year["id"], "name": "3AM - 1", "grade_level": "3AM"},
        headers=headers_math,
    ).json()
    client.patch(
        f"/classrooms/{classroom['id']}/homeroom-teacher",
        json={"homeroom_teacher_id": teacher_math["id"]},
        headers=headers_math,
    )

    math_subject = client.post(
        "/subjects", json={"name": "الرياضيات", "coefficient": 4}, headers=headers_math
    ).json()
    arabic_subject = client.post(
        "/subjects", json={"name": "اللغة العربية", "coefficient": 5}, headers=headers_arabic
    ).json()

    student = client.post(
        "/students",
        json={"classroom_id": classroom["id"], "first_name": "سارة", "last_name": "بلقاسم"},
        headers=headers_math,
    ).json()

    # Both teachers are assigned to teach this classroom.
    client.post(
        "/teacher-classroom-assignments",
        json={
            "teacher_id": teacher_math["id"],
            "classroom_id": classroom["id"],
            "subject_id": math_subject["id"],
            "academic_year_id": year["id"],
        },
        headers=headers_math,
    )
    client.post(
        "/teacher-classroom-assignments",
        json={
            "teacher_id": teacher_arabic["id"],
            "classroom_id": classroom["id"],
            "subject_id": arabic_subject["id"],
            "academic_year_id": year["id"],
        },
        headers=headers_arabic,
    )

    math_assessment = client.post(
        "/assessments",
        json={
            "classroom_id": classroom["id"],
            "subject_id": math_subject["id"],
            "assessment_type": "test",
            "title": "فرض 1",
            "date": "2025-10-01",
            "coefficient": 1,
            "max_score": 20,
        },
        headers=headers_math,
    ).json()
    client.post(
        "/assessment-scores",
        json={"assessment_id": math_assessment["id"], "student_id": student["id"], "score": 16},
        headers=headers_math,
    )

    arabic_assessment = client.post(
        "/assessments",
        json={
            "classroom_id": classroom["id"],
            "subject_id": arabic_subject["id"],
            "assessment_type": "test",
            "title": "فرض 1",
            "date": "2025-10-05",
            "coefficient": 1,
            "max_score": 10,  # different max_score -- must be normalized to /20
        },
        headers=headers_arabic,
    ).json()
    client.post(
        "/assessment-scores",
        json={"assessment_id": arabic_assessment["id"], "student_id": student["id"], "score": 8},  # -> 16/20
        headers=headers_arabic,
    )

    report = client.get(
        f"/council/classrooms/{classroom['id']}/report",
        params={"term_id": term["id"]},
        headers=headers_math,
    ).json()

    row = report["rows"][0]
    assert row["student_id"] == student["id"]
    subject_avgs = {sa["subject_name"]: sa["average"] for sa in row["subject_averages"]}
    assert subject_avgs["الرياضيات"] == 16.0
    assert subject_avgs["اللغة العربية"] == 16.0
    # overall = (16*4 + 16*5) / (4+5) = 16.0
    assert row["overall_average"] == 16.0
    assert row["rank"] == 1
