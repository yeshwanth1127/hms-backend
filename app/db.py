from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


engine_options = {"pool_pre_ping": True}
if settings.database_url == "sqlite:///:memory:":
    engine_options.update(connect_args={"check_same_thread": False}, poolclass=StaticPool)
elif settings.database_url.startswith("sqlite"):
    engine_options.update(connect_args={"check_same_thread": False})
elif settings.database_url.startswith("postgresql"):
    # One worker shares a small thread pool: a stuck doctor-row lock must fail fast, not queue every booking.
    engine_options.update(pool_timeout=10, connect_args={"options": "-c lock_timeout=5s -c statement_timeout=15s"})

engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

