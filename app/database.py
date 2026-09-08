from sqlmodel import SQLModel, Session, create_engine

from app.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def init_db() -> None:
    """Create tables if they don't exist yet.

    For real deployments, prefer Alembic migrations (see backend/alembic/) over
    this — it's kept here for zero-friction local development.
    """
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
