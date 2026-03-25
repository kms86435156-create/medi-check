"""
멀티 AI 병원 리뷰 분석기 (Best-of-3 방식)
Gemini, OpenAI, Claude 3개를 동시 호출 -> 품질 점수가 가장 높은 응답 선택

사용법:
  python gemini_analyzer.py              샘플 5개 병원
  python gemini_analyzer.py --all        전체 병원
  python gemini_analyzer.py --provider openai   특정 AI만 사용
"""

import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

# -- 경로 --
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ENV_FILE = BASE_DIR / ".env"

REVIEWS_JSON = DATA_DIR / "reviews_raw.json"
SAMPLE_OUTPUT = DATA_DIR / "ai_sample.json"
FULL_OUTPUT = DATA_DIR / "ai_reports.json"

# -- 환경 변수 --
load_dotenv(ENV_FILE)

# -- 상수 --
CHUNK_SIZE = 100
MAX_RETRIES = 2
RETRY_DELAY = 2

# 동점 시 우선순위 (낮을수록 우선)
PRIORITY = {"gemini": 0, "openai": 1, "claude": 2}

# -- 프롬프트 --
PROMPT_TEMPLATE = """\
다음은 [{hospital_name}]에 대한 실제 환자 리뷰 {review_count}개입니다.

아래 항목을 JSON 형식으로만 응답하세요 (다른 텍스트 없이, 코드블록 없이):
{{
  "price_score": 1-5,
  "pain_score": 1-5,
  "wait_time_score": 1-5,
  "cleanliness_score": 1-5,
  "staff_score": 1-5,
  "summary": "3줄 이내 핵심 요약 (장점, 단점, 종합평가)",
  "keywords": ["태그1", "태그2", "태그3", "태그4", "태그5"],
  "procedures": [
    {{"name": "시술명1", "price_range": "가격대1"}},
    {{"name": "시술명2", "price_range": "가격대2"}}
  ]
}}

점수 기준:
- price_score: 1=매우비쌈 ~ 5=매우저렴
- pain_score: 1=매우아픔 ~ 5=무통
- wait_time_score: 1=매우오래기다림 ~ 5=대기없음
- cleanliness_score: 1=비위생 ~ 5=매우청결
- staff_score: 1=불친절 ~ 5=매우친절

리뷰에 언급이 없는 항목은 3(보통)으로 설정하세요.
procedures에서 가격 정보가 없으면 "정보없음"으로 기재하세요.

=== 리뷰 목록 ===
{reviews_text}
"""

# -- 처리 통계 --
provider_stats = Counter()    # 선택된 횟수
provider_calls = Counter()    # 호출 시도 횟수
provider_quality = {}         # provider별 품질 점수 누적 {name: [scores]}


# ============================================
# 공통 유틸
# ============================================

