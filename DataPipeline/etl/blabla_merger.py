import json
import os

# ── 가키짱의 절대 경로 마법 ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "nikke_full_scroll_result.json")
PROCESSED_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "user_state_clean.json")

def merge_blabla_data_v3():
    print("🛠️ 가키짱의 Full-Scan Left Outer Join 엔진 기동...")

    if not os.path.exists(RAW_FILE):
        print(f"❌ 야! 원본 파일이 없잖아! ({RAW_FILE})")
        return

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # 🔥 [핵심 패치] Phase 1과 Phase 2의 장벽을 허물고 하나로 합친다!
    phase1 = raw_data.get("phase_1_initial_load", [])
    phase2 = raw_data.get("phase_2_after_click", [])
    all_packets = phase1 + phase2

    user_global = {"synchro_level": 1, "consoles": []}
    merged_characters = {}

    # ── [1] 178명 전체의 '완벽한 뼈대' 구축 (Master Table) ──
    print("🔍 [Step 1] 전역 스탯 및 178명 전체 캐릭터 베이스 구축 중...")
    for packet in all_packets:
        data = packet.get("data") or {}
        
        if "synchro_level" in data:
            user_global["synchro_level"] = data["synchro_level"]
        if "recycle_room_researches" in data:
            user_global["consoles"] = data["recycle_room_researches"]

        # 캐릭터 178명 명단 스틸
        if "characters" in data:
            for char in data["characters"]:
                nc = str(char.get("name_code", ""))
                if nc:
                    merged_characters[nc] = {
                        "name_code": nc,
                        "level": char.get("lv", 1),
                        "core": char.get("core", 0),
                        "combat": char.get("combat", 0),
                        "bond_level": 1,
                        "favorite_item_lv": 0,
                        "skills": {"skill1": 1, "skill2": 1, "burst": 1},
                        "overload_stats": [] 
                    }

    # ── [2] 전 구간(Phase 1 & 2) 오버로드 옵션 딕셔너리 빌드 ──
    print("🔍 [Step 2] 전 구간 오버로드 옵션 딕셔너리 빌드 중 (타입 캐스팅!)...")
    state_effects_dict = {}
    for packet in all_packets:
        data = packet.get("data") or {}
        if "state_effects" in data:
            for eff in data["state_effects"]:
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
    print("🔗 [Step 3] 잃어버린 에이스들의 살점(스킬, 오버옵)을 뼈대에 주입 중...")
    for packet in all_packets:
        data = packet.get("data") or {}
        if "character_details" in data:
            for char in data["character_details"]:
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

    print(f"\n✅ [완벽] 총 {len(merged_characters)}명의 유저 캐릭터 무결점 JOIN 완료!")
    print(f"💾 Phase 1에 갇혀있던 에이스 니케들을 구출했어! '{PROCESSED_FILE}'을 확인해♥")

if __name__ == "__main__":
    merge_blabla_data_v3()