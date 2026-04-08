"""
NIKKE 오버로드 옵션 스크래퍼
니케 블라블라 시프티패드 도감 목록에서
"필터 옆 버튼"(오버로드 뷰 전환) 클릭 후 표시되는
각 니케의 오버로드 옵션 합산 수치를 추출.

출력 형식 (overload_options.json):
{
  "5001": {
    "name": "Snow White",
    "options": {
      "우월코드 대미지": 111.04,
      "공격력": 57.82,
      "크리티컬 대미지": 65.76
    }
  },
  ...
}

실행:
  python crawler/overload_scraper.py
  → Blabla UID 입력 → 브라우저에서 로그인 → 자동 수집
  → overload_options.json 저장
"""

import asyncio
import json
import re
import base64
from playwright.async_api import async_playwright, Page

# ═══════════════════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════════════════

BASE_DOMAIN = "https://www.blablalink.com"
API_DOMAIN  = "api.blablalink.com"


def encode_uid(uid: str) -> str:
    return base64.b64encode(f"29080-{uid}".encode()).decode()


def build_url(uid: str, path: str = "nikke-list") -> str:
    enc = encode_uid(uid)
    return f"{BASE_DOMAIN}/shiftyspad/{path}?uid={enc}&openid={enc}"


def build_login_url(uid: str) -> str:
    target = build_url(uid)
    return f"{BASE_DOMAIN}/login?to={target}&back_to={target}"


# ═══════════════════════════════════════════════════════
# 값 파싱
# ═══════════════════════════════════════════════════════

def parse_value(raw: str) -> float | dict:
    """
    "111.04%"        → 111.04
    "141.97%(+426)"  → {"pct": 141.97, "count": 426}
    "+426"           → 426
    """
    raw = raw.strip()
    # 퍼센트 + 카운트: "141.97%(+426)"
    m = re.match(r"([\d.]+)%\(\+(\d+)\)", raw)
    if m:
        return {"pct": float(m.group(1)), "count": int(m.group(2))}
    # 퍼센트만: "111.04%"
    m = re.match(r"([\d.]+)%", raw)
    if m:
        return float(m.group(1))
    # 정수: "+426" 또는 숫자
    m = re.match(r"\+?(\d+)", raw)
    if m:
        return int(m.group(1))
    return raw  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════
# 오버로드 뷰 전환
# ═══════════════════════════════════════════════════════

async def activate_overload_view(page: Page) -> bool:
    """
    필터 옆 버튼을 클릭해 오버로드 옵션 뷰로 전환.
    성공 여부 반환.
    """

    # ── 1단계: 직접 셀렉터 후보 ──────────────────────────────
    direct_selectors = [
        "[data-type='overload']",
        "[data-view='overload']",
        "[aria-label*='overload']",
        "[aria-label*='오버로드']",
        "[class*='OverloadView']",
        "[class*='overload-view']",
        "[class*='EquipView']",
        "[class*='equip-view']",
        "[class*='StatView']",
    ]
    for sel in direct_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_timeout(1500)
                if await _overload_visible(page):
                    print(f"  ✅ 오버로드 뷰 버튼 클릭 (셀렉터: {sel})")
                    return True
        except Exception:
            pass

    # ── 2단계: JS — 필터 버튼 앞 형제 버튼들을 순서대로 클릭 ──
    try:
        result = await page.evaluate("""
        async () => {
            // "필터" 텍스트를 포함한 버튼 찾기
            const allBtns = Array.from(document.querySelectorAll('button, [role="button"]'));
            const filterBtn = allBtns.find(b =>
                b.textContent.trim().startsWith('필터') ||
                b.textContent.trim() === 'Filter'
            );
            if (!filterBtn) return { ok: false, reason: 'filter_not_found' };

            const parent = filterBtn.parentElement;
            const siblings = Array.from(parent.querySelectorAll('button, [role="button"]'));
            const filterIdx = siblings.indexOf(filterBtn);
            if (filterIdx <= 0) return { ok: false, reason: 'no_prev_sibling' };

            // 필터 바로 앞 버튼부터 클릭 시도
            for (let i = filterIdx - 1; i >= 0; i--) {
                siblings[i].click();
                return { ok: true, idx: i, text: siblings[i].textContent.trim() };
            }
            return { ok: false, reason: 'no_click' };
        }
        """)
        if result.get("ok"):
            await page.wait_for_timeout(1800)
            if await _overload_visible(page):
                print(f"  ✅ 필터 이전 버튼 클릭 (idx={result.get('idx')}, text='{result.get('text')}')")
                return True
            # 성공 아니었으면 되돌리기 위해 한 번 더 클릭
            await page.evaluate("""
            () => {
                const allBtns = Array.from(document.querySelectorAll('button, [role="button"]'));
                const filterBtn = allBtns.find(b =>
                    b.textContent.trim().startsWith('필터') ||
                    b.textContent.trim() === 'Filter'
                );
                if (filterBtn) {
                    const siblings = Array.from(filterBtn.parentElement.querySelectorAll('button, [role="button"]'));
                    const idx = siblings.indexOf(filterBtn);
                    if (idx > 0) siblings[idx - 1].click();
                }
            }
            """)
    except Exception as e:
        print(f"  ⚠️  JS 클릭 예외: {e}")

    print("  ⚠️  오버로드 뷰 버튼 미발견 — 현재 뷰 그대로 진행")
    return False


