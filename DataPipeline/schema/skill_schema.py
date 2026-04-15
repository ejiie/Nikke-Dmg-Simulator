"""
DataPipeline/schema/skill_schema.py

NIKKE 스킬 텍스트 → 구조화 JSON 변환을 위한 Pydantic 스키마 + LLM Few-Shot 예시.

──────────────────────────────────────────────────────────────
대미지 공식 (v2 확정판)
──────────────────────────────────────────────────────────────
Damage = (FinalAtk - FinalDef)
       × (1 + fullBurst + properDist + Σcrit_dmg + coreHitBase + Σcore_hit_buff)   [B2]
       × (1 + Σattack_dmg                                                          [B3]
               + Σpierce_dmg     ← 관통탄 시에만  (condition: piercing_attack)
               + Σparts_dmg      ← 파츠 힛 시에만 (condition: hitting_parts)
               + Σdot_dmg        ← DoT 틱 시에만  (condition: dot_instance)
               + Σsequential_dmg ← 순차 대미지 시에만 (condition: sequential_hit)
         )
       × (1 + Σdamage_taken + Σdistrib_dmg)                                        [B4]
               ↑ distrib_dmg만 예외: B3가 아닌 B4에 속함 (condition: distribution_attack)
       × (1 + Σstrong_elem)      ← 속성 유리 시에만                               [B5]
       × 계수

Simulator constants (런타임 주입, 스킬 파싱 대상 아님):
  fullBurst  = 0.5  (Full Burst Time 활성 시)
  properDist = 0.3  (적정 거리 / 특정 부위 공격 시)
  coreHitBase: atk_parser.py 가 basicAttack 텍스트에서 파싱
"""

from __future__ import annotations

import json
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# 1. Enums
# ─────────────────────────────────────────────────────────────

class StatType(str, Enum):
    # ── Final ATK modifiers ───────────────────────────────────
    ATK_PCT              = "atk_pct"             # ATK × (1 + Σatk_pct) 에 가산
    ATK_FLAT             = "atk_flat"            # ATK에 절대값 가산
    ATK_RATIO_OF_CASTER  = "atk_ratio_of_caster" # (value% × caster FinalAtk) → 아군 FinalAtk에 평탄 가산

    # ── Defense ───────────────────────────────────────────────
    DEF_PCT              = "def_pct"
    DEF_FLAT             = "def_flat"

    # ── HP ────────────────────────────────────────────────────
    MAX_HP_PCT           = "max_hp_pct"
    MAX_HP_FLAT          = "max_hp_flat"

    # ── B2 : Crit / Core ─────────────────────────────────────
    CRIT_RATE            = "crit_rate"           # 치명타 확률 (브래킷 없음, 독립 계산)
    CRIT_DMG             = "crit_dmg"            # B2 가산항
    CORE_HIT_BUFF        = "core_hit_buff"       # B2 가산항 (스킬 버프; coreHitBase와 별도)

    # ── B3 : Attack Damage 계열 ───────────────────────────────
    ATTACK_DMG           = "attack_dmg"          # 공격 대미지 증가 (모든 공격에 공통)
    PIERCE_DMG           = "pierce_dmg"          # 관통 대미지 증가 (관통탄 시에만)
    PARTS_DMG            = "parts_dmg"           # 파츠 대미지 증가 (파츠 힛 시에만)
    DOT_DMG              = "dot_dmg"             # 지속 대미지 증가 (DoT 틱 시에만)
    SEQUENTIAL_DMG       = "sequential_dmg"      # 순차 대미지 증가 (순차 대미지 시에만)

    # ── B4 : Damage Taken / Distribution ─────────────────────
    DAMAGE_TAKEN         = "damage_taken"        # 받는 대미지 증가 (무조건 B4 가산)
    DISTRIB_DMG          = "distrib_dmg"         # 분배 대미지 증가 (B4 가산, 분배 공격 시에만)

    # ── B5 : Strong Element ───────────────────────────────────
    STRONG_ELEM          = "strong_elem"         # 속성 유리 대미지 증가

    # ── 브래킷 외 스탯 ────────────────────────────────────────
    AMMO_CAPACITY        = "ammo_capacity"
    RELOAD_SPEED         = "reload_speed"
    TRUE_DMG             = "true_dmg"            # 방어 무시 대미지 (별도 계산, 브래킷 없음)
    HP_POTENCY           = "hp_potency"          # 회복/실드 효율 증가
    BURST_GAUGE          = "burst_gauge"         # 버스트 게이지 충전
    BURST_COOLDOWN       = "burst_cooldown"      # 버스트 스킬 쿨다운 감소 (단위: 초)
    HEAL                 = "heal"                # HP 회복
    SHIELD               = "shield"             # 실드 부여
    CHARGE_SPEED         = "charge_speed"        # 차지 무기 차지 속도
    MOVE_SPEED           = "move_speed"
    IMMUNITY             = "immunity"            # CC·디버프 면역


