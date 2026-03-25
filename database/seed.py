"""
DAY 3 - CSV/JSON 데이터를 MySQL에 일괄 삽입
SQLAlchemy bulk_insert_mappings 사용

사용법:
  1) .env 파일에 DB 접속 정보 설정
  2) MySQL에서 schema.sql 실행
  3) python seed.py
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Double,
    SmallInteger, Date, DateTime, JSON, ForeignKey,
    create_engine, text, inspect,
)
from sqlalchemy.orm import declarative_base, Session, relationship

# ── 경로 ──
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ENV_FILE = BASE_DIR / ".env"

HOSPITALS_CSV = DATA_DIR / "hospitals_base.csv"
REVIEWS_JSON = DATA_DIR / "reviews_raw.json"

# ── 환경 변수 로드 ──
load_dotenv(ENV_FILE)

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "medicheck")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    f"?charset=utf8mb4"
)

# ── ORM 모델 ──
Base = declarative_base()


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
    created_at = Column(DateTime, default=datetime.utcnow)

    reviews = relationship("Review", back_populates="hospital", cascade="all, delete-orphan")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    hospital_id = Column(Integer, ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False)
    review_text = Column(Text)
    rating = Column(SmallInteger)
    review_date = Column(Date)

    hospital = relationship("Hospital", back_populates="reviews")


# ── 데이터 로드 ──

def load_hospitals() -> list[dict]:
    """hospitals_base.csv → dict 리스트"""
    rows = []
    with open(HOSPITALS_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": int(r["id"]),
                "name": r["name"].strip(),
                "phone": r.get("phone", "").strip() or None,
                "address": r.get("address", "").strip() or None,
                "hours": r.get("hours", "").strip() or None,
                "place_url": r.get("place_url", "").strip() or None,
                "lat": None,
                "lng": None,
                "ai_summary": None,
                "premium_rank": 0,
            })
    return rows


def load_reviews() -> list[dict]:
    """reviews_raw.json → dict 리스트"""
    with open(REVIEWS_JSON, encoding="utf-8") as f:
        raw = json.load(f)

    rows = []
    for r in raw:
        review_date = None
        date_str = r.get("date", "")
        if date_str:
            try:
                review_date = datetime.strptime(date_str.rstrip("."), "%Y.%m.%d").date()
            except ValueError:
                pass

        rating = r.get("rating")
        if isinstance(rating, float):
            rating = int(rating)
        if rating and (rating < 1 or rating > 5):
            rating = None

        rows.append({
            "hospital_id": r["hospital_id"],
            "review_text": r.get("review_text", ""),
            "rating": rating,
            "review_date": review_date,
        })
    return rows


# ── 메인 ──

def seed():
    print(f"DB 연결: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    engine = create_engine(DATABASE_URL, echo=False)

    # 테이블 존재 확인, 없으면 자동 생성
    inspector = inspect(engine)
    existing = inspector.get_table_names()
    if "hospitals" not in existing or "reviews" not in existing:
        print("테이블이 없습니다. 자동 생성합니다...")
        Base.metadata.create_all(engine)
        print("테이블 생성 완료")

    # 데이터 로드
    hospitals = load_hospitals()
    reviews = load_reviews()
    print(f"로드 완료 - 병원: {len(hospitals)}건, 리뷰: {len(reviews)}건")

    with Session(engine) as session:
        # 기존 데이터 정리 (재실행 안전)
        existing_count = session.execute(text("SELECT COUNT(*) FROM hospitals")).scalar()
        if existing_count > 0:
            print(f"기존 데이터 {existing_count}건 존재 - 초기화합니다")
            session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            session.execute(text("TRUNCATE TABLE reviews"))
            session.execute(text("TRUNCATE TABLE hospitals"))
            session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            session.commit()

        # bulk insert - hospitals
        print("병원 데이터 삽입 중...")
        session.bulk_insert_mappings(Hospital, hospitals)
        session.commit()
        h_count = session.execute(text("SELECT COUNT(*) FROM hospitals")).scalar()
        print(f"  hospitals: {h_count}행 삽입 완료")

        # bulk insert - reviews (배치)
        print("리뷰 데이터 삽입 중...")
        BATCH = 1000
        for i in range(0, len(reviews), BATCH):
            batch = reviews[i : i + BATCH]
            session.bulk_insert_mappings(Review, batch)
            session.commit()
            done = min(i + BATCH, len(reviews))
            print(f"  reviews: {done}/{len(reviews)} 삽입 완료", end="\r")
        print()

        r_count = session.execute(text("SELECT COUNT(*) FROM reviews")).scalar()
        print(f"  reviews: {r_count}행 삽입 완료")

        # ── 검증 쿼리 ──
        print(f"\n{'='*50}")
        print("  검증 쿼리 결과")
        print(f"{'='*50}")

        print(f"\n  [1] 전체 카운트")
        print(f"      hospitals: {h_count}행")
        print(f"      reviews:   {r_count}행")

        avg_rating = session.execute(
            text("SELECT ROUND(AVG(rating), 2) FROM reviews WHERE rating > 0")
        ).scalar()
        print(f"\n  [2] 평균 별점: {avg_rating}")

        top5 = session.execute(text("""
            SELECT h.name, COUNT(r.id) AS cnt
            FROM hospitals h
            JOIN reviews r ON h.id = r.hospital_id
            GROUP BY h.id, h.name
            ORDER BY cnt DESC
            LIMIT 5
        """)).fetchall()
        print(f"\n  [3] 리뷰 수 TOP 5:")
        for name, cnt in top5:
            print(f"      {name}: {cnt}건")

        date_range = session.execute(text("""
            SELECT MIN(review_date), MAX(review_date)
            FROM reviews
            WHERE review_date IS NOT NULL
        """)).fetchone()
        print(f"\n  [4] 리뷰 날짜 범위: {date_range[0]} ~ {date_range[1]}")

        rating_dist = session.execute(text("""
            SELECT rating, COUNT(*) AS cnt
            FROM reviews
            WHERE rating IS NOT NULL
            GROUP BY rating
            ORDER BY rating
        """)).fetchall()
        print(f"\n  [5] 별점 분포:")
        for rating, cnt in rating_dist:
            bar = "#" * (cnt // 20)
            print(f"      {rating}점: {cnt:>5}건 {bar}")

    print(f"\n{'='*50}")
    print("  seed 완료!")
    print(f"{'='*50}")


if __name__ == "__main__":
    seed()
