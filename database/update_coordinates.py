"""
병원 주소 → 위경도 좌표 변환 (카카오 로컬 API)
hospitals 테이블의 address를 기반으로 lat/lng를 업데이트합니다.

사용법:
  1) .env 파일에 KAKAO_API_KEY 설정
  2) python update_coordinates.py
"""

import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ── 경로 / 환경 변수 ──
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "medicheck")
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY", "")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

KAKAO_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

# 카카오 API 분당 호출 제한 대비 딜레이 (초)
REQUEST_DELAY = 0.15


def geocode_address(client: httpx.Client, address: str) -> dict | None:
    """주소 검색 API로 위경도를 반환합니다."""
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    params = {"query": address}

    resp = client.get(KAKAO_SEARCH_URL, headers=headers, params=params)
    resp.raise_for_status()
    docs = resp.json().get("documents", [])

    if docs:
        return {"lat": float(docs[0]["y"]), "lng": float(docs[0]["x"])}
    return None


def geocode_keyword(client: httpx.Client, keyword: str) -> dict | None:
    """키워드 검색 API로 위경도를 반환합니다 (주소 검색 실패 시 폴백)."""
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    params = {"query": keyword}

    resp = client.get(KAKAO_KEYWORD_URL, headers=headers, params=params)
    resp.raise_for_status()
    docs = resp.json().get("documents", [])

    if docs:
        return {"lat": float(docs[0]["y"]), "lng": float(docs[0]["x"])}
    return None


def main():
    if not KAKAO_API_KEY:
        print("오류: .env 파일에 KAKAO_API_KEY를 설정하세요.")
        return

    engine = create_engine(DATABASE_URL, echo=False)
    print(f"DB 연결: {DB_HOST}:{DB_PORT}/{DB_NAME}")

    # 주소가 있고 lat/lng가 비어있는 병원 조회
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, address FROM hospitals "
            "WHERE address IS NOT NULL AND address != '' "
            "AND (lat IS NULL OR lng IS NULL) "
            "ORDER BY id "
            "LIMIT 300"
        )).fetchall()

    total = len(rows)
    print(f"좌표 변환 대상: {total}건\n")

    if total == 0:
        print("변환할 병원이 없습니다. (이미 모두 완료되었거나 주소가 없음)")
        return

    success = 0
    fail = 0
    fail_list = []

    with httpx.Client(timeout=10) as client, engine.begin() as conn:
        for idx, (hospital_id, name, address) in enumerate(rows, 1):
            # 1차: 주소 검색
            coords = geocode_address(client, address)

            # 2차: 실패 시 병원명으로 키워드 검색
            if not coords:
                coords = geocode_keyword(client, name)

            if coords:
                conn.execute(text(
                    "UPDATE hospitals SET lat = :lat, lng = :lng WHERE id = :id"
                ), {"lat": coords["lat"], "lng": coords["lng"], "id": hospital_id})
                success += 1
                status = f"({coords['lat']:.6f}, {coords['lng']:.6f})"
            else:
                fail += 1
                fail_list.append(f"  [{hospital_id}] {name} | {address}")
                status = "실패"

            print(f"  [{idx}/{total}] {name} → {status}")

            time.sleep(REQUEST_DELAY)

    # ── 결과 요약 ──
    print(f"\n{'='*50}")
    print(f"  좌표 변환 완료")
    print(f"{'='*50}")
    print(f"  성공: {success}건")
    print(f"  실패: {fail}건")

    if fail_list:
        print(f"\n  실패 목록:")
        for item in fail_list:
            print(item)

    # 전체 현황
    with engine.connect() as conn:
        total_hospitals = conn.execute(text("SELECT COUNT(*) FROM hospitals")).scalar()
        has_coords = conn.execute(text(
            "SELECT COUNT(*) FROM hospitals WHERE lat IS NOT NULL AND lng IS NOT NULL"
        )).scalar()
        print(f"\n  전체 병원: {total_hospitals}건")
        print(f"  좌표 보유: {has_coords}건 ({has_coords/total_hospitals*100:.1f}%)")

    print(f"{'='*50}")


if __name__ == "__main__":
    main()
