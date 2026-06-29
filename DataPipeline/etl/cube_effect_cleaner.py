"""blabla_static_tables.json(cubes) → cube_effect_table.json (C# enum+dict 입력).

하모니 큐브 특수효과를 파싱한다. 효과는 캐릭터 스킬과 동일 구조화 포맷
(description + {placeholder} + description_value_list). 효과 종류는 description 키워드로
식별(StateEffect 함수정의는 CDN 미노출). 큐브 레벨(1~15) → 스킬 레벨(level1/2/3 배열)
→ description_value_list[valueIdx].description_value[skillLevel-1] 로 레벨별 값 해석.

출력: { tid: {name, rare, effects:[{type, values:[v_lvl1..v_lvl15], conditional?}]} }
effect type 어휘는 C# EffectType enum 과 1:1.
"""
import json
import os
import re

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "blabla_static_tables.json")
OUT_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "cube_effect_table.json")

# description 구절 → EffectType (순서 중요: 더 긴/구체적 구절 먼저)
EFFECT_KEYWORDS = [
    ("Hit Rate", "HitRate"),
    ("Elemental Advantage Attack Damage", "ElementAdvantageDamage"),
    ("Charge Damage Multiplier", "ChargeDamageMultiplier"),
    ("Charge Damage", "ChargeDamage"),
    ("Charge Speed", "ChargeSpeed"),
    ("Reload Speed", "ReloadSpeed"),
    ("Max Ammunition Capacity", "MaxAmmo"),
    ("Burst Gauge filling speed", "BurstGauge"),
    ("Max HP of Cover", "CoverHp"),
    ("Max HP", "MaxHp"),
    ("DEF", "Def"),
    ("Potency of HP granted", "HealPotency"),
    ("Damage Taken", "DamageTaken"),
    ("Damage to Parts", "PartsDamage"),
    ("Pierce Damage", "PierceDamage"),
    ("True Damage", "TrueDamage"),
    ("Damage dealt when attacking core", "CoreDamage"),
    ("Normal Attack Damage Multiplier", "NormalAttackMultiplier"),
    ("Reload", "ReloadRounds"),   # Bastion: "Reload ▲ N round(s)" — 위 키워드 다 미스 시
]


def strip_html(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def effect_type_of(desc):
    for phrase, etype in EFFECT_KEYWORDS:
        if phrase in desc:
            return etype
    return "Unknown"


def _to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def resolve_values(skill, skill_levels):
    """큐브 레벨별 값 배열. skill_levels[n] = 큐브 레벨 n+1 에서의 이 스킬 레벨(0=미활성)."""
    dvl = skill.get("description_value_list") or []
    # 첫 placeholder({description_value_01}) 기준 (대부분 단일효과)
    first = dvl[0].get("description_value") if dvl and dvl[0] else None
    out = []
    for sl in skill_levels:
        if sl and first and sl - 1 < len(first):
            out.append(_to_float(first[sl - 1]))
        else:
            out.append(0.0)
    return out


def clean_cube_effects():
    print("🧊 큐브 특수효과 파싱 (cubes → cube_effect_table)...")
    if not os.path.exists(RAW_FILE):
        print(f"❌ 원본 없음: {RAW_FILE}")
        raise SystemExit(1)

    cubes = json.load(open(RAW_FILE, encoding="utf-8")).get("cubes", {})
    out = {}
    level_keys = ("level1", "level2", "level3")

    for tid, c in cubes.items():
        skills = c.get("harmonycube_skill_group") or []
        effects = []
        for i, sk in enumerate(skills):
            if not sk:
                continue
            desc = strip_html(sk.get("description_localkey"))
            etype = effect_type_of(desc)
            skill_levels = c.get(level_keys[i], []) if i < len(level_keys) else []
            values = resolve_values(sk, skill_levels)
            # 조건부(Bastion "N발 발사→", Assist "HP<X%→") = placeholder 2개+ → 표식
            dvl = sk.get("description_value_list") or []
            conditional = sum(1 for d in dvl if d) >= 2
            effects.append({
                "type": etype,
                "values": values,
                "conditional": conditional,
                "desc": desc,
            })
        out[tid] = {
            "name": c.get("name_localkey"),
            "rare": c.get("item_rare"),
            "effects": effects,
        }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    types = sorted({e["type"] for v in out.values() for e in v["effects"]})
    print(f"✅ {len(out)} 큐브 → '{OUT_FILE}'  (effect types: {types})")


if __name__ == "__main__":
    clean_cube_effects()
