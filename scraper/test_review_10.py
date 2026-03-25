"""10곳만 빠르게 테스트하는 스크립트"""

import asyncio
import csv
import json
import random
import re
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError as PwTimeout

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
INPUT_CSV = DATA_DIR / "hospitals_base.csv"

EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]", flags=re.UNICODE)
PHONE_RE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")
MULTI_SPACE_RE = re.compile(r"\s+")
MIN_LENGTH = 10


def clean_review(text):
    if not text:
        return None
    text = EMOJI_RE.sub("", text)
    text = PHONE_RE.sub("", text)
    text = MULTI_SPACE_RE.sub(" ", text).strip()
    return text if len(text) >= MIN_LENGTH else None


async def main():
    # 첫 10곳만 로드
    hospitals = []
    with open(INPUT_CSV, encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f)):
            if i >= 10:
                break
            hospitals.append(row)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        total_reviews = 0

        for h in hospitals:
            name = h["name"]
            print(f"\n--- {h['id']}. {name} ---")

            # 1) Place ID 확보
            url = f"https://map.kakao.com/?q={quote(name)}"
            await page.goto(url, wait_until="networkidle", timeout=20000)
            await asyncio.sleep(1)
            si = await page.query_selector("#search\\.keyword\\.query")
            if si:
                await si.fill(name)
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)

            pids = await page.evaluate('''
                (() => {
                    const ids = new Set();
                    document.querySelectorAll("a").forEach(a => {
                        const m = (a.href || "").match(/place\\.map\\.kakao\\.com\\/(\\d+)/);
                        if (m) ids.add(m[1]);
                    });
                    return [...ids];
                })()
            ''')

            if not pids:
                print("  Place ID 없음, 스킵")
                continue

            pid = pids[0]
            print(f"  Place ID: {pid}")

            # 2) 플레이스 페이지로 이동
            await page.goto(f"https://place.map.kakao.com/{pid}", wait_until="networkidle", timeout=25000)
            await asyncio.sleep(2)

            # 후기 탭 클릭
            await page.evaluate('''
                (() => {
                    const tabs = document.querySelectorAll("a.link_tab, a, button");
                    for (const t of tabs) {
                        if (t.textContent.trim().includes("후기") && !t.textContent.includes("블로그")) {
                            t.click();
                            return;
                        }
                    }
                })()
            ''')
            await asyncio.sleep(2)

            # 더보기 클릭 (최대 5회)
            for click_num in range(5):
                clicked = await page.evaluate('''
                    (() => {
                        const section = document.querySelector(".section_review, .group_review");
                        if (section) {
                            const btn = section.querySelector("a.link_more, a.btn_comm, button.btn_comm");
                            if (btn && btn.offsetParent !== null) {
                                btn.click();
                                return true;
                            }
                        }
                        // 일반 더보기
                        const btns = document.querySelectorAll("a, button");
                        for (const b of btns) {
                            const t = b.textContent.trim();
                            if (t.includes("후기") && t.includes("더보기") && b.offsetParent !== null) {
                                b.click();
                                return true;
                            }
                        }
                        return false;
                    })()
                ''')
                if not clicked:
                    break
                await asyncio.sleep(random.uniform(0.8, 1.5))

            # 리뷰 추출
            raw = await page.evaluate('''
                (() => {
                    const results = [];
                    const items = document.querySelectorAll("ul.list_review > li");
                    for (const li of items) {
                        let text = "";
                        const desc = li.querySelector(".desc_review");
                        if (desc) text = desc.textContent.trim();
                        else {
                            const wrap = li.querySelector(".wrap_review, a.link_review");
                            if (wrap) text = wrap.textContent.trim();
                        }

                        let rating = 0;
                        const star = li.querySelector(".num_star");
                        if (star) rating = parseFloat(star.textContent.trim()) || 0;

                        let date = "";
                        const info = li.querySelector(".info_review, .area_review");
                        if (info) {
                            const dm = info.textContent.match(/(\\d{4}\\.\\d{2}\\.\\d{2})/);
                            if (dm) date = dm[1];
                        }

                        if (text.length >= 5) results.push({text, rating, date});
                    }
                    return results;
                })()
            ''')

            count = 0
            for r in raw:
                cleaned = clean_review(r["text"])
                if cleaned:
                    count += 1

            total_reviews += count
            print(f"  리뷰: {count}건 (원본 {len(raw)}건), 누적: {total_reviews}건")

            # 첫 3개 리뷰 미리보기
            for r in raw[:3]:
                cleaned = clean_review(r["text"])
                if cleaned:
                    preview = cleaned[:80] + ("..." if len(cleaned) > 80 else "")
                    print(f"    [{r['rating']}] {r['date']} {preview}")

            await asyncio.sleep(random.uniform(0.5, 1.5))

        await browser.close()

    print(f"\n총 리뷰: {total_reviews}건")


if __name__ == "__main__":
    asyncio.run(main())
