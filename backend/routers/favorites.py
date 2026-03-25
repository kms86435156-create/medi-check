"""즐겨찾기 API 라우터"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.database import get_db, User, Hospital, Favorite
from utils.auth import get_current_user

router = APIRouter(prefix="/api/favorites", tags=["favorites"])


# ── Pydantic 스키마 ──

class FavoriteItem(BaseModel):
    id: int
    hospital_id: int
    hospital_name: str
    hospital_address: str | None = None
    created_at: datetime | None = None


class FavoriteListResponse(BaseModel):
    items: list[FavoriteItem]
    total: int


class FavoriteResponse(BaseModel):
    message: str
    hospital_id: int


# ── 엔드포인트 ──

@router.get("", response_model=FavoriteListResponse)
def list_favorites(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """내 즐겨찾기 목록 조회"""
    favs = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )

    items = []
    for fav in favs:
        hospital = db.query(Hospital).filter(Hospital.id == fav.hospital_id).first()
        items.append(FavoriteItem(
            id=fav.id,
            hospital_id=fav.hospital_id,
            hospital_name=hospital.name if hospital else "삭제된 병원",
            hospital_address=hospital.address if hospital else None,
            created_at=fav.created_at,
        ))

    return FavoriteListResponse(items=items, total=len(items))


@router.post("/{hospital_id}", response_model=FavoriteResponse, status_code=status.HTTP_201_CREATED)
def add_favorite(
    hospital_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """즐겨찾기 추가"""
    hospital = db.query(Hospital).filter(Hospital.id == hospital_id).first()
    if not hospital:
        raise HTTPException(status_code=404, detail="병원을 찾을 수 없습니다.")

    existing = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id, Favorite.hospital_id == hospital_id)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 즐겨찾기에 추가된 병원입니다.",
        )

    fav = Favorite(
        user_id=current_user.id,
        hospital_id=hospital_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(fav)
    db.commit()
    return FavoriteResponse(message="즐겨찾기에 추가되었습니다.", hospital_id=hospital_id)


@router.delete("/{hospital_id}", response_model=FavoriteResponse)
def remove_favorite(
    hospital_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """즐겨찾기 삭제"""
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == current_user.id, Favorite.hospital_id == hospital_id)
        .first()
    )
    if not fav:
        raise HTTPException(status_code=404, detail="즐겨찾기에 없는 병원입니다.")

    db.delete(fav)
    db.commit()
    return FavoriteResponse(message="즐겨찾기에서 삭제되었습니다.", hospital_id=hospital_id)