def load_reviews() -> dict[int, dict]:
    with open(REVIEWS_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    hospitals = {}
    for r in raw:
        hid = r["hospital_id"]
        if hid not in hospitals:
            hospitals[hid] = {
                "name": r.get("hospital_name", f"Hospital_{hid}"),
                "reviews": [],
            }
        hospitals[hid]["reviews"].append(r["review_text"])
    return hospitals


def chunk_reviews(reviews: list[str], size: int = CHUNK_SIZE) -> list[list[str]]:
    return [reviews[i : i + size] for i in range(0, len(reviews), size)]


def build_prompt(hospital_name: str, reviews: list[str]) -> str:
    reviews_text = "\n".join(f"[{i+1}] {rev}" for i, rev in enumerate(reviews))
    return PROMPT_TEMPLATE.format(
        hospital_name=hospital_name,
        review_count=len(reviews),
        reviews_text=reviews_text,
    )


def extract_json(text: str) -> dict | None:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def validate_report(report: dict) -> dict:
    for field in ["price_score", "pain_score", "wait_time_score",
                   "cleanliness_score", "staff_score"]:
        val = report.get(field, 3)
        if not isinstance(val, (int, float)) or val < 1 or val > 5:
            report[field] = 3
        else:
            report[field] = int(val)
    if "summary" not in report or not report["summary"]:
        report["summary"] = "요약 정보 없음"
    if "keywords" not in report or not isinstance(report["keywords"], list):
        report["keywords"] = []
    if "procedures" not in report or not isinstance(report["procedures"], list):
        report["procedures"] = []
    return report


def make_default_report(hospital_name: str) -> dict:
    return {
        "price_score": 3, "pain_score": 3, "wait_time_score": 3,
        "cleanliness_score": 3, "staff_score": 3,
        "summary": f"{hospital_name}에 대한 분석을 수행할 수 없습니다.",
        "keywords": [], "procedures": [], "analyzed_by": "none",
    }


def merge_reports(reports: list[dict]) -> dict:
    score_fields = ["price_score", "pain_score", "wait_time_score",
                     "cleanliness_score", "staff_score"]
    merged = {}
    for f in score_fields:
        vals = [r.get(f, 3) for r in reports]
        merged[f] = round(sum(vals) / len(vals))
    merged["summary"] = reports[-1].get("summary", "")
    kws = []
    for r in reports:
        kws.extend(r.get("keywords", []))
    merged["keywords"] = list(dict.fromkeys(kws))[:10]
    seen = set()
    merged["procedures"] = []
    for r in reports:
        for p in r.get("procedures", []):
            n = p.get("name", "")
            if n and n not in seen:
                seen.add(n)
                merged["procedures"].append(p)
    merged["analyzed_by"] = reports[-1].get("analyzed_by", "unknown")
    return merged


# ============================================
# 품질 점수 함수
# ============================================

def score_report(report: dict) -> int:
    """
    리포트 품질 점수 (높을수록 좋음).
      - 점수 필드 5개 모두 1~5 범위: +5 (필드당 +1)
      - summary 50자 이상: +3, 20자 이상: +1
      - keywords 3개 이상: +3, 1개 이상: +1
      - procedures 1개 이상: +2
    최대 13점.
    """
    score = 0
    score_fields = ["price_score", "pain_score", "wait_time_score",
                     "cleanliness_score", "staff_score"]

    for f in score_fields:
        val = report.get(f)
        if isinstance(val, (int, float)) and 1 <= val <= 5:
            score += 1

    summary = report.get("summary", "")
    if len(summary) >= 50:
        score += 3
    elif len(summary) >= 20:
        score += 1

    kw_count = len(report.get("keywords", []))
    if kw_count >= 3:
        score += 3
    elif kw_count >= 1:
        score += 1

    if len(report.get("procedures", [])) >= 1:
        score += 2

    return score


# ============================================
# Provider 별 API 호출
# ============================================

def call_gemini(prompt: str) -> tuple[str | None, str]:
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None, "gemini"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    resp = model.generate_content(prompt, request_options={"timeout": 30})
    return resp.text, "gemini"


def call_openai(prompt: str) -> tuple[str | None, str]:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return None, "openai"
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "JSON 형식으로만 응답하세요. 코드블록 없이 순수 JSON만 출력하세요."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        timeout=30,
    )
    return resp.choices[0].message.content, "openai"


def call_claude(prompt: str) -> tuple[str | None, str]:
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None, "claude"
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text, "claude"


PROVIDERS = [
    ("gemini", call_gemini),
    ("openai", call_openai),
    ("claude", call_claude),
]


# ============================================
# 단일 provider 호출 (스레드용)
# ============================================

def try_provider(provider_name: str, call_fn, prompt: str) -> dict | None:
    """한 provider를 호출하고 파싱된 report를 반환. 실패 시 None."""
    provider_calls[provider_name] += 1
    for attempt in range(MAX_RETRIES):
        try:
            text, _ = call_fn(prompt)
            if text is None:
                return None  # API 키 없음

            report = extract_json(text)
            if report:
                report = validate_report(report)
                report["analyzed_by"] = provider_name
                return report

        except Exception:
            time.sleep(RETRY_DELAY * (attempt + 1))

    return None


