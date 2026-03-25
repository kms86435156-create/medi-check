"""
DAY 2 — 리뷰 데이터 크롤링 및 클렌징
hospitals_base.csv → 카카오 플레이스 리뷰 수집 → reviews_raw.json

Phase 1: 병원명으로 카카오 Place ID 확보
Phase 2: 각 병원의 리뷰를 '더보기' 클릭으로 전량 수집
Phase 3: 정규표현식으로 클렌징 후 JSON 저장
"""

import asyncio
import csv
import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from tqdm import tqdm

# ── 경로 ──
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

INPUT_CSV = DATA_DIR / "hospitals_base.csv"
OUTPUT_JSON = DATA_DIR / "reviews_raw.json"
LOG_FILE = LOG_DIR / "scrape.log"

# ── 로깅 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── 클렌징 패턴 ──
EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]", flags=re.UNICODE)
PHONE_RE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")
MULTI_SPACE_RE = re.compile(r"\s+")
DATE_RE = re.compile(r"(\d{4}\.\d{2}\.\d{2})")
MIN_LENGTH = 10
MAX_RETRIES = 2


def clean_review(text: str) -> str | None:
    if not text:
        return None
    text = EMOJI_RE.sub("", text)
    text = PHONE_RE.sub("", text)
    text = MULTI_SPACE_RE.sub(" ", text).strip()
    if len(text) < MIN_LENGTH:
        return None
    return text


