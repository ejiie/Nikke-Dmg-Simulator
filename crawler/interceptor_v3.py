import asyncio
import json
import base64
from datetime import datetime
from playwright.async_api import async_playwright

# ── UID 유틸 ──────────────────────────────────────────────────────────────────
def encode_uid(blabla_uid: str) -> str:
    raw = f"29080-{blabla_uid}"
    return base64.b64encode(raw.encode()).decode()

def build_url(blabla_uid: str) -> str:
    encoded = encode_uid(blabla_uid)
    return (
        f"https://www.blablalink.com/shiftyspad/nikke-list"
        f"?uid={encoded}&openid={encoded}"
    )

# ── 저장소 ────────────────────────────────────────────────────────────────────
captured_routes: list[dict] = []
captured_cookies: list[dict] = []
captured_storage: dict      = {}

# ── 핵심 타겟 ─────────────────────────────────────────────────────────────────
FOCUS = ["api.blablalink.com"]

# ── page.route() 핸들러 — 요청 완전 덤프 ─────────────────────────────────────
async def handle_route(route, request):
    url = request.url

    if any(kw in url for kw in FOCUS):
        # ✅ post_data_buffer로 raw body 캡처 (post_data보다 신뢰도 높음)
        try:
            raw_body = request.post_data_buffer  # bytes
            if raw_body:
                try:
                    body_parsed = json.loads(raw_body.decode("utf-8"))
                except Exception:
                    body_parsed = raw_body.decode("utf-8", errors="replace")
            else:
                body_parsed = None
        except Exception as e:
            body_parsed = f"ERROR: {e}"

        entry = {
            "_type":     "ROUTE_REQUEST",
            "timestamp": datetime.now().isoformat(),
            "method":    request.method,
            "url":       url,
            "headers":   dict(request.headers),   # 쿠키 포함 모든 헤더
            "body":      body_parsed,
        }
        captured_routes.append(entry)
        print(f"🛑 ROUTE [{request.method}] {url}")
        print(f"   body: {json.dumps(body_parsed, ensure_ascii=False)[:200]}")
        
        # 쿠키 헤더 별도 강조
        cookie_val = request.headers.get("cookie", "")
        if cookie_val:
            print(f"   🍪 cookie: {cookie_val[:300]}")
        else:
            print(f"   🍪 cookie: (없음)")

    # 요청은 반드시 계속 진행
    await route.continue_()


async def intercept_v3(blabla_uid: str, headless: bool = False, wait_sec: int = 15):
    url = build_url(blabla_uid)
    print(f"\n🔍 대상 URL: {url}\n{'='*70}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        # ✅ 모든 요청을 route로 가로채기
        await page.route("**/*", handle_route)

        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(wait_sec * 1000)

        # ✅ 쿠키 전체 스냅샷
        cookies = await context.cookies()
        captured_cookies.extend(cookies)

        # ✅ localStorage / sessionStorage 덤프
        try:
            ls = await page.evaluate("() => JSON.stringify(window.localStorage)")
            ss = await page.evaluate("() => JSON.stringify(window.sessionStorage)")
            captured_storage["localStorage"]  = json.loads(ls)  if ls != "null" else {}
            captured_storage["sessionStorage"] = json.loads(ss) if ss != "null" else {}
        except Exception as e:
            captured_storage["error"] = str(e)

        await browser.close()

    return {
        "routes":  captured_routes,
        "cookies": captured_cookies,
        "storage": captured_storage,
    }


def save_and_summarize(result: dict, path: str = "intercepted_v3.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n💾 저장: {path}")

    print("\n" + "=" * 70)
    print("📊 요약")
    print("=" * 70)

    # 핵심 요청 헤더
    for r in result["routes"]:
        print(f"\n🛑 [{r['method']}] {r['url']}")
        print(f"   body  : {json.dumps(r['body'], ensure_ascii=False)[:300]}")
        cookie = r["headers"].get("cookie", "(없음)")
        print(f"   cookie: {cookie[:300]}")
        # 인증 관련 헤더 출력
        for k, v in r["headers"].items():
            if any(x in k.lower() for x in ["auth", "token", "x-uid", "x-open", "x-game"]):
                print(f"   🔑 {k}: {v}")

    # 쿠키 스냅샷
    print(f"\n🍪 context.cookies() — {len(result['cookies'])}개")
    for c in result["cookies"]:
        print(f"   {c['name']} = {str(c['value'])[:80]}  (domain: {c['domain']})")

    # Storage
    print(f"\n📦 localStorage  : {list(result['storage'].get('localStorage', {}).keys())}")
    print(f"📦 sessionStorage: {list(result['storage'].get('sessionStorage', {}).keys())}")


if __name__ == "__main__":
    BLABLA_UID = input("Blabla UID 입력: ").strip()
    result = asyncio.run(intercept_v3(BLABLA_UID, headless=False, wait_sec=15))
    save_and_summarize(result, "intercepted_v3.json")
