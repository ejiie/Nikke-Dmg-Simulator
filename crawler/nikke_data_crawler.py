"""
NIKKE Data Crawler v5
니케 블라블라(blablalink.com) 시프티패드에서 종합 게임 데이터 수집

수집 항목:
  1. 현재 싱크로 레벨, 체력, 공격력, 방어력
  2. 400레벨 기준 체력, 공격력, 방어력
  3. 장비 오버로드 옵션  {"옵션명": 합산수치, ...}
  4. 하모니 큐브 효과 (전투 기준)
  5. 소장품 효과
  6. 스킬 레벨/설명/레벨당 수치, 속성, 클래스, 버스트 단계, 기업, 전투력

실행:
  python crawler/nikke_data_crawler.py
  → Blabla UID 입력 → 브라우저에서 로그인 → 자동 크롤링
  → nikke_data_raw.json 저장
"""

import asyncio
import json
import base64
from playwright.async_api import async_playwright, Page

# ═══════════════════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════════════════

BASE_DOMAIN = "https://www.blablalink.com"
API_DOMAIN  = "api.blablalink.com"

# 큐브 섹션 후보 경로 (발견되면 루프 중단)
CUBE_PATHS = [
    "cube",
    "harmony-cube",
    "cubes",
    "equipment",
    "equipment/cube",
]

# 소장품 섹션 후보 경로
SOUVENIR_PATHS = [
    "souvenir",
    "collection",
    "pilgrim",
    "pilgrimage",
    "collectibles",
    "mementos",
    "trophy",
]

# 니케 상세 페이지 URL 패턴 후보
NIKKE_DETAIL_PATTERNS = [
    "nikke-list/{id}",
    "nikke-detail/{id}",
    "nikke/{id}",
    "nikke-detail?id={id}",
]

# ═══════════════════════════════════════════════════════
# URL 유틸
# ═══════════════════════════════════════════════════════

def encode_uid(uid: str) -> str:
    return base64.b64encode(f"29080-{uid}".encode()).decode()


def build_url(uid: str, path: str = "nikke-list") -> str:
    enc = encode_uid(uid)
    if "?" in path:
        # 이미 쿼리 파라미터가 있는 경우
        return f"{BASE_DOMAIN}/shiftyspad/{path}&uid={enc}&openid={enc}"
    return f"{BASE_DOMAIN}/shiftyspad/{path}?uid={enc}&openid={enc}"


def build_login_url(uid: str) -> str:
    target = build_url(uid)
    return f"{BASE_DOMAIN}/login?to={target}&back_to={target}"


# ═══════════════════════════════════════════════════════
# 데이터 수집기
# ═══════════════════════════════════════════════════════

class DataCollector:
    def __init__(self):
        self.responses: list[dict] = []
        self.login_done   = asyncio.Event()
        self.nikkes_loaded = asyncio.Event()

    async def on_response(self, response):
        if API_DOMAIN not in response.url:
            return

        try:
            text = await response.text()
            try:
                body = json.loads(text)
            except Exception:
                body = text
        except Exception as e:
            body = f"[읽기 실패: {e}]"

        endpoint = response.url.split("?")[0].rstrip("/").split("/")[-1]
        code = body.get("code", "?") if isinstance(body, dict) else "?"
        msg  = body.get("msg",  "") if isinstance(body, dict) else ""

        self.responses.append({
            "endpoint": endpoint,
            "url":      response.url,
            "method":   response.request.method,
            "status":   response.status,
            "req_body": response.request.post_data,
            "res_body": body,
        })

        tag = "✅" if code == 0 else "❌"
        print(f"    {tag} [{endpoint}] code={code} {str(msg)[:60]}")

        if "CheckLogin" in response.url and code == 0:
            self.login_done.set()
        if "GetNikkesOrder" in response.url and code == 0:
            self.nikkes_loaded.set()

    def find(self, keyword: str) -> list[dict]:
        kw = keyword.lower()
        return [r for r in self.responses if kw in r["url"].lower()]

    def extract_nikke_ids(self) -> list[str]:
        """GetNikkesOrder 응답에서 니케 ID 목록 추출"""
        ids: list[str] = []
        for r in self.find("GetNikkesOrder"):
            body = r.get("res_body", {})
            if not isinstance(body, dict) or body.get("code") != 0:
                continue
            data = body.get("data", {})

            # 응답 구조가 list 또는 dict 안의 list
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                for key in ["list", "nikke_list", "nikkes", "characters",
                            "items", "data", "nikkeList", "charList"]:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break

            for item in items:
                if not isinstance(item, dict):
                    continue
                nid = (item.get("id")
                       or item.get("nikke_id")
                       or item.get("char_id")
                       or item.get("character_id")
                       or item.get("charId"))
                if nid and str(nid) not in ids:
                    ids.append(str(nid))

        return ids


