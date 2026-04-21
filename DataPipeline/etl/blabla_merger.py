import json
import os

# ── 가키짱의 절대 경로 마법 ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "nikke_full_scroll_result.json")
PROCESSED_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "user_state_clean.json")

def deep_find(obj, key):
    """
    JSON 객체 내부를 끝까지 파고들어 원하는 key를 찾아내는 재귀 탐색 함수.
    API 응답의 계층이 깊거나 유동적일 때 데이터를 놓치지 않도록 보장함.
    """
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            res = deep_find(v, key)
            if res is not None:
                return res
    elif isinstance(obj, list):
        for item in obj:
            res = deep_find(item, key)
            if res is not None:
                return res
    return None

def merge_blabla_data_v4():
    print("🛠️ 가키짱의 Deep-Dive Left Outer Join 엔진 기동...")

    if not os.path.exists(RAW_FILE):
        print(f"❌ 야! 원본 파일이 없잖아! ({RAW_FILE})")
        return

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    phase1 = raw_data.get("phase_1_initial_load", [])
    phase2 = raw_data.get("phase_2_after_click", [])
    all_packets = phase1 + phase2

    # 콘솔은 C# 시뮬레이터에서 O(1) 탐색이 가능하도록 Dict 형태로 초기화
    user_global = {"synchro_level": 1, "consoles": {}}
    merged_characters = {}

    print("🔍 [Step 1] 전역 스탯 및 178명 전체 캐릭터 베이스 구축 중...")
    for packet in all_packets:
        data = packet.get("data") or {}
        
        # [패치] Deep Search를 통한 무조건적 추출
        synchro_lv = deep_find(data, "synchro_level")
        if synchro_lv is not None:
            user_global["synchro_level"] = synchro_lv

        consoles_data = deep_find(data, "recycle_room_researches")
        
        # 값이 존재하고 비어있지 않을 때만 "tid": lv 형태의 Dict로 압축
        if consoles_data and isinstance(consoles_data, list) and len(consoles_data) > 0:
            # 덮어쓰기 방지: 이미 유효 데이터가 확보되었다면 무시 (Lock)
            if not user_global["consoles"]:
                user_global["consoles"] = {
                    str(c.get("tid", 0)): c.get("lv", 0) 
                    for c in consoles_data if "tid" in c
                }

        chars = deep_find(data, "characters")
        if chars and isinstance(chars, list):
            for char in chars:
                nc = str(char.get("name_code", ""))
                # 중복 초기화 방지
                if nc and nc not in merged_characters:
                    merged_characters[nc] = {
                        "name_code": nc,
                        "level": char.get("lv", 1),
                        "grade": char.get("grade", 1),
                        "core": char.get("core", 0),
                        "combat": char.get("combat", 0),
                        "bond_level": 1,
                        "favorite_item_lv": 0,
                        "skills": {"skill1": 1, "skill2": 1, "burst": 1},
                        "equipments": {
                            "head": {"tier": 0, "level": 0},
                            "torso": {"tier": 0, "level": 0},
                            "arm": {"tier": 0, "level": 0},
                            "leg": {"tier": 0, "level": 0}
                        },
                        "overload_stats": [] 
                    }

    # ── [2] 전 구간(Phase 1 & 2) 오버로드 옵션 딕셔너리 빌드 ──
    print("🔍 [Step 2] 전 구간 오버로드 옵션 딕셔너리 빌드 중...")
    state_effects_dict = {}
    for packet in all_packets:
        data = packet.get("data") or {}
        
        state_effs = deep_find(data, "state_effects")
        if state_effs and isinstance(state_effs, list):
            for eff in state_effs:
                eff_id = str(eff.get("id", "")) 
                func_details = eff.get("function_details", [])
                if eff_id and func_details:
                    func = func_details[0]
                    state_effects_dict[eff_id] = {
                        "type": func.get("function_type"),
                        "value": func.get("function_value"),
                        "val_type": func.get("function_value_type")
                    }

    # ── [3] 전 구간(Phase 1 & 2) 디테일 정보를 뼈대에 '덮어쓰기' ──
    print("🔗 [Step 3] 잃어버린 에이스들의 살점(스킬, 장비, 오버옵)을 뼈대에 주입 중...")
    for packet in all_packets:
        data = packet.get("data") or {}
        char_details = deep_find(data, "character_details")
        
        if char_details and isinstance(char_details, list):
            for char in char_details:
                nc = str(char.get("name_code", ""))
                
                if nc in merged_characters:
                    merged_characters[nc]["bond_level"] = char.get("attractive_lv", 1)
                    merged_characters[nc]["favorite_item_lv"] = char.get("favorite_item_lv", 0)
                    
                    merged_characters[nc]["skills"]["skill1"] = char.get("skill1_lv", 1)
                    merged_characters[nc]["skills"]["skill2"] = char.get("skill2_lv", 1)
                    merged_characters[nc]["skills"]["burst"] = char.get("ulti_skill_lv", 1)

                    overloads = []
                    parts = ["head", "torso", "arm", "leg"]
                    
                    for part in parts:
                        merged_characters[nc]["equipments"][part]["tier"] = char.get(f"{part}_equip_tier", 0)
                        merged_characters[nc]["equipments"][part]["level"] = char.get(f"{part}_equip_lv", 0)

                        for i in range(1, 4):
                            opt_id = str(char.get(f"{part}_equip_option{i}_id", 0))
                            if opt_id != "0" and opt_id in state_effects_dict:
                                opt_data = state_effects_dict[opt_id].copy()
                                if opt_data["val_type"] == "Percent":
                                    opt_data["value"] = opt_data["value"] / 10000.0 
                                overloads.append(opt_data)
                                
                    merged_characters[nc]["overload_stats"] = overloads

    # ── [4] 최종 포장 및 저장 ──
    final_db = {
        "uid": raw_data.get("uid", "unknown"),
        "global_state": user_global,
        "characters": merged_characters
    }

    os.makedirs(os.path.dirname(PROCESSED_FILE), exist_ok=True)
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(final_db, f, ensure_ascii=False, indent=2)

    print(f"\n✅ [완벽] 총 {len(merged_characters)}명의 유저 캐릭터 및 콘솔 데이터 추출 완료!")
    print(f"💾 '{PROCESSED_FILE}'을 확인해봐♥")

if __name__ == "__main__":
    merge_blabla_data_v4()