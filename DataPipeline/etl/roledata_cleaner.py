"""roledata(blabla_roledata.json) → roledata_clean.json (name_code 키).

prydwen_cleaner 를 대체. blablalink 공식 roledata 를 db_merger 가 쓰던 static 블록과
**동일한 키 형태**로 정제한다(name/element/weapon/class/burstType/manufacturer/ammoCapacity/
reloadTime/iconUrl/basicAttack/skills). 단 키는 slug 가 아니라 **name_code** — db_merger 가
유저데이터(name_code)와 직접 조인하므로 name_code↔slug 매핑(auto_mapper)이 더 이상 불필요.

basicAttack 단위 변환(45캐릭 prydwen 교차검증 일치):
  multiplier   = shot.damage / 100
  coreHitBonus = shot.core_damage_rate / 10000 - 1
  chargeTime   = shot.charge_time / 100
  chargeDamage = shot.full_charge_damage / 10000     (비차지 = 10000 → 1.0)
"""
import json
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "blabla_roledata.json")
PROCESSED_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "roledata_clean.json")

# roledata → 기존 contract 정규화 (prydwen_cleaner 와 동일 타깃 포맷)
WEAPON_MAP = {
    "AR": "Assault Rifle", "RL": "Rocket Launcher", "SR": "Sniper Rifle",
    "SG": "Shotgun", "MG": "Minigun", "LMG": "Minigun", "SMG": "SMG",
}
ELEMENT_MAP = {"Electronic": "Electric"}  # 나머지(Fire/Water/Wind/Iron)는 동일


def _burst_type(use_burst_skill):
    s = use_burst_skill or ""
    return s[4:] if s.startswith("Step") else s   # "Step3" → "3", "StepAll" → "All"


def _basic_attack(shot):
    shot = shot or {}
    return {
        "multiplier": (shot.get("damage") or 0) / 100.0,
        "coreHitBonus": (shot.get("core_damage_rate") or 0) / 10000.0 - 1.0,
        "chargeTime": (shot.get("charge_time") or 0) / 100.0,
        "chargeDamage": (shot.get("full_charge_damage") or 0) / 10000.0,
    }


def clean_roledata():
    print("🧼 roledata 정제 시작 (blablalink 공식 → prydwen_clean 호환, name_code 키)...")
    if not os.path.exists(RAW_FILE):
        print(f"❌ 원본 파일이 없음: {RAW_FILE}")
        raise SystemExit(1)

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        roster = json.load(f).get("roster", {})

    clean = {}
    for nc, c in roster.items():
        shot = c.get("shot") or {}
        clean[nc] = {
            "name_code": c.get("name_code"),
            "name": c.get("name"),
            "element": ELEMENT_MAP.get(c.get("element"), c.get("element")),
            "weapon": WEAPON_MAP.get((shot.get("weapon_type")), shot.get("weapon_type")),
            "class": c.get("class"),
            "burstType": _burst_type(c.get("use_burst_skill")),
            "manufacturer": (c.get("corporation") or "").capitalize() or None,
            "ammoCapacity": shot.get("max_ammo"),
            "reloadTime": (shot.get("reload_time") or 0) / 100.0,
            "iconUrl": f"portraits/si/{nc}.webp",   # 로컬 초상화(getFromBlaLinkPortraits), name_code 키
            "basicAttack": _basic_attack(shot),
            "skills": c.get("skills"),              # 공식 구조화 스킬(skill1/skill2/burst)
        }

    os.makedirs(os.path.dirname(PROCESSED_FILE), exist_ok=True)
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    print(f"✅ 총 {len(clean)}명 정제 완료 → '{PROCESSED_FILE}'")


if __name__ == "__main__":
    clean_roledata()
