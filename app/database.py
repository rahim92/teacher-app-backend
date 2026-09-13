from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlmodel import SQLModel, Session, create_engine

from app.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)

# Columns added to an already-existing table after it first shipped.
# SQLModel.metadata.create_all() only creates missing TABLES, never adds
# missing COLUMNS to a table that already exists -- so a brand-new nullable
# column with a server-side default is patched in here, idempotently, on
# every boot. This is a deliberate stand-in for a real Alembic migration
# (see backend/alembic/): fine for small, additive, defaulted columns like
# this one, not a substitute once a change needs data backfill or isn't
# purely additive.
_ADDITIVE_COLUMNS = [
    ("seat_assignments", "seat_slot", "INTEGER NOT NULL DEFAULT 0"),
    # VARCHAR(9), not the native `notebookquality` PostgreSQL enum type
    # create_all() gave the sibling `quality` column, so this one ALTER
    # TABLE statement works unchanged on SQLite and PostgreSQL alike --
    # SQLAlchemy only ever sends/reads the enum's plain string value either
    # way, so a same-length VARCHAR holds it exactly as well.
    ("notebook_checks", "writing_quality", "VARCHAR(9)"),
    # `lesson` is the correct backfill for every pre-existing row -- they
    # were all real taught lessons (the only kind LessonLog could represent
    # before lesson_type existed).
    ("lesson_logs", "lesson_type", "VARCHAR(20) NOT NULL DEFAULT 'lesson'"),
    ("lesson_logs", "resource", "TEXT"),
    # Free-text, teacher-typed -- see models/session.py's docstring for why
    # these aren't derived from CurriculumUnit.
    ("lesson_logs", "domain", "TEXT"),
    ("lesson_logs", "segment", "TEXT"),
]

# Columns that used to be NOT NULL but had that constraint deliberately
# relaxed later (as opposed to _ADDITIVE_COLUMNS, which only ever adds a
# brand-new column). PostgreSQL supports dropping a NOT NULL constraint in
# place; SQLite's ALTER TABLE can't do this at all, so this only runs on
# PostgreSQL -- a stale local SQLite file predating the change is rare and
# disposable in dev (tests already start from a fresh DB file every run).
_NULLABLE_COLUMNS = [
    # curriculum_unit_id: a holiday/general-support LessonLog entry has no
    # single competency to point at (see models/session.py's docstring).
    ("lesson_logs", "curriculum_unit_id"),
]


def _patch_nullable_columns() -> None:
    if engine.dialect.name != "postgresql":
        return
    for table, column in _NULLABLE_COLUMNS:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL"))
                trans.commit()
            except (OperationalError, ProgrammingError):
                trans.rollback()


def _patch_additive_columns() -> None:
    # One connection/transaction per column, not one shared across the
    # whole loop: on PostgreSQL, a failed statement (duplicate-column error,
    # the expected/common case here) poisons the rest of that transaction --
    # so isolating each ALTER TABLE keeps one already-applied column from
    # breaking the next one, and lets us explicitly roll back the failed
    # attempt instead of leaving it for the implicit commit to trip over.
    for table, column, ddl in _ADDITIVE_COLUMNS:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                trans.commit()
            except (OperationalError, ProgrammingError):
                # Column already exists (duplicate-column error, phrased
                # differently by SQLite vs PostgreSQL) -- nothing to do.
                trans.rollback()


def init_db() -> None:
    """Create tables if they don't exist yet, then patch in any additive
    columns a table gained after it first shipped (see _ADDITIVE_COLUMNS).

    For real deployments, prefer Alembic migrations (see backend/alembic/) over
    this — it's kept here for zero-friction local development.
    """
    SQLModel.metadata.create_all(engine)
    _patch_additive_columns()
    _patch_nullable_columns()


def get_session():
    with Session(engine) as session:
        yield session
