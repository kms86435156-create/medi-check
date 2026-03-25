"""
DAY 1 — 강남/신논현 피부과 스크래핑 (카카오맵)
Playwright 헤드리스 모드로 카카오맵에서 피부과 정보를 수집합니다.
"""

import asyncio
import random
import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from tqdm import tqdm

# 프로젝트 루트 기준 data 폴더
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

OUTPUT_CSV = DATA_DIR / "hospitals_base.csv"

# 다양한 키워드로 300곳 이상 확보
KEYWORDS = [
    "강남역 피부과",
    "신논현역 피부과",
    "강남구 피부과",
    "역삼역 피부과",
    "선릉역 피부과",
    "논현역 피부과",
    "압구정 피부과",
    "삼성역 피부과",
    "학동역 피부과",
    "신사역 피부과",
    "강남 성형외과 피부과",
    "서초 피부과",
    "양재역 피부과",
    "도곡역 피부과",
    "대치동 피부과",
    "청담동 피부과",
    "잠실역 피부과",
    "교대역 피부과",
    "방배동 피부과",
    "반포 피부과",
    "개포동 피부과",
    "일원동 피부과",
    "수서역 피부과",
    "한티역 피부과",
    "매봉역 피부과",
    "강남 레이저 피부과",
    "강남 미용 피부과",
    "서초구 피부 클리닉",
    "강남 피부과 의원",
    "테헤란로 피부과",
    "봉은사역 피부과",
    "강남 피부 관리",
    "서초동 피부과",
    "잠원동 피부과",
    "논현동 피부과",
    "역삼동 피부과",
    "삼성동 피부과",
    "신사동 피부과",
    "청담역 피부과",
    "압구정역 피부과",
    "강남 아토피 피부과",
    "강남 여드름 피부과",
]

MAX_RETRIES = 2


async def random_delay(min_s=1.0, max_s=3.0):
    """차단 방지를 위한 랜덤 딜레이"""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def js_click(page, selector):
    """JavaScript로 직접 클릭 (visibility 체크 우회)"""
    await page.evaluate(f'document.querySelector("{selector}")?.click()')


async def extract_page_items(page, collected_names):
    """현재 페이지의 검색 결과 목록에서 병원 정보를 추출합니다."""
    results = []

    items = await page.query_selector_all("#info\\.search\\.place\\.list > li")
    if not items:
        return results

    for item in items:
        try:
            # 병원명
            name_el = await item.query_selector(".head_item .tit_name .link_name")
            if not name_el:
                name_el = await item.query_selector(".head_item .tit_name")
            name = (await name_el.inner_text()).strip() if name_el else ""

            if not name or name in collected_names:
                continue

            # data-id (카카오 place ID)
            data_id = await item.get_attribute("data-id")

            # 전화번호
            phone = ""
            phone_el = await item.query_selector(".contact .phone")
            if not phone_el:
                phone_el = await item.query_selector("[class*='phone']")
            if phone_el:
                phone = (await phone_el.inner_text()).strip()

            # 주소
            addr = ""
            addr_el = await item.query_selector(".addr p[data-id='address']")
            if not addr_el:
                addr_el = await item.query_selector(".addr")
            if addr_el:
                addr = (await addr_el.inner_text()).strip()
                addr = addr.split("\n")[0].strip()

            # 진료시간
            hours = ""
            hours_el = await item.query_selector(".openhour .txt_operation")
            if not hours_el:
                hours_el = await item.query_selector("[class*='hour']")
            if hours_el:
                hours = (await hours_el.inner_text()).strip()
                # 줄바꿈을 구분자로 변환
                hours = hours.replace("\n", " | ")

            # 카카오 플레이스 URL
            place_url = ""
            if data_id:
                place_url = f"https://place.map.kakao.com/{data_id}"

            results.append({
                "name": name,
                "phone": phone,
                "address": addr,
                "hours": hours,
                "place_url": place_url,
            })
            collected_names.add(name)

        except Exception:
            continue

    return results


