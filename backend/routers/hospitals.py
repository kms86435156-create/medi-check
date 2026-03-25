"""병원 API 라우터"""

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from models.database import get_db, Hospital, Review
from schemas.hospital import HospitalResponse, HospitalList

router = APIRouter(prefix="/api/hospitals", tags=["hospitals"])


@router.get("", response_model=HospitalList)
def list_hospitals(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str = Query(None, description="병원명 검색"),
    sort: str = Query("id", description="정렬 기준: id, name, premium_rank"),
    db: Session = Depends(get_db),
):
    """병원 목록 조회 (페이지네이션)"""
    query = db.query(Hospital)

    if search:
        query = query.filter(Hospital.name.contains(search))

    total = query.count()

    # 정렬
    if sort == "name":
        query = query.order_by(Hospital.name)
    elif sort == "premium_rank":
        query = query.order_by(Hospital.premium_rank.desc(), Hospital.id)
    else:
        query = query.order_by(Hospital.id)

    # 페이지네이션
    offset = (page - 1) * size
    hospitals = query.offset(offset).limit(size).all()

    items = []
    for h in hospitals:
        review_count = db.query(func.count(Review.id)).filter(Review.hospital_id == h.id).scalar()
        resp = HospitalResponse.model_validate(h)
        resp.review_count = review_count
        items.append(resp)

    return HospitalList(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=math.ceil(total / size) if total else 0,
    )


@router.get("/{hospital_id}", response_model=HospitalResponse)
def get_hospital(hospital_id: int, db: Session = Depends(get_db)):
    """병원 상세 조회"""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="병원을 찾을 수 없습니다.")

    review_count = db.query(func.count(Review.id)).filter(Review.hospital_id == hospital_id).scalar()
    resp = HospitalResponse.model_validate(hospital)
    resp.review_count = review_count
    return resp