def load_hospitals() -> list[dict]:
    hospitals = []
    with open(INPUT_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            hospitals.append(row)
    logger.info(f"CSV 로드: {len(hospitals)}곳")
    return hospitals


async def random_delay(lo=1.0, hi=3.0):
    await asyncio.sleep(random.uniform(lo, hi))


# ═══════════════════════════════════════
# Phase 1 — Place ID 확보
# ═══════════════════════════════════════

async def resolve_place_id(page, name: str) -> str | None:
    """카카오맵 검색 → 링크에서 place ID 추출"""
    for attempt in range(MAX_RETRIES + 1):
        try:
            url = f"https://map.kakao.com/?q={quote(name)}"
            await page.goto(url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(1)

            # 검색 입력 + Enter
            si = await page.query_selector("#search\\.keyword\\.query")
            if si:
                await si.fill(name)
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)

            # 링크에서 place ID 추출
            place_ids = await page.evaluate('''
                (() => {
                    const ids = new Set();
                    document.querySelectorAll("a").forEach(a => {
                        const m = (a.href || "").match(/place\\.map\\.kakao\\.com\\/(\\d+)/);
                        if (m) ids.add(m[1]);
                    });
                    return [...ids];
                })()
            ''')
            if place_ids:
                return place_ids[0]
            return None

        except (PwTimeout, Exception) as e:
            if attempt < MAX_RETRIES:
                await random_delay(2, 4)
            else:
                logger.warning(f"Place ID 실패: {name} — {e}")
                return None
    return None


# ═══════════════════════════════════════
# Phase 2 — 리뷰 크롤링
# ═══════════════════════════════════════

async def crawl_reviews(page, place_id: str, max_clicks=50) -> list[dict]:
    """
    카카오 플레이스 상세 페이지에서 리뷰를 수집합니다.
    '후기 더보기' 버튼을 반복 클릭하여 전량 수집합니다.
    """
    reviews = []
    place_url = f"https://place.map.kakao.com/{place_id}"

    for attempt in range(MAX_RETRIES + 1):
        try:
            await page.goto(place_url, wait_until="networkidle", timeout=25000)
            await random_delay(1.5, 3)
            break
        except (PwTimeout, Exception):
            if attempt < MAX_RETRIES:
                await random_delay(2, 4)
            else:
                return reviews

    # 후기 탭 클릭
    try:
        await page.evaluate('''
            (() => {
                const tabs = document.querySelectorAll("a.link_tab, a, button");
                for (const t of tabs) {
                    const txt = t.textContent.trim();
                    if (txt.includes("후기") && !txt.includes("블로그")) {
                        t.click();
                        return true;
                    }
                }
                return false;
            })()
        ''')
        await random_delay(1.5, 2.5)
    except Exception:
        pass

    # '후기 더보기' 반복 클릭
    for _ in range(max_clicks):
        clicked = await click_review_more(page)
        if not clicked:
            break
        await random_delay(0.8, 1.8)

    # 리뷰 추출
    raw_reviews = await extract_reviews(page)
    return raw_reviews


async def click_review_more(page) -> bool:
    """후기 더보기 버튼 클릭"""
    try:
        clicked = await page.evaluate('''
            (() => {
                // 1) "후기 더보기" 버튼 (btn_comm 스타일)
                const btns = document.querySelectorAll("a.btn_comm, button.btn_comm, a.link_more, button");
                for (const b of btns) {
                    const txt = b.textContent.trim();
                    if ((txt.includes("후기") && txt.includes("더보기")) ||
                        (txt.includes("후기") && txt.includes("더 보기"))) {
                        if (b.offsetParent !== null) {
                            b.click();
                            return true;
                        }
                    }
                }
                // 2) 일반적인 "더보기" 링크 (review 섹션 내)
                const section = document.querySelector(".section_review, .group_review");
                if (section) {
                    const moreBtn = section.querySelector("a.link_more, button.btn_more, a.btn_comm");
                    if (moreBtn && moreBtn.offsetParent !== null) {
                        moreBtn.click();
                        return true;
                    }
                }
                return false;
            })()
        ''')
        return clicked
    except Exception:
        return False


async def extract_reviews(page) -> list[dict]:
    """현재 페이지에서 리뷰를 추출합니다."""
    raw = await page.evaluate('''
        (() => {
            const results = [];

            // 리뷰 리스트 아이템
            const items = document.querySelectorAll("ul.list_review > li");
            for (const li of items) {
                // 리뷰 텍스트
                let text = "";
                const descEl = li.querySelector(".desc_review");
                if (descEl) {
                    text = descEl.textContent.trim();
                } else {
                    const wrapEl = li.querySelector(".wrap_review, a.link_review");
                    if (wrapEl) text = wrapEl.textContent.trim();
                }

                // 별점 (여러 셀렉터 + 텍스트 파싱)
                let rating = 0;
                const starEl = li.querySelector(".num_star, .starred_grade, [class*='star']");
                if (starEl) {
                    const sm = starEl.textContent.match(/(\\d+\\.?\\d*)/);
                    if (sm) rating = parseFloat(sm[1]);
                }
                if (rating === 0) {
                    const allInfo = li.querySelector(".info_review, .review_detail, .area_review");
                    if (allInfo) {
                        const rm = allInfo.textContent.match(/별점\\s*(\\d+\\.?\\d*)/);
                        if (rm) rating = parseFloat(rm[1]);
                    }
                }

                // 날짜
                let date = "";
                const infoEl = li.querySelector(".info_review, .review_detail, .area_review");
                if (infoEl) {
                    const infoText = infoEl.textContent;
                    const dateMatch = infoText.match(/(\\d{4}\\.\\d{2}\\.\\d{2})/);
                    if (dateMatch) date = dateMatch[1];
                }

                if (text && text.length >= 5) {
                    results.push({ review_text: text, rating: rating, date: date });
                }
            }

            // 리뷰가 list_review에 없으면 다른 셀렉터 시도
            if (results.length === 0) {
                const altItems = document.querySelectorAll(
                    ".review_detail, .inner_review, [class*='review'] li"
                );
                for (const el of altItems) {
                    const text = el.querySelector(".desc_review, .wrap_review, a.link_review");
                    if (text) {
                        const t = text.textContent.trim();
                        if (t.length >= 5) {
                            let rating = 0;
                            const s = el.querySelector(".num_star");
                            if (s) rating = parseFloat(s.textContent.trim()) || 0;

                            let date = "";
                            const dm = el.textContent.match(/(\\d{4}\\.\\d{2}\\.\\d{2})/);
                            if (dm) date = dm[1];

                            results.push({ review_text: t, rating, date });
                        }
                    }
                }
            }

            return results;
        })()
    ''')
    return raw


# ═══════════════════════════════════════
# Phase 3 — 메인 파이프라인
# ═══════════════════════════════════════

async def main():
    hospitals = load_hospitals()
    all_reviews = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        logger.info("=" * 60)
        logger.info(f"  리뷰 크롤링 시작 ({len(hospitals)}곳)")
        logger.info(f"  시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)

        # ── Phase 1: Place ID 확보 ──
        logger.info("[Phase 1] Place ID 확보")
        pbar1 = tqdm(total=len(hospitals), desc="[Phase 1] Place ID", unit="곳")

        for h in hospitals:
            pid = await resolve_place_id(page, h["name"])
            h["place_id"] = pid or ""
            pbar1.update(1)
            await random_delay(0.3, 1.0)

        pbar1.close()
        resolved = sum(1 for h in hospitals if h["place_id"])
        logger.info(f"Place ID 확보: {resolved}/{len(hospitals)}곳")

        # ── Phase 2: 리뷰 크롤링 ──
        logger.info("[Phase 2] 리뷰 크롤링")
        pbar2 = tqdm(total=resolved, desc="[Phase 2] 리뷰 수집", unit="곳")

        for h in hospitals:
            pid = h.get("place_id", "")
            if not pid:
                continue

            hospital_id = int(h["id"])
            hospital_name = h["name"]

            try:
                raw = await crawl_reviews(page, pid, max_clicks=50)
                count = 0
                for rev in raw:
                    cleaned_text = clean_review(rev.get("review_text", ""))
                    if cleaned_text:
                        all_reviews.append({
                            "hospital_id": hospital_id,
                            "hospital_name": hospital_name,
                            "review_text": cleaned_text,
                            "date": rev.get("date", ""),
                            "rating": rev.get("rating", 0),
                        })
                        count += 1

                logger.info(
                    f"[{hospital_id:>3}] {hospital_name}: "
                    f"{count}건 (누적 {len(all_reviews)}건)"
                )
            except Exception as e:
                logger.error(f"[{hospital_id:>3}] {hospital_name}: 실패 — {e}")

            pbar2.update(1)
            await random_delay(0.5, 1.5)

        pbar2.close()
        await browser.close()

    # ── Phase 3: 중복 제거 + JSON 저장 ──
    logger.info(f"[Phase 3] 클렌징 (원본: {len(all_reviews)}건)")

    seen = set()
    final = []
    for rev in all_reviews:
        key = (rev["hospital_id"], rev["review_text"][:80])
        if key not in seen:
            seen.add(key)
            final.append(rev)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    hospital_coverage = len({r["hospital_id"] for r in final})
    logger.info(f"저장 완료: {OUTPUT_JSON}")
    logger.info(f"최종 리뷰: {len(final)}건 / 병원 커버리지: {hospital_coverage}곳")

    print(f"\n{'='*60}")
    print(f"  크롤링 완료!")
    print(f"  총 리뷰: {len(final)}건")
    print(f"  병원 커버리지: {hospital_coverage}곳")
    print(f"  저장: {OUTPUT_JSON}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
