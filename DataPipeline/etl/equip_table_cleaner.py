"""blabla_static_tables.json(장비 base) → equip_stat_table.json (C# StatTable 용).

ItemEquipTable 의 124 레코드(3 class × 10 tier × 4 module) 중 실제 장비만 추려
{class: {tier: {slot: {ATK, HP, DEF}}}} 형태로 펼친다. 레벨 스탯은 별도표가 아니라
C# 에서 공식 `round(base × (1 + 0.3·corp일치 + 0.1·level))` 로 계산하므로 여기선 base 만.
"""
import json
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "blabla_static_tables.json")
OUT_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "equip_stat_table.json")

MODULE_TO_SLOT = {"Module_A": "head", "Module_B": "torso", "Module_C": "arm", "Module_D": "leg"}
STAT_MAP = {"Atk": "ATK", "Hp": "HP", "Defence": "DEF"}
CLASSES = ("Attacker", "Defender", "Supporter")


def clean_equip_table():
    print("🛡️ 장비 base 표 정제 (static_tables → equip_stat_table)...")
    if not os.path.exists(RAW_FILE):
        print(f"❌ 원본 없음: {RAW_FILE} (getFromBlaLinkStatic.py 먼저 실행)")
        raise SystemExit(1)

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        records = json.load(f).get("equipment", [])

    table = {c: {} for c in CLASSES}
    count = 0
    for r in records:
        cls = r.get("class")
        slot = MODULE_TO_SLOT.get(r.get("item_sub_type"))
        rare = r.get("item_rare") or ""
        if cls not in CLASSES or not slot or not rare.startswith("T"):
            continue   # 'All' 테스트 더미 등 제외
        tier = rare[1:]   # "T10" → "10"
        stats = {"ATK": 0, "HP": 0, "DEF": 0}
        for s in r.get("stat", []):
            key = STAT_MAP.get(s.get("stat_type"))
            if key:
                stats[key] = s.get("stat_value", 0)
        table[cls].setdefault(tier, {})[slot] = stats
        count += 1

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=2)
    tiers = {c: sorted(table[c], key=int) for c in CLASSES}
    print(f"✅ {count} 레코드 → '{OUT_FILE}'  (tier: Attacker {tiers['Attacker']})")


if __name__ == "__main__":
    clean_equip_table()
