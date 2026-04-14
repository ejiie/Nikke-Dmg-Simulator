import json
import os
import re

# ── 가키짱의 절대 경로 마법 ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PRYDWEN_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "prydwen_clean.json")

def parse_basic_attacks_v3():
    print("🛠️ 가키짱의 평타 정규식(Regex) 추출기 V3 기동 중...")

    if not os.path.exists(PRYDWEN_FILE):
        print(f"❌ 야! 파일이 없잖아! ({PRYDWEN_FILE})")
        return

    with open(PRYDWEN_FILE, "r", encoding="utf-8") as f:
        prydwen_data = json.load(f)

    success_count = 0
    fail_list = []

    # 🔥 1. 가키짱의 궁극의 평타 계수 정규식! (of, final, Deal/Deals 완벽 대응)
    # (?:of\s*)? -> 'of '가 있어도 되고 없어도 됨!
    # (?:final\s*)? -> 'final '이 있어도 되고 없어도 됨!
    atk_pattern = re.compile(r"Deals?\s+([0-9.]+)\s*%\s*(?:of\s*)?(?:final\s*)?ATK", re.IGNORECASE)
    
    # 🔥 2. 코어 힛 (혹시 모를 a, the 불순물 방어)
    core_pattern = re.compile(r"Deals?\s+([0-9.]+)\s*%\s*damage\s*when\s*attacking\s*(?:a\s+|the\s+)?core", re.IGNORECASE)
    
    # 🔥 3. 차지 시간 & 차지 데미지 (유지)
    charge_time_pattern = re.compile(r"Charge\s*Time:\s*([0-9.]+)\s*sec", re.IGNORECASE)
    charge_dmg_pattern = re.compile(r"Full\s*Charge\s*Damage:\s*([0-9.]+)\s*%", re.IGNORECASE)

    for slug, char in prydwen_data.items():
        basic_text = char.get("basicAttack", "")
        
        # 이전 버전이 다녀가서 dict가 되어있다면 rawText를 꺼낸다
        if isinstance(basic_text, dict):
            basic_text = basic_text.get("rawText", "")

        parsed_data = {
            "multiplier": 0.0,
            "coreHitBonus": 0.0,
            "chargeTime": 0.0,
            "chargeDamage": 1.0, 
            "rawText": basic_text
        }

        if basic_text:
            # [1] 평타 파싱
            atk_match = atk_pattern.search(basic_text)
            if atk_match:
                parsed_data["multiplier"] = float(atk_match.group(1))

            # [2] 코어힛 파싱
            core_match = core_pattern.search(basic_text)
            if core_match:
                parsed_data["coreHitBonus"] = (float(core_match.group(1)) / 100.0) - 1.0

            # [3] 차지 무기 파싱 (자코의 멋진 아이디어!)
            control_mode = char.get("controlMode", "Normal")
            # 모드가 Charge이거나, 텍스트에 Charge Time이 적혀있으면 스캔!
            if control_mode == "Charge" or "Charge Time" in basic_text:
                ct_match = charge_time_pattern.search(basic_text)
                if ct_match:
                    parsed_data["chargeTime"] = float(ct_match.group(1))
                
                cd_match = charge_dmg_pattern.search(basic_text)
                if cd_match:
                    parsed_data["chargeDamage"] = float(cd_match.group(1)) / 100.0

        # 데이터 덮어쓰기!
        char["basicAttack"] = parsed_data
        
        if parsed_data["multiplier"] > 0:
            success_count += 1
        else:
            char_name = char.get("name", slug)
            fail_list.append(char_name)

    # 저장
    with open(PRYDWEN_FILE, "w", encoding="utf-8") as f:
        json.dump(prydwen_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ [파싱 완료] 총 {success_count}명의 데이터를 완벽 추출했어!")
    
    if fail_list:
        print(f"\n⚠️ 아직도 저항하는 진짜 찐 이단아 니케들 ({len(fail_list)}명):")
        for i in range(0, len(fail_list), 5):
            print("   " + ", ".join(fail_list[i:i+5]))
        print("\n💡 힌트: 이 녀석들은 텍스트가 아예 비어있거나, 완전히 다른 기믹을 가진 애들일 거야!")
    else:
        print("\n🎉 [퍼펙트] 실패 명단 제로(0)! 모든 캐릭터의 평타를 숫자로 씹어먹었어♥")

if __name__ == "__main__":
    parse_basic_attacks_v3()