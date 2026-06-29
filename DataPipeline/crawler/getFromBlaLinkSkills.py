"""BlaBlaLink 공식 스킬 데이터 크롤러 (roledata).

blablalink 공개 CDN 의 `roledata/{resource_id}-v2-{locale}.json` 에서 각 NIKKE 의
**구조화 스킬 데이터**(레벨별 exact 값 + skill_type 코드 + function 참조)를 수집한다.
prydwen 산문 + LLM 파싱 트랙을 대체할 수 있는 ground-truth. 구조는 Docs/SKILL_DATA_BLABLALINK.md.

로그인 불필요(공개 CDN). 게임 업데이트 때만 가끔 돌리면 된다.
enumerate: nikke_list 의 resource_id 순회 → roledata.
출력: Database/raw/blabla_skills.json  (name_code 키)
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

# 평타/스킬1/2 공통 필드 + 버스트 전용 필드
_BURST_FIELDS = (
    "skill_type", "attack_type", "counter_type", "prefer_target", "prefer_target_condition",
    "skill_cooltime", "skill_cooltime_list", "duration_type", "duration_value",
    "skill_value_data",
    "before_use_function_id_list", "after_use_function_id_list",
    "before_hurt_function_id_list", "after_hurt_function_id_list",
)


def extract_skill(detail, is_burst=False):
    """스킬 detail 에서 시뮬에 필요한 필드만 추출. 텍스트/값은 원본 그대로(placeholder 유지)."""
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


def fetch_skills():
    if not cdn.self_check():
        print("❌ URL 난독화 알고리즘 self-check 실패 → blablalink 규칙 변경 가능. 중단.")
        return EXIT_ALGO_DRIFT
    print("🛰️ blablalink 공식 스킬 데이터 크롤 시작 (공개 CDN, 로그인 불필요)...")

    nlist = cdn.fetch_json(f"character/{LOCALE}/nikke_list_{LOCALE}_v2.json")
    if not nlist:
        print("❌ nikke_list 실패 → 중단.")
        return EXIT_FETCH_FAIL
    recs = nlist.get("records", nlist) if isinstance(nlist, dict) else nlist

    # resource_id 순회 (중복 제거)
    targets, seen = [], set()
    for r in recs:
        rid = r.get("resource_id")
        if rid is not None and rid not in seen:
            seen.add(rid)
            targets.append(rid)
    print(f"🎯 대상 {len(targets)}명 (resource_id). roledata 순회 시작...")

    roster, fail = {}, []
    for n, rid in enumerate(targets, 1):
        rd = cdn.fetch_json(f"roledata/{rid}-v2-{LOCALE}.json", required=False)
        if not rd:
            fail.append(rid)
        else:
            nc = rd.get("name_code")
            roster[str(nc)] = {
                "name_code": nc,
                "resource_id": rid,
                "name": rd.get("name_localkey"),
                "class": rd.get("class"),
                "element_id": rd.get("element_id"),
                "shot_id": rd.get("shot_id"),
                "original_rare": rd.get("original_rare"),
                "critical_ratio": rd.get("critical_ratio"),
                "critical_damage": rd.get("critical_damage"),
                "use_burst_skill": rd.get("use_burst_skill"),
                "change_burst_step": rd.get("change_burst_step"),
                "burst_apply_delay": rd.get("burst_apply_delay"),
                "burst_duration": rd.get("burst_duration"),
                "skills": {
                    "skill1": extract_skill(rd.get("skill1_detail")),
                    "skill2": extract_skill(rd.get("skill2_detail")),
                    "burst": extract_skill(rd.get("ulti_skill_detail"), is_burst=True),
                },
            }
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
    save_path = os.path.join(RAW_DIR, "blabla_skills.json")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅ {len(roster)}/{len(targets)}명 스킬 저장: '{save_path}'")
    if fail:
        print(f"⚠️ roledata 없음 {len(fail)}명 (스킨/비공개 resource_id 등): {str(fail[:12])[1:-1]}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(fetch_skills())
