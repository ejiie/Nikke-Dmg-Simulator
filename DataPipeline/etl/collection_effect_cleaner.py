"""blabla_static_tables.json(favorites) → collection_effect_table.json (C# 입력).

소장품(generic 컬렉션 = R 등급 favorite, 무기별 1개)의 특수효과를 파싱한다. 각 효과는
"<무기효과> ▲ {v01}. DEF ▲ {v02}" 처럼 placeholder 가 여러 개 → 각 placeholder 앞 구절로
효과 종류 식별, description_value_list[NN-1] 로 레벨별 값 해석.

출력: { weapon_type: {name, effects:[{type, values:[v_lvl1..v_lvl15]}]} }
무기별: AR=CoreDamage, MG=MaxAmmo, SR/RL=ChargeDamageMultiplier, SMG/SG=NormalAttackMultiplier
(+ 공통 Def). effect type 어휘는 cube 와 동일(C# EffectType enum).
"""
import json
import os
import re

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "blabla_static_tables.json")
OUT_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "collection_effect_table.json")

EFFECT_KEYWORDS = [
    ("Elemental Advantage Attack Damage", "ElementAdvantageDamage"),
    ("Charge Damage Multiplier", "ChargeDamageMultiplier"),
    ("Charge Damage", "ChargeDamage"),
    ("Max Ammunition Capacity", "MaxAmmo"),
    ("Max HP of Cover", "CoverHp"),
    ("Max HP", "MaxHp"),
    ("DEF", "Def"),
    ("Damage Taken", "DamageTaken"),
    ("Damage dealt when attacking core", "CoreDamage"),
    ("Normal Attack Damage Multiplier", "NormalAttackMultiplier"),
]


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def effect_type_of(text):
    for phrase, etype in EFFECT_KEYWORDS:
        if phrase in text:
            return etype
    return "Unknown"


def _f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def parse_effects(skill, skill_levels):
    """placeholder 별로 (앞 구절→효과종류, dvl[NN-1]→레벨별 값) 추출 (멀티효과)."""
    desc = skill.get("description_localkey") or ""
    dvl = skill.get("description_value_list") or []
    effects = []
    seg_text = ""
    for seg in re.split(r"(\{description_value_\d+\})", desc):
        m = re.match(r"\{description_value_(\d+)\}", seg)
        if not m:
            seg_text += seg
            continue
        nn = int(m.group(1))
        etype = effect_type_of(strip_html(seg_text))
        vals = []
        first = (dvl[nn - 1].get("description_value") if nn - 1 < len(dvl) and dvl[nn - 1] else None)
        for sl in skill_levels:
            vals.append(_f(first[sl - 1]) if sl and first and sl - 1 < len(first) else 0.0)
        effects.append({"type": etype, "values": vals})
        seg_text = ""
    return effects


def clean_collection_effects():
    print("💝 소장품 특수효과 파싱 (favorites → collection_effect_table)...")
    if not os.path.exists(RAW_FILE):
        print(f"❌ 원본 없음: {RAW_FILE}")
        raise SystemExit(1)

    favs = json.load(open(RAW_FILE, encoding="utf-8")).get("favorites", {})
    out = {}
    for fid, f in favs.items():
        # generic 컬렉션 = R 등급 + name_code 0 (무기별 1개)
        if f.get("favorite_rare") != "R" or f.get("name_code") not in (0, None):
            continue
        weapon = f.get("weapon_type")
        sg = (f.get("collection_skill_group_data") or [])
        effects = []
        for sk in sg:
            if sk:
                effects.extend(parse_effects(sk, f.get("level1") or []))
        out[weapon] = {"name": f.get("name_localkey"), "effects": effects}

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    summary = {w: [e["type"] for e in v["effects"]] for w, v in out.items()}
    print(f"✅ {len(out)} 무기 → '{OUT_FILE}'")
    for w, types in summary.items():
        print(f"   {w}: {types}")


if __name__ == "__main__":
    clean_collection_effects()
