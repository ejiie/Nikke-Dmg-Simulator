"""캐릭터 초상화 다운로더 — blablalink 공개 CDN, webp 원본 로컬 저장 (로그인 불필요).

frontend 의 이미지 URL 규칙(`SM_CHARACTER_URL`/`MI_CHARACTER_URL`/full)을 그대로 써서
si(아이콘)/mi(중간)/full(풀아트) 3사이즈를 받는다. URL 계산은 공유 모듈 `_bbl_cdn`.
게임 업데이트(신캐) 때만 가끔 돌리면 된다.

저장: Database/raw/portraits/{si|mi|full}/{name_code}.webp  (기본 스킨 skin_index=0)
"""
import os
import sys
import time

from curl_cffi import requests as creq

import _bbl_cdn as cdn

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw")
PORTRAIT_DIR = os.path.join(RAW_DIR, "portraits")

LOCALE = cdn.LOCALE
SKIN = "00"  # skin_index 0 (기본 스킨)

# 사이즈 → 논리경로 템플릿 ({rid}=resource_id 3자리, {skin}=skin_index 2자리)
SIZE_TEMPLATES = {
    "si":   "character/si/si_c{rid}_{skin}_s.webp",
    "mi":   "character/mi/mi_c{rid}_{skin}_s.webp",
    "full": "character/full/c{rid}_{skin}.webp",
}

EXIT_OK = 0
EXIT_FETCH_FAIL = 10      # nikke_list(인덱스) fetch 실패
EXIT_ALGO_DRIFT = 11      # URL 난독화 self-check 실패
EXIT_NO_IMAGES = 12       # 이미지를 하나도 못 받음


def fetch_image(logical, retries=3):
    url = cdn.cdn_url(logical)
    for attempt in range(retries):
        try:
            r = creq.get(url, impersonate=cdn.IMPERSONATE, timeout=20)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception:
            pass
        time.sleep(0.3 * (attempt + 1))
    return None


def fetch_portraits():
    if not cdn.self_check():
        print("❌ URL 난독화 알고리즘 self-check 실패 → blablalink 규칙 변경 가능. 중단.")
        return EXIT_ALGO_DRIFT
    print("🖼️ blablalink 캐릭터 초상화 다운로드 시작 (공개 CDN, 로그인 불필요)...")

    nlist = cdn.fetch_json(f"character/{LOCALE}/nikke_list_{LOCALE}_v2.json")
    if not nlist:
        print("❌ nikke_list 실패 → 중단.")
        return EXIT_FETCH_FAIL
    recs = nlist.get("records", nlist) if isinstance(nlist, dict) else nlist

    # (resource_id, name_code) 대상 (resource_id 중복 제거)
    targets, seen = [], set()
    for r in recs:
        rid, nc = r.get("resource_id"), r.get("name_code")
        if rid is not None and nc is not None and rid not in seen:
            seen.add(rid)
            targets.append((rid, nc))

    for size in SIZE_TEMPLATES:
        os.makedirs(os.path.join(PORTRAIT_DIR, size), exist_ok=True)
    print(f"🎯 {len(targets)}명 × {len(SIZE_TEMPLATES)} 사이즈. 다운로드 중...")

    counts = {s: 0 for s in SIZE_TEMPLATES}
    fail = []
    for n, (rid, nc) in enumerate(targets, 1):
        for size, tmpl in SIZE_TEMPLATES.items():
            logical = tmpl.format(rid=str(rid).zfill(3), skin=SKIN)
            data = fetch_image(logical)
            if data:
                with open(os.path.join(PORTRAIT_DIR, size, f"{nc}.webp"), "wb") as f:
                    f.write(data)
                counts[size] += 1
            else:
                fail.append((nc, size))
            time.sleep(0.05)
        if n % 25 == 0 or n == len(targets):
            print(f"   ⚡ {n}/{len(targets)}  (si {counts['si']} / mi {counts['mi']} / full {counts['full']})")

    total = sum(counts.values())
    if total == 0:
        print("❌ 이미지를 하나도 받지 못함 → 실패 종료.")
        return EXIT_NO_IMAGES

    print(f"\n✅ 저장: '{PORTRAIT_DIR}' — si {counts['si']} / mi {counts['mi']} / full {counts['full']}")
    if fail:
        print(f"⚠️ 누락 {len(fail)}건 (스킨 없음/신캐 등): {str(fail[:10])[1:-1]}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(fetch_portraits())
