"""MediCheck API 서버"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import hospitals, reviews, search, auth, favorites

app = FastAPI(
    title="MediCheck API",
    description="강남/신논현 피부과 AI 리뷰 분석 플랫폼",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터
app.include_router(hospitals.router)
app.include_router(reviews.router)
app.include_router(search.router)
app.include_router(auth.router)
app.include_router(favorites.router)


@app.get("/", tags=["root"])
def root():
    return {
        "service": "MediCheck API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "hospitals": "/api/hospitals",
            "hospital_detail": "/api/hospitals/{id}",
            "reviews": "/api/reviews/{hospital_id}",
            "search": "/api/search?lat=37.5&lng=127.0&radius=5&sort=ai_score",
            "register": "/api/auth/register",
            "login": "/api/auth/login",
            "me": "/api/auth/me",
            "favorites": "/api/favorites",
        },
    }
