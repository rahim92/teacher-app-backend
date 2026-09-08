# Backend — Middle School Teacher App API

FastAPI + SQLModel backend implementing the schema in `../docs/data_model.md`.
Runs on SQLite with zero setup for development; point `DATABASE_URL` at
PostgreSQL for production.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
python seed.py        # optional: seeds a subject + curriculum tree so the app isn't empty
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs for interactive API docs (Swagger UI).

## Test

```bash
pytest tests/ -v
```

`tests/test_smoke.py` exercises the full offline-first loop: register → login
→ create classroom/student → open a class session → log a quick-tap event →
close the session (writes a LessonLog) → push a batch through `/sync/push`.

`tests/test_council.py` covers the multi-teacher pieces: a teacher can be
homeroom teacher ("الأستاذ الرئيسي") of at most one classroom per academic
year (DB-level unique constraint), the council report at `/council/...` is
refused (403) to any teacher who isn't that classroom's homeroom teacher or
an admin, and the report correctly averages grades logged by *different*
teachers across subjects with different coefficients and max scores.

## Migrations (production)

`init_db()` auto-creates tables on startup, which is fine for development.
For production, use Alembic instead:

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

## Project layout

```
app/
  models/       SQLModel table models (one file per domain area)
  schemas/      Pydantic request/response shapes (kept separate from table models)
  routers/      One router per feature area; sync.py is the offline-sync engine
  auth.py       JWT + password hashing
  database.py   Engine/session setup
  main.py       App wiring
```

## Notes on scope

- The app's screens still target a single teacher per classroom (MVP), but
  the schema and API already support multiple teachers per classroom
  (`TeacherClassroomAssignment`) and a permission-gated cross-teacher report
  (`/council/classrooms/{id}/report`) restricted to the classroom's homeroom
  teacher or an `admin` account -- see docs/data_model.md §8. A teacher may
  teach any number of classrooms but be homeroom teacher of at most one per
  academic year (enforced by a DB unique constraint on
  `Classroom(homeroom_teacher_id, academic_year_id)`).
- `/export/students/{id}/card.pdf` needs WeasyPrint's native dependencies
  (cairo/pango) to actually render; the rest of the API works without them.
  Local, on-device PDF generation in the Flutter app is the primary path for
  single-document exports; this endpoint is for bulk/server-side generation.
