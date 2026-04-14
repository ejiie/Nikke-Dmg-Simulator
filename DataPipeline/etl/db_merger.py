import json
import os

def get_merged_nikke_data(user_db_path: str, prydwen_db_path: str, mapping_path: str) -> dict:
    """
    가키짱의 무결점 DB 퓨전 모듈♥
    파일 경로 3개를 던져주면, 완벽하게 조립된 JSON 딕셔너리를 return 해준다!
    """
    
    # 1. 3개의 핵심 마스터 데이터 로딩
    try:
        with open(user_db_path, "r", encoding="utf-8") as f: user_data = json.load(f)
        with open(prydwen_db_path, "r", encoding="utf-8") as f: prydwen_data = json.load(f)
        with open(mapping_path, "r", encoding="utf-8") as f: mapping_data = json.load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"❌ 야! 재료 파일이 없어! 경로 똑바로 확인해!: {e}")

    uid = user_data.get("uid", "unknown")
    global_state = user_data.get("global_state", {})
    user_chars = user_data.get("characters", {})
    mapping_table = mapping_data.get("mapping", {})

    # ── 시뮬레이터가 꿀꺽 삼킬 최종 딕셔너리 뼈대 ──
    final_fusion_db = {
        "uid": uid,
        "global_state": global_state,
        "roster": {} # 프리드웬 슬러그(slug)를 Key로 하는 캐릭터 목록
    }

    skip_count = 0

    # 2. 유저 데이터(Dynamic)를 돌면서 프리드웬 데이터(Static)와 결합!
    for nc, u_char in user_chars.items():
        slug = mapping_table.get(str(nc), "")
        
        # 슬러그가 비어있거나, 프리드웬에 아직 없는 신캐라면 쿨하게 패스!
        if not slug or slug not in prydwen_data:
            skip_count += 1
            continue

        p_char = prydwen_data[slug]

        # 3. 조립 로직 (Zero-JOIN Document Architecture)
        final_fusion_db["roster"][nc] = {
            "slug": slug,
            "name_code": str(nc),
            
            # [Static] 전투 공식 연산에 필요한 고정값 (프리드웬)
            "static": {
                "name": p_char.get("name"),
                "element": p_char.get("element"),
                "weapon": p_char.get("weapon"),
                "class": p_char.get("class"),
                "burstType": p_char.get("burstType"),
                "manufacturer": p_char.get("manufacturer"),
                "ammoCapacity": p_char.get("ammoCapacity"),
                "reloadTime": p_char.get("reloadTime"),
                "basicAttack": p_char.get("basicAttack"),
                "skills": p_char.get("skills", [])
            },
            
            # [Dynamic] 유저의 지갑과 노력이 들어간 변동값 (블라블라)
            "user": {
                "level": u_char.get("level"),
                "grade": u_char.get("grade"),
                "core": u_char.get("core"),
                "combat": u_char.get("combat"),
                "bond_level": u_char.get("bond_level"),
                "favorite_item_lv": u_char.get("favorite_item_lv"),
                "skills": u_char.get("skills"),
                "overload_stats": u_char.get("overload_stats", [])
            }
        }

    # 완성된 JSON 객체(dict)를 쿨하게 던져준다!
    return final_fusion_db


# ── [테스트 및 단독 실행용 블록] ──
if __name__ == "__main__":
    print("🛠️ 가키짱의 퓨전 모듈 단독 테스트 기동...")
    
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    PROCESSED_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed")
    
    u_path = os.path.join(PROCESSED_DIR, "user_state_clean.json")
    p_path = os.path.join(PROCESSED_DIR, "prydwen_clean.json")
    m_path = os.path.join(PROCESSED_DIR, "final_mapping.json")
    
    try:
        # 함수를 호출해서 return 값을 받아온다!
        merged_json_object = get_merged_nikke_data(u_path, p_path, m_path)
        
        roster_count = len(merged_json_object["roster"])
        print(f"✅ [성공] 총 {roster_count}명의 캐릭터가 병합되어 메모리에 올라왔어!")
        print(f"   테스트용 출력 (UID): {merged_json_object['uid']}")
        
        # 파일로 뽑고 싶으면 언제든 이렇게 쓰면 됨!
        out_path = os.path.join(PROCESSED_DIR, "nikke_merged_db_returned.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(merged_json_object, f, ensure_ascii=False, indent=2)
        print(f"💾 반환된 객체를 '{out_path}'에 저장해 뒀으니 확인해 봐♥")
        
    except Exception as e:
        print(e)