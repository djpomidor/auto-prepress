"""
Менеджер соединения с БД.
SQLite (локально, общий файл с Printery) или PostgreSQL (VPS).
"""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from db.models import Base
import config


def _make_engine():
    cfg = config.CFG
    if cfg["db_type"] == "postgresql":
        # Удалённая PostgreSQL — общая с Printery
        url = cfg["pg_dsn"]
        return create_engine(url, echo=False, pool_pre_ping=True)
    else:
        # SQLite — указываем путь к БД Printery если задан,
        # иначе создаём рядом с main.py
        db_path = cfg.get("sqlite_path") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "impo_reader.db"
        )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        url = "sqlite:///" + db_path.replace("\\", "/")
        return create_engine(url, echo=False,
                             connect_args={"check_same_thread": False})


_engine = None
_SessionLocal = None


def init_db():
    global _engine, _SessionLocal
    _engine = _make_engine()

    # Создаём только недостающие таблицы — не трогаем существующие
    Base.metadata.create_all(_engine, checkfirst=True)

    # Добавляем колонки ImpoReader если их нет (для существующей БД Printery)
    _migrate_extra_columns()

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def _migrate_extra_columns():
    """Добавляет колонки folder_path и monitoring если их нет."""
    extra = [
        ("printery_order", "folder_path", "VARCHAR(256)"),
        ("printery_order", "monitoring",  "BOOLEAN DEFAULT 0"),
    ]
    with _engine.connect() as conn:
        for table, col, col_type in extra:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass  # колонка уже есть


def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()


def next_order_number() -> int:
    """Возвращает следующий номер заказа (как в Printery: max + 1)."""
    from db.models import Order
    from sqlalchemy import func
    session = get_session()
    try:
        max_num = session.query(func.max(Order.number)).scalar()
        return (max_num or 0) + 1
    finally:
        session.close()
