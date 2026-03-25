"""카카오 플레이스 상세 페이지 리뷰 DOM 구조 탐색"""

import asyncio
from playwright.async_api import async_playwright


async def main():
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

        # 1) 카카오맵에서 검색 후 Place ID 추출
        from urllib.parse import quote
        name = "이지함피부과의원 강남점"
        url = f"https://map.kakao.com/?q={quote(name)}"
        await page.goto(url, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2)

        # 검색 입력 + Enter
        si = await page.query_selector("#search\\.keyword\\.query")
        if si:
            await si.fill(name)
            await page.keyboard.press("Enter")
            await asyncio.sleep(3)

        # 링크에서 place ID 추출
        place_ids = await page.evaluate('''
            (() => {
                const links = document.querySelectorAll("a");
                const ids = new Set();
                for (const l of links) {
                    const m = (l.href || "").match(/place\\.map\\.kakao\\.com\\/(\\d+)/);
                    if (m) ids.add(m[1]);
                }
                return [...ids];
            })()
        ''')
        print(f"Place IDs: {place_ids}")
        if not place_ids:
            print("No place IDs found!")
            await browser.close()
            return

        place_id = place_ids[0]

        # 2) 카카오 플레이스 상세 페이지로 이동
        place_url = f"https://place.map.kakao.com/{place_id}"
        print(f"\nNavigating to: {place_url}")
        await page.goto(place_url, wait_until="networkidle", timeout=25000)
        await asyncio.sleep(3)

        # 3) 페이지 전체 구조 분석
        analysis = await page.evaluate('''
            (() => {
                const result = {
                    title: document.title,
                    url: location.href,
                };

                // 모든 탭/메뉴 항목
                const tabs = [];
                document.querySelectorAll("a, button").forEach(el => {
                    const t = el.textContent.trim();
                    if (t && t.length < 20 && (
                        t.includes("후기") || t.includes("리뷰") ||
                        t.includes("평가") || t.includes("사진") ||
                        t.includes("메뉴") || t.includes("정보") ||
                        t.includes("홈")
                    )) {
                        tabs.push({tag: el.tagName, text: t, cls: el.className, id: el.id});
                    }
                });
                result.tabs = tabs;

                // 리뷰 관련 섹션 찾기
                const sections = {};
                ["section", "div", "ul"].forEach(tag => {
                    document.querySelectorAll(tag).forEach(el => {
                        const cls = el.className || "";
                        const id = el.id || "";
                        if (cls.includes("review") || cls.includes("comment") ||
                            cls.includes("evaluation") || id.includes("review") ||
                            id.includes("comment")) {
                            const key = `${tag}.${cls || id}`;
                            if (!sections[key]) {
                                sections[key] = {
                                    childCount: el.children.length,
                                    textLen: el.textContent.length,
                                    preview: el.innerHTML.substring(0, 300)
                                };
                            }
                        }
                    });
                });
                result.reviewSections = sections;

                // 별점/점수 관련
                const scores = [];
                document.querySelectorAll("[class*='star'], [class*='score'], [class*='rate'], [class*='grade']").forEach(el => {
                    scores.push({
                        cls: el.className,
                        text: el.textContent.trim().substring(0, 50)
                    });
                });
                result.scores = scores.slice(0, 10);

                // 더보기 버튼
                const moreButtons = [];
                document.querySelectorAll("button, a, span").forEach(el => {
                    const t = el.textContent.trim();
                    if (t.includes("더보기") || t.includes("더 보기") || t === "more" || el.className.includes("more")) {
                        moreButtons.push({tag: el.tagName, text: t.substring(0, 30), cls: el.className});
                    }
                });
                result.moreButtons = moreButtons;

                return result;
            })()
        ''')

        print(f"\nTitle: {analysis['title']}")
        print(f"URL: {analysis['url']}")

        print(f"\n== 탭/메뉴 ==")
        for t in analysis['tabs']:
            print(f"  {t}")

        print(f"\n== 리뷰 관련 섹션 ==")
        for key, info in analysis['reviewSections'].items():
            print(f"  {key}: children={info['childCount']}, textLen={info['textLen']}")
            print(f"    preview: {info['preview'][:200]}")

        print(f"\n== 별점/점수 ==")
        for s in analysis['scores']:
            print(f"  {s}")

        print(f"\n== 더보기 버튼 ==")
        for b in analysis['moreButtons']:
            print(f"  {b}")

        # 4) 후기/리뷰 탭 클릭 시도
        print("\n== 후기 탭 클릭 ==")
        tab_clicked = await page.evaluate('''
            (() => {
                const tabs = document.querySelectorAll("a, button");
                for (const t of tabs) {
                    if (t.textContent.trim().includes("후기")) {
                        t.click();
                        return t.textContent.trim();
                    }
                }
                return null;
            })()
        ''')
        print(f"  Clicked: {tab_clicked}")
        await asyncio.sleep(3)

        # 5) 후기 탭 클릭 후 리뷰 내용 추출
        review_data = await page.evaluate('''
            (() => {
                const reviews = [];

                // 방법 1: 리뷰 리스트 아이템들
                const listItems = document.querySelectorAll(
                    ".list_evaluation li, .review_list li, .list_comment li, " +
                    "[data-id='reviewList'] li, .evaluation_review"
                );
                for (const li of listItems) {
                    reviews.push({
                        method: "listItem",
                        text: li.textContent.trim().substring(0, 200),
                        html: li.innerHTML.substring(0, 300)
                    });
                }

                // 방법 2: 직접 텍스트 추출
                const textEls = document.querySelectorAll(
                    ".txt_comment, .review_text, .comment_text, " +
                    ".txt_review, .desc_review"
                );
                for (const el of textEls) {
                    reviews.push({
                        method: "textSelector",
                        text: el.textContent.trim().substring(0, 200),
                        cls: el.className
                    });
                }

                // 방법 3: 현재 보이는 모든 리뷰 관련 영역
                const allReviewDivs = document.querySelectorAll(
                    "[class*='review'], [class*='comment'], [class*='evaluation']"
                );
                const divSummary = [];
                for (const d of allReviewDivs) {
                    if (d.textContent.trim().length > 20) {
                        divSummary.push({
                            tag: d.tagName,
                            cls: d.className,
                            text: d.textContent.trim().substring(0, 150)
                        });
                    }
                }

                return {
                    reviewCount: reviews.length,
                    reviews: reviews.slice(0, 10),
                    divSummary: divSummary.slice(0, 10)
                };
            })()
        ''')

        print(f"\n== 리뷰 추출 결과 ==")
        print(f"Review count: {review_data['reviewCount']}")
        for r in review_data['reviews']:
            print(f"  [{r['method']}] {r['text'][:120]}")

        print(f"\n== 리뷰 관련 div ==")
        for d in review_data['divSummary']:
            print(f"  {d['tag']}.{d['cls'][:50]}: {d['text'][:100]}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
