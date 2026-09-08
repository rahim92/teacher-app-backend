"""End-to-end smoke test covering the core offline-first loop: register,
login, create a classroom + student, open a class session, log a quick-tap
event, close the session, and confirm the sync push endpoint accepts a batch.
"""
import os
import uuid
from datetime import datetime, timedelta

os.environ["DATABASE_URL"] = "sqlite:///./test.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _auth_headers() -> dict:
    email = f"teacher_{uuid.uuid4().hex[:8]}@example.com"
    password = "S3cret!pass"

    resp = client.post(
        "/auth/register", json={"full_name": "أستاذ تجريبي", "email": email, "password": password}
    )
    assert resp.status_code == 201, resp.text

    resp = client.post("/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_full_classroom_flow():
    headers = _auth_headers()

    year = client.post(
        "/academic-years",
        json={"label": "2025-2026", "start_date": "2025-09-01", "end_date": "2026-06-30"},
        headers=headers,
    ).json()

    subject = client.post("/subjects", json={"name": "الرياضيات", "code": "MATH"}, headers=headers).json()

    classroom = client.post(
        "/classrooms",
        json={"academic_year_id": year["id"], "name": "1AM - 1", "grade_level": "1AM"},
        headers=headers,
    ).json()
    assert classroom["grade_level"] == "1AM"

    student = client.post(
        "/students",
        json={"classroom_id": classroom["id"], "first_name": "ياسين", "last_name": "بن علي"},
        headers=headers,
    ).json()

    seat = client.put(
        "/seat-assignments",
        json={"classroom_id": classroom["id"], "student_id": student["id"], "seat_row": 1, "seat_col": 1},
        headers=headers,
    ).json()
    assert seat["seat_row"] == 1

    session_ = client.post(
        "/class-sessions",
        json={"classroom_id": classroom["id"], "subject_id": subject["id"], "date": "2025-09-15"},
        headers=headers,
    ).json()
    assert session_["status"] == "open"

    event = client.post(
        f"/class-sessions/{session_['id']}/events",
        json={
            "session_id": session_["id"],
            "student_id": student["id"],
            "event_type": "attendance_present",
        },
        headers=headers,
    ).json()
    assert event["event_type"] == "attendance_present"

    closed = client.post(
        f"/class-sessions/{session_['id']}/close",
        json={"end_time": "09:00"},
        headers=headers,
    ).json()
    assert closed["status"] == "closed"

    ledger = client.get(f"/students/{student['id']}/ledger", headers=headers).json()
    assert len(ledger) == 1


def test_sync_push_creates_record_with_client_id():
    headers = _auth_headers()

    year = client.post(
        "/academic-years",
        json={"label": "2026-2027", "start_date": "2026-09-01", "end_date": "2027-06-30"},
        headers=headers,
    ).json()
    subject = client.post("/subjects", json={"name": "العلوم"}, headers=headers).json()
    classroom = client.post(
        "/classrooms",
        json={"academic_year_id": year["id"], "name": "2AM - 3", "grade_level": "2AM"},
        headers=headers,
    ).json()

    local_id = str(uuid.uuid4())
    payload = {
        "device_id": "phone-1",
        "mutations": [
            {
                "entity": "students",
                "operation": "create",
                "local_id": local_id,
                "data": {
                    "classroom_id": classroom["id"],
                    "first_name": "أمينة",
                    "last_name": "قاسمي",
                },
                "client_updated_at": datetime.utcnow().isoformat(),
            }
        ],
    }
    resp = client.post("/sync/push", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    result = resp.json()["results"][0]
    assert result["local_id"] == local_id
    assert result["status"] == "applied"

    since = (datetime.utcnow() - timedelta(days=1)).isoformat()
    pull = client.get("/sync/pull", params={"since": since}, headers=headers)
    assert pull.status_code == 200, pull.text
