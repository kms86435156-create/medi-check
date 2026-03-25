"""위치기반 병원 검색 API 라우터"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from models.database import get_db

router = APIRouter(prefix="/api", tags=["search"])


class SearchHospitalItem(BaseModel):
    id: int
    name: str
    phone: str | None = None
    address: str | None = None
    hours: str | None = None
    place_url: str | None = None
    lat: float | None = None
    lng: float | None = None
    ai_summary: dict | None = None
    premium_rank: int = 0
    distance: float
    ai_score: float = 0.0

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    items: list[SearchHospitalItem]
    total: int
    center: dict
    radius: float


def _extract_ai_score(ai_summary) -> float:
    """ai_summary JSON에서 평균 AI 점수를 계산합니다."""
    if not ai_summary or not isinstance(ai_summary, dict):
        return 0.0

    score_keys = [
        "price_score", "pain_score", "wait_time_score",
        "cleanliness_score", "staff_score",
    ]
    scores = [ai_summary.get(k, 0) for k in score_keys if ai_summary.get(k)]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 2)


HAVERSINE_SQL = text("""
    SELECT *,
        (6371 * ACOS(
            COS(RADIANS(:lat)) * COS(RADIANS(lat))
            * COS(RADIANS(lng) - RADIANS(:lng))
            + SIN(RADIANS(:lat)) * SIN(RADIANS(lat))
        )) AS distance
    FROM hospitals
    WHERE lat IS NOT NULL AND lng IS NOT NULL
    HAVING distance < :radius
    ORDER BY distance ASC
""")


@router.get("/search", response_model=SearchResponse)
def search_nearby_hospitals(
    lat: float = Query(..., description="사용자 위도", ge=-90, le=90),
    lng: float = Query(..., description="사용자 경도", ge=-180, le=180),
    radius: float = Query(5, description="검색 반경 (km)", ge=0.1, le=50),
    sort: str = Query("distance", description="정렬 기준: distance, ai_score"),
    db: Session = Depends(get_db),
):
    """
    사용자 위경도 기준 반경 내 병원을 검색합니다.

    - Haversine 공식으로 거리를 계산합니다.
    - sort=ai_score 시 AI 평점 내림차순으로 정렬합니다.
    """
    rows = db.execute(
        HAVERSINE_SQL,
        {"lat": lat, "lng": lng, "radius": radius},
    ).mappings().all()

    items = []
    for row in rows:
        ai_summary = row.get("ai_summary")
        items.append(SearchHospitalItem(
            id=row["id"],
            name=row["name"],
            phone=row.get("phone"),
            address=row.get("address"),
            hours=row.get("hours"),
            place_url=row.get("place_url"),
            lat=row.get("lat"),
            lng=row.get("lng"),
            ai_summary=ai_summary,
            premium_rank=row.get("premium_rank", 0),
            distance=round(row["distance"], 2),
            ai_score=_extract_ai_score(ai_summary),
        ))

    if sort == "ai_score":
        items.sort(key=lambda x: x.ai_score, reverse=True)

    return SearchResponse(
        items=items,
        total=len(items),
        center={"lat": lat, "lng": lng},
        radius=radius,
    )