async def get_first_item_name(page):
    """현재 목록의 첫 번째 항목 이름을 반환 (페이지 변경 감지용)"""
    try:
        first = await page.query_selector("#info\\.search\\.place\\.list > li:first-child .link_name")
        if first:
            return (await first.inner_text()).strip()
    except Exception:
        pass
    return ""


async def wait_for_list_change(page, old_first_name, timeout=8):
    """목록이 변경될 때까지 대기합니다."""
    for _ in range(int(timeout / 0.5)):
        new_name = await get_first_item_name(page)
        if new_name and new_name != old_first_name:
            return True
        await asyncio.sleep(0.5)
    return False


async def extract_from_kakao(page, keyword, pbar, collected, collected_names, limit):
    """카카오맵에서 검색 결과를 페이지별로 순회하며 추출합니다."""
    encoded = quote(keyword)
    url = f"https://map.kakao.com/?q={encoded}"
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await random_delay(2, 4)

    # "장소" 탭 클릭 (검색 결과가 장소 탭이 아닐 수 있음)
    try:
        place_tab = await page.query_selector("#info\\.main\\.options .option1 a")
        if place_tab:
            await place_tab.click()
            await random_delay(1, 2)
    except Exception:
        pass

    total_pages_scraped = 0
    max_pages = 5  # 카카오맵은 키워드당 최대 5페이지 (약 75곳)

    while len(collected) < limit and total_pages_scraped < max_pages:
        # 검색 결과 목록 대기
        try:
            await page.wait_for_selector("#info\\.search\\.place\\.list", timeout=10000)
        except PwTimeout:
            break

        # 현재 목록 첫 번째 항목 이름 기록 (변경 감지용)
        old_first = await get_first_item_name(page)

        # 현재 페이지에서 추출
        new_items = await extract_page_items(page, collected_names)
        for item in new_items:
            if len(collected) >= limit:
                break
            item["id"] = len(collected) + 1
            collected.append(item)
            pbar.update(1)

        total_pages_scraped += 1

        if len(collected) >= limit:
            break

        # 다음 페이지로 이동 시도
        moved = await go_to_next_page(page, total_pages_scraped)
        if not moved:
            break

        # 목록이 실제로 갱신될 때까지 대기
        changed = await wait_for_list_change(page, old_first)
        if not changed:
            break
        await random_delay(1, 2)


async def go_to_next_page(page, current_page_index):
    """카카오맵 페이지네이션을 JavaScript로 처리합니다."""
    # current_page_index: 1-based, 이미 본 페이지 수
    next_page = current_page_index + 1  # 이동할 페이지 번호 (1~5 범위)

    # 같은 그룹 내 다음 페이지 (2, 3, 4, 5)
    if next_page <= 5:
        try:
            clicked = await page.evaluate(f'''
                (() => {{
                    const el = document.querySelector("#info\\.search\\.page\\.no{next_page}");
                    if (el && el.textContent.trim() !== "") {{
                        el.click();
                        return true;
                    }}
                    return false;
                }})()
            ''')
            if clicked:
                return True
        except Exception:
            pass

    # 다음 그룹 버튼 (>) 클릭 시도
    try:
        clicked = await page.evaluate('''
            (() => {
                const el = document.querySelector("#info\\.search\\.page\\.next");
                if (el && !el.classList.contains("disabled")) {
                    el.click();
                    return true;
                }
                return false;
            })()
        ''')
        if clicked:
            return True
    except Exception:
        pass

    return False


