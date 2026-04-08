import asyncio
import json
import base64
from playwright.async_api import async_playwright

# ── UID 유틸 ──────────────────────────────────────────────────────────────────
def encode_uid(blabla_uid: str) -> str:
    raw = f"29080-{blabla_uid}"
    return base64.b64encode(raw.encode()).decode()

def build_target_url(blabla_uid: str) -> str:
    encoded = encode_uid(blabla_uid)
    return (
        f"https://www.blablalink.com/shiftyspad/nikke-list"
        f"?uid={encoded}&openid={encoded}"
    )

def build_login_url(blabla_uid: str) -> str:
    """로그인 완료 후 목표 URL로 자동 리다이렉트"""
    target = build_target_url(blabla_uid)
    # URL 인코딩 없이 그대로 to= 파라미터에 삽입
    return f"https://www.blablalink.com/login?to={target}&back_to={target}"

# ── 캡처 저장소 ───────────────────────────────────────────────────────────────
captured: list[dict] = []
login_done = asyncio.Event()

# ── 응답 핸들러 ───────────────────────────────────────────────────────────────
async def on_response(response):
    if "api.blablalink.com" not in response.url:
        return
    try:
        body = json.loads(await response.text())
    except Exception:
        body = await response.text()

    entry = {
        "method":      response.request.method,
        "url":         response.url,
        "status":      response.status,
        "req_body":    response.request.post_data,
        "req_headers": dict(response.request.headers),
        "res_body":    body,
    }
    captured.append(entry)

    code = body.get("code", "?") if isinstance(body, dict) else "?"
    msg  = body.get("msg",  "?") if isinstance(body, dict) else "?"
    tag  = "✅" if code == 0 else "❌"
    print(f"\n{tag} [{response.status}] {response.request.method} {response.url}")
    print(f"    code={code} | msg={msg}")

    if isinstance(body, dict) and body.get("data"):
        d = body["data"]
        print(f"    data: {list(d.keys()) if isinstance(d, dict) else f'list({len(d)})'}")

    # ── 로그인 성공 감지 ──────────────────────────────────────────────────────
    if "CheckLogin" in response.url and code == 0:
        print("\n🎉 로그인 성공 감지! 목표 URL로 이동 준비...")
        login_done.set()

    # ── 최종 목표 성공 감지 ───────────────────────────────────────────────────
    if "GetNikkesOrder" in response.url and code == 0:
        print("\n🏆 GetNikkesOrder 성공! 데이터 확보!")


# ── 메인 ──────────────────────────────────────────────────────────────────────
async def run(blabla_uid: str):
    target_url = build_target_url(blabla_uid)
    login_url  = build_login_url(blabla_uid)

    print(f"\n{'='*70}")
    print(f"🔑 로그인 URL : {login_url}")
    print(f"🎯 목표 URL  : {target_url}")
    print(f"{'='*70}\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
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
        page.on("response", on_response)

        # ── Step 1: 로그인 페이지 직접 진입 ─────────────────────────────────
        print("🌐 [Step 1] 로그인 페이지 진입...")
        await page.goto(login_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)

        # ── Step 2: 로그인 대기 (최대 120초) ────────────────────────────────
        print("⏳ [Step 2] 직접 로그인해주세요! (최대 120초 대기)\n")
        try:
            await asyncio.wait_for(login_done.wait(), timeout=120)
            print("\n✅ 로그인 감지! 3초 후 목표 URL로 이동...")
            await page.wait_for_timeout(3000)
        except asyncio.TimeoutError:
            print("⚠️  120초 타임아웃 — 현재 상태로 목표 URL 강제 이동")

        # ── Step 3: 목표 URL 이동 (리다이렉트 안 됐을 경우 대비) ─────────────
        current = page.url
        if "nikke-list" not in current:
            print(f"\n🚀 [Step 3] 목표 URL로 이동...")
            await page.goto(target_url, wait_until="domcontentloaded")
        else:
            print(f"\n🚀 [Step 3] 자동 리다이렉트 완료! 현재: {current}")

        # ── Step 4: 데이터 로딩 대기 ────────────────────────────────────────
        print("⏳ [Step 4] 데이터 로딩 대기 (15초)...")
        await page.wait_for_timeout(15000)

        # ── Step 5: IndexedDB 덤프 (토큰 구조 확인용) ────────────────────────
        print("\n🗄️  [Step 5] IndexedDB 덤프...")
        idb = await page.evaluate("""
        async () => {
            return new Promise((resolve) => {
                const req = indexedDB.open("__ss_index_db_name");
                req.onsuccess = (e) => {
                    const db     = e.target.result;
                    const stores = Array.from(db.objectStoreNames);
                    if (!stores.length) return resolve({ stores, data: [] });
                    const tx    = db.transaction(stores[0], "readonly");
                    const store = tx.objectStore(stores[0]);
                    const all   = store.getAll();
                    all.onsuccess = () => resolve({ stores, data: all.result });
                    all.onerror   = () => resolve({ stores, data: [] });
                };
                req.onerror = () => resolve({ stores: [], data: [] });
            });
        }
        """)
        print(f"  stores : {idb.get('stores')}")
        for item in idb.get("data", []):
            # token/openid 포함 항목 강조
            val = str(item)
            tag = "🔑" if any(k in val for k in ["token","openid","gameid"]) else "  "
            print(f"  {tag} {item}")

        # ── Step 6: Storage 스냅샷 ───────────────────────────────────────────
        ls = await page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
        ss = await page.evaluate("() => Object.fromEntries(Object.entries(sessionStorage))")

        await browser.close()

    # ── 저장 ─────────────────────────────────────────────────────────────────
    result = {
        "captured":       captured,
        "idb":            idb,
        "localStorage":   ls,
        "sessionStorage": ss,
    }
    with open("intercepted_v6.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ── 최종 요약 ─────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("📊 캡처 요약")
    print(f"{'='*70}")
    nikke_order = [r for r in captured if "GetNikkesOrder" in r["url"]]
    check_login = [r for r in captured if "CheckLogin"     in r["url"]]

    if check_login:
        cl = check_login[-1]["res_body"]
        print(f"\n🔑 CheckLogin  → code: {cl.get('code')} | msg: {cl.get('msg')}")

    if nikke_order:
        no = nikke_order[-1]["res_body"]
        print(f"\n🏆 GetNikkesOrder → code: {no.get('code')} | msg: {no.get('msg')}")
        if isinstance(no.get("data"), dict):
            print(f"   data keys: {list(no['data'].keys())}")
        elif isinstance(no.get("data"), list):
            print(f"   data: list({len(no['data'])}개)")
    else:
        print("\n❌ GetNikkesOrder 미캡처 — 로그인 상태 확인 필요")

    print(f"\n💾 intercepted_v6.json 저장 완료")


if __name__ == "__main__":
    uid = input("Blabla UID 입력: ").strip()
    asyncio.run(run(uid))
