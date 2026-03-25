"""카카오 로컬 API를 이용한 주소 → 위경도 변환"""

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

KAKAO_API_KEY = os.getenv("KAKAO_API_KEY", "")
KAKAO_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/address.json"


async def address_to_coords(address: str) -> dict | None:
    """
    주소를 위경도 좌표로 변환합니다.

    Returns:
        {"lat": float, "lng": float} 또는 결과 없으면 None
    """
    if not KAKAO_API_KEY:
        raise ValueError("KAKAO_API_KEY 환경변수가 설정되지 않았습니다.")

    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    params = {"query": address}

    async with httpx.AsyncClient() as client:
        resp = await client.get(KAKAO_SEARCH_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    documents = data.get("documents", [])
    if not documents:
        return None

    doc = documents[0]
    return {
        "lat": float(doc["y"]),
        "lng": float(doc["x"]),
    }
