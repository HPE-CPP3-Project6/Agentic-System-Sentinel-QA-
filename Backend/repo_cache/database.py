"""
database.py
-----------
Configures the SQLAlchemy engine, session factory, and declarative base.
SQLite is used for local persistence; the database file is created at
"./smart_task_manager.db" relative to the project root.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# ---------------------------------------------------------------------------
# Database URL
# ---------------------------------------------------------------------------
# SQLite stores everything in a single file. For production, swap this with a
# PostgreSQL/MySQL connection string and set pool settings appropriately.
DATABASE_URL = "sqlite:///./smart_task_manager.db"

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# "check_same_thread=False" is required for SQLite when used with FastAPI's
# async request lifecycle (multiple threads may share the same connection).
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,          # Set to True during development to log all SQL
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(
    autocommit=False,   # Transactions must be committed explicitly
    autoflush=False,    # Prevents implicit flushes between operations
    bind=engine,
)

# ---------------------------------------------------------------------------
# Declarative base – all ORM models inherit from this
# ---------------------------------------------------------------------------
Base = declarative_base()


# ---------------------------------------------------------------------------
# Dependency: yields a database session and ensures it is closed after use
# ---------------------------------------------------------------------------
def get_db():
    """
    FastAPI dependency that provides a database session per request.
    The session is always closed in the `finally` block, even if an
    exception is raised, preventing connection leaks.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
