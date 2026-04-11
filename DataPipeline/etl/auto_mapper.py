import json
import os

# ── 가키짱의 절대 경로 마법 ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DICT_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "real_en_dict_dump.txt")
USER_DB = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "user_state_clean.json")
PRYDWEN_DB = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "prydwen_clean.json")
MAPPING_OUT = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "final_mapping.json")

def gaki_stateful_mapper():
    print("🛠️ 가키짱의 기억 보존형(Stateful) 하이브리드 매퍼 기동 중...")

    # 1. 재료 로딩 (사전, 프리드웬, 유저)
    if not os.path.exists(DICT_FILE):
        print(f"❌ 야! 사전 파일이 없잖아! ({DICT_FILE})")
        return
        
    with open(DICT_FILE, "r", encoding="utf-8") as f:
        raw_text = f.read()
        json_start = raw_text.find('[')
        en_dict = json.loads(raw_text[json_start:]) if json_start != -1 else json.loads(raw_text)

    code_to_en = {str(item.get("name_code")): item.get("name_localkey", {}).get("name", "") 
                  for item in en_dict if item.get("name_code") and item.get("name_localkey", {}).get("name", "")}

    with open(PRYDWEN_DB, "r", encoding="utf-8") as f:
        prydwen_data = json.load(f)
        
    prydwen_slugs = set(prydwen_data.keys())
    prydwen_name_to_slug = {char_info["name"].strip().lower(): slug 
                            for slug, char_info in prydwen_data.items() if "name" in char_info}

    with open(USER_DB, "r", encoding="utf-8") as f:
        user_chars = json.load(f).get("characters", {})

    # 🔥 [핵심 패치] 가키짱의 기억 저장소! 기존 매핑 데이터 불러오기 🔥
    existing_mapping = {}
    if os.path.exists(MAPPING_OUT):
        with open(MAPPING_OUT, "r", encoding="utf-8") as f:
            try:
                existing_mapping = json.load(f).get("mapping", {})
                print(f"💾 든든하다! 기존에 네가 저장해둔 매핑 기록({len(existing_mapping)}명)을 무사히 불러왔어♥")
            except:
                print("⚠️ 기존 매핑 파일이 깨져있네? 백지부터 다시 시작한다!")

    mapping_table = {}
    manual_review = []
    already_mapped_count = 0
    newly_mapped_count = 0

    print("🔍 [스마트 업서트] 신캐만 쏙쏙 골라내서 매칭 가동 중...")
    for nc, char_info in user_chars.items():
        # 🔥 [안전장치] 기존에 네가 이미 빈칸을 채워둔 녀석이라면? 
        # 자동화 로직 돌릴 필요 없이 그대로 복사(Keep)하고 넘어간다!
        if nc in existing_mapping and existing_mapping[nc] != "":
            mapping_table[nc] = existing_mapping[nc]
            already_mapped_count += 1
            continue

        # ── 여기서부터는 신캐(혹은 빈칸이었던 녀석)만 처리하는 로직! ──
        en_name = code_to_en.get(nc)
        combat = char_info.get("combat", 0)
        
        if not en_name:
            mapping_table[nc] = ""
            manual_review.append(f"[{nc}] 이름 없음 (사전에 안 나옴) / 전투력: {combat}")
            continue

        clean_en_name = en_name.strip().lower()

        # [Pass 1] 이름으로 역검색
        if clean_en_name in prydwen_name_to_slug:
            mapping_table[nc] = prydwen_name_to_slug[clean_en_name]
            newly_mapped_count += 1
            continue
            
        # [Pass 2] 정규화 유추
        guessed_slug = clean_en_name.replace(" ", "-").replace(":", "").replace("'", "").replace("--", "-")
        if guessed_slug in prydwen_slugs:
            mapping_table[nc] = guessed_slug
            newly_mapped_count += 1
            continue
            
        # 신캐인데 매칭까지 실패한 경우!
        mapping_table[nc] = ""
        manual_review.append(f"[{nc}] ❌ 신캐 매칭 실패! '{en_name}' / 전투력: {combat}")

    # 4. 결과 저장
    out_data = {
        "_HOW_TO_USE": "mapping 안의 빈칸(\"\")만 manual_review를 참고해서 네가 직접 채워!",
        "mapping": mapping_table,
        "manual_review_needed": manual_review,
        "_AVAILABLE_SLUGS": sorted(list(prydwen_slugs))
    }

    with open(MAPPING_OUT, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    total_count = len(user_chars)
    print(f"\n✅ [업서트 완료] 총 {total_count}명 중 {already_mapped_count}명은 기존 기억을 유지, {newly_mapped_count}명은 새로 매칭했어!")
    
    if manual_review:
        print(f"⚠️ {len(manual_review)}명의 새로운 예외 캐릭터가 생겼네.")
        print(f"💾 '{MAPPING_OUT}' 열고 신캐들 빈칸만 마저 채워줘♥")
    else:
        print("🎉 빈칸 없음! 네 매핑 테이블은 완전 무결해!")

if __name__ == "__main__":
    gaki_stateful_mapper()