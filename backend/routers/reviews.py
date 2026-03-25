"""리뷰 API 라우터"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from models.database import get_db, Hospital, Review
from schemas.review import ReviewResponse, ReviewList

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("/{hospital_id}", response_model=ReviewList)
def get_reviews(
    hospital_id: int,
    rating: int = Query(None, ge=1, le=5, description="별점 필터"),
    db: Session = Depends(get_db),
):
    """병원별 리뷰 조회"""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="병원을 찾을 수 없습니다.")

    query = db.query(Review).filter(Review.hospital_id == hospital_id)

    if rating:
        query = query.filter(Review.rating == rating)

    query = query.order_by(Review.review_date.desc())
    reviews = query.all()

    return ReviewList(
        items=[ReviewResponse.model_validate(r) for r in reviews],
        total=len(reviews),
        hospital_name=hospital.name,
    )