class FormulaBracket(str, Enum):
    B2_CRIT_CORE   = "b2_crit_core"    # (1 + ... + Σcrit_dmg + Σcore_hit_buff)
    B3_ATTACK_DMG  = "b3_attack_dmg"   # (1 + Σattack_dmg [+pierce][+parts][+dot][+sequential])
    B4_DMG_TAKEN   = "b4_dmg_taken"    # (1 + Σdamage_taken + Σdistrib_dmg)
    B5_STRONG_ELEM = "b5_strong_elem"  # (1 + Σstrong_elem)


class ConditionOn(str, Enum):
    """효과가 적용되는 추가 조건. TriggerType을 보완한다."""
    NONE                 = "none"
    # B3 sub-type conditions
    PIERCING_ATTACK      = "piercing_attack"      # 관통탄 발사 시
    HITTING_PARTS        = "hitting_parts"        # 보스 파츠 힛 시
    DOT_INSTANCE         = "dot_instance"         # DoT 틱 인스턴스 시
    SEQUENTIAL_HIT       = "sequential_hit"       # 순차 대미지 인스턴스 시
    # B4 sub-type condition
    DISTRIBUTION_ATTACK  = "distribution_attack"  # 분배 대미지 인스턴스 시
    # Situational
    FULL_BURST           = "full_burst"           # Full Burst Time 활성 중
    HP_BELOW_PCT         = "hp_below_pct"         # 자신/대상 HP < threshold_pct
    HP_ABOVE_PCT         = "hp_above_pct"         # 자신/대상 HP > threshold_pct
    IN_COVER             = "in_cover"
    OUT_OF_COVER         = "out_of_cover"
    ENEMY_DEBUFFED       = "enemy_debuffed"       # 대상에 디버프 존재 시


class ValueBasis(str, Enum):
    PCT                  = "pct"                  # 스탯의 %
    FLAT                 = "flat"                 # 절대값
    PCT_OF_CASTER_ATK    = "pct_of_caster_atk"   # (value% × 시전자 FinalAtk)
    PCT_OF_MAX_HP        = "pct_of_max_hp"        # (value% × 대상 MaxHP)
    PCT_OF_CURRENT_HP    = "pct_of_current_hp"    # (value% × 현재 HP)
    SECONDS              = "seconds"              # 초 단위 (쿨다운 등)


class TriggerType(str, Enum):
    PASSIVE              = "passive"              # 항상 활성
    ENTER_BATTLE         = "enter_battle"         # 전투 시작 / 스킬 발동 시
    SKILL_CAST           = "skill_cast"           # 스킬 사용 시
    BURST_START          = "burst_start"          # Full Burst 시작 시
    BURST_END            = "burst_end"            # Full Burst 종료 시
    BURST_ACTIVE         = "burst_active"         # Full Burst 지속 중
    ON_HIT               = "on_hit"               # 명중 시
    ON_KILL              = "on_kill"              # 킬 시
    LAST_BULLET_HIT      = "last_bullet_hit"      # 마지막 탄환 명중 시
    ON_RELOAD            = "on_reload"            # 재장전 시
    FULL_MAGAZINE        = "full_magazine"        # 탄창 가득 찼을 때
    LOW_AMMO             = "low_ammo"             # 탄약 임계치 이하
    ALLY_HIT             = "ally_hit"             # 아군이 피격 시
    ALLY_KILL            = "ally_kill"            # 아군 킬 시
    HP_DROPS_BELOW       = "hp_drops_below"       # HP가 임계치 이하로 감소 시
    HP_ABOVE             = "hp_above"             # HP가 임계치 이상인 동안
    STACK_THRESHOLD      = "stack_threshold"      # 버프 스택 수 도달 시
    EFFECT_EXPIRY        = "effect_expiry"        # 버프/디버프 만료 시


