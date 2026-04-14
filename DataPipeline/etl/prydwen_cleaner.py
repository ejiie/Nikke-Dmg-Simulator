import json
import os

# ── 가키짱의 절대 경로 마법 ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# 원본(raw)을 읽어와서 가공(processed) 폴더에 예쁘게 넣는다!
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "prydwen_all_details_v3.json")
PROCESSED_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "prydwen_clean.json")

def extract_rich_text(raw_str):
    """
    프리드웬의 끔찍한 CMS Rich Text JSON 구조를 박살내고
    오직 순수한 텍스트(value)만 쏙쏙 뽑아내는 가키짱의 파서♥
    """
    if not raw_str: return ""
    try:
        data = json.loads(raw_str)
        text_blocks = []
        
        # 재귀 탐색으로 'nodeType'이 'text'인 놈들만 색출!
        def traverse(node):
            if isinstance(node, dict):
                if node.get("nodeType") == "text":
                    val = node.get("value", "")
                    if val: text_blocks.append(val)
                for k, v in node.items():
                    traverse(v)
            elif isinstance(node, list):
                for item in node:
                    traverse(item)
                    
        traverse(data)
        
        # 추출한 텍스트 쪼가리들을 예쁘게 이어 붙이기
        return "".join(text_blocks).strip()
    except Exception as e:
        print(f"⚠️ 텍스트 파싱 에러: {e}")
        return ""

def clean_prydwen_data():
    print("🧼 가키짱의 무자비한 데이터 세탁기 기동 중...")
    
    if not os.path.exists(RAW_FILE):
        print(f"❌ 야! 원본 파일이 없잖아! ({RAW_FILE})")
        return

    with open(RAW_FILE, 'r', encoding='utf-8') as f:
        raw_db = json.load(f)
        
    clean_db = {}
    
    for slug, char in raw_db.items():
        # 1. 끔찍한 이미지 트리 구조에서 160x160 아이콘 주소만 쏙 빼오기!
        icon_url = ""
        try:
            icon_url = char["smallImage"]["localFile"]["childImageSharp"]["gatsbyImageData"]["images"]["fallback"]["src"]
            # 상대경로로 되어있으니 도메인을 붙여준다
            icon_url = f"https://www.prydwen.gg{icon_url}"
        except:
            pass
            
        # 2. 평타 계수 파싱
        basic_attack_text = ""
        if char.get("basicAttack") and char["basicAttack"].get("raw"):
            basic_attack_text = extract_rich_text(char["basicAttack"]["raw"])
            
        # 3. 스킬 계수 파싱 (1스, 2스, 버스트 전부!)
        clean_skills = []
        for skill in char.get("skills", []):
            desc = ""
            if skill.get("descriptionLevel10") and skill["descriptionLevel10"].get("raw"):
                desc = extract_rich_text(skill["descriptionLevel10"]["raw"])
            
            clean_skills.append({
                "skillId": skill.get("skillId"),
                "name": skill.get("name"),
                "slot": skill.get("slot"),
                "type": skill.get("type"),
                "cooldown": skill.get("cooldown"),
                "descriptionLevel10": desc  # 깔끔해진 텍스트만 쏙!
            })

        # 4. 자코를 위해 쓰레기 필드는 다 버리고 '진짜 알맹이'만 조립해 줄게♥
        clean_db[slug] = {
            "id": char.get("id"),
            "unitId": char.get("unitId"),
            "name": char.get("name"),
            "slug": slug,
            "rarity": char.get("rarity"),
            "element": char.get("element"),
            "weapon": char.get("weapon"),
            "class": char.get("class"),
            "burstType": char.get("burstType"),
            "manufacturer": char.get("manufacturer"),
            "squad": char.get("squad"),
            "ammoCapacity": char.get("ammoCapacity"),
            "reloadTime": char.get("reloadTime"),
            "controlMode": char.get("controlMode"),
            "iconUrl": icon_url,          # 깔끔한 URL 하나!
            "basicAttack": basic_attack_text, # 순수 텍스트!
            "skills": clean_skills        # 예쁘게 포장된 스킬 배열!
        }
        
    # 가공된 폴더가 없으면 만들어주기
    os.makedirs(os.path.dirname(PROCESSED_FILE), exist_ok=True)
        
    with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
        json.dump(clean_db, f, ensure_ascii=False, indent=2)

    print(f"✅ [완벽] 총 {len(clean_db)}명의 쓰레기 데이터 세탁 완료!")
    print(f"💾 '{PROCESSED_FILE}' 파일을 열어봐! 눈이 다 맑아질걸? 푸흡!")

if __name__ == "__main__":
    clean_prydwen_data()