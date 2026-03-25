# MediCheck — 피부과 AI 리뷰 분석 플랫폼

강남/신논현 지역 피부과 병원의 리뷰를 AI로 분석하여 평점, 키워드, 시술 정보를 제공하는 백엔드 API입니다.

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI, SQLAlchemy, PyMySQL |
| Database | MySQL 8.0 |
| Auth | JWT (python-jose), bcrypt (passlib) |
| AI 분석 | Google Gemini API |
| 위치 검색 | 카카오 로컬 API, Haversine |
| 배포 | Railway + Docker |

## API 엔드포인트

### 병원
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/hospitals` | 병원 목록 (페이지네이션, 검색) |
| GET | `/api/hospitals/{id}` | 병원 상세 |

### 리뷰
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/reviews/{hospital_id}` | 병원별 리뷰 목록 |

### 위치 검색
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/search?lat=37.5&lng=127.0&radius=5&sort=ai_score` | 반경 내 병원 검색 |

### 인증
| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/auth/register` | 회원가입 |
| POST | `/api/auth/login` | 로그인 (JWT 발급) |
| GET | `/api/auth/me` | 내 정보 조회 |

### 즐겨찾기
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/favorites` | 내 즐겨찾기 목록 |
| POST | `/api/favorites/{hospital_id}` | 즐겨찾기 추가 |
| DELETE | `/api/favorites/{hospital_id}` | 즐겨찾기 삭제 |

## 로컬 실행

```bash
# 1. 환경변수 설정
cp .env.example .env
# .env 파일에 실제 값 입력

# 2. 의존성 설치
cd backend
pip install -r requirements.txt

# 3. DB 스키마 생성
mysql -u root -p < database/schema.sql

# 4. 시드 데이터 삽입
cd database && python seed.py

# 5. 서버 실행
cd backend && uvicorn main:app --reload
```

API 문서: http://localhost:8000/docs

## Railway 배포

1. GitHub 레포를 Railway에 연결
2. Railway 대시보드에서 MySQL 플러그인 추가
3. Variables 탭에 `backend/.env.example`의 환경변수 등록
4. 자동 배포 완료

## 프로젝트 구조

```
Project_Medi/
├── backend/
│   ├── main.py              # FastAPI 앱 진입점
│   ├── Dockerfile            # 컨테이너 빌드
│   ├── requirements.txt
│   ├── models/
│   │   └── database.py       # SQLAlchemy ORM 모델
│   ├── routers/
│   │   ├── hospitals.py      # 병원 API
│   │   ├── reviews.py        # 리뷰 API
│   │   ├── search.py         # 위치 검색 API
│   │   ├── auth.py           # 인증 API
│   │   └── favorites.py      # 즐겨찾기 API
│   ├── schemas/
│   │   ├── hospital.py       # Pydantic 스키마
│   │   └── review.py
│   └── utils/
│       ├── auth.py           # JWT 유틸리티
│       └── geocoding.py      # 카카오 지오코딩
├── database/
│   ├── schema.sql            # DDL
│   ├── seed.py               # 시드 스크립트
│   └── update_coordinates.py # 좌표 변환 스크립트
├── ai/
│   ├── gemini_analyzer.py    # Gemini AI 분석
│   └── batch_runner.py       # 배치 실행
├── scraper/                  # 웹 스크래퍼
├── data/                     # CSV/JSON 데이터
├── postman/
│   └── medi-check.json       # Postman 컬렉션
├── railway.toml              # Railway 설정
└── .env.example              # 환경변수 템플릿
```