class TargetType(str, Enum):
    SELF                 = "self"
    SINGLE_ALLY          = "single_ally"
    ALL_ALLIES           = "all_allies"
    ATTACKER             = "attacker"             # 명중 이벤트를 발생시킨 아군
    MOST_INJURED_ALLY    = "most_injured_ally"
    RANDOM_ALLY          = "random_ally"
    SINGLE_ENEMY         = "single_enemy"
    ALL_ENEMIES          = "all_enemies"
    RANDOM_ENEMY         = "random_enemy"
    HIT_TARGET           = "hit_target"           # 명중된 특정 적


class ActionType(str, Enum):
    BUFF                 = "buff"
    DEBUFF               = "debuff"
    DEAL_DAMAGE          = "deal_damage"
    HEAL                 = "heal"
    GRANT_SHIELD         = "grant_shield"
    FILL_BURST_GAUGE     = "fill_burst_gauge"
    REDUCE_COOLDOWN      = "reduce_cooldown"
    RESTORE_AMMO         = "restore_ammo"
    GRANT_IMMUNITY       = "grant_immunity"
    DISPEL               = "dispel"


# ─────────────────────────────────────────────────────────────
# 2. STAT_BRACKET lookup
#    (formula_bracket, default_condition_on) — 시뮬레이터 런타임 참조용
# ─────────────────────────────────────────────────────────────

STAT_BRACKET: dict[str, tuple[Optional[FormulaBracket], ConditionOn]] = {
    # B2
    StatType.CRIT_RATE:        (None,                          ConditionOn.NONE),
    StatType.CRIT_DMG:         (FormulaBracket.B2_CRIT_CORE,  ConditionOn.NONE),
    StatType.CORE_HIT_BUFF:    (FormulaBracket.B2_CRIT_CORE,  ConditionOn.NONE),

    # B3 — attack_dmg 계열
    StatType.ATTACK_DMG:       (FormulaBracket.B3_ATTACK_DMG, ConditionOn.NONE),
    StatType.PIERCE_DMG:       (FormulaBracket.B3_ATTACK_DMG, ConditionOn.PIERCING_ATTACK),
    StatType.PARTS_DMG:        (FormulaBracket.B3_ATTACK_DMG, ConditionOn.HITTING_PARTS),
    StatType.DOT_DMG:          (FormulaBracket.B3_ATTACK_DMG, ConditionOn.DOT_INSTANCE),
    StatType.SEQUENTIAL_DMG:   (FormulaBracket.B3_ATTACK_DMG, ConditionOn.SEQUENTIAL_HIT),

    # B4
    StatType.DAMAGE_TAKEN:     (FormulaBracket.B4_DMG_TAKEN,  ConditionOn.NONE),
    StatType.DISTRIB_DMG:      (FormulaBracket.B4_DMG_TAKEN,  ConditionOn.DISTRIBUTION_ATTACK),

    # B5
    StatType.STRONG_ELEM:      (FormulaBracket.B5_STRONG_ELEM, ConditionOn.NONE),

    # 브래킷 없음
    StatType.ATK_PCT:          (None, ConditionOn.NONE),
    StatType.ATK_FLAT:         (None, ConditionOn.NONE),
    StatType.ATK_RATIO_OF_CASTER: (None, ConditionOn.NONE),
    StatType.DEF_PCT:          (None, ConditionOn.NONE),
    StatType.DEF_FLAT:         (None, ConditionOn.NONE),
    StatType.MAX_HP_PCT:       (None, ConditionOn.NONE),
    StatType.MAX_HP_FLAT:      (None, ConditionOn.NONE),
    StatType.AMMO_CAPACITY:    (None, ConditionOn.NONE),
    StatType.RELOAD_SPEED:     (None, ConditionOn.NONE),
    StatType.TRUE_DMG:         (None, ConditionOn.NONE),
    StatType.HP_POTENCY:       (None, ConditionOn.NONE),
    StatType.BURST_GAUGE:      (None, ConditionOn.NONE),
    StatType.BURST_COOLDOWN:   (None, ConditionOn.NONE),
    StatType.HEAL:             (None, ConditionOn.NONE),
    StatType.SHIELD:           (None, ConditionOn.NONE),
    StatType.CHARGE_SPEED:     (None, ConditionOn.NONE),
    StatType.MOVE_SPEED:       (None, ConditionOn.NONE),
    StatType.IMMUNITY:         (None, ConditionOn.NONE),
}