# ============================================
# Best-of-3: 동시 호출 + 품질 기반 선택
# ============================================

def call_best_of_3(prompt: str, force_provider: str | None = None) -> dict | None:
    """
    3개 API를 동시 호출하고 품질 점수가 가장 높은 응답을 선택합니다.
    동점이면 Gemini > OpenAI > Claude 우선순위.
    force_provider 지정 시 해당 API만 사용.
    """
    if force_provider:
        providers = [(n, fn) for n, fn in PROVIDERS if n == force_provider]
    else:
        # 키가 있는 provider만 필터링
        providers = []
        key_map = {
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "claude": "ANTHROPIC_API_KEY",
        }
        for name, fn in PROVIDERS:
            if os.getenv(key_map[name], ""):
                providers.append((name, fn))

    if not providers:
        return None

    # 동시 호출
    candidates = []
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = {
            executor.submit(try_provider, name, fn, prompt): name
            for name, fn in providers
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                report = future.result()
                if report:
                    q = score_report(report)
                    candidates.append((name, report, q))
            except Exception:
                pass

    if not candidates:
        return None

    # 품질 점수 내림차순 정렬, 동점이면 우선순위(PRIORITY) 오름차순
    candidates.sort(key=lambda x: (-x[2], PRIORITY.get(x[0], 99)))

    winner_name, winner_report, winner_score = candidates[0]

    # 품질 점수 기록
    for name, _, q in candidates:
        provider_quality.setdefault(name, []).append(q)

    # 경쟁 로그
    parts = []
    for name, _, q in candidates:
        marker = " *" if name == winner_name else ""
        parts.append(f"{name}={q}{marker}")
    print(f"      품질: [{' | '.join(parts)}]")

    return winner_report


# ============================================
# analyze_hospital (Best-of-3 버전)
# ============================================

def analyze_hospital(
    hospital_id: int,
    hospital_name: str,
    reviews: list[str],
    model=None,
    force_provider: str | None = None,
) -> dict:
    """
    병원 리뷰를 분석합니다.
    3개 AI를 동시 호출하고 품질 최고 응답을 선택합니다.
    """
    chunks = chunk_reviews(reviews, CHUNK_SIZE)
    chunk_reports = []

    for ci, chunk in enumerate(chunks):
        prompt = build_prompt(hospital_name, chunk)
        report = call_best_of_3(prompt, force_provider)

        if report:
            chunk_reports.append(report)
            provider_stats[report["analyzed_by"]] += 1
            print(f"    chunk {ci+1}/{len(chunks)}: BEST={report['analyzed_by']}")
        else:
            default = make_default_report(hospital_name)
            chunk_reports.append(default)
            provider_stats["failed"] += 1
            print(f"    chunk {ci+1}/{len(chunks)}: FAIL")

    if len(chunk_reports) == 1:
        final = chunk_reports[0]
    else:
        final = merge_reports(chunk_reports)

    final["hospital_id"] = hospital_id
    final["hospital_name"] = hospital_name
    final["review_count"] = len(reviews)
    return final


# ============================================
# 통계 출력
# ============================================

def print_provider_stats():
    print(f"\n  {'='*55}")
    print(f"  Best-of-3 경쟁 결과")
    print(f"  {'='*55}")

    # 선택 횟수
    total = sum(provider_stats.values())
    print(f"\n  [선택 횟수] (품질 점수 기반)")
    for name in ["gemini", "openai", "claude", "failed"]:
        cnt = provider_stats.get(name, 0)
        pct = cnt / total * 100 if total else 0
        bar = "#" * int(pct / 3) if cnt else ""
        label = name.upper() if name != "failed" else "FAILED"
        print(f"    {label:<10} {cnt:>4}건 ({pct:>5.1f}%) {bar}")
    print(f"    {'TOTAL':<10} {total:>4}건")

    # 호출 횟수
    print(f"\n  [API 호출 횟수]")
    for name in ["gemini", "openai", "claude"]:
        calls = provider_calls.get(name, 0)
        wins = provider_stats.get(name, 0)
        rate = wins / calls * 100 if calls else 0
        print(f"    {name.upper():<10} 호출 {calls:>4}건 -> 선택 {wins:>4}건 (승률 {rate:>5.1f}%)")

    # 평균 품질 점수
    if provider_quality:
        print(f"\n  [평균 품질 점수] (13점 만점)")
        for name in ["gemini", "openai", "claude"]:
            scores = provider_quality.get(name, [])
            if scores:
                avg = sum(scores) / len(scores)
                bar = "#" * int(avg)
                print(f"    {name.upper():<10} {avg:>5.1f}/13  {bar}")

    print(f"  {'='*55}")


# ============================================
# 실행 모드
# ============================================

def run_sample(hospitals: dict, n=5, force_provider=None):
    sorted_h = sorted(
        hospitals.items(), key=lambda x: len(x[1]["reviews"]), reverse=True,
    )[:n]
    results = []
    for hid, data in sorted_h:
        name = data["name"]
        revs = data["reviews"]
        print(f"\n  [{hid}] {name} ({len(revs)}건)")
        report = analyze_hospital(hid, name, revs, force_provider=force_provider)
        results.append(report)
        print(f"    price={report['price_score']} pain={report['pain_score']} "
              f"wait={report['wait_time_score']} clean={report['cleanliness_score']} "
              f"staff={report['staff_score']} by={report.get('analyzed_by','?')}")
        print(f"    summary: {report.get('summary','')[:70]}...")
        time.sleep(1)
    with open(SAMPLE_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  저장: {SAMPLE_OUTPUT}")
    print_provider_stats()
    return results


def run_all(hospitals: dict, force_provider=None):
    results = []
    total = len(hospitals)
    for i, (hid, data) in enumerate(hospitals.items(), 1):
        name = data["name"]
        revs = data["reviews"]
        print(f"\n  [{i}/{total}] [{hid}] {name} ({len(revs)}건)")
        report = analyze_hospital(hid, name, revs, force_provider=force_provider)
        results.append(report)
        if i % 10 == 0:
            with open(FULL_OUTPUT, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"    -- 중간 저장: {i}/{total} --")
        time.sleep(1)
    with open(FULL_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  전체 저장: {FULL_OUTPUT} ({len(results)}건)")
    print_provider_stats()
    return results


def main():
    keys = {
        "gemini": os.getenv("GEMINI_API_KEY", ""),
        "openai": os.getenv("OPENAI_API_KEY", ""),
        "claude": os.getenv("ANTHROPIC_API_KEY", ""),
    }
    available = [k for k, v in keys.items() if v]
    if not available:
        print("API 키가 하나도 설정되지 않았습니다.")
        sys.exit(1)

    print("=" * 55)
    print("  Multi-AI 병원 리뷰 분석기 (Best-of-3)")
    print(f"  사용 가능: {', '.join(available)}")
    print(f"  방식: 동시 호출 -> 품질 점수 기반 최고 응답 선택")
    print("=" * 55)

    force = None
    if "--provider" in sys.argv:
        idx = sys.argv.index("--provider")
        if idx + 1 < len(sys.argv):
            force = sys.argv[idx + 1]
            print(f"  강제 지정: {force}")

    hospitals = load_reviews()
    print(f"  병원 {len(hospitals)}곳, 총 리뷰 {sum(len(h['reviews']) for h in hospitals.values())}건")

    if "--all" in sys.argv:
        run_all(hospitals, force_provider=force)
    else:
        run_sample(hospitals, n=5, force_provider=force)


if __name__ == "__main__":
    main()
