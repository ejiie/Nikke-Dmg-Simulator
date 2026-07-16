"""blabla_static_tables.json(cubes) → cube_effect_table.json (C# enum+dict 입력).

하모니 큐브 특수효과를 파싱한다. 효과는 캐릭터 스킬과 동일 구조화 포맷
(description + {placeholder} + description_value_list). 효과 종류는 각 placeholder 바로 앞
description 구절의 키워드로 식별한다. 큐브 레벨(1~15) → 스킬 레벨(level1/2/3 배열)
→ description_value_list[valueIdx].description_value[skillLevel-1] 로 레벨별 값을 해석한다.

출력: { tid: {name, rare, effects:[{
  type, value_placeholder, values:[v_lvl1..v_lvl15],
  description_values:{description_value_NN:[v_lvl1..v_lvl15]}, conditional, desc
}]} }
effect type 어휘는 C# EffectType enum 과 1:1.
"""
import json
import os
import re

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "blabla_static_tables.json")
OUT_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed", "cube_effect_table.json")
PLACEHOLDER_RE = re.compile(r"\{description_value_(\d+)\}")

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


def resolve_values(skill, skill_levels, value_index=1):
    """placeholder 하나의 큐브 레벨별 값 배열을 해석한다.

    ``value_index=1`` 은 ``description_value_01`` 이다. 결손/범위 밖 값은 게임 데이터
    drift로 간주해 0(no-op)으로 보존한다.
    """
    dvl = skill.get("description_value_list") or []
    idx = value_index - 1
    source = (
        dvl[idx].get("description_value")
        if 0 <= idx < len(dvl) and isinstance(dvl[idx], dict)
        else None
    )
    out = []
    for sl in skill_levels:
        if sl and source and 0 <= sl - 1 < len(source):
            out.append(_to_float(source[sl - 1]))
        else:
            out.append(0.0)
    return out


def description_values_of(skill, skill_levels):
    """description이 실제 참조하는 모든 placeholder를 순서대로 보존한다."""
    desc = skill.get("description_localkey") or ""
    indices = []
    for match in PLACEHOLDER_RE.finditer(desc):
        nn = int(match.group(1))
        if nn not in indices:
            indices.append(nn)
    return {
        f"description_value_{nn:02d}": resolve_values(skill, skill_levels, nn)
        for nn in indices
    }


def parse_effects(skill, skill_levels):
    """스킬 description에서 실제 효과 placeholder와 전체 설명 인자를 추출한다.

    조건부 큐브는 첫 placeholder가 트리거이고 뒤 placeholder가 효과인 경우가 있다.
    예: Bastion은 v01=발사 횟수, v02=재장전 탄수이고 Assist는
    v01=HP 임계값, v02=Max HP 증가량, v03=지속시간이다. 따라서 전체 description으로
    효과 타입을 고른 뒤 v01을 붙이지 않고, 각 placeholder 바로 앞 구절로 타입을 고른다.
    """
    raw_desc = skill.get("description_localkey") or ""
    desc = strip_html(raw_desc)
    description_values = description_values_of(skill, skill_levels)
    conditional = len(description_values) >= 2
    effects = []
    context = ""

    for segment in re.split(r"(\{description_value_\d+\})", raw_desc):
        match = PLACEHOLDER_RE.fullmatch(segment)
        if not match:
            context += segment
            continue

        nn = int(match.group(1))
        placeholder = f"description_value_{nn:02d}"
        etype = effect_type_of(strip_html(context))
        if etype != "Unknown":
            effects.append({
                "type": etype,
                "value_placeholder": placeholder,
                "values": description_values[placeholder],
                "description_values": description_values,
                "conditional": conditional,
                "desc": desc,
            })
        context = ""

    if effects:
        return effects

    # 미지/새 형식도 버리지 않는다. 기존 shape를 유지하고 첫 참조값(없으면 v01)을
    # no-op Unknown으로 내보내 다음 게임 버전의 enum drift를 관찰할 수 있게 한다.
    placeholder = next(iter(description_values), "description_value_01")
    nn = int(placeholder.rsplit("_", 1)[1])
    return [{
        "type": effect_type_of(desc),
        "value_placeholder": placeholder,
        "values": description_values.get(placeholder) or resolve_values(
            skill, skill_levels, nn
        ),
        "description_values": description_values,
        "conditional": conditional,
        "desc": desc,
    }]


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
            skill_levels = c.get(level_keys[i], []) if i < len(level_keys) else []
            effects.extend(parse_effects(sk, skill_levels))
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