async def _overload_visible(page: Page) -> bool:
    """페이지에 '▲ [' 패턴의 오버로드 텍스트가 보이는지 확인"""
    try:
        content = await page.content()
        return bool(re.search(r"▲\s*\[", content))
    except Exception:
        return False


# ═══════════════════════════════════════════════════════
# DOM 추출 (JS)
# ═══════════════════════════════════════════════════════

# 니케 카드 컨테이너 내부 텍스트 수집
_EXTRACT_JS = """
() => {
    const OPTION_RE = /▲\\s*\\[([^\\]]+)\\]\\s*([\\d.]+%(?:\\(\\+\\d+\\))?|\\+?\\d+)/;

    // ▲ 텍스트를 포함하는 리프 노드를 찾고, 그 조상 카드 컨테이너를 수집
    const cardSet = new Set();

    function walk(el) {
        if (el.nodeType === 3) { // Text node
            const t = el.textContent;
            if (t && /▲\\s*\\[/.test(t)) {
                // 카드 컨테이너 탐색 (최대 8단계 위)
                let p = el.parentElement;
                for (let i = 0; i < 8 && p; i++, p = p.parentElement) {
                    const tag = p.tagName.toLowerCase();
                    const cls = (p.className || '').toLowerCase();
                    if (tag === 'li' || tag === 'article' ||
                        cls.includes('item') || cls.includes('card') ||
                        cls.includes('nikke') || cls.includes('character') ||
                        cls.includes('row')) {
                        cardSet.add(p);
                        break;
                    }
                }
            }
            return;
        }
        for (const child of el.childNodes) walk(child);
    }
    walk(document.body);

    const rows = [];
    for (const card of cardSet) {
        // 카드 내 이미지 alt (니케 이름) 추출 시도
        const imgEl = card.querySelector('img[alt]');
        const imgAlt = imgEl ? imgEl.getAttribute('alt').trim() : '';

        // 전투력(Pow.) 추출
        const fullText = card.innerText || card.textContent || '';
        const powMatch = fullText.match(/Pow\\.\\s*([\\d,]+)/);
        const power = powMatch ? parseInt(powMatch[1].replace(',', '')) : 0;

        // 오버로드 옵션 라인 수집
        const options = {};
        const lines = fullText.split('\\n');
        for (const line of lines) {
            const m = line.match(/▲\\s*\\[([^\\]]+)\\]\\s*([\\d.]+%(?:\\(\\+\\d+\\))?|\\+?\\d+)/);
            if (m) {
                const optName = m[1].trim();
                options[optName] = m[2].trim();
            }
        }

        if (Object.keys(options).length > 0) {
            rows.push({ imgAlt, power, options, rawText: fullText.slice(0, 300) });
        }
    }
    return rows;
}
"""


# ═══════════════════════════════════════════════════════
# 메인 스크래퍼
# ═══════════════════════════════════════════════════════

