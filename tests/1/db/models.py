"""
SQLAlchemy модели. Совместимы с SQLite и PostgreSQL.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, Session

Base = declarative_base()


class Order(Base):
    __tablename__ = "printery_order"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    number       = Column(Integer, nullable=False, unique=True)
    name         = Column(String(32), nullable=False)
    type         = Column(String(3), nullable=False, default="")
    circulation  = Column(Integer, nullable=True)
    binding      = Column(String(4), nullable=False, default="")
    width        = Column(Integer, nullable=True)
    height       = Column(Integer, nullable=True)
    created      = Column(DateTime, nullable=False, default=datetime.now)
    delivery_date    = Column(DateTime, nullable=True)
    submiting_files  = Column(DateTime, nullable=True)
    due_date         = Column(DateTime, nullable=True)

    # Дополнительные поля (не в исходной схеме, но нужны UI)
    folder_path      = Column(String(256), nullable=True)
    monitoring       = Column(Boolean, default=False)
    status_text      = Column(String(64), nullable=True)

    parts   = relationship("Part", back_populates="order", cascade="all, delete-orphan")
    owners  = relationship("OrderOwner", back_populates="order", cascade="all, delete-orphan")

    @property
    def folder_name(self) -> str:
        """0641_ShortName"""
        return f"{self.number:04d}_{self.name}"

    def __repr__(self):
        return f"<Order #{self.number} {self.name}>"


class User(Base):
    __tablename__ = "printery_user"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), nullable=False, unique=True)
    owners   = relationship("OrderOwner", back_populates="user")


class OrderOwner(Base):
    __tablename__ = "printery_order_owner"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("printery_order.id"), nullable=False)
    user_id  = Column(Integer, ForeignKey("printery_user.id"), nullable=False)
    order    = relationship("Order", back_populates="owners")
    user     = relationship("User", back_populates="owners")


class Paper(Base):
    __tablename__ = "printery_paper"
    id      = Column(Integer, primary_key=True, autoincrement=True)
    name    = Column(String(64), nullable=False)
    type    = Column(String(3), nullable=False, default="")
    width   = Column(Integer, nullable=True)
    height  = Column(Integer, nullable=True)
    density = Column(Integer, nullable=True)
    parts   = relationship("Part", back_populates="paper")


class Part(Base):
    __tablename__ = "printery_part"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    part_name = Column(String(3), nullable=False)
    pages     = Column(Integer, nullable=True)
    color     = Column(String(3), nullable=False, default="")
    laminate  = Column(String(3), nullable=False, default="")
    uflak     = Column(Boolean, nullable=False, default=False)
    order_id  = Column(Integer, ForeignKey("printery_order.id"), nullable=False)
    paper_id  = Column(Integer, ForeignKey("printery_paper.id"), nullable=True)
    order     = relationship("Order", back_populates="parts")
    paper     = relationship("Paper", back_populates="parts")
