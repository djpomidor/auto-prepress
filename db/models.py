"""
SQLAlchemy модели — совместимы со схемой Django-приложения Printery.
Таблицы те же что в Printery, добавлены только поля нужные ImpoReader.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float,
    ForeignKey, Table, Text, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, Session

Base = declarative_base()

# ManyToMany: Order ↔ User (owner)
order_owner_table = Table(
    "printery_order_owner", Base.metadata,
    Column("id",       Integer, primary_key=True, autoincrement=True),
    Column("order_id", Integer, ForeignKey("printery_order.id")),
    Column("user_id",  Integer, ForeignKey("printery_user.id")),
)

# ManyToMany: Paper ↔ Company (manufacturer)
paper_manufacturer_table = Table(
    "printery_paper_manufacturer", Base.metadata,
    Column("id",         Integer, primary_key=True, autoincrement=True),
    Column("paper_id",   Integer, ForeignKey("printery_paper.id")),
    Column("company_id", Integer, ForeignKey("printery_company.id")),
)


class User(Base):
    __tablename__ = "printery_user"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    username     = Column(String(150), nullable=False, unique=True)
    password     = Column(String(128), nullable=False, default="")
    email        = Column(String(254), nullable=False, default="")
    first_name   = Column(String(150), default="")
    last_name    = Column(String(150), default="")
    is_active    = Column(Boolean, default=True)
    is_staff     = Column(Boolean, default=False)
    is_superuser = Column(Boolean, default=False)
    date_joined  = Column(DateTime, default=datetime.now)
    phone_number = Column(String(128), default="")
    is_customer  = Column(Boolean, default=True)
    is_employee  = Column(Boolean, default=False)
    company_id   = Column(Integer, ForeignKey("printery_company.id"), nullable=True)

    orders  = relationship("Order", secondary=order_owner_table, back_populates="owners")
    company = relationship("Company", back_populates="users")


class Company(Base):
    __tablename__ = "printery_company"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    name            = Column(String(64), unique=True, nullable=False)
    address         = Column(String(64), default="")
    city            = Column(String(25), default="")
    postal_code     = Column(Integer, nullable=True)
    country         = Column(String(56), default="")
    email           = Column(String(64), default="")
    phone           = Column(String(128), default="")
    is_manufacturer = Column(Boolean, default=False)
    is_customer     = Column(Boolean, default=False)

    users = relationship("User", back_populates="company")


class Paper(Base):
    __tablename__ = "printery_paper"
    id      = Column(Integer, primary_key=True, autoincrement=True)
    name    = Column(String(64), default="")
    type    = Column(String(3),  default="")
    density = Column(Integer, nullable=True)
    width   = Column(Integer, nullable=True)
    height  = Column(Integer, nullable=True)

    manufacturers = relationship("Company", secondary=paper_manufacturer_table)
    parts         = relationship("Part", back_populates="paper")


class Order(Base):
    __tablename__ = "printery_order"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    number          = Column(Integer, nullable=False, unique=True)
    name            = Column(String(32), default="")
    type            = Column(String(3),  default="")
    circulation     = Column(Integer, nullable=True)
    binding         = Column(String(4),  default="")
    width           = Column(Integer, nullable=True)
    height          = Column(Integer, nullable=True)
    created         = Column(DateTime, nullable=False, default=datetime.now)
    delivery_date   = Column(DateTime, nullable=True)
    submiting_files = Column(DateTime, nullable=True)
    due_date        = Column(DateTime, nullable=True)

    # Дополнительные поля ImpoReader (не в Printery — добавляем миграцией)
    folder_path = Column(String(256), nullable=True)
    monitoring  = Column(Boolean, default=False)

    # Поля из спецификации заказа (заполняются OCR или вручную)
    description    = Column(String(64),  nullable=True)  # "Описание заказа" (книга, брошюра...)
    pages_block    = Column(Integer,     nullable=True)   # Объём блок
    pages_cover    = Column(Integer,     nullable=True)   # Объём обл.
    pages_insert   = Column(Integer,     nullable=True)   # Объём вкл.
    color_block    = Column(String(16),  nullable=True)   # Красочность блока, напр. "4+4"
    color_cover    = Column(String(16),  nullable=True)   # Красочность обложки
    color_insert   = Column(String(16),  nullable=True)   # Красочность вклейки
    postprocessing = Column(Text,        nullable=True)   # (не используется в UI — оставлено для совместимости с БД)
    tech_notes     = Column(Text,        nullable=True)   # Технические пояснения
    paper_block    = Column(String(64),  nullable=True)   # Бумага блок, напр. "мат. 130"
    paper_cover    = Column(String(64),  nullable=True)   # Бумага обл.+подл.
    paper_insert   = Column(String(64),  nullable=True)   # Бумага вкл.
    lak            = Column(String(32),  nullable=True)   # Лак
    customer       = Column(String(80),  nullable=True)   # Заказчик (организация)
    spec_path      = Column(String(256), nullable=True)   # Путь к файлу спецификации (в корне папки заказа)

    owners = relationship("User", secondary=order_owner_table, back_populates="orders")
    parts  = relationship("Part", back_populates="order", cascade="all, delete-orphan")

    @property
    def folder_name(self) -> str:
        return f"{self.number:04d}_{self.name}"

    def __repr__(self):
        return f"<Order #{self.number} {self.name}>"


class Part(Base):
    __tablename__ = "printery_part"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    part_name = Column(String(3),  default="")
    pages     = Column(Integer, nullable=True)
    color     = Column(String(3),  default="")
    laminate  = Column(String(3),  default="")
    uflak     = Column(Boolean, default=False)
    order_id  = Column(Integer, ForeignKey("printery_order.id"), nullable=False)
    paper_id  = Column(Integer, ForeignKey("printery_paper.id"), nullable=True)

    order = relationship("Order", back_populates="parts")
    paper = relationship("Paper", back_populates="parts")


class PrintSchedule(Base):
    __tablename__ = "printery_printschedule"
    id                  = Column(Integer, primary_key=True, autoincrement=True)
    order_part_id       = Column(Integer, ForeignKey("printery_part.id"), nullable=False)
    sm1                 = Column(Boolean, default=False)
    sm2                 = Column(Boolean, default=False)
    rapida              = Column(Boolean, default=False)
    printed_sheets      = Column(Float, nullable=True)
    circulation_sheets  = Column(Integer, nullable=True)
    position            = Column(Integer, nullable=True)
    parent_day          = Column(String(20), default="")
    ctp_id              = Column(Integer, ForeignKey("printery_ctp.id"), nullable=True)

    order_part = relationship("Part")


class Ctp(Base):
    __tablename__ = "printery_ctp"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    plates           = Column(Integer, nullable=True)
    plates_bad       = Column(Integer, nullable=True)
    printing_id      = Column(Integer, ForeignKey("printery_printschedule.id"), nullable=True)
    plates_done_date = Column(DateTime, nullable=True)
    notes            = Column(Text, default="")
    status           = Column(String(15), nullable=True)
