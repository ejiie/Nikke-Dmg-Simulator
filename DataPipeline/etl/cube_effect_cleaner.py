"""blabla_static_tables.json(cubes) → cube_effect_table.json (C# enum+dict 입력).

하모니 큐브 특수효과를 파싱한다. 효과는 캐릭터 스킬과 동일 구조화 포맷
(description + {placeholder} + description_value_list). 효과 종류는 각 placeholder 바로 앞
description 구절의 키워드로 식별한다. 큐브 레벨(1~15) → 스킬 레벨(level1/2/3 배열)
→ description_value_list[valueIdx].description_value[skillLevel-1] 로 레벨별 값을 해석한다.

출력 3종 (모두 값 배열 = 큐브 레벨 1..15, index 0 = lvl 1):

1. cube_effect_table.json — C# 엔진 계약 (EffectTable.cs 가 type/values/conditional 소비).
   { tid: {name, rare, effects:[{
     type, value_placeholder, values:[v_lvl1..v_lvl15],
     description_values:{description_value_NN:[...]}, conditional, desc
   }]} }
   description_values 는 value_placeholder 를 **제외한** 나머지 설명 인자(트리거 임계값·
   지속시간 등)만 담는다 — 효과 값 배열은 values 한 곳에만 존재.

2. cube_effect_table_semantic.json — 외부 공유용 typed 버전. placeholder dict 대신
   의미 필드: effects:[{type, values, trigger:{type: ShotsFired|HpBelow|Unknown,
   values}|null, duration_sec:[...]|null, desc}]. 미분류 잔여 인자는 params 로 무손실 보존.

3. cube_effect_table_plain.json — 외부 공유용 무해석 버전. 스킬당 1행 flat 리스트:
   [{cube_id, cube_name, rarity, skill_index, description(placeholder 원문),
     parameters:{description_value_NN:[...]}}] — 효과 분류/해석 없음, 소비자가 해석.
effect type 어휘는 C# EffectType enum 과 1:1.
"""
import json
import os
import re

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_FILE = os.path.join(CURRENT_DIR, "..", "..", "Database", "raw", "blabla_static_tables.json")
PROCESSED_DIR = os.path.join(CURRENT_DIR, "..", "..", "Database", "processed")
OUT_FILE = os.path.join(PROCESSED_DIR, "cube_effect_table.json")
OUT_SEMANTIC = os.path.join(PROCESSED_DIR, "cube_effect_table_semantic.json")
OUT_PLAIN = os.path.join(PROCESSED_DIR, "cube_effect_table_plain.json")
PLACEHOLDER_RE = re.compile(r"\{description_value_(\d+)\}")
# 조건부 효과 파라미터 역할 (semantic 출력용): 트리거 = "Activates when ..." 문장 안
# placeholder, 지속시간 = "for {NN} sec" 패턴. 미지 트리거 구절 = Unknown 보존 (drift 관찰).
TRIGGER_RE = re.compile(r"Activates when ([^.{]*)\{description_value_(\d+)\}")
DURATION_RE = re.compile(r"for \{description_value_(\d+)\} sec")
TRIGGER_PHRASES = [
    ("firing", "ShotsFired"),
    ("HP is lower than", "HpBelow"),
]

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
    all_values = description_values_of(skill, skill_levels)
    conditional = len(all_values) >= 2

    def extra_values(placeholder):
        # 효과 값 배열은 values 에만 두고, 여기엔 나머지 인자만 남긴다 (중복 저장 금지).
        return {k: v for k, v in all_values.items() if k != placeholder}

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
                "values": all_values[placeholder],
                "description_values": extra_values(placeholder),
                "conditional": conditional,
                "desc": desc,
            })
        context = ""

    if effects:
        return effects

    # 미지/새 형식도 버리지 않는다. 기존 shape를 유지하고 첫 참조값(없으면 v01)을
    # no-op Unknown으로 내보내 다음 게임 버전의 enum drift를 관찰할 수 있게 한다.
    placeholder = next(iter(all_values), "description_value_01")
    nn = int(placeholder.rsplit("_", 1)[1])
    return [{
        "type": effect_type_of(desc),
        "value_placeholder": placeholder,
        "values": all_values.get(placeholder) or resolve_values(
            skill, skill_levels, nn
        ),
        "description_values": extra_values(placeholder),
        "conditional": conditional,
        "desc": desc,
    }]


def classify_extra_params(desc):
    """desc(HTML 제거, placeholder 보존)에서 부가 인자의 역할을 찾는다.

    반환: {placeholder: ("trigger", 트리거타입) | ("duration", None)}.
    """
    roles = {}
    match = TRIGGER_RE.search(desc)
    if match:
        phrase, nn = match.group(1), int(match.group(2))
        ttype = next((t for kw, t in TRIGGER_PHRASES if kw in phrase), "Unknown")
        roles[f"description_value_{nn:02d}"] = ("trigger", ttype)
    for match in DURATION_RE.finditer(desc):
        placeholder = f"description_value_{int(match.group(1)):02d}"
        roles.setdefault(placeholder, ("duration", None))
    return roles


def semantic_effect(effect):
    """엔진 계약 effect → typed 외부 공유 형식 (trigger/duration_sec 의미 필드)."""
    roles = classify_extra_params(effect["desc"])
    trigger = None
    duration = None
    leftover = {}
    for placeholder, values in effect["description_values"].items():
        role = roles.get(placeholder)
        if role and role[0] == "trigger" and trigger is None:
            trigger = {"type": role[1], "values": values}
        elif role and role[0] == "duration" and duration is None:
            duration = values
        else:
            leftover[placeholder] = values   # 미분류 잔여 — 무손실 보존
    out = {
        "type": effect["type"],
        "values": effect["values"],
        "trigger": trigger,
        "duration_sec": duration,
        "desc": effect["desc"],
    }
    if leftover:
        out["params"] = leftover
    return out


def build_plain(cubes):
    """무해석 flat 버전: 스킬당 1행, 모든 placeholder 값을 그대로 나열."""
    rows = []
    level_keys = ("level1", "level2", "level3")
    for tid, c in sorted(cubes.items(), key=lambda kv: int(kv[0])):
        skills = c.get("harmonycube_skill_group") or []
        for i, sk in enumerate(skills):
            if not sk:
                continue
            skill_levels = c.get(level_keys[i], []) if i < len(level_keys) else []
            rows.append({
                "cube_id": int(tid),
                "cube_name": c.get("name_localkey"),
                "rarity": c.get("item_rare"),
                "skill_index": i + 1,
                "description": strip_html(sk.get("description_localkey") or ""),
                "parameters": description_values_of(sk, skill_levels),
            })
    return rows


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

    semantic = {
        tid: {
            "name": v["name"],
            "rare": v["rare"],
            "effects": [semantic_effect(e) for e in v["effects"]],
        }
        for tid, v in out.items()
    }
    plain = build_plain(cubes)

    os.makedirs(PROCESSED_DIR, exist_ok=True)
    for path, payload in ((OUT_FILE, out), (OUT_SEMANTIC, semantic), (OUT_PLAIN, plain)):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    types = sorted({e["type"] for v in out.values() for e in v["effects"]})
    print(f"✅ {len(out)} 큐브 → '{OUT_FILE}' (+semantic/plain)  (effect types: {types})")


if __name__ == "__main__":
    clean_cube_effects()