async def enrich_details(page, hospital, pbar_detail):
    """개별 병원 상세 페이지에서 진료시간 등 추가 정보를 수집합니다."""
    if not hospital.get("place_url") or hospital["place_url"] == "#none":
        pbar_detail.update(1)
        return

    for attempt in range(MAX_RETRIES + 1):
        try:
            await page.goto(hospital["place_url"], wait_until="networkidle", timeout=20000)
            await random_delay(1, 2)

            # 진료시간
            if not hospital["hours"]:
                for sel in [".openhour_wrap .fold_floor",
                            "[class*='OperationInfo'] .txt_operation",
                            ".location_detail .detail_operate",
                            ".placeinfo_default .openhour"]:
                    hours_el = await page.query_selector(sel)
                    if hours_el:
                        hospital["hours"] = (await hours_el.inner_text()).strip().replace("\n", " | ")
                        break

            # 전화번호 보완
            if not hospital["phone"]:
                for sel in [".contact .txt_contact", "span.phone",
                            ".placeinfo_default .phone"]:
                    phone_el = await page.query_selector(sel)
                    if phone_el:
                        hospital["phone"] = (await phone_el.inner_text()).strip()
                        break

            # 주소 보완
            if not hospital["address"]:
                for sel in [".location_detail .txt_address",
                            ".placeinfo_default .txt_address"]:
                    addr_el = await page.query_selector(sel)
                    if addr_el:
                        hospital["address"] = (await addr_el.inner_text()).strip()
                        break

            break

        except (PwTimeout, Exception):
            if attempt < MAX_RETRIES:
                await random_delay(2, 4)
            continue

    pbar_detail.update(1)


async def scrape_hospitals(keyword="강남 피부과", limit=300):
    """
    메인 스크래핑 함수
    - keyword: 검색 키워드 (여러 키워드를 순회)
    - limit: 수집 목표 수
    """
    collected = []
    collected_names = set()  # 중복 방지용

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

        print(f"\n{'='*60}")
        print(f"  피부과 스크래핑 시작 (목표: {limit}곳)")
        print(f"  시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        # --- Phase 1: 검색 결과에서 기본 정보 수집 ---
        pbar = tqdm(total=limit, desc="[Phase 1] 병원 목록 수집", unit="곳")

        for kw in KEYWORDS:
            if len(collected) >= limit:
                break
            print(f"\n  검색 키워드: '{kw}'")
            before = len(collected)
            for attempt in range(MAX_RETRIES + 1):
                try:
                    await extract_from_kakao(page, kw, pbar, collected, collected_names, limit)
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        print(f"  재시도 {attempt + 1}/{MAX_RETRIES}: {e}")
                        await random_delay(3, 5)
                    else:
                        print(f"  키워드 '{kw}' 스킵: {e}")
            after = len(collected)
            print(f"  → {after - before}곳 신규 수집 (누적: {after}곳)")

        pbar.close()

        # --- Phase 2: 상세 페이지에서 추가 정보 보강 ---
        missing_detail = [h for h in collected if not h["hours"] or not h["phone"]]
        if missing_detail:
            print(f"\n  상세 정보 보강 대상: {len(missing_detail)}곳")
            pbar_detail = tqdm(total=len(missing_detail), desc="[Phase 2] 상세 정보 보강", unit="곳")
            for hospital in missing_detail:
                await enrich_details(page, hospital, pbar_detail)
                await random_delay(0.5, 1.5)
            pbar_detail.close()

        await browser.close()

    # --- ID 재정렬 ---
    for i, h in enumerate(collected, 1):
        h["id"] = i

    print(f"\n  총 {len(collected)}곳 수집 완료!")
    return collected


def save_to_csv(hospitals, output_path=OUTPUT_CSV):
    """수집 결과를 CSV로 저장합니다."""
    fieldnames = ["id", "name", "phone", "address", "hours", "place_url"]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(hospitals)

    print(f"  CSV 저장 완료: {output_path}")
    print(f"  총 {len(hospitals)}행")


async def main():
    hospitals = await scrape_hospitals(limit=300)
    save_to_csv(hospitals)


if __name__ == "__main__":
    asyncio.run(main())
