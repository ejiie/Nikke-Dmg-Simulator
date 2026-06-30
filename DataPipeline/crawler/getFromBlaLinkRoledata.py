"""BlaBlaLink 공식 캐릭터 데이터 크롤러 (roledata) — 메타 + 무기 + 스킬.

prydwen 정적 캐릭터 데이터를 **대체**하는 공식 소스. `roledata/{resource_id}-v2-{locale}.json`
에서 캐릭당 메타(class/element/manufacturer/burst) + 무기(shot_detail) + 구조화 스킬을 추출한다.
값은 원본 그대로 보존(예: damage=2708, element="Electronic") — `etl/roledata_cleaner.py` 가
prydwen_clean 호환 형태(name_code 키)로 정제/변환한다.

공개 CDN(로그인 불필요, 공유 `_bbl_cdn`). 게임 업데이트 때만 가끔.
출력:
  - Database/raw/blabla_roledata.json       (name_code 키, 큐레이트 subset — ETL 계약)
  - Database/raw/blabla_roledata_full.json  (name_code 키, 풀 raw — 미래 채굴용 아카이브)
"""
import json
import os
import sys
import time

import _bbl_cdn as cdn

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

LOCALE = cdn.LOCALE

EXIT_OK = 0
EXIT_FETCH_FAIL = 10      # nikke_list(인덱스) fetch 실패
EXIT_ALGO_DRIFT = 11      # URL 난독화 self-check 실패
EXIT_NO_DETAILS = 12      # roledata 를 하나도 못 긁음

# 버스트 전용 추가 필드 (skill1/2 = 패시브라 description+값만)
_BURST_FIELDS = (
    "skill_type", "attack_type", "counter_type", "prefer_target", "prefer_target_condition",
    "skill_cooltime", "skill_cooltime_list", "duration_type", "duration_value",
    "skill_value_data",
    "before_use_function_id_list", "after_use_function_id_list",
    "before_hurt_function_id_list", "after_hurt_function_id_list",
)


def extract_skill(detail, is_burst=False):
    if not detail:
        return None
    out = {
        "id": detail.get("id"),
        "group_id": detail.get("group_id"),
        "name": detail.get("name_localkey"),
        "skill_level": detail.get("skill_level"),
        "description": detail.get("description_localkey"),
        # {description_value_NN} → description_value_list[NN-1].description_value[level-1]
        "description_value_list": detail.get("description_value_list"),
    }
    if is_burst:
        for k in _BURST_FIELDS:
            if k in detail:
                out[k] = detail[k]
    return out


def extract_char(rd):
    el = (rd.get("element_details") or [{}])[0].get("element")
    return {
        "name_code": rd.get("name_code"),
        "resource_id": rd.get("resource_id"),
        "name": rd.get("name_localkey"),
        "class": rd.get("class"),
        "corporation": rd.get("corporation"),
        "original_rare": rd.get("original_rare"),
        "element": el,
        "critical_ratio": rd.get("critical_ratio"),
        "critical_damage": rd.get("critical_damage"),
        "use_burst_skill": rd.get("use_burst_skill"),
        "change_burst_step": rd.get("change_burst_step"),
        "burst_apply_delay": rd.get("burst_apply_delay"),
        "burst_duration": rd.get("burst_duration"),
        "squad": rd.get("squad"),               # 동일 스쿼드 아군 조건 버프 스킬용
        # 적정거리(proper distance) 보너스 범위 — 무기별 결정(SR 1명 예외). cleaner 가 무기별표로 집계.
        "bonusrange_min": rd.get("bonusrange_min"),
        "bonusrange_max": rd.get("bonusrange_max"),
        "shot": rd.get("shot_detail"),          # 무기/평타 원본 (cleaner 가 basicAttack 으로 변환)
        "skills": {
            "skill1": extract_skill(rd.get("skill1_detail")),
            "skill2": extract_skill(rd.get("skill2_detail")),
            "burst": extract_skill(rd.get("ulti_skill_detail"), is_burst=True),
        },
    }


def fetch_roledata():
    if not cdn.self_check():
        print("❌ URL 난독화 알고리즘 self-check 실패 → blablalink 규칙 변경 가능. 중단.")
        return EXIT_ALGO_DRIFT
    print("🛰️ blablalink 공식 캐릭터 데이터(roledata) 크롤 시작 (공개 CDN, 로그인 불필요)...")

    nlist = cdn.fetch_json(f"character/{LOCALE}/nikke_list_{LOCALE}_v2.json")
    if not nlist:
        print("❌ nikke_list 실패 → 중단.")
        return EXIT_FETCH_FAIL
    recs = nlist.get("records", nlist) if isinstance(nlist, dict) else nlist

    targets, seen = [], set()
    for r in recs:
        rid = r.get("resource_id")
        if rid is not None and rid not in seen:
            seen.add(rid)
            targets.append(rid)
    print(f"🎯 대상 {len(targets)}명 (resource_id). roledata 순회 시작...")

    roster, roster_full, fail = {}, {}, []
    for n, rid in enumerate(targets, 1):
        rd = cdn.fetch_json(f"roledata/{rid}-v2-{LOCALE}.json", required=False)
        if not rd or rd.get("name_code") is None:
            fail.append(rid)
        else:
            nc = str(rd["name_code"])
            roster[nc] = extract_char(rd)       # 큐레이트 subset (기존 ETL 계약)
            roster_full[nc] = rd                # 풀 raw (function_id_list·스킬값·성장 등 미래 채굴)
        if n % 25 == 0 or n == len(targets):
            print(f"   ⚡ {n}/{len(targets)} (수집 {len(roster)}, 실패 {len(fail)})")
        time.sleep(0.1)

    if not roster:
        print("❌ roledata 를 하나도 못 긁음 → 저장 생략, 실패 종료.")
        return EXIT_NO_DETAILS

    out = {
        "_source": "sg-tools-cdn.blablalink.com roledata (public)",
        "locale": LOCALE,
        "roster": roster,
    }
    save_path = os.path.join(RAW_DIR, "blabla_roledata.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅ {len(roster)}/{len(targets)}명 저장(curate): '{save_path}'")

    # 풀 raw 아카이브 (subset 으로 버려지는 필드 전수 보존 — 스킬 런타임/성장 채굴용)
    full_path = os.path.join(RAW_DIR, "blabla_roledata_full.json")
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump({"_source": out["_source"], "locale": LOCALE, "roster": roster_full},
                  f, ensure_ascii=False, indent=2)
    print(f"📦 {len(roster_full)}명 풀 raw 저장: '{full_path}'")
    if fail:
        print(f"⚠️ roledata 없음 {len(fail)}명: {str(fail[:12])[1:-1]}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(fetch_roledata())
