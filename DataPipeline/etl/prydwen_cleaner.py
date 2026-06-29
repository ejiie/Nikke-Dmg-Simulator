"""Prydwen raw(신 Next.js data 객체) → prydwen_clean.json 정제.

prydwen 의 Next.js 이전(2026)으로 raw 스키마가 바뀜:
  - 필드명 snake_case (burst_type / ammo_capacity / reload_time / control_mode …)
  - 스킬 설명이 Contentful rich-text(JSON)가 아니라 **HTML** 문자열
  - 평타는 별도 필드가 아니라 skills[] 중 slot == "Normal Attack" 항목의 description
출력 shape(=clean) 은 기존과 동일하게 유지해 db_merger / C# DTO 는 무수정.
"""
import html as html_lib
import json
import os
import re
import sys

# ── 절대 경로 ──
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "prydwen_all_details_v3.json")
PROCESSED_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "prydwen_clean.json")

# 신 스키마(약어/로마) → 기존 contract(풀네임/아라비아) 정규화. db_merger·C# 가 옛 포맷 기대.
WEAPON_MAP = {
    "AR": "Assault Rifle", "RL": "Rocket Launcher", "SR": "Sniper Rifle",
    "SG": "Shotgun", "MG": "Minigun", "LMG": "Minigun", "SMG": "SMG",
}
BURST_MAP = {"I": "1", "II": "2", "III": "3"}  # "All" 등은 그대로 통과


def html_to_text(s):
    """스킬/평타 설명 HTML 을 순수 텍스트로 변환 (atk_parser 정규식·LLM 입력용)."""
    if not s:
        return ""
    # 블록 경계는 줄바꿈으로 보존
    s = re.sub(r"(?i)</p\s*>|<br\s*/?>|</li\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)          # 나머지 태그 제거
    s = html_lib.unescape(s)               # &amp; &#039; 등 복원
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]*\n+", "\n", s)
    return s.strip()


def clean_prydwen_data():
    print("🧼 prydwen 데이터 정제 시작 (Next.js 신 스키마)...")

    if not os.path.exists(RAW_FILE):
        print(f"❌ 원본 파일이 없음: {RAW_FILE}")
        sys.exit(1)

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        raw_db = json.load(f)

    clean_db = {}
    for slug, char in raw_db.items():
        skills_in = char.get("skills") or []

        # 평타 = slot 이 'Normal Attack' 인 스킬의 description (HTML → 텍스트)
        basic_attack_text = ""
        clean_skills = []
        for skill in skills_in:
            slot = (skill.get("slot") or "")
            desc = html_to_text(skill.get("description"))
            if slot.strip().lower() == "normal attack":
                basic_attack_text = desc
                continue  # 평타는 skills 배열에서 제외 (basicAttack 으로 분리)
            clean_skills.append({
                "skillId": skill.get("skillId"),   # 신 스키마엔 없음 → None
                "name": skill.get("name"),
                "slot": slot,
                "type": skill.get("type"),
                "cooldown": skill.get("cooldown"),
                "descriptionLevel10": desc,
            })

        # 아이콘: 신 스키마는 card_image / full_image (절대 URL)
        icon_url = char.get("card_image") or char.get("full_image") or ""

        clean_db[slug] = {
            "id": char.get("id"),            # 신 스키마엔 없음 → None (downstream 미사용)
            "unitId": char.get("unitId"),
            "name": char.get("name"),
            "slug": slug,
            "rarity": char.get("rarity"),
            "element": char.get("element"),
            "weapon": WEAPON_MAP.get(char.get("weapon"), char.get("weapon")),
            "class": char.get("class"),
            "burstType": BURST_MAP.get(char.get("burst_type"), char.get("burst_type")),
            "manufacturer": char.get("manufacturer"),
            "squad": char.get("squad"),
            "ammoCapacity": char.get("ammo_capacity"),
            "reloadTime": char.get("reload_time"),
            "controlMode": char.get("control_mode"),
            "iconUrl": icon_url,
            "basicAttack": basic_attack_text,
            "skills": clean_skills,
        }

    os.makedirs(os.path.dirname(PROCESSED_FILE), exist_ok=True)
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(clean_db, f, ensure_ascii=False, indent=2)

    print(f"✅ 총 {len(clean_db)}명 정제 완료 → '{PROCESSED_FILE}'")


if __name__ == "__main__":
    clean_prydwen_data()
