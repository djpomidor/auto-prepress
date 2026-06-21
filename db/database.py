import os
"""
Менеджер соединения с БД.
Переключение SQLite ↔ PostgreSQL через config.py
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from db.models import Base
import config


def _make_engine():
    cfg = config.CFG
    if cfg["db_type"] == "postgresql":
        url = cfg["pg_dsn"]
    else:
        # Всегда рядом с main.py
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base_dir, "impo_reader.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        url = "sqlite:///" + db_path.replace("\\", "/")
    return create_engine(url, echo=False)


_engine = None
_SessionLocal = None


def init_db():
    global _engine, _SessionLocal
    _engine = _make_engine()
    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()