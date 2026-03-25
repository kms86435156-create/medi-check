# 강남/신논현 피부과 스크래퍼

카카오맵에서 강남·신논현 지역 피부과 정보를 수집합니다.

## 설치

```bash
pip install playwright pandas tqdm
python -m playwright install chromium
```

## 실행

```bash
cd scraper
python hospital_scraper.py
```

## 수집 항목

| 컬럼 | 설명 |
|------|------|
| id | 순번 |
| name | 병원명 |
| phone | 전화번호 |
| address | 주소 |
| hours | 진료시간 |
| place_url | 카카오맵 상세 URL |

## 결과물

`data/hospitals_base.csv` (UTF-8 BOM, 엑셀 호환)

## 동작 방식

1. **Phase 1** — 여러 검색 키워드로 카카오맵 검색 결과를 페이지별로 순회하며 병원 기본 정보 수집 (중복 제거)
2. **Phase 2** — 전화번호/진료시간이 누락된 병원은 상세 페이지에서 보강
3. 1~3초 랜덤 딜레이 적용, 실패 시 최대 2회 재시도
