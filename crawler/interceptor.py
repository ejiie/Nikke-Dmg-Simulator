import asyncio
import json
import base64
from datetime import datetime
from playwright.async_api import async_playwright, Response, Request

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

# ── 필터링 ────────────────────────────────────────────────────────────────────
IGNORE_EXT = [".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2",
              ".ttf", ".css", ".mp4", ".webp", ".gif"]
IGNORE_HOST = ["google-analytics", "gtag", "hotjar", "clarity",
               "sentry", "segment", "amplitude", "onetrust", "rumt-sg"]

# 관심 집중 타겟
FOCUS_KEYWORDS = ["api.blablalink.com", "sg-tools-cdn.blablalink.com"]

def is_relevant(url: str) -> bool:
    url_lower = url.lower()
    if any(ext in url_lower for ext in IGNORE_EXT):
        return False
    if any(h in url_lower for h in IGNORE_HOST):
        return False
    return True

def is_focus(url: str) -> bool:
    return any(kw in url for kw in FOCUS_KEYWORDS)

# ── 저장소 ────────────────────────────────────────────────────────────────────
captured: list[dict] = []

# ── 요청 캡처 (헤더 + 바디) ───────────────────────────────────────────────────
async def on_request(request: Request):
    if not is_focus(request.url):
        return
    try:
        entry = {
            "_type":          "REQUEST",
            "timestamp":      datetime.now().isoformat(),
            "method":         request.method,
            "url":            request.url,
            "headers":        dict(request.headers),   # ← 인증 토큰 여기 있음
            "post_data":      None,
        }
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                raw = request.post_data
                entry["post_data"] = json.loads(raw) if raw else None
            except Exception:
                entry["post_data"] = request.post_data  # raw string

        captured.append(entry)
        print(f"📤 REQ  [{request.method}] {request.url}")

    except Exception as e:
        print(f"⚠️  요청 캡처 실패: {e}")

# ── 응답 캡처 (text/plain도 JSON 시도) ───────────────────────────────────────
async def on_response(response: Response):
    if not is_relevant(response.url):
        return
    try:
        content_type = response.headers.get("content-type", "")

        entry = {
            "_type":        "RESPONSE",
            "timestamp":    datetime.now().isoformat(),
            "status":       response.status,
            "method":       response.request.method,
            "url":          response.url,
            "content_type": content_type,
            "body":         None,
            "body_raw":     None,
            "parse_error":  None,
        }

        # ✅ 핵심 수정: 모든 응답에 대해 JSON 파싱 시도
        try:
            body_text = await response.text()

            if not body_text.strip():
                entry["body_raw"] = "(empty)"
            else:
                try:
                    entry["body"] = json.loads(body_text)       # JSON 파싱 성공
                except json.JSONDecodeError:
                    entry["body_raw"] = body_text[:1000]        # 파싱 실패 → raw 저장

        except Exception as e:
            entry["parse_error"] = str(e)

        captured.append(entry)

        # 콘솔 실시간 출력
        if is_focus(response.url):
            tag = "🎯"
        elif entry["body"] is not None:
            tag = "🟢"
        else:
            tag = "⚪"

        print(f"{tag} RES [{response.status}] {response.request.method} {response.url}")
        if entry["body"] and is_focus(response.url):
            # 핵심 타겟은 즉시 미리보기 출력
            preview = json.dumps(entry["body"], ensure_ascii=False)
            print(f"    └─ body preview: {preview[:300]}")

    except Exception as e:
        print(f"⚠️  응답 캡처 실패: {response.url} → {e}")

# ── 메인 인터셉터 ─────────────────────────────────────────────────────────────
async def intercept(blabla_uid: str, headless: bool = False, wait_sec: int = 15):
    url = build_url(blabla_uid)
    print(f"\n🔍 대상 URL: {url}")
    print(f"⏳ {wait_sec}초간 네트워크 캡처 중...\n")
    print("=" * 70)

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

        # 요청 + 응답 모두 리스닝
        page.on("request",  on_request)
        page.on("response", on_response)

        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(wait_sec * 1000)

        await browser.close()

    return captured

# ── 결과 저장 ─────────────────────────────────────────────────────────────────
def save_results(results: list[dict], path: str = "intercepted_v2.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n💾 저장 완료: {path}")

# ── 요약 출력 ─────────────────────────────────────────────────────────────────
def print_summary(results: list[dict]):
    print("\n" + "=" * 70)
    print("📊 캡처 요약")
    print("=" * 70)

    focus = [r for r in results if is_focus(r["url"])]
    print(f"\n🎯 핵심 타겟 ({len(focus)}건):")
    for r in focus:
        t = r["_type"]
        if t == "REQUEST":
            print(f"\n  📤 REQUEST [{r['method']}] {r['url']}")
            # 인증 헤더 추출
            headers = r.get("headers", {})
            auth_keys = ["authorization", "token", "x-token",
                         "cookie", "x-uid", "x-openid", "x-auth"]
            for k, v in headers.items():
                if any(ak in k.lower() for ak in auth_keys):
                    print(f"     🔑 {k}: {v[:120]}")
            if r.get("post_data"):
                print(f"     📦 post_data: {json.dumps(r['post_data'], ensure_ascii=False)[:300]}")
        else:
            print(f"\n  📥 RESPONSE [{r['status']}] {r['method']} {r['url']}")
            if r["body"]:
                body = r["body"]
                if isinstance(body, dict):
                    print(f"     Keys: {list(body.keys())}")
                    # 중첩 미리보기
                    for k, v in body.items():
                        if isinstance(v, (dict, list)):
                            sub = list(v.keys()) if isinstance(v, dict) else f"list({len(v)})"
                            print(f"       └─ {k}: {sub}")
                        else:
                            print(f"       └─ {k}: {str(v)[:80]}")
                elif isinstance(body, list):
                    print(f"     list({len(body)}개) → 첫번째: {json.dumps(body[0], ensure_ascii=False)[:200]}")
            elif r["body_raw"]:
                print(f"     body_raw: {r['body_raw'][:200]}")

# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    BLABLA_UID = input("Blabla UID 입력 (예: 10620366463748434922): ").strip()

    results = asyncio.run(
        intercept(
            blabla_uid=BLABLA_UID,
            headless=False,   # False = 브라우저 창 확인 가능
            wait_sec=15,      # JS 느리면 20으로 올릴 것
        )
    )

    print_summary(results)
    save_results(results, "intercepted_v2.json")