# ═══════════════════════════════════════════════════════
# 페이지 헬퍼
# ═══════════════════════════════════════════════════════

async def safe_goto(page: Page, url: str, timeout: int = 12000) -> bool:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        print(f"      ✗ {url.split('?')[0].split('/')[-2:]}: {type(e).__name__}")
        return False


async def scroll_page(page: Page, steps: int = 8, delay_ms: int = 500):
    for _ in range(steps):
        await page.evaluate("window.scrollBy(0, 600)")
        await page.wait_for_timeout(delay_ms)
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(800)


async def find_and_click_nikkes(page: Page, max_items: int = 30) -> int:
    """
    UI에서 니케 카드를 찾아 클릭.
    클릭 성공 수를 반환.
    """
    selectors = [
        ".nikke-card",
        ".character-card",
        "[class*='NikkeCard']",
        "[class*='CharacterItem']",
        "[class*='nikke-item']",
        "[class*='char-item']",
        "li[class*='nikke']",
        ".list-item",
        "[data-nikke-id]",
        "[data-char-id]",
    ]
    for selector in selectors:
        try:
            elements = await page.query_selector_all(selector)
        except Exception:
            continue
        if not elements:
            continue

        print(f"      → '{selector}' 로 {len(elements)}개 발견 → 클릭 시작")
        clicked = 0
        for elem in elements[:max_items]:
            try:
                await elem.scroll_into_view_if_needed()
                await elem.click()
                await page.wait_for_timeout(1500)
                clicked += 1
            except Exception:
                pass
        return clicked

    return 0


# ═══════════════════════════════════════════════════════
# 메인 크롤러
# ═══════════════════════════════════════════════════════

