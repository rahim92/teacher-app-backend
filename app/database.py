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
]


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


def get_session():
    with Session(engine) as session:
        yield session
