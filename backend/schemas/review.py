"""리뷰 Pydantic 스키마"""

from datetime import date
from pydantic import BaseModel


class ReviewBase(BaseModel):
    review_text: str | None = None
    rating: int | None = None
    review_date: date | None = None


class ReviewResponse(ReviewBase):
    id: int
    hospital_id: int

    model_config = {"from_attributes": True}


class ReviewList(BaseModel):
    items: list[ReviewResponse]
    total: int
    hospital_name: str