async def crawl(uid: str, headless: bool = False) -> dict:
    collector  = DataCollector()
    target_url = build_url(uid)
    login_url  = build_login_url(uid)
    enc        = encode_uid(uid)

    print(f"\n{'='*70}")
    print(f"🔑 Login : {login_url[:90]}...")
    print(f"🎯 Target: {target_url[:90]}...")
    print(f"{'='*70}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport=None,
        )
        page = await context.new_page()
        page.on(
            "response",
            lambda r: asyncio.ensure_future(collector.on_response(r)),
        )

        # ──────────────────────────────────────────────
        # Phase 1 : 로그인
        # ──────────────────────────────────────────────
        print("┌─ [Phase 1] 로그인")
        await page.goto(login_url, wait_until="domcontentloaded")
        print("│  ⏳ 직접 로그인해 주세요 (최대 120초)...")

        try:
            await asyncio.wait_for(collector.login_done.wait(), timeout=120)
            print("│  ✅ 로그인 성공!")
        except asyncio.TimeoutError:
            print("│  ⚠️  타임아웃 — 강제 진행")

        await page.wait_for_timeout(2000)
        print("└─ 완료\n")

        # ──────────────────────────────────────────────
        # Phase 2 : 니케 목록 (메인 데이터)
        # ──────────────────────────────────────────────
        print("┌─ [Phase 2] 니케 목록 로딩")
        if "nikke-list" not in page.url:
            print(f"│  → 목표 페이지로 이동...")
            await page.goto(target_url, wait_until="domcontentloaded")

        try:
            await asyncio.wait_for(collector.nikkes_loaded.wait(), timeout=30)
            print("│  ✅ GetNikkesOrder 수신 완료!")
        except asyncio.TimeoutError:
            print("│  ⚠️  GetNikkesOrder 미수신 — 대기 연장 (10초)")
            await page.wait_for_timeout(10000)

        # 지연 로딩 유발 (스크롤)
        print("│  → 스크롤 (지연 로딩 유발)...")
        await scroll_page(page, steps=10, delay_ms=500)
        print("└─ 완료\n")

        # ──────────────────────────────────────────────
        # Phase 3 : 개별 니케 상세 (스킬·오버로드·기본수치)
        # ──────────────────────────────────────────────
        print("┌─ [Phase 3] 니케 상세 데이터 수집")
        nikke_ids = collector.extract_nikke_ids()

        if nikke_ids:
            print(f"│  니케 ID {len(nikke_ids)}개 발견 → 상세 페이지 순회")
            for nid in nikke_ids:
                success = False
                for pattern in NIKKE_DETAIL_PATTERNS:
                    path = pattern.replace("{id}", nid)
                    url  = build_url(uid, path)
                    if await safe_goto(page, url, timeout=10000):
                        success = True
                        break
                if not success:
                    print(f"│    ✗ 니케 ID {nid}: 모든 패턴 실패")
                await page.wait_for_timeout(800)

        else:
            print("│  ⚠️  ID 없음 — UI 클릭으로 시도")
            clicked = await find_and_click_nikkes(page)
            if clicked == 0:
                print("│  ⚠️  클릭 가능한 니케 없음")

        # 목록 페이지로 복귀
        await safe_goto(page, target_url, timeout=15000)
        await page.wait_for_timeout(1000)
        print("└─ 완료\n")

        # ──────────────────────────────────────────────
        # Phase 4 : 하모니 큐브
        # ──────────────────────────────────────────────
        print("┌─ [Phase 4] 하모니 큐브")
        found_cube = False
        for path in CUBE_PATHS:
            url = build_url(uid, path)
            print(f"│  → /{path} 시도...")
            if await safe_goto(page, url, timeout=10000):
                await page.wait_for_timeout(3000)
                await scroll_page(page, steps=4, delay_ms=400)
                # 현재 URL에 해당 경로가 포함되면 성공으로 간주
                if any(seg in page.url for seg in path.split("/")):
                    print(f"│  ✅ 큐브 섹션 발견: /{path}")
                    found_cube = True
                    break
        if not found_cube:
            print("│  ⚠️  큐브 섹션 URL 미발견 (API 응답에서 확인 필요)")
        print("└─ 완료\n")

        # ──────────────────────────────────────────────
        # Phase 5 : 소장품
        # ──────────────────────────────────────────────
        print("┌─ [Phase 5] 소장품")
        found_souvenir = False
        for path in SOUVENIR_PATHS:
            url = build_url(uid, path)
            print(f"│  → /{path} 시도...")
            if await safe_goto(page, url, timeout=10000):
                await page.wait_for_timeout(3000)
                await scroll_page(page, steps=4, delay_ms=400)
                if path in page.url:
                    print(f"│  ✅ 소장품 섹션 발견: /{path}")
                    found_souvenir = True
                    break
        if not found_souvenir:
            print("│  ⚠️  소장품 섹션 URL 미발견 (API 응답에서 확인 필요)")
        print("└─ 완료\n")

        # ──────────────────────────────────────────────
        # Phase 6 : 스토리지 스냅샷
        # ──────────────────────────────────────────────
        print("┌─ [Phase 6] 스토리지 스냅샷")
        try:
            ls = await page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))"
            )
            ss = await page.evaluate(
                "() => Object.fromEntries(Object.entries(sessionStorage))"
            )
            print(f"│  localStorage  : {len(ls)}개 키")
            print(f"│  sessionStorage: {len(ss)}개 키")
        except Exception as e:
            print(f"│  ⚠️  스토리지 캡처 실패: {e}")
            ls, ss = {}, {}

        idb = await page.evaluate("""
        async () => {
            return new Promise(resolve => {
                const req = indexedDB.open("__ss_index_db_name");
                req.onsuccess = e => {
                    const db     = e.target.result;
                    const stores = Array.from(db.objectStoreNames);
                    if (!stores.length) return resolve({ stores, data: [] });
                    const tx  = db.transaction(stores[0], "readonly");
                    const all = tx.objectStore(stores[0]).getAll();
                    all.onsuccess = () => resolve({ stores, data: all.result });
                    all.onerror   = () => resolve({ stores, data: [] });
                };
                req.onerror = () => resolve({ stores: [], data: [] });
            });
        }
        """)
        print(f"│  IndexedDB stores: {idb.get('stores')}")
        print("└─ 완료\n")

        await browser.close()

    return {
        "uid":            uid,
        "responses":      collector.responses,
        "localStorage":   ls,
        "sessionStorage": ss,
        "indexedDB":      idb,
    }


