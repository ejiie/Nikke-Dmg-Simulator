"""BlaBlaLink 정적 게임 데이터 크롤러 — 장비 / 하모니 큐브 / 소장품(favorite).

blablalink 프론트엔드가 사용하는 **공개 CDN**(sg-tools-cdn.blablalink.com)의 게임
데이터 JSON 을 가져온다. CDN URL 은 프론트의 난독화 규칙(논리경로 MD5 + 디렉토리
djb2 해시)을 그대로 재현해 **로그인 없이** 계산한다.

게임 업데이트 때만 가끔 돌리면 되는 정적 데이터다. 수집 대상:
  - 장비 base 스탯 : equip/ItemEquipTable-{locale}.json       (class × tier × module)
  - 하모니 큐브    : equip/cube_rare_map.json → equip/{locale}/cube_{id}.json   (레벨별 atk/hp)
  - 소장품(favorite): equip/favorite_rare_map.json → equip/{locale}/favorite_{id}.json

출력: Database/raw/blabla_static_tables.json
"""
import hashlib
import json
import os
import sys
import time

from curl_cffi import requests as creq

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

CDN = "https://sg-tools-cdn.blablalink.com"
LOCALE = "en"
IMPERSONATE = "chrome"

EXIT_OK = 0
EXIT_FETCH_FAIL = 10          # 필수 인덱스/테이블 fetch 실패
EXIT_ALGO_DRIFT = 11          # URL 난독화 알고리즘 self-check 실패 (사이트 변경)

# ── blablalink CDN URL 난독화 재현 (frontend createNormalObfuscatedPath) ──
LARGE_PRIMES = [224737, 1000639, 2654435761, 2654435769, 1000621, 4294967291]


def _to_int32(x):
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x >= 0x80000000 else x


def _djb2(s, seed):
    ie = seed
    for ch in s:
        ie = _to_int32(ie * 33 + ord(ch))
    return ie


def _two_letter(path, prime):
    re = ((_djb2(path, prime) % prime) + prime) % prime
    return chr(97 + (re // 26) % 26) + chr(97 + re % 26)


def _two_number(path, prime):
    re = ((_djb2(path, prime) % prime) + prime) % prime
    return str(re % 99).zfill(2)


def _obfuscated_path(logical):
    """논리경로 → 난독화 CDN 경로 (디렉토리는 djb2 해시, 파일명은 md5(전체경로))."""
    logical = logical.lstrip("/")
    segs = [s for s in logical.split("/") if s]
    out = []
    last = len(segs) - 1
    for i, seg in enumerate(segs):
        if i == last:
            parts = seg.split(".")
            parts.pop(0)  # 이름 토막 제거, 확장자만 유지
            out.append(f"{hashlib.md5(logical.encode()).hexdigest()}." + ".".join(parts))
        else:
            out.append(f"{_two_letter(logical, LARGE_PRIMES[i])}-{_two_number(logical, LARGE_PRIMES[i])}")
    return "/".join(out)


def cdn_url(logical):
    return f"{CDN}/{_obfuscated_path(logical)}"


# 알고리즘 self-check 기준 (영문 캐릭터 사전의 알려진 해시)
_KNOWN = ("character/en/nikke_list_en_v2.json",
          "yl-57/hd-03/1bf030193826e243c2e195f951a4be00.json")


def fetch_json(logical, retries=3, required=True):
    """CDN 에서 JSON 1개를 가져온다. 실패 시 None (required 면 호출부가 처리)."""
    url = cdn_url(logical)
    last = None
    for attempt in range(retries):
        try:
            r = creq.get(url, impersonate=IMPERSONATE, timeout=20)
            if r.status_code == 200:
                return r.json()
            last = f"status {r.status_code}"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(0.5 * (attempt + 1))
    tag = "❌" if required else "⚠️"
    print(f"   {tag} fetch 실패: {logical} ({last})")
    return None


def fetch_static_tables():
    # 0) self-check: 난독화 알고리즘이 여전히 유효한지 확인
    if _obfuscated_path(_KNOWN[0]) != _KNOWN[1]:
        print("❌ URL 난독화 알고리즘 self-check 실패 → blablalink 가 규칙을 바꿨을 수 있음. 중단.")
        return EXIT_ALGO_DRIFT
    print("🛰️ blablalink 정적 데이터 크롤 시작 (공개 CDN, 로그인 불필요)...")

    # 1) 장비 base 스탯표
    equip = fetch_json(f"equip/ItemEquipTable-{LOCALE}.json")
    if not equip:
        print("❌ ItemEquipTable 실패 → 중단.")
        return EXIT_FETCH_FAIL
    equip_records = equip.get("records", equip) if isinstance(equip, dict) else equip
    print(f"🛡️ 장비: {len(equip_records)} records")

    # 2) 하모니 큐브 (인덱스 → 개별 레벨별 스탯)
    cube_map = fetch_json("equip/cube_rare_map.json") or []
    cubes = {}
    for c in cube_map:
        cid = c.get("id")
        if cid is None:
            continue
        data = fetch_json(f"equip/{LOCALE}/cube_{cid}.json", required=False)
        if data:
            cubes[str(cid)] = data
        time.sleep(0.1)
    print(f"🧊 큐브: {len(cubes)}/{len(cube_map)}")

    # 3) 소장품(favorite) (rarity 인덱스 → 개별)
    fav_map = fetch_json("equip/favorite_rare_map.json") or {}
    favorites = {}
    fav_ids = [fid for ids in fav_map.values() for fid in ids] if isinstance(fav_map, dict) else []
    for fid in fav_ids:
        data = fetch_json(f"equip/{LOCALE}/favorite_{fid}.json", required=False)
        if data:
            favorites[str(fid)] = data
        time.sleep(0.1)
    print(f"💝 소장품: {len(favorites)}/{len(fav_ids)}")

    out = {
        "_source": "sg-tools-cdn.blablalink.com (public)",
        "locale": LOCALE,
        "equipment": equip_records,
        "cube_rare_map": cube_map,
        "cubes": cubes,
        "favorite_rare_map": fav_map,
        "favorites": favorites,
    }
    save_path = os.path.join(RAW_DIR, "blabla_static_tables.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 저장: '{save_path}' (장비 {len(equip_records)} / 큐브 {len(cubes)} / 소장품 {len(favorites)})")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(fetch_static_tables())
