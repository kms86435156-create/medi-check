"""
DAY 5 - AI 자동화 배치: 300개 병원 분석 + DB 업데이트
멀티 AI 폴백 (Gemini -> OpenAI -> Claude) + asyncio Semaphore

사용법:
  python batch_runner.py                         전체 실행
  python batch_runner.py --retry                 실패 건만 재시도
  python batch_runner.py --dry-run               DB 저장 없이 테스트
  python batch_runner.py --provider openai       특정 API만 사용
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# gemini_analyzer 에서 멀티 AI 함수 임포트
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemini_analyzer import (
    analyze_hospital,
    make_default_report,
    load_reviews as load_reviews_map,
    print_provider_stats,
    provider_stats,
)

# -- 경로 --
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

FULL_OUTPUT = DATA_DIR / "ai_reports.json"
FAILED_IDS_FILE = LOG_DIR / "failed_ids.txt"

# -- 환경 변수 --
load_dotenv(BASE_DIR / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "medicheck")

DATABASE_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

# -- 상수 --
CONCURRENCY = 5
RPM_DELAY = 1.5


# ============================================
# 데이터 로드
# ============================================

def load_all_hospital_ids(engine) -> list[int]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM hospitals ORDER BY id")).fetchall()
    return [r[0] for r in rows]


def load_failed_ids() -> set[int]:
    if not FAILED_IDS_FILE.exists():
        return set()
    ids = set()
    for line in FAILED_IDS_FILE.read_text().strip().splitlines():
        line = line.strip()
        if line.isdigit():
            ids.add(int(line))
    return ids


def save_failed_ids(ids: set[int]):
    FAILED_IDS_FILE.write_text("\n".join(str(i) for i in sorted(ids)))


# ============================================
# 비동기 배치 실행
# ============================================

async def process_hospital(
    sem, loop, hid, name, reviews, results, failed, counter, total,
    force_provider,
):
    async with sem:
        try:
            report = await loop.run_in_executor(
                None, analyze_hospital, hid, name, reviews, None, force_provider,
            )
            results.append(report)
            counter["ok"] += 1
        except Exception as e:
            print(f"  [{hid}] {name}: 실패 - {str(e)[:60]}")
            failed.add(hid)
            counter["fail"] += 1

        done = counter["ok"] + counter["fail"]
        by = report.get("analyzed_by", "?") if "report" in dir() else "?"
        print(f"  {done}/{total} processed "
              f"(ok={counter['ok']} fail={counter['fail']}) "
              f"[{hid}] {name} ({by})")

        await asyncio.sleep(RPM_DELAY)


async def run_batch(hospital_ids, reviews_map, force_provider=None):
    sem = asyncio.Semaphore(CONCURRENCY)
    loop = asyncio.get_event_loop()
    results = []
    failed = set()
    counter = {"ok": 0, "fail": 0}
    total = len(hospital_ids)

    print(f"\n{'='*55}")
    print(f"  배치 실행: {total}곳 | 동시 {CONCURRENCY}건")
    print(f"  시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*55}\n")

    tasks = []
    for hid in hospital_ids:
        data = reviews_map.get(hid)
        if not data or not data["reviews"]:
            name = data["name"] if data else f"Hospital_{hid}"
            report = make_default_report(name)
            report["hospital_id"] = hid
            report["hospital_name"] = name
            report["review_count"] = 0
            results.append(report)
            counter["ok"] += 1
            done = counter["ok"] + counter["fail"]
            print(f"  {done}/{total} [{hid}] {name} (리뷰 없음)")
            continue

        tasks.append(process_hospital(
            sem, loop, hid, data["name"], data["reviews"],
            results, failed, counter, total, force_provider,
        ))

    await asyncio.gather(*tasks)

    results.sort(key=lambda r: r["hospital_id"])
    with open(FULL_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  JSON 저장: {FULL_OUTPUT} ({len(results)}건)")

    if failed:
        save_failed_ids(failed)
        print(f"  실패 목록: {FAILED_IDS_FILE} ({len(failed)}건)")
    elif FAILED_IDS_FILE.exists():
        FAILED_IDS_FILE.unlink()

    return results, failed


# ============================================
# DB 업데이트
# ============================================

def update_db(results):
    engine = create_engine(DATABASE_URL, echo=False)
    updated = 0
    with engine.begin() as conn:
        for r in results:
            summary = {
                "price_score": r.get("price_score", 3),
                "pain_score": r.get("pain_score", 3),
                "wait_time_score": r.get("wait_time_score", 3),
                "cleanliness_score": r.get("cleanliness_score", 3),
                "staff_score": r.get("staff_score", 3),
                "summary": r.get("summary", ""),
                "keywords": r.get("keywords", []),
                "procedures": r.get("procedures", []),
                "review_count": r.get("review_count", 0),
                "analyzed_by": r.get("analyzed_by", "unknown"),
                "analyzed_at": datetime.now().isoformat(),
            }
            conn.execute(
                text("UPDATE hospitals SET ai_summary = :s WHERE id = :id"),
                {"s": json.dumps(summary, ensure_ascii=False), "id": r["hospital_id"]},
            )
            updated += 1
    print(f"  DB 업데이트: {updated}건")
    return engine


def print_stats(engine, results):
    print(f"\n{'='*55}")
    print("  배치 완료 통계")
    print(f"{'='*55}")

    with engine.connect() as conn:
        filled = conn.execute(
            text("SELECT COUNT(*) FROM hospitals WHERE ai_summary IS NOT NULL")
        ).scalar()
        total = conn.execute(text("SELECT COUNT(*) FROM hospitals")).scalar()
    print(f"\n  DB: ai_summary {filled}/{total}곳")

    score_fields = ["price_score", "pain_score", "wait_time_score",
                     "cleanliness_score", "staff_score"]
    scored = []
    for r in results:
        avg = sum(r.get(f, 3) for f in score_fields) / len(score_fields)
        scored.append((r["hospital_id"], r["hospital_name"], avg, r.get("review_count", 0)))
    scored.sort(key=lambda x: x[2], reverse=True)

    print(f"\n  평균 점수 TOP 10:")
    print(f"  {'#':>3}  {'ID':>4}  {'병원명':<28} {'평균':>5} {'리뷰':>4} {'AI':<8}")
    print(f"  {'-'*62}")
    for rank, (hid, name, avg, cnt) in enumerate(scored[:10], 1):
        by = next((r.get("analyzed_by", "?") for r in results if r["hospital_id"] == hid), "?")
        print(f"  {rank:>3}  {hid:>4}  {name[:26]:<28} {avg:>5.2f} {cnt:>4} {by:<8}")

    print(f"\n  항목별 전체 평균:")
    for f in score_fields:
        vals = [r.get(f, 3) for r in results]
        avg = sum(vals) / len(vals)
        label = f.replace("_score", "")
        print(f"    {label:<16} {avg:.2f}")

    print(f"\n{'='*55}")


# ============================================
# 메인
# ============================================

def main():
    reviews_map = load_reviews_map()
    engine = create_engine(DATABASE_URL, echo=False)

    retry_mode = "--retry" in sys.argv
    dry_run = "--dry-run" in sys.argv
    force_provider = None
    if "--provider" in sys.argv:
        idx = sys.argv.index("--provider")
        if idx + 1 < len(sys.argv):
            force_provider = sys.argv[idx + 1]

    all_ids = load_all_hospital_ids(engine)

    if retry_mode:
        fids = load_failed_ids()
        if not fids:
            print("재시도할 실패 건이 없습니다.")
            return
        target_ids = [i for i in all_ids if i in fids]
        print(f"재시도 모드: {len(target_ids)}건")
    else:
        target_ids = all_ids

    results, failed = asyncio.run(run_batch(target_ids, reviews_map, force_provider))

    if not dry_run and results:
        print(f"\n  DB 업데이트 중...")
        engine = update_db(results)

    print_provider_stats()
    print_stats(engine, results)
    print(f"\n  최종: 성공 {len(results)}건, 실패 {len(failed)}건")


if __name__ == "__main__":
    main()
