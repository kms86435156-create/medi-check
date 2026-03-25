"""병원 Pydantic 스키마"""

from datetime import datetime
from pydantic import BaseModel


class AISummary(BaseModel):
    price_score: int = 3
    pain_score: int = 3
    wait_time_score: int = 3
    cleanliness_score: int = 3
    staff_score: int = 3
    summary: str = ""
    keywords: list[str] = []
    procedures: list[dict] = []
    review_count: int = 0
    analyzed_by: str = ""
    analyzed_at: str = ""


class HospitalBase(BaseModel):
    name: str
    phone: str | None = None
    address: str | None = None
    hours: str | None = None
    place_url: str | None = None
    lat: float | None = None
    lng: float | None = None


class HospitalCreate(HospitalBase):
    pass


class HospitalResponse(HospitalBase):
    id: int
    ai_summary: dict | None = None
    premium_rank: int = 0
    created_at: datetime | None = None
    review_count: int = 0

    model_config = {"from_attributes": True}


class HospitalList(BaseModel):
    items: list[HospitalResponse]
    total: int
    page: int
    size: int
    pages: int
