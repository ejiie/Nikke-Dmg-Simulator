"""Prydwen NIKKE 캐릭터 정적 데이터 크롤러.

prydwen.gg 가 2026 중 Gatsby → Next.js(App Router) 로 이전하면서 옛
`/page-data/.../page-data.json` API 가 제거(410 Gone)되고 Cloudflare 가
httpx 류 클라이언트의 TLS fingerprint 를 차단(403)한다. 그래서:
  - fetch  : curl_cffi(impersonate=chrome) — Chrome TLS 위장으로 Cloudflare 통과
  - 데이터 : 페이지 HTML 안 `self.__next_f`(RSC 스트림)에 들어있는 `"data":{...}` JSON

리스트 페이지에서 슬러그 209개를 뽑고, 각 상세 페이지에서 캐릭터 data 객체
(이름/속성/무기/클래스/버스트/탄약/재장전/스킬 등)를 추출해 Database/raw/ 에 저장한다.
출력 shape = { slug: <data 객체> }  (prydwen_cleaner 가 정제).
"""
import json
import os
import re
import sys
import time

from curl_cffi import requests as creq

# ── 절대 경로 ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

BASE = "https://www.prydwen.gg"
LIST_URL = f"{BASE}/nikke/characters"
IMPERSONATE = "chrome"

# ── 종료 코드 (automation 이 성공/실패를 구분) ──
EXIT_OK = 0
EXIT_NO_SLUGS = 10    # 캐릭터 목록(slug) 추출 실패
EXIT_NO_DETAILS = 11  # slug 는 있었지만 상세를 하나도 못 긁음


def fetch_html(url, retries=3):
    """Cloudflare 통과(curl_cffi)로 HTML 가져오기. 실패 시 None."""
    last = None
    for attempt in range(retries):
        try:
            r = creq.get(url, impersonate=IMPERSONATE, timeout=20)
            if r.status_code == 200:
                return r.text
            last = f"status {r.status_code}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.0 * (attempt + 1))
    print(f"   ⚠️ fetch 실패 {url} ({last})")
    return None


def _decode_rsc_stream(html):
    """페이지의 모든 self.__next_f.push([n,"..."]) 청크를 풀어 하나의 스트림으로 잇는다."""
    chunks = []
    key = "self.__next_f.push("
    i = 0
    while True:
        j = html.find(key, i)
        if j < 0:
            break
        k = j + len(key)
        depth = 0
        in_str = False
        esc = False
        start = k
        # 문자열 안의 괄호는 무시해야 depth 가 안 깨진다 (스킬 텍스트의 "(...)" 대응)
        while k < len(html):
            c = html[k]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "(":
                    depth += 1
                elif c == ")":
                    if depth == 0:
                        break
                    depth -= 1
            k += 1
        try:
            val = json.loads(html[start:k])
            if isinstance(val, list) and len(val) > 1 and isinstance(val[1], str):
                chunks.append(val[1])
        except Exception:
            pass
        i = k + 1
    return "".join(chunks)


def extract_slugs(list_html):
    """리스트 페이지 RSC 에서 캐릭터 슬러그 목록(중복 제거)을 뽑는다."""
    stream = _decode_rsc_stream(list_html)
    return sorted(set(re.findall(r'"slug":"([a-z0-9][a-z0-9-]*)"', stream)))


def extract_character_data(detail_html):
    """상세 페이지 RSC 에서 캐릭터 data 객체(skills 포함)를 파싱해 반환. 실패 시 None."""
    stream = _decode_rsc_stream(detail_html)
    decoder = json.JSONDecoder()
    pos = 0
    best = None
    while True:
        idx = stream.find('"data":{', pos)
        if idx < 0:
            break
        try:
            obj, end = decoder.raw_decode(stream, idx + len('"data":'))
            pos = end
        except Exception:
            pos = idx + 8
            continue
        # 캐릭터 data = skills 리스트 + slug 를 가진 객체. 가장 풍부한 것을 택한다.
        if isinstance(obj, dict) and isinstance(obj.get("skills"), list) and obj.get("slug"):
            if best is None or len(obj["skills"]) > len(best.get("skills", [])):
                best = obj
    return best


def fetch_prydwen():
    print("🌐 prydwen 캐릭터 목록 가져오는 중...")
    list_html = fetch_html(LIST_URL)
    if not list_html:
        print("❌ 목록 페이지 fetch 실패 → 중단.")
        return EXIT_NO_SLUGS
    slugs = extract_slugs(list_html)
    if not slugs:
        print("❌ 슬러그를 추출하지 못함 (사이트 구조 변경 가능) → 중단.")
        return EXIT_NO_SLUGS
    print(f"🎯 총 {len(slugs)}명 슬러그 확보. 상세 페이지 순회 시작...")

    all_details = {}
    fail = []
    for n, slug in enumerate(slugs, 1):
        html = fetch_html(f"{BASE}/nikke/characters/{slug}")
        data = extract_character_data(html) if html else None
        if data:
            all_details[slug] = data
        else:
            fail.append(slug)
        if n % 20 == 0 or n == len(slugs):
            print(f"   ⚡ {n}/{len(slugs)} (수집 {len(all_details)}, 실패 {len(fail)})")
        time.sleep(0.15)  # 예의상 딜레이

    if not all_details:
        print("❌ 상세 데이터를 하나도 수집하지 못함 → 저장 생략, 실패 종료.")
        return EXIT_NO_DETAILS

    save_path = os.path.join(RAW_DIR, "prydwen_all_details_v3.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(all_details, f, ensure_ascii=False, indent=2)
    print(f"\n✅ {len(all_details)}/{len(slugs)}명 저장 완료: '{save_path}'")
    if fail:
        print(f"⚠️ 실패 {len(fail)}명: {', '.join(fail[:15])}{' …' if len(fail) > 15 else ''}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(fetch_prydwen())