# ─────────────────────────────────────────────────────────────
# 3. Pydantic Models
# ─────────────────────────────────────────────────────────────

class EffectBlock(BaseModel):
    """단일 원자 효과: 스탯 하나, 트리거 하나, 대상 하나."""
    stat: StatType
    action: ActionType
    value: float = Field(..., description="수치 크기 (예: 15.22 → 15.22%)")
    value_basis: ValueBasis = ValueBasis.PCT
    formula_bracket: Optional[FormulaBracket] = Field(
        default=None,
        description="이 스탯이 속하는 대미지 공식 브래킷. 비대미지 스탯은 None."
    )
    target: TargetType
    trigger: TriggerType
    duration: Optional[float] = Field(
        default=None,
        description="지속 시간(초). None = 영구 / 패시브."
    )
    max_stacks: Optional[int] = Field(
        default=None,
        description="최대 버프 스택 수. None = 스택 없음."
    )
    stack_increment: Optional[int] = Field(
        default=None,
        description="트리거당 획득 스택 수."
    )
    internal_cooldown: Optional[float] = Field(
        default=None,
        description="트리거 최소 간격(초, ICD)."
    )
    condition_on: ConditionOn = ConditionOn.NONE
    condition_threshold_pct: Optional[float] = Field(
        default=None,
        description="hp_below_pct / hp_above_pct 조건의 HP 임계치(%)."
    )
    notes: Optional[str] = Field(
        default=None,
        description="파싱 특이사항 또는 런타임 주의사항."
    )


class StackConditionBranch(BaseModel):
    """Once / Twice / Three times 패턴 스킬의 스택별 분기."""
    threshold: int = Field(..., description="이 분기가 활성화되는 스택 수.")
    effects: List[EffectBlock]


class SkillParsed(BaseModel):
    """LLM 스킬 파서의 최상위 출력 모델. 스킬 하나(S1/S2/Burst)에 대응."""
    skill_name: str
    skill_slot: str = Field(..., description="'s1', 's2', 'burst' 중 하나.")
    raw_text: str = Field(..., description="원문 그대로 보존. 수치 교차검증용.")
    effects: List[EffectBlock] = Field(
        default_factory=list,
        description="무조건 / 기본 효과 목록."
    )
    stack_conditions: Optional[List[StackConditionBranch]] = Field(
        default=None,
        description="Once/Twice/Three times 분기가 있는 스킬에서만 사용. 없으면 None."
    )
    parsing_notes: Optional[str] = Field(
        default=None,
        description="LLM의 파싱 판단 근거 또는 엣지케이스 메모."
    )


# ─────────────────────────────────────────────────────────────
# 4. Few-Shot Examples
#    형식: (input_text: str, expected_output: dict)
#    expected_output 은 SkillParsed JSON 스키마를 만족해야 함
# ─────────────────────────────────────────────────────────────

