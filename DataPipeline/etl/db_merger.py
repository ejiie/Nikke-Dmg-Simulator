"""유저 동적 데이터(name_code) + 공식 정적 데이터(roledata_clean, name_code) → 최종 마스터 DB.

prydwen + name_code↔slug 매핑(auto_mapper) 의존을 제거한 버전. roledata_clean 이 이미
name_code 키이므로 유저데이터와 **직접 조인**한다(매핑 불필요).
출력 roster shape 은 기존과 동일: { name_code: {name_code, static{...}, user{...}} }.
"""
import json
import os
import sys


def get_merged_nikke_data(user_db_path: str, roledata_clean_path: str) -> dict:
    """유저 데이터 + roledata_clean 을 name_code 로 조인한 마스터 DB(dict) 반환."""
    try:
        with open(user_db_path, "r", encoding="utf-8") as f:
            user_data = json.load(f)
        with open(roledata_clean_path, "r", encoding="utf-8") as f:
            static_data = json.load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"❌ 재료 파일이 없어. 경로 확인: {e}")

    user_chars = user_data.get("characters", {})
    final_fusion_db = {
        "uid": user_data.get("uid", "unknown"),
        "global_state": user_data.get("global_state", {}),
        "roster": {},
    }

    skip_count = 0
    for nc, u_char in user_chars.items():
        s_char = static_data.get(str(nc))
        if not s_char:
            # 공식 데이터에 아직 없는 name_code → 패스
            skip_count += 1
            continue

        final_fusion_db["roster"][str(nc)] = {
            "name_code": str(nc),
            # [Static] 공식 roledata (전투 공식/스킬에 필요한 고정값)
            "static": {
                "name": s_char.get("name"),
                "element": s_char.get("element"),
                "weapon": s_char.get("weapon"),
                "class": s_char.get("class"),
                "burstType": s_char.get("burstType"),
                "manufacturer": s_char.get("manufacturer"),
                "ammoCapacity": s_char.get("ammoCapacity"),
                "reloadTime": s_char.get("reloadTime"),
                "iconUrl": s_char.get("iconUrl"),
                "basicAttack": s_char.get("basicAttack"),
                "skills": s_char.get("skills"),
            },
            # [Dynamic] 유저의 레벨/장비/오버로드 등
            "user": {
                "level": u_char.get("level"),
                "grade": u_char.get("grade"),
                "core": u_char.get("core"),
                "combat": u_char.get("combat"),
                "bond_level": u_char.get("bond_level"),
                "favorite_item_lv": u_char.get("favorite_item_lv"),
                "skills": u_char.get("skills"),
                "equipments": u_char.get("equipments", {}),
                "cube": u_char.get("cube", {"tid": 0, "level": 0}),
                "overload_stats": u_char.get("overload_stats", []),
            },
        }

    if skip_count:
        print(f"   (공식 데이터 없는 {skip_count}명 스킵)")
    return final_fusion_db


if __name__ == "__main__":
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROCESSED_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed")
    u_path = os.path.join(PROCESSED_DIR, "user_state_clean.json")
    r_path = os.path.join(PROCESSED_DIR, "roledata_clean.json")
    try:
        merged = get_merged_nikke_data(u_path, r_path)
        print(f"✅ 총 {len(merged['roster'])}명 병합 (uid {merged['uid']})")
        out_path = os.path.join(PROCESSED_DIR, "nikke_merged_db_returned.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        print(f"💾 '{out_path}' 저장 완료")
    except Exception as e:
        print(e)
        sys.exit(1)