# ═══════════════════════════════════════════════════════
# 저장 & 요약
# ═══════════════════════════════════════════════════════

def save_result(result: dict, out_path: str = "nikke_data_raw.json"):
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"💾 저장 완료: {out_path}")


def print_summary(result: dict):
    responses = result.get("responses", [])
    print(f"\n{'='*70}")
    print(f"📊 캡처 요약  |  총 {len(responses)}개 API 응답")
    print(f"{'='*70}")

    # 엔드포인트별 통계
    stats: dict[str, dict] = {}
    for r in responses:
        ep = r.get("endpoint", "unknown")
        body = r.get("res_body", {})
        code = body.get("code", "?") if isinstance(body, dict) else "?"
        if ep not in stats:
            stats[ep] = {"total": 0, "ok": 0}
        stats[ep]["total"] += 1
        if code == 0:
            stats[ep]["ok"] += 1

    for ep, s in sorted(stats.items()):
        mark = "✅" if s["ok"] > 0 else "❌"
        print(f"  {mark} {ep:<35} {s['ok']}/{s['total']}")

    # 핵심 엔드포인트 데이터 미리보기
    key_endpoints = [
        "GetNikkesOrder",
        "GetNikkeDetail",
        "GetNikkeSkillInfo",
        "GetNikkeEquip",
        "GetCube",
        "GetSouvenir",
        "GetHarmonyCube",
        "GetCollection",
    ]
    print()
    for kw in key_endpoints:
        hits = [r for r in responses if kw.lower() in r.get("url", "").lower()]
        if not hits:
            continue
        body = hits[-1].get("res_body", {})
        if not isinstance(body, dict) or body.get("code") != 0:
            continue
        data = body.get("data", {})
        if isinstance(data, list):
            preview = f"list({len(data)}개)"
        elif isinstance(data, dict):
            preview = f"dict keys={list(data.keys())[:6]}"
        else:
            preview = str(data)[:60]
        print(f"  📦 {kw}: {preview}")

    print(f"\n  localStorage  : {len(result.get('localStorage', {}))}개 키")
    print(f"  sessionStorage: {len(result.get('sessionStorage', {}))}개 키")
    idb_data = result.get("indexedDB", {}).get("data", [])
    print(f"  IndexedDB     : {len(idb_data)}개 레코드")


# ═══════════════════════════════════════════════════════
# 진입점
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    uid = input("Blabla UID 입력: ").strip()
    if not uid:
        print("❌ UID를 입력해야 합니다.")
        exit(1)

    result = asyncio.run(crawl(uid, headless=False))
    save_result(result, "nikke_data_raw.json")
    print_summary(result)
