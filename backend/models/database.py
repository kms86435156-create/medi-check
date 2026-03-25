"""DB 연결 및 ORM 모델"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Double,
    SmallInteger, Date, DateTime, JSON, ForeignKey,
    UniqueConstraint, create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "medicheck")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(100), nullable=False, default="")
    phone = Column(String(20))
    role = Column(String(20), nullable=False, default="patient")
    profile_image_url = Column(String(500))
    created_at = Column(DateTime)

    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")


class Hospital(Base):
    __tablename__ = "hospitals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20))
    address = Column(String(200))
    hours = Column(String(300))
    place_url = Column(String(500))
    lat = Column(Double)
    lng = Column(Double)
    ai_summary = Column(JSON)
    premium_rank = Column(Integer, default=0)
    created_at = Column(DateTime)

    reviews = relationship("Review", back_populates="hospital", lazy="dynamic")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    review_text = Column(Text)
    rating = Column(SmallInteger)
    review_date = Column(Date)

    hospital = relationship("Hospital", back_populates="reviews")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "hospital_id", name="uq_user_hospital"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    hospital_id = Column(Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime)

    user = relationship("User", back_populates="favorites")
    hospital = relationship("Hospital")
