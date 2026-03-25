"""카카오맵 검색 및 Place ID 추출 방법 탐색"""

import asyncio
from urllib.parse import quote
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

        # 방법 1: URL 파라미터로 검색
        name = "이지함피부과의원 강남점"
        url = f"https://map.kakao.com/?q={quote(name)}"
        await page.goto(url, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2)

        # 검색 입력창에 직접 입력하고 검색
        search_input = await page.query_selector("#search\\.keyword\\.query")
        if search_input:
            await search_input.fill(name)
            await page.keyboard.press("Enter")
            await asyncio.sleep(3)
            print("검색 입력 + Enter 완료")
        else:
            print("검색 입력창 못 찾음")

        # 검색 결과 확인
        result = await page.evaluate('''
            (() => {
                const list = document.querySelector("#info\\.search\\.place\\.list");
                if (!list) {
                    // 다른 가능한 리스트 셀렉터
                    const alt = document.querySelectorAll(".placelist li, #info li");
                    return {
                        error: "main list not found",
                        altCount: alt.length,
                        bodySnippet: document.body.innerHTML.substring(0, 1500)
                    };
                }

                const items = list.querySelectorAll("li");
                const data = [];
                for (let i = 0; i < Math.min(items.length, 3); i++) {
                    const li = items[i];
                    const attrs = {};
                    for (const a of li.attributes) {
                        attrs[a.name] = a.value;
                    }
                    // 모든 링크
                    const links = li.querySelectorAll("a");
                    const hrefs = [];
                    for (const l of links) {
                        if (l.href) hrefs.push({text: l.textContent.trim().substring(0, 30), href: l.href, cls: l.className});
                    }
                    data.push({
                        index: i,
                        attrs: attrs,
                        linkCount: links.length,
                        links: hrefs,
                    });
                }
                return { itemCount: items.length, items: data };
            })()
        ''')

        if "error" in result:
            print(f"Error: {result['error']}")
            print(f"Alt count: {result.get('altCount', 0)}")
            # 페이지 내 검색 관련 요소 확인
            snippet = result.get('bodySnippet', '')
            # 'info.search' 관련 요소 찾기
            import re
            ids = re.findall(r'id="([^"]*search[^"]*)"', snippet)
            print(f"Search-related IDs: {ids[:10]}")
            print(f"Body snippet (500 chars): {snippet[:500]}")
        else:
            print(f"\nItems found: {result['itemCount']}")
            for item in result['items']:
                print(f"\n--- Item {item['index']} ---")
                print(f"  Attrs: {item['attrs']}")
                for l in item['links']:
                    print(f"  Link: {l['text']} -> {l['href']} ({l['cls']})")

        # 방법 2: 직접 카카오 Local REST API 호출 시도 (비밀키 없이)
        # 페이지 내 스크립트에서 place ID 가져오기
        place_ids = await page.evaluate('''
            (() => {
                // 링크에서 place ID 추출
                const links = document.querySelectorAll("a");
                const ids = [];
                for (const l of links) {
                    const href = l.href || "";
                    const match = href.match(/place\\.map\\.kakao\\.com\\/(\\d+)/);
                    if (match) ids.push(match[1]);
                    const match2 = href.match(/place_(?:id|num)=(\\d+)/);
                    if (match2) ids.push(match2[1]);
                }
                // data-id 속성 확인
                const allEls = document.querySelectorAll("[data-id]");
                for (const el of allEls) {
                    ids.push("data-id:" + el.getAttribute("data-id"));
                }
                return [...new Set(ids)];
            })()
        ''')
        print(f"\nPlace IDs found in page: {place_ids}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