FEW_SHOT_EXAMPLES: list[tuple[str, dict]] = [
    # ── 1. ATK 버프 — 전체 아군, skill_cast, 시간 제한 ─────────────────────────
    (
        "Active: Increases ATK of all allies by 5.28% for 5 sec.",
        {
            "skill_name": "Power Surge",
            "skill_slot": "s1",
            "raw_text": "Active: Increases ATK of all allies by 5.28% for 5 sec.",
            "effects": [{
                "stat": "atk_pct", "action": "buff",
                "value": 5.28, "value_basis": "pct",
                "formula_bracket": None,
                "target": "all_allies", "trigger": "skill_cast",
                "duration": 5.0, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),

    # ── 2. 자신 패시브 치명타율 ────────────────────────────────────────────────
    (
        "Passive: Increases own Crit Rate by 11.34%.",
        {
            "skill_name": "Sharp Eye",
            "skill_slot": "s1",
            "raw_text": "Passive: Increases own Crit Rate by 11.34%.",
            "effects": [{
                "stat": "crit_rate", "action": "buff",
                "value": 11.34, "value_basis": "pct",
                "formula_bracket": None,
                "target": "self", "trigger": "passive",
                "duration": None, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),

    # ── 3. 치명타 대미지 버프 — B2, skill_cast, 시간 제한 ────────────────────
    (
        "Active: Increases Crit DMG of all allies by 15.55% for 10 sec.",
        {
            "skill_name": "Lethal Shot",
            "skill_slot": "s2",
            "raw_text": "Active: Increases Crit DMG of all allies by 15.55% for 10 sec.",
            "effects": [{
                "stat": "crit_dmg", "action": "buff",
                "value": 15.55, "value_basis": "pct",
                "formula_bracket": "b2_crit_core",
                "target": "all_allies", "trigger": "skill_cast",
                "duration": 10.0, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),

    # ── 4. 코어 힛 대미지 버프 — B2, burst_active, condition_on=full_burst ───
    (
        "Active: During Full Burst Time, increases Core Hit DMG of all allies by 7.97%.",
        {
            "skill_name": "Bullseye",
            "skill_slot": "burst",
            "raw_text": "Active: During Full Burst Time, increases Core Hit DMG of all allies by 7.97%.",
            "effects": [{
                "stat": "core_hit_buff", "action": "buff",
                "value": 7.97, "value_basis": "pct",
                "formula_bracket": "b2_crit_core",
                "target": "all_allies", "trigger": "burst_active",
                "duration": None, "condition_on": "full_burst"
            }],
            "stack_conditions": None
        }
    ),

    # ── 5. 공격 대미지 증가 — B3, 패시브 ─────────────────────────────────────
    (
        "Passive: Increases Attack Damage by 14.33%.",
        {
            "skill_name": "Aggression",
            "skill_slot": "s1",
            "raw_text": "Passive: Increases Attack Damage by 14.33%.",
            "effects": [{
                "stat": "attack_dmg", "action": "buff",
                "value": 14.33, "value_basis": "pct",
                "formula_bracket": "b3_attack_dmg",
                "target": "self", "trigger": "passive",
                "duration": None, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),

    # ── 6. 관통 대미지 증가 — B3, condition_on=piercing_attack ───────────────
    (
        "Passive: Increases Pierce Damage by 21.06%.",
        {
            "skill_name": "Armor Piercer",
            "skill_slot": "s1",
            "raw_text": "Passive: Increases Pierce Damage by 21.06%.",
            "effects": [{
                "stat": "pierce_dmg", "action": "buff",
                "value": 21.06, "value_basis": "pct",
                "formula_bracket": "b3_attack_dmg",
                "target": "self", "trigger": "passive",
                "duration": None, "condition_on": "piercing_attack",
                "notes": "B3 가산, 관통탄 발사 시에만 적용. attack_dmg와 동일 브래킷."
            }],
            "stack_conditions": None
        }
    ),

    # ── 7. 파츠 대미지 증가 — B3, condition_on=hitting_parts ─────────────────
    (
        "Passive: Increases Damage to Parts by 9.56%.",
        {
            "skill_name": "Weak Spot",
            "skill_slot": "s1",
            "raw_text": "Passive: Increases Damage to Parts by 9.56%.",
            "effects": [{
                "stat": "parts_dmg", "action": "buff",
                "value": 9.56, "value_basis": "pct",
                "formula_bracket": "b3_attack_dmg",
                "target": "self", "trigger": "passive",
                "duration": None, "condition_on": "hitting_parts",
                "notes": "B3 가산, 보스 파츠 힛 시에만 적용."
            }],
            "stack_conditions": None
        }
    ),

    # ── 8. 지속 대미지 증가 — B3, condition_on=dot_instance ──────────────────
    (
        "Passive: Increases Continuous Damage by 15.46%.",
        {
            "skill_name": "Toxin",
            "skill_slot": "s2",
            "raw_text": "Passive: Increases Continuous Damage by 15.46%.",
            "effects": [{
                "stat": "dot_dmg", "action": "buff",
                "value": 15.46, "value_basis": "pct",
                "formula_bracket": "b3_attack_dmg",
                "target": "self", "trigger": "passive",
                "duration": None, "condition_on": "dot_instance",
                "notes": "B3 가산, DoT 틱 인스턴스에만 적용. pierce_dmg·parts_dmg는 DoT에 미적용."
            }],
            "stack_conditions": None
        }
    ),

    # ── 9. 순차 대미지 증가 — B3, condition_on=sequential_hit ────────────────
    (
        "Passive: Increases Sequential Damage by 12.80%.",
        {
            "skill_name": "Momentum",
            "skill_slot": "s1",
            "raw_text": "Passive: Increases Sequential Damage by 12.80%.",
            "effects": [{
                "stat": "sequential_dmg", "action": "buff",
                "value": 12.80, "value_basis": "pct",
                "formula_bracket": "b3_attack_dmg",
                "target": "self", "trigger": "passive",
                "duration": None, "condition_on": "sequential_hit",
                "notes": "B3 가산, 순차 대미지 인스턴스에만 적용."
            }],
            "stack_conditions": None
        }
    ),

    # ── 10. 분배 대미지 증가 — B4(예외!), condition_on=distribution_attack ──
    (
        "Passive: Increases Distributed Damage by 18.34%.",
        {
            "skill_name": "Scatter",
            "skill_slot": "s2",
            "raw_text": "Passive: Increases Distributed Damage by 18.34%.",
            "effects": [{
                "stat": "distrib_dmg", "action": "buff",
                "value": 18.34, "value_basis": "pct",
                "formula_bracket": "b4_dmg_taken",
                "target": "self", "trigger": "passive",
                "duration": None, "condition_on": "distribution_attack",
                "notes": "attack_dmg 계열이지만 유일하게 B4에 속함. damage_taken과 같은 브래킷에서 가산."
            }],
            "stack_conditions": None
        }
    ),

    # ── 11. 받는 대미지 증가 (적 디버프) — B4 ────────────────────────────────
    (
        "Active: Affected enemies take 5.79% more damage for 10 sec.",
        {
            "skill_name": "Vulnerability",
            "skill_slot": "s2",
            "raw_text": "Active: Affected enemies take 5.79% more damage for 10 sec.",
            "effects": [{
                "stat": "damage_taken", "action": "debuff",
                "value": 5.79, "value_basis": "pct",
                "formula_bracket": "b4_dmg_taken",
                "target": "all_enemies", "trigger": "skill_cast",
                "duration": 10.0, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),

    # ── 12. 마지막 탄환 명중 시 ATK 버프 ─────────────────────────────────────
    (
        "Passive: When the last bullet hits, increases ATK of all allies by 15.22% for 10 sec.",
        {
            "skill_name": "Final Round",
            "skill_slot": "s1",
            "raw_text": "Passive: When the last bullet hits, increases ATK of all allies by 15.22% for 10 sec.",
            "effects": [{
                "stat": "atk_pct", "action": "buff",
                "value": 15.22, "value_basis": "pct",
                "formula_bracket": None,
                "target": "all_allies", "trigger": "last_bullet_hit",
                "duration": 10.0, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),

    # ── 13. HP 조건부 자신 ATK 버프 ──────────────────────────────────────────
    (
        "Passive: When own HP falls below 30%, increases own ATK by 25.74%.",
        {
            "skill_name": "Last Stand",
            "skill_slot": "s1",
            "raw_text": "Passive: When own HP falls below 30%, increases own ATK by 25.74%.",
            "effects": [{
                "stat": "atk_pct", "action": "buff",
                "value": 25.74, "value_basis": "pct",
                "formula_bracket": None,
                "target": "self", "trigger": "hp_drops_below",
                "duration": None,
                "condition_on": "hp_below_pct",
                "condition_threshold_pct": 30.0
            }],
            "stack_conditions": None
        }
    ),

    # ── 14. 스택 조건 분기 — Once / Twice / Three times ──────────────────────
    (
        "Passive: ▲ Activates when the skill effect of Quantum Detonation stacks.\n"
        "Once: Increases ATK of all allies by 5.93%.\n"
        "Twice: Increases ATK of all allies by 8.69%.\n"
        "Three times: Increases ATK of all allies by 10.52%.",
        {
            "skill_name": "Overcharge",
            "skill_slot": "s2",
            "raw_text": (
                "Passive: ▲ Activates when the skill effect of Quantum Detonation stacks.\n"
                "Once: Increases ATK of all allies by 5.93%.\n"
                "Twice: Increases ATK of all allies by 8.69%.\n"
                "Three times: Increases ATK of all allies by 10.52%."
            ),
            "effects": [],
            "stack_conditions": [
                {
                    "threshold": 1,
                    "effects": [{
                        "stat": "atk_pct", "action": "buff",
                        "value": 5.93, "value_basis": "pct",
                        "formula_bracket": None,
                        "target": "all_allies", "trigger": "stack_threshold",
                        "duration": None, "max_stacks": 3, "condition_on": "none"
                    }]
                },
                {
                    "threshold": 2,
                    "effects": [{
                        "stat": "atk_pct", "action": "buff",
                        "value": 8.69, "value_basis": "pct",
                        "formula_bracket": None,
                        "target": "all_allies", "trigger": "stack_threshold",
                        "duration": None, "max_stacks": 3, "condition_on": "none"
                    }]
                },
                {
                    "threshold": 3,
                    "effects": [{
                        "stat": "atk_pct", "action": "buff",
                        "value": 10.52, "value_basis": "pct",
                        "formula_bracket": None,
                        "target": "all_allies", "trigger": "stack_threshold",
                        "duration": None, "max_stacks": 3, "condition_on": "none"
                    }]
                }
            ],
            "parsing_notes": "스택 분기는 누적이 아닌 교체 방식. 최대 스택 = 3. effects[]는 비워두고 stack_conditions에만 기재."
        }
    ),

    # ── 15. 시전자 ATK 비율 전이 — pct_of_caster_atk ─────────────────────────
    (
        "Passive: Adds 27.82% of own ATK as additional ATK to all allies within attack range.",
        {
            "skill_name": "Battle Sync",
            "skill_slot": "s2",
            "raw_text": "Passive: Adds 27.82% of own ATK as additional ATK to all allies within attack range.",
            "effects": [{
                "stat": "atk_ratio_of_caster", "action": "buff",
                "value": 27.82, "value_basis": "pct_of_caster_atk",
                "formula_bracket": None,
                "target": "all_allies", "trigger": "passive",
                "duration": None, "condition_on": "none",
                "notes": "런타임: (27.82% × 시전자 FinalAtk)를 아군 FinalAtk에 평탄 가산. 배율이 아님."
            }],
            "stack_conditions": None
        }
    ),

    # ── 16. 회복 — MaxHP의 % ─────────────────────────────────────────────────
    (
        "Active: Recovers HP of all allies by 3.46% of Max HP.",
        {
            "skill_name": "Field Medic",
            "skill_slot": "burst",
            "raw_text": "Active: Recovers HP of all allies by 3.46% of Max HP.",
            "effects": [{
                "stat": "heal", "action": "heal",
                "value": 3.46, "value_basis": "pct_of_max_hp",
                "formula_bracket": None,
                "target": "all_allies", "trigger": "skill_cast",
                "duration": None, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),

    # ── 17. 버스트 게이지 충전 ────────────────────────────────────────────────
    (
        "Passive: Fills Burst Gauge by 17.28% when entering battle.",
        {
            "skill_name": "Energy Surge",
            "skill_slot": "s1",
            "raw_text": "Passive: Fills Burst Gauge by 17.28% when entering battle.",
            "effects": [{
                "stat": "burst_gauge", "action": "fill_burst_gauge",
                "value": 17.28, "value_basis": "pct",
                "formula_bracket": None,
                "target": "self", "trigger": "enter_battle",
                "duration": None, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),

    # ── 18. 복합 효과 — Crit DMG + Attack DMG 동시 버프 ──────────────────────
    (
        "Active: For 10 sec, increases Crit DMG of all allies by 15.55% and Attack Damage by 11.32%.",
        {
            "skill_name": "Double Edge",
            "skill_slot": "s2",
            "raw_text": "Active: For 10 sec, increases Crit DMG of all allies by 15.55% and Attack Damage by 11.32%.",
            "effects": [
                {
                    "stat": "crit_dmg", "action": "buff",
                    "value": 15.55, "value_basis": "pct",
                    "formula_bracket": "b2_crit_core",
                    "target": "all_allies", "trigger": "skill_cast",
                    "duration": 10.0, "condition_on": "none"
                },
                {
                    "stat": "attack_dmg", "action": "buff",
                    "value": 11.32, "value_basis": "pct",
                    "formula_bracket": "b3_attack_dmg",
                    "target": "all_allies", "trigger": "skill_cast",
                    "duration": 10.0, "condition_on": "none"
                }
            ],
            "stack_conditions": None
        }
    ),

    # ── 19. 트루 대미지 — 방어 무시 ──────────────────────────────────────────
    (
        "Active: Deals True Damage to 1 enemy equal to 128.93% ATK.",
        {
            "skill_name": "Null Buster",
            "skill_slot": "burst",
            "raw_text": "Active: Deals True Damage to 1 enemy equal to 128.93% ATK.",
            "effects": [{
                "stat": "true_dmg", "action": "deal_damage",
                "value": 128.93, "value_basis": "pct",
                "formula_bracket": None,
                "target": "single_enemy", "trigger": "skill_cast",
                "duration": None, "condition_on": "none",
                "notes": "방어 무시 대미지. 공식 브래킷 없음. FinalAtk × 128.93%로 단독 계산."
            }],
            "stack_conditions": None
        }
    ),

    # ── 20. 버스트 쿨다운 감소 ────────────────────────────────────────────────
    (
        "Passive: Reduces Cooldown of Burst Skill by 2.58 sec.",
        {
            "skill_name": "Rush",
            "skill_slot": "s1",
            "raw_text": "Passive: Reduces Cooldown of Burst Skill by 2.58 sec.",
            "effects": [{
                "stat": "burst_cooldown", "action": "reduce_cooldown",
                "value": 2.58, "value_basis": "seconds",
                "formula_bracket": None,
                "target": "self", "trigger": "passive",
                "duration": None, "condition_on": "none"
            }],
            "stack_conditions": None
        }
    ),
]


# ─────────────────────────────────────────────────────────────
# 5. System Prompt Builder
# ─────────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    """
    LLM에게 전달할 시스템 프롬프트 생성.
    스키마 설명 + 공식 레퍼런스 + few-shot 예시 포함.
    """
    schema_json = json.dumps(SkillParsed.model_json_schema(), ensure_ascii=False, indent=2)

    examples_text = ""
    for i, (input_text, output_dict) in enumerate(FEW_SHOT_EXAMPLES, 1):
        examples_text += f"\n--- Example {i} ---\n"
        examples_text += f"INPUT:\n{input_text}\n\n"
        examples_text += f"OUTPUT:\n{json.dumps(output_dict, ensure_ascii=False, indent=2)}\n"

    return f"""You are a structured data extractor for NIKKE: Goddess of Victory.
Parse skill descriptions into structured JSON that matches the SkillParsed schema.

## Damage Formula Reference
Damage = (FinalAtk - FinalDef)
       × (1 + Σcrit_dmg + Σcore_hit_buff + ...)                           [B2]
       × (1 + Σattack_dmg [+pierce_dmg] [+parts_dmg] [+dot_dmg] [+sequential_dmg])  [B3]
       × (1 + Σdamage_taken + Σdistrib_dmg)                               [B4]
       × (1 + Σstrong_elem)                                                [B5]
       × coefficient

## Critical Rules
1. pierce_dmg / parts_dmg / dot_dmg / sequential_dmg are all B3 sub-types.
   They share formula_bracket="b3_attack_dmg" but differ in condition_on:
     pierce_dmg    → condition_on: "piercing_attack"
     parts_dmg     → condition_on: "hitting_parts"
     dot_dmg       → condition_on: "dot_instance"
     sequential_dmg→ condition_on: "sequential_hit"
2. distrib_dmg is the SOLE EXCEPTION among attack_dmg sub-types:
   it belongs to B4 (formula_bracket="b4_dmg_taken"), condition_on="distribution_attack".
3. For "Once / Twice / Three times" skills: populate stack_conditions[], leave effects=[].
4. Preserve raw_text verbatim. Extract numeric values exactly as written.
5. One EffectBlock per stat per trigger. Multi-stat skills → multiple EffectBlocks.

## JSON Schema
{schema_json}

## Examples
{examples_text}

Now parse the skill text and return valid JSON only (no markdown fences, no explanation):"""