async def scrape_overload(uid: str, headless: bool = False) -> dict:
    target_url = build_url(uid)
    login_url  = build_login_url(uid)

    print(f"\n{'='*60}")
    print("NIKKE 오버로드 옵션 스크래퍼")
    print(f"{'='*60}\n")

    login_done     = asyncio.Event()
    # GetUserCharacters 인터셉트: name_code ↔ display index 매핑용
    characters_raw: list[dict] = []
    nikkes_order:   list      = []

    async def on_response(response):
        if API_DOMAIN not in response.url:
            return
        try:
            body = await response.json()
        except Exception:
            return
        if body.get("code") != 0:
            return

        if "CheckLogin" in response.url:
            login_done.set()

        if "GetUserCharacters" in response.url:
            chars = body.get("data", {}).get("characters", [])
            if chars and not characters_raw:
                characters_raw.extend(chars)
                print(f"  [API] GetUserCharacters: {len(chars)}개 니케")

        if "GetNikkesOrder" in response.url:
            data = body.get("data", {})
            order = data if isinstance(data, list) else data.get("list", [])
            if order and not nikkes_order:
                nikkes_order.extend(order)
                print(f"  [API] GetNikkesOrder: {len(order)}개")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
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
        page.on("response", lambda r: asyncio.ensure_future(on_response(r)))

        # ── Phase 1: 로그인 ─────────────────────────────────────
        print("┌─ [Phase 1] 로그인")
        await page.goto(login_url, wait_until="domcontentloaded")
        print("│  ⏳ 직접 로그인해 주세요 (최대 120초)...")
        try:
            await asyncio.wait_for(login_done.wait(), timeout=120)
            print("│  ✅ 로그인 성공!")
        except asyncio.TimeoutError:
            print("│  ⚠️  타임아웃 — 강제 진행")
        await page.wait_for_timeout(2000)
        print("└─ 완료\n")

        # ── Phase 2: 니케 목록 이동 ─────────────────────────────
        print("┌─ [Phase 2] 니케 목록 로딩")
        if "nikke-list" not in page.url:
            await page.goto(target_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        print("└─ 완료\n")

        # ── Phase 3: 오버로드 뷰 전환 ───────────────────────────
        print("┌─ [Phase 3] 오버로드 뷰 전환")
        overload_active = await activate_overload_view(page)
        await page.wait_for_timeout(1500)
        print("└─ 완료\n")

        # ── Phase 4: 전체 스크롤 (lazy load) ────────────────────
        print("┌─ [Phase 4] 스크롤 (lazy load)")
        prev_card_count = 0
        stall = 0
        for i in range(60):
            await page.evaluate("window.scrollBy(0, 700)")
            await page.wait_for_timeout(350)

            cur_cards = await page.evaluate("""
            () => document.querySelectorAll('*').length  // placeholder
            """)
            # 실제 오버로드 텍스트 개수로 판단
            ov_count = len(re.findall(r"▲\s*\[", await page.content()))
            if ov_count == prev_card_count:
                stall += 1
                if stall >= 8:
                    break
            else:
                stall = 0
            prev_card_count = ov_count

        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(800)
        ov_count = len(re.findall(r"▲\s*\[", await page.content()))
        print(f"│  오버로드 옵션 텍스트 {ov_count}개 감지")
        print("└─ 완료\n")

        # ── Phase 5: DOM 추출 ────────────────────────────────────
        print("┌─ [Phase 5] 데이터 추출")
        raw_rows: list[dict] = await page.evaluate(_EXTRACT_JS)
        print(f"│  카드 {len(raw_rows)}개 발견")
        print("└─ 완료\n")

        await browser.close()

    # ── 파싱 & 정리 ──────────────────────────────────────────────
    # name_code 매핑 (GetUserCharacters 기준, 인덱스 = 표시 순서)
    # characters_raw는 서버 반환 순서 — GetNikkesOrder로 재정렬 시도
    name_code_by_idx: dict[int, str] = {}
    name_by_code:     dict[str, str] = {}
    for char in characters_raw:
        nc   = str(char.get("name_code", ""))
        name = char.get("name", "") or char.get("nikke_name", "") or nc
        name_by_code[nc] = name

    results: dict = {}
    for i, row in enumerate(raw_rows):
        options_parsed = {
            opt: parse_value(val)
            for opt, val in row.get("options", {}).items()
        }
        if not options_parsed:
            continue

        # 니케 식별: imgAlt → characters_raw 이름 매핑 → 폴백: 순서 인덱스
        img_alt = row.get("imgAlt", "").strip()
        power   = row.get("power", 0)

        # characters_raw에서 이름 매치 시도
        matched_code = ""
        if img_alt:
            for char in characters_raw:
                cn = char.get("name", "") or char.get("nikke_name", "") or ""
                if img_alt and (img_alt in cn or cn in img_alt):
                    matched_code = str(char.get("name_code", ""))
                    break

        key  = matched_code if matched_code else f"idx_{i:03d}"
        name = name_by_code.get(key, img_alt or f"Nikke#{i+1}")

        results[key] = {
            "name":    name,
            "power":   power,
            "options": options_parsed,
        }

    return results


# ═══════════════════════════════════════════════════════
# 저장 & 요약
# ═══════════════════════════════════════════════════════

def save(data: dict, path: str = "overload_options.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 저장 완료: {path}")


def print_summary(data: dict):
    print(f"\n{'='*60}")
    print(f"📊 오버로드 요약  |  니케 {len(data)}개")
    print(f"{'='*60}")

    # 옵션 종류별 집계
    opt_count: dict[str, int] = {}
    for entry in data.values():
        for opt in entry.get("options", {}):
            opt_count[opt] = opt_count.get(opt, 0) + 1

    print("옵션 종류:")
    for opt, cnt in sorted(opt_count.items(), key=lambda x: -x[1]):
        print(f"  {opt:<28} {cnt}개 니케")

    print("\n샘플 (상위 5개):")
    for key, entry in list(data.items())[:5]:
        print(f"  [{key}] {entry['name']}  (전투력 {entry['power']:,})")
        for opt, val in entry["options"].items():
            print(f"    {opt}: {val}")


# ═══════════════════════════════════════════════════════
# 진입점
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    uid = input("Blabla UID 입력: ").strip()
    if not uid:
        print("❌ UID를 입력해야 합니다.")
        exit(1)

    data = asyncio.run(scrape_overload(uid, headless=False))
    save(data, "overload_options.json")
    print_summary(data)
