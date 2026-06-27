"""
DataPipeline/schema/skill_schema.py

NIKKE 스킬 텍스트 → 구조화 JSON 변환을 위한 Pydantic 스키마 + LLM Few-Shot 예시.

──────────────────────────────────────────────────────────────
v3: 3계층 구조 + scale/scale_base 직교 분해
──────────────────────────────────────────────────────────────
  SkillParsed
    └─ groups: List[TriggeredEffectGroup]        ← '한 ■ 불릿 단위' 묶음
         ├─ trigger: TriggerBlock                (언제 — event, condition, token)
         ├─ target : TargetBlock                 (누구에게 — target, count, filter)
         └─ effects: List[EffectBlock]           (무엇을 — stat 수정만, trigger/target 중복 X)

  stack_conditions: Optional[List[StackConditionBranch]]  ← Once/Twice/Three times
       └─ branch.threshold + branch.groups: List[TriggeredEffectGroup]

──────────────────────────────────────────────────────────────
대미지 공식 (런타임 참조)
──────────────────────────────────────────────────────────────
Damage = floor( B2 × (1 + ΣB3) × (1 + ΣB4) × (1 + ΣB5) )   ※ 18 golden 검증; 권위 = Docs/DESIGN.md §3
  P  = (FinalAtk - FinalDef) × 계수(W) × chargeDmg_final(C)
  B2 = floor(P) + Σ_active floor(P × bracket)                ← **가산 per-term FLOOR** (곱셈 아님!)
       bracket ∈ { properDist, fullBurst, (크리)Σcrit_dmg, (코어)coreHitBase+Σcore_hit_buff }
  B3 = 1 + Σattack_dmg [+pierce_dmg][+parts_dmg][+dot_dmg][+sequential_dmg]
  B4 = 1 + Σdamage_taken + Σdistrib_dmg
  B5 = 1 + Σstrong_elem
  ※ 과거 'B2 도 곱셈' 표기는 폐기. B2 만 가산-per-term-floor, B3~B5 곱셈, 마지막 단일 floor.

Full Charge 계수 (계수 자리의 별도 2-축):
  chargeDmg_final = (chargeDmg_base + Σcharge_dmg) × (1 + Σcharge_dmg_mult)
                         └─ coeff_charge_add ──┘   └─ coeff_charge_mult ──┘

──────────────────────────────────────────────────────────────
값 해석: Scale + ScaleBase 직교 분해 (v2 의 ValueBasis 복합 enum 교체)
──────────────────────────────────────────────────────────────
  value: 실제 수치 (예: 11.67)
  scale: 수치의 단위  (pct / flat / seconds)
  scale_base: 수치의 기준값 소스
     none                  = target 자기 stat 에 대한 단순 증감
     caster_atk            = value% × caster.FinalAtk, target stat 에 평탄 가산
     caster_max_hp         = value% × caster.MaxHP,    target stat 에 평탄 가산
     caster_charge_speed   = value% × caster.chargeSpeed_base, target 에 평탄 적용
     target_max_hp         = value% × target.MaxHP     (회복/실드용)
     target_current_hp     = value% × target.HP        (회복/실드용)
     damage_dealt          = value% × inflicted damage (흡혈용, stat=lifesteal 전용)

  → 이 설계로 v2 의 pct_of_caster_atk / pct_of_caster_stat / pct_of_max_hp
    복합 enum 을 모두 커버하고, 새 조합("ATK ▲ X% of caster's Max HP")도 자연스러움.
  → v2 의 stat=atk_ratio_of_caster 는 삭제. 대신 atk_flat + scale_base=caster_atk 로.

Simulator constants (런타임 주입, 스킬 파싱 대상 아님):
  fullBurst  = 0.5  (Full Burst Time 활성 시)
  properDist = 0.3  (적정 거리 / 특정 부위 공격 시)
  coreHitBase: atk_parser.py 가 basicAttack 텍스트에서 파싱
"""

from __future__ import annotations

import json
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ═════════════════════════════════════════════════════════════
# 1. Enums
# ═════════════════════════════════════════════════════════════

class StatType(str, Enum):
    # ── Final ATK modifiers ───────────────────────────────────
    ATK_PCT              = "atk_pct"             # ATK × (1 + Σatk_pct) 에 가산
    ATK_FLAT             = "atk_flat"            # ATK에 평탄 가산. scale_base=caster_atk 와 결합하면
                                                 # v2 의 atk_ratio_of_caster 시맨틱 동일.

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

    # ── Full Charge 계수 구성 (Charge Damage 2축) ─────────────
    # 공식: chargeDmg_final = (chargeDmg_base + Σcharge_dmg) × (1 + Σcharge_dmg_mult)
    CHARGE_DMG           = "charge_dmg"          # "Charge Damage ▲ X%" — 가산 축.
    CHARGE_DMG_MULT      = "charge_dmg_mult"     # "Charge Damage Multiplier ▲ X%" — 곱셈 축.

    # ── Trait 부여 (action=grant_trait 전용, 플래그성 on/off) ───
    TRAIT_PIERCE                = "trait_pierce"                 # "Gains (continuous) Pierce" 관통 특성 획득
    TRAIT_TRUE_DMG_CONVERSION   = "trait_true_dmg_conversion"    # "Normal damage is applied as true damage"
                                                                 # — 무기 변환 + 조건부 대미지 타입 변환.
                                                                 # required_token 으로 변환 조건 문구 보존.
    TRAIT_WEAPON_TRANSFORMED    = "trait_weapon_transformed"     # "Change the weapon in use" — 무기 파라미터
                                                                 # 덮어쓰기 플래그. 실제 덮어쓸 값(charge_time,
                                                                 # damage%, full_charge_damage%, max_ammo 등)은
                                                                 # notes 에 원문 보존. 시뮬레이터 측 per-character
                                                                 # override table 이 실 처리 (long-tail, ≤10 캐릭).

    # ── 브래킷 외 스탯 ────────────────────────────────────────
    AMMO_CAPACITY        = "ammo_capacity"
    RELOAD_SPEED         = "reload_speed"
    TRUE_DMG             = "true_dmg"            # 방어 무시 대미지 (별도 계산, 브래킷 없음)
    HP_POTENCY           = "hp_potency"          # 회복/실드 효율 증가
    BURST_GAUGE          = "burst_gauge"         # 버스트 게이지 충전
    BURST_COOLDOWN       = "burst_cooldown"      # 버스트 스킬 쿨다운 감소 (단위: 초)
    HEAL                 = "heal"                # 일반 HP 회복 (Max HP/Current HP 기반)
    LIFESTEAL            = "lifesteal"           # 흡혈: "Recover HP by X% of attack damage"
                                                 # scale_base=damage_dealt 필수.
    SHIELD               = "shield"              # 실드 부여
    CHARGE_SPEED         = "charge_speed"        # 차지 무기 차지 속도 (+% = 차지시간 감소)
    MOVE_SPEED           = "move_speed"
    IMMUNITY             = "immunity"            # CC·디버프 면역
    HIT_RATE             = "hit_rate"            # 명중률. 대미지 공식 무관(dps_scope=false). crit_rate 와 혼동 금지.

    # ── 미지원 탈출구 (B7) ────────────────────────────────────
    # 스키마에 정확히 맞는 stat 이 없을 때, 대미지축 칸에 우겨넣지 말고 여기로.
    # 원문 이름은 stat_token 에 보존. SKILL_MISMAPPING_GUARD.md 참조.
    UNSUPPORTED          = "unsupported"


class FormulaBracket(str, Enum):
    B2_CRIT_CORE      = "b2_crit_core"        # (1 + ... + Σcrit_dmg + Σcore_hit_buff)
    B3_ATTACK_DMG     = "b3_attack_dmg"       # (1 + Σattack_dmg [+pierce][+parts][+dot][+sequential])
    B4_DMG_TAKEN      = "b4_dmg_taken"        # (1 + Σdamage_taken + Σdistrib_dmg)
    B5_STRONG_ELEM    = "b5_strong_elem"      # (1 + Σstrong_elem)
    COEFF_CHARGE_ADD  = "coeff_charge_add"    # (chargeDmg_base + Σcharge_dmg)
    COEFF_CHARGE_MULT = "coeff_charge_mult"   # × (1 + Σcharge_dmg_mult)


class ConditionOn(str, Enum):
    """TriggerBlock.condition_on — 트리거 위에 추가로 걸리는 조건 술어."""
    NONE                 = "none"
    # B3 sub-type (특정 스탯은 이 조건이 '기본값' — STAT_BRACKET 에서 강제됨)
    PIERCING_ATTACK      = "piercing_attack"      # 관통탄 발사 시
    HITTING_PARTS        = "hitting_parts"        # 보스 파츠 힛 시
    DOT_INSTANCE         = "dot_instance"         # DoT 틱 인스턴스 시
    SEQUENTIAL_HIT       = "sequential_hit"       # 순차 대미지 인스턴스 시
    # B4 sub-type
    DISTRIBUTION_ATTACK  = "distribution_attack"  # 분배 대미지 인스턴스 시
    # Situational
    FULL_BURST           = "full_burst"           # Full Burst Time 활성 중
    HP_BELOW_PCT         = "hp_below_pct"         # 자신/대상 HP < threshold_pct
    HP_ABOVE_PCT         = "hp_above_pct"         # 자신/대상 HP > threshold_pct
    IN_COVER             = "in_cover"
    OUT_OF_COVER         = "out_of_cover"
    ENEMY_DEBUFFED       = "enemy_debuffed"       # 대상에 디버프 존재 시


class Scale(str, Enum):
    """value 의 단위. '어떻게 측정하는가'."""
    PCT     = "pct"       # 백분율 (예: 15.22 → 15.22%)
    FLAT    = "flat"      # 절대값
    SECONDS = "seconds"   # 초 (쿨다운 등)


class ScaleBase(str, Enum):
    """
    value 의 기준값 소스. '무엇의 X% 인가'.

    - none               = 단순 단위 증감. target 자기 stat 에 대한 값.
                           (예: 'ATK ▲ 10%' → target.ATK × 1.10)
    - caster_atk         = value% × caster.FinalAtk 를 target stat 에 평탄 가산.
                           deal_damage action 의 스킬 계수도 이 값.
                           (예: 'ATK ▲ 27.82% of caster's ATK' / 'Deals 150% of final ATK')
    - caster_max_hp      = value% × caster.MaxHP 를 target stat 에 평탄 가산.
                           (예: 'ATK ▲ 6.16% of caster's Max HP')
    - caster_charge_speed = value% × caster.chargeSpeed_base 를 target 에 평탄 적용.
                           (예: 'Charge Speed ▲ 11.67% of caster's Charge Speed')
    - target_max_hp      = value% × target.MaxHP. 회복/실드 action 에서 주로 사용.
                           (예: 'Recovers 15% of Max HP' → target 본인의 MaxHP 기준)
    - target_current_hp  = value% × target.CurrentHP.
    - damage_dealt       = value% × inflicted damage (흡혈 전용, stat=lifesteal).
    """
    NONE                 = "none"
    CASTER_ATK           = "caster_atk"
    CASTER_MAX_HP        = "caster_max_hp"
    CASTER_CHARGE_SPEED  = "caster_charge_speed"
    TARGET_MAX_HP        = "target_max_hp"
    TARGET_CURRENT_HP    = "target_current_hp"
    DAMAGE_DEALT         = "damage_dealt"


class TriggerType(str, Enum):
    PASSIVE              = "passive"              # 항상 활성
    ENTER_BATTLE         = "enter_battle"         # 전투 시작 시
    SKILL_CAST           = "skill_cast"           # ※ "이 group 이 속한 스킬(동일 슬롯) 자체 발동 시".
                                                  #   '다른 슬롯' 지칭("when using Burst Skill" 등)에는
                                                  #   아래 전용 트리거 사용.
    SKILL1_USE           = "skill1_use"           # 자신의 Skill 1 사용 시
    SKILL2_USE           = "skill2_use"           # 자신의 Skill 2 사용 시
    BURST_USE            = "burst_use"            # 자신의 Burst Skill 사용 시
                                                  #   ※ burst_start 와 구분 (아래 참조).
    BURST_START          = "burst_start"          # Full Burst 타임 시작 시 (3인 합산 직후)
    BURST_END            = "burst_end"            # Full Burst 타임 종료 시
    BURST_ACTIVE         = "burst_active"         # Full Burst 타임 지속 중
    ON_HIT               = "on_hit"               # 명중 시 (매 히트)
    ON_KILL              = "on_kill"              # 킬 시
    LAST_BULLET_HIT      = "last_bullet_hit"      # 마지막 탄환 명중 시
    ON_RELOAD            = "on_reload"            # 재장전 시
    FULL_MAGAZINE        = "full_magazine"        # 탄창 가득 찼을 때
    LOW_AMMO             = "low_ammo"             # 탄약 임계치 이하
    ALLY_HIT             = "ally_hit"             # 아군이 피격 시
    ALLY_KILL            = "ally_kill"            # 아군 킬 시
    HP_DROPS_BELOW       = "hp_drops_below"       # HP가 임계치 이하로 감소 시
    HP_ABOVE             = "hp_above"             # HP가 임계치 이상인 동안
    STACK_THRESHOLD      = "stack_threshold"      # 버프 스택 수 도달 시 (분기 내부용)
    EFFECT_EXPIRY        = "effect_expiry"        # 버프/디버프 만료 시
    # ── 카운팅형 (반드시 trigger_count 와 함께) ────────────────────
    EVERY_N_SHOTS        = "every_n_shots"
    EVERY_N_NORMAL_ATK   = "every_n_normal_attacks"
    WHEN_ATTACKED_N      = "when_attacked_n_times"
    EVERY_N_FULL_CHARGE  = "every_n_full_charge"  # "when attacking with Full Charge for N time(s)" (카운팅형)
    EVERY_N_HITS         = "every_n_hits"         # "when hitting/landing N time(s)" 일반 명중 카운트.
                                                  # 종류(파츠/펠릿/크리)는 condition_on 또는 required_token 으로.
    EVERY_N_BURST_USE    = "every_n_burst_use"    # "when using Burst Skill for N time(s)" (카운팅형)
    FULL_CHARGE_HIT      = "full_charge_hit"      # "when hitting a target with Full Charge" (단발, 비카운팅)


class TargetFilter(str, Enum):
    """target 에 추가로 걸리는 선정 필터. 게임 텍스트의 'with the highest X' 류를 기계값으로."""
    NONE                 = "none"
    HIGHEST_MAX_HP       = "highest_max_hp"       # "with the highest Max HP"
    LOWEST_HP_PCT        = "lowest_hp_pct"        # "most injured" / "lowest HP"
    HIGHEST_ATK          = "highest_atk"          # "with the highest ATK"
    HIGHEST_DEF          = "highest_def"
    NEAREST_CROSSHAIR    = "nearest_to_crosshair"
    NEAREST_CASTER       = "nearest_to_caster"
    WITHIN_ATTACK_RANGE  = "within_attack_range"
    SAME_SQUAD           = "same_squad"
    SAME_ELEMENT_CODE    = "same_element_code"


class TargetType(str, Enum):
    SELF                 = "self"
    SINGLE_ALLY          = "single_ally"
    ALL_ALLIES           = "all_allies"
    ATTACKER             = "attacker"
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
    GRANT_TRAIT          = "grant_trait"          # 'Gains continuous X' — 3종 고정 trait 플래그 on/off.
    GRANT_STATUS         = "grant_status"         # 'Gains <named status> X' — 캐릭터 고유 상태 부여.
                                                  # stat=unsupported + stat_token="@<상태명>". 핸들러가 소유.
                                                  # 그 상태가 내포하는 수치 버프는 별도 effect/group (required_token 게이트).
    FILL_BURST_GAUGE     = "fill_burst_gauge"
    REDUCE_COOLDOWN      = "reduce_cooldown"
    RESTORE_AMMO         = "restore_ammo"
    GRANT_IMMUNITY       = "grant_immunity"
    DISPEL               = "dispel"


# ═════════════════════════════════════════════════════════════
# 2. STAT_BRACKET lookup
#    (formula_bracket, default_condition_on)
# ═════════════════════════════════════════════════════════════

STAT_BRACKET: dict[StatType, tuple[Optional[FormulaBracket], ConditionOn]] = {
    # B2
    StatType.CRIT_RATE:        (None,                           ConditionOn.NONE),
    StatType.CRIT_DMG:         (FormulaBracket.B2_CRIT_CORE,    ConditionOn.NONE),
    StatType.CORE_HIT_BUFF:    (FormulaBracket.B2_CRIT_CORE,    ConditionOn.NONE),

    # B3 — attack_dmg 계열
    StatType.ATTACK_DMG:       (FormulaBracket.B3_ATTACK_DMG,   ConditionOn.NONE),
    StatType.PIERCE_DMG:       (FormulaBracket.B3_ATTACK_DMG,   ConditionOn.PIERCING_ATTACK),
    StatType.PARTS_DMG:        (FormulaBracket.B3_ATTACK_DMG,   ConditionOn.HITTING_PARTS),
    StatType.DOT_DMG:          (FormulaBracket.B3_ATTACK_DMG,   ConditionOn.DOT_INSTANCE),
    StatType.SEQUENTIAL_DMG:   (FormulaBracket.B3_ATTACK_DMG,   ConditionOn.SEQUENTIAL_HIT),

    # B4
    StatType.DAMAGE_TAKEN:     (FormulaBracket.B4_DMG_TAKEN,    ConditionOn.NONE),
    StatType.DISTRIB_DMG:      (FormulaBracket.B4_DMG_TAKEN,    ConditionOn.DISTRIBUTION_ATTACK),

    # B5
    StatType.STRONG_ELEM:      (FormulaBracket.B5_STRONG_ELEM,  ConditionOn.NONE),

    # 계수 측 배율 (Full Charge 2-축)
    StatType.CHARGE_DMG:       (FormulaBracket.COEFF_CHARGE_ADD,  ConditionOn.NONE),
    StatType.CHARGE_DMG_MULT:  (FormulaBracket.COEFF_CHARGE_MULT, ConditionOn.NONE),

    # Trait (플래그성)
    StatType.TRAIT_PIERCE:                (None, ConditionOn.NONE),
    StatType.TRAIT_TRUE_DMG_CONVERSION:   (None, ConditionOn.NONE),
    StatType.TRAIT_WEAPON_TRANSFORMED:    (None, ConditionOn.NONE),

    # 브래킷 없음
    StatType.ATK_PCT:          (None, ConditionOn.NONE),
    StatType.ATK_FLAT:         (None, ConditionOn.NONE),
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
    StatType.LIFESTEAL:        (None, ConditionOn.NONE),
    StatType.SHIELD:           (None, ConditionOn.NONE),
    StatType.CHARGE_SPEED:     (None, ConditionOn.NONE),
    StatType.MOVE_SPEED:       (None, ConditionOn.NONE),
    StatType.IMMUNITY:         (None, ConditionOn.NONE),
    StatType.HIT_RATE:         (None, ConditionOn.NONE),
    StatType.UNSUPPORTED:      (None, ConditionOn.NONE),
}


# ═════════════════════════════════════════════════════════════
# 3. Pydantic Models (3-layer)
# ═════════════════════════════════════════════════════════════

class TriggerBlock(BaseModel):
    """'언제 / 어떤 조건에서' — 그룹의 발동 조건."""
    event: TriggerType
    trigger_count: Optional[int] = Field(
        default=None,
        description=(
            "카운팅형 event 의 N. event 가 every_n_shots / every_n_normal_attacks / "
            "when_attacked_n_times 일 때 반드시 채운다. 예: 'after firing 300 time(s)' → 300."
        )
    )
    condition_on: ConditionOn = ConditionOn.NONE
    condition_threshold_pct: Optional[float] = Field(
        default=None,
        description="hp_below_pct / hp_above_pct 조건의 HP 임계치(%)."
    )
    required_token: Optional[str] = Field(
        default=None,
        description=(
            "enum 에 담기 어려운 **캐릭터 전용 상태/토큰** 을 자유 문자열로. "
            "예: 'Sword Coin status', 'Nano Coating', 'Making Memories', "
            "'Wheel of Fortune status'. LLM 이 원문에서 보이는 대로 기재. "
            "파서는 이 문자열을 투명 플래그로만 취급 (해석은 C# 캐릭터별 핸들러)."
        )
    )
    internal_cooldown: Optional[float] = Field(
        default=None,
        description="트리거 최소 간격(초, ICD)."
    )

    @model_validator(mode="after")
    def _check_trigger_invariants(self) -> "TriggerBlock":
        _counter_triggers = {
            TriggerType.EVERY_N_SHOTS,
            TriggerType.EVERY_N_NORMAL_ATK,
            TriggerType.WHEN_ATTACKED_N,
            TriggerType.EVERY_N_FULL_CHARGE,
            TriggerType.EVERY_N_HITS,
            TriggerType.EVERY_N_BURST_USE,
        }
        # INV-3: 카운팅형 → trigger_count 필수
        if self.event in _counter_triggers and self.trigger_count is None:
            raise ValueError(
                f"[INV-3] event={self.event.value} 은 trigger_count 필수. "
                f"'after firing N time(s)' 의 N 값을 기록해야 한다."
            )
        # INV-3b: 비카운팅형 → trigger_count 금지
        if self.event not in _counter_triggers and self.trigger_count is not None:
            raise ValueError(
                f"[INV-3b] event={self.event.value} 은 카운팅형이 아니므로 "
                f"trigger_count 를 설정하면 안 된다. got {self.trigger_count}."
            )
        # INV-8: HP 조건 → 임계치 필수
        if self.condition_on in {ConditionOn.HP_BELOW_PCT, ConditionOn.HP_ABOVE_PCT} \
                and self.condition_threshold_pct is None:
            raise ValueError(
                f"[INV-8] condition_on={self.condition_on.value} 은 "
                f"condition_threshold_pct (HP %) 필수."
            )
        return self


class TargetBlock(BaseModel):
    """'누구에게' — 그룹의 효과 대상."""
    target: TargetType
    target_count: Optional[int] = Field(
        default=None,
        description=(
            "'Affects N ally/enemy unit(s)' 의 N. "
            "target='all_allies'/'all_enemies' 이면 None."
        )
    )
    target_filter: TargetFilter = TargetFilter.NONE
    filter_token: Optional[str] = Field(
        default=None,
        description=(
            "enum 에 없는 **커스텀 필터** 를 자유 문자열로. "
            "예: 'with a Shotgun', 'Fire Code', 'Defender ally', "
            "'in Lock-On status'. C# 캐릭터별 핸들러가 해석."
        )
    )

    @model_validator(mode="after")
    def _check_target_invariants(self) -> "TargetBlock":
        # INV-6: 전체 대상에 target_count 설정 금지
        if self.target in {TargetType.ALL_ALLIES, TargetType.ALL_ENEMIES} \
                and self.target_count is not None:
            raise ValueError(
                f"[INV-6] target={self.target.value} 은 전체 대상이므로 target_count=None. "
                f"got {self.target_count}."
            )
        return self


class EffectBlock(BaseModel):
    """'무엇을' — 단일 스탯에 대한 수정 하나. trigger/target 중복 없음."""
    stat: StatType
    action: ActionType
    value: float = Field(..., description="수치 (예: 15.22).")
    scale: Scale = Scale.PCT
    scale_base: ScaleBase = ScaleBase.NONE
    formula_bracket: Optional[FormulaBracket] = Field(
        default=None,
        description="이 스탯이 속하는 대미지 공식 브래킷. 비대미지 스탯은 None."
    )
    duration: Optional[float] = Field(
        default=None,
        description="지속 시간(초). None = 영구 / 패시브."
    )
    max_stacks: Optional[int] = Field(
        default=None, description="최대 버프 스택 수. None = 스택 없음."
    )
    stack_increment: Optional[int] = Field(
        default=None, description="트리거당 획득 스택 수."
    )
    dps_scope: bool = Field(
        default=True,
        description=(
            "이 효과가 DPS(대미지) 계산에 영향을 주는가. 기본 True. "
            "명중률/이동속도/면역/엄폐물 등 대미지 무관 효과는 False — "
            "엔진이 '안다, 그러나 DPS 미반영'으로 분류(커버리지 정직 카운트). "
            "stat=hit_rate / unsupported / move_speed / immunity 등은 보통 False."
        )
    )
    stat_token: Optional[str] = Field(
        default=None,
        description=(
            "stat=unsupported 일 때 원문 stat 이름을 보존(@접두 권장). "
            "예: 'Hit Rate'→unsupported+stat_token='@HitRate'(또는 hit_rate enum 사용), "
            "'Explosion Range'→stat_token='@ExplosionRange', 'Shield Damage'→'@ShieldDamage'. "
            "대미지축 칸에 우겨넣는 것 금지(SKILL_MISMAPPING_GUARD.md)."
        )
    )
    value_scales_with_token: Optional[str] = Field(
        default=None,
        description=(
            "'Mirrors the stack count of <X>' — value 가 @토큰 스택 수에 비례할 때 "
            "그 토큰명(@접두). 런타임 실효값 = value × 해당 토큰 현재 스택. "
            "deal_damage / buff 공통. 없으면 None(=배수 1)."
        )
    )
    notes: Optional[str] = Field(default=None, description="파싱 특이사항.")

    @model_validator(mode="after")
    def _check_effect_invariants(self) -> "EffectBlock":
        # INV-13: stat=unsupported ↔ stat_token 쌍대성 (B7 탈출구).
        if self.stat == StatType.UNSUPPORTED and not self.stat_token:
            raise ValueError(
                "[INV-13] stat=unsupported 는 stat_token(원문 이름) 필수. "
                "대미지축 칸에 우겨넣지 말고 여기로 park (SKILL_MISMAPPING_GUARD.md)."
            )
        # INV-14: grant_status 는 캐릭터 고유 '상태 플래그' 부여 전용.
        # stat=unsupported + stat_token="@<상태명>" 로만. (수치 버프는 grant_status 가 아니라
        # 별도 buff/debuff effect — required_token=@상태명 으로 게이트.)
        if self.action == ActionType.GRANT_STATUS and self.stat != StatType.UNSUPPORTED:
            raise ValueError(
                f"[INV-14] action=grant_status 는 stat=unsupported + stat_token='@<상태명>' 필수. "
                f"got stat={self.stat.value}. 상태가 내포하는 수치 버프는 별도 buff effect 로 분리하라."
            )
        # INV-1: deal_damage → formula_bracket=null
        # (스킬 계수는 공식의 '계수' 자리. B2/B3/B4 버프 합산과 다른 위치.)
        if self.action == ActionType.DEAL_DAMAGE and self.formula_bracket is not None:
            raise ValueError(
                f"[INV-1] action=deal_damage 는 formula_bracket=null 이어야 한다. "
                f"got {self.formula_bracket.value}. "
                f"공격 종류는 TriggerBlock.condition_on (distribution_attack 등) 으로 표시."
            )

        # INV-2: deal_damage 의 계수 기준. 대부분 caster_atk('Deals X% of final ATK')이지만,
        # NIKKE 엔 Max HP 비례 누커('X% of ATK calculated from N% of Max HP' — kilo, maiden 등)와
        # damage_dealt 비례('X% of the damage dealt by self' — emilia)도 실재한다.
        # 따라서 {caster_atk, caster_max_hp, damage_dealt} 만 허용. (2026-05-29 완화)
        _dd_allowed = {ScaleBase.CASTER_ATK, ScaleBase.CASTER_MAX_HP, ScaleBase.DAMAGE_DEALT}
        if self.action == ActionType.DEAL_DAMAGE and self.scale_base not in _dd_allowed:
            raise ValueError(
                f"[INV-2] action=deal_damage 의 scale_base 는 "
                f"caster_atk / caster_max_hp / damage_dealt 중 하나여야 한다. "
                f"got {self.scale_base.value}."
            )

        # INV-7: buff/debuff 에서 formula_bracket 은 STAT_BRACKET 과 일치해야 함
        if self.action in {ActionType.BUFF, ActionType.DEBUFF}:
            expected, _ = STAT_BRACKET.get(self.stat, (None, ConditionOn.NONE))
            if self.formula_bracket != expected:
                exp_s = expected.value if expected else "null"
                got_s = self.formula_bracket.value if self.formula_bracket else "null"
                raise ValueError(
                    f"[INV-7] stat={self.stat.value}, action={self.action.value} 은 "
                    f"formula_bracket={exp_s} 이어야 한다. got {got_s}."
                )

        # INV-9: grant_trait ↔ trait_* 쌍대성
        _trait_stats = {
            StatType.TRAIT_PIERCE,
            StatType.TRAIT_TRUE_DMG_CONVERSION,
            StatType.TRAIT_WEAPON_TRANSFORMED,
        }
        if self.action == ActionType.GRANT_TRAIT:
            if self.stat not in _trait_stats:
                _names = ", ".join(s.value for s in _trait_stats)
                raise ValueError(
                    f"[INV-9a] action=grant_trait 은 stat ∈ {{{_names}}} 필수. "
                    f"got stat={self.stat.value}."
                )
            if self.scale != Scale.FLAT or self.scale_base != ScaleBase.NONE or self.value != 1.0:
                raise ValueError(
                    f"[INV-9b] action=grant_trait 은 value=1.0, scale=flat, scale_base=none "
                    f"(on/off 플래그). got value={self.value}, "
                    f"scale={self.scale.value}, scale_base={self.scale_base.value}."
                )
        if self.stat in _trait_stats and self.action != ActionType.GRANT_TRAIT:
            raise ValueError(
                f"[INV-9c] stat={self.stat.value} 은 action=grant_trait 전용. "
                f"got action={self.action.value}."
            )

        # INV-10: lifesteal ↔ heal + scale_base=damage_dealt
        if self.stat == StatType.LIFESTEAL:
            if self.action != ActionType.HEAL:
                raise ValueError(
                    f"[INV-10a] stat=lifesteal 은 action=heal 필수. got {self.action.value}."
                )
            if self.scale_base != ScaleBase.DAMAGE_DEALT:
                raise ValueError(
                    f"[INV-10b] stat=lifesteal 은 scale_base=damage_dealt 필수. "
                    f"got {self.scale_base.value}. "
                    f"'Recover HP by X% of attack damage' 해석."
                )
        # 역방향: damage_dealt 는 lifesteal(흡혈) 또는 deal_damage(damage_dealt 비례 대미지)에서만.
        if (self.scale_base == ScaleBase.DAMAGE_DEALT
                and self.stat != StatType.LIFESTEAL
                and self.action != ActionType.DEAL_DAMAGE):
            raise ValueError(
                f"[INV-10c] scale_base=damage_dealt 는 stat=lifesteal 또는 action=deal_damage 전용. "
                f"got stat={self.stat.value}, action={self.action.value}."
            )

        return self


class TriggeredEffectGroup(BaseModel):
    """한 ■ 불릿 단위. (trigger, target, effects[]) 로 구성."""
    trigger: TriggerBlock
    target: TargetBlock
    effects: List[EffectBlock]

    @model_validator(mode="after")
    def _check_group_invariants(self) -> "TriggeredEffectGroup":
        # INV-12: target=self + scale_base 가 '수정 대상과 같은 stat' 을 가리키면 의미 중복.
        # 본인 기준이 곧 시전자 기준(self==caster)이므로 scale_base=none 과 동일.
        # → 거부하지 않고 **자동정규화**한다 (scale_base=none 으로 silently 교정).
        #   의미 보존(self 기준=caster 기준)이고, LLM 이 caster_* 를 써도 결과가 같으므로
        #   파싱 실패로 떨어뜨릴 이유가 없다. (2026-05-29: reject → normalize 전환.)
        _self_collapse = {
            (StatType.ATK_PCT,      ScaleBase.CASTER_ATK),
            (StatType.ATK_FLAT,     ScaleBase.CASTER_ATK),
            (StatType.MAX_HP_PCT,   ScaleBase.CASTER_MAX_HP),
            (StatType.MAX_HP_FLAT,  ScaleBase.CASTER_MAX_HP),
            (StatType.CHARGE_SPEED, ScaleBase.CASTER_CHARGE_SPEED),
        }
        if self.target.target == TargetType.SELF:
            for eff in self.effects:
                if (eff.stat, eff.scale_base) in _self_collapse:
                    eff.scale_base = ScaleBase.NONE  # self==caster → 동일 의미로 축약
        # (cross-stat: stat=atk_flat + scale_base=caster_max_hp 등은 _self_collapse 에
        #  없으므로 그대로 보존됨 — 다른 stat 을 caster 스탯으로 스케일하는 정상 케이스.)
        return self


class StackConditionBranch(BaseModel):
    """Once / Twice / Three times 분기."""
    threshold: int = Field(..., description="이 분기가 활성화되는 스택 수.")
    groups: List[TriggeredEffectGroup]


class SkillParsed(BaseModel):
    """LLM 스킬 파서의 최상위 출력. 한 스킬(S1/S2/Burst)에 대응."""
    skill_name: str
    skill_slot: Literal["s1", "s2", "burst"] = Field(
        ..., description="'s1', 's2', 'burst' 중 하나."
    )
    raw_text: str = Field(..., description="원문 그대로 보존. 수치 교차검증용.")
    groups: List[TriggeredEffectGroup] = Field(
        default_factory=list,
        description="무조건 / 기본 효과 그룹 목록."
    )
    stack_conditions: Optional[List[StackConditionBranch]] = Field(
        default=None,
        description="Once/Twice/Three times 분기가 있는 스킬에서만. 없으면 None."
    )
    stack_mode: Optional[Literal["replace", "cumulative"]] = Field(
        default=None,
        description=(
            "stack_conditions 있을 때만 의미. "
            "'cumulative' = 'Previous effects trigger repeatedly' 문구 있음 — "
            "상위 threshold 활성 시 하위도 전부 유지. "
            "'replace' = 최상위 threshold 만 활성."
        )
    )
    stack_trigger: Optional[TriggerType] = Field(
        default=None,
        description=(
            "stack_conditions 분기의 스택 카운터를 +1 시키는 이벤트. "
            "분기 내부 TriggerBlock.event 는 stack_threshold 로 고정하고, "
            "실제 증가 이벤트는 여기에 기록. "
            "예: 'when using Burst Skill' → burst_use, 'after Full Burst ends' → burst_end."
        )
    )
    stack_trigger_count: Optional[int] = Field(
        default=None,
        description="stack_trigger 가 카운팅형일 때의 N. 예: 'every 5 normal attacks' → 5."
    )
    parsing_notes: Optional[str] = Field(
        default=None,
        description="LLM 의 파싱 판단 근거 / 엣지케이스 메모."
    )

    @model_validator(mode="after")
    def _check_skill_invariants(self) -> "SkillParsed":
        # INV-4a/4b: stack_conditions 있으면 stack_mode / stack_trigger 필수
        if self.stack_conditions is not None:
            if self.stack_mode is None:
                raise ValueError(
                    "[INV-4a] stack_conditions 있을 때 stack_mode 필수. "
                    "'Previous effects trigger repeatedly' 있으면 'cumulative', 없으면 'replace'."
                )
            if self.stack_trigger is None:
                raise ValueError(
                    "[INV-4b] stack_conditions 있을 때 stack_trigger 필수. "
                    "스택 카운터 증가 이벤트 ('when using Burst Skill' → burst_use 등)."
                )

            # INV-5: stack_conditions 내부 groups 의 trigger.event = stack_threshold 고정
            for branch in self.stack_conditions:
                for grp in branch.groups:
                    if grp.trigger.event != TriggerType.STACK_THRESHOLD:
                        raise ValueError(
                            f"[INV-5] stack_conditions[threshold={branch.threshold}] 내부 "
                            f"TriggerBlock.event 는 'stack_threshold' 고정. "
                            f"got {grp.trigger.event.value}. "
                            f"실제 증가 이벤트는 SkillParsed.stack_trigger 에 기록."
                        )
        else:
            # INV-4c/4d: stack_conditions 없이 stack_mode/stack_trigger 설정 금지
            if self.stack_mode is not None:
                raise ValueError(
                    f"[INV-4c] stack_conditions 없이 stack_mode={self.stack_mode} 금지."
                )
            if self.stack_trigger is not None:
                raise ValueError(
                    f"[INV-4d] stack_conditions 없이 stack_trigger={self.stack_trigger.value} 금지."
                )

        return self


# ═════════════════════════════════════════════════════════════
# 4. Few-Shot Examples
#    형식: (input_text: str, expected_output: dict)
#    expected_output 은 SkillParsed 스키마를 만족해야 함.
# ═════════════════════════════════════════════════════════════

def _group(trigger: dict, target: dict, effects: list[dict]) -> dict:
    """Few-shot 딕셔너리를 간결하게 만들기 위한 헬퍼."""
    return {"trigger": trigger, "target": target, "effects": effects}


FEW_SHOT_EXAMPLES: list[tuple[str, dict]] = [
    # ── 1. ATK 버프 — 전체 아군, skill_cast, 시간 제한 ─────────────────────────
    (
        "■ Affects all allies.ATK ▲ 5.28% for 5 sec.",
        {
            "skill_name": "Power Surge",
            "skill_slot": "s1",
            "raw_text": "■ Affects all allies.ATK ▲ 5.28% for 5 sec.",
            "groups": [_group(
                {"event": "skill_cast"},
                {"target": "all_allies"},
                [{
                    "stat": "atk_pct", "action": "buff", "value": 5.28,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": None, "duration": 5.0,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 2. 자신 패시브 치명타율 ────────────────────────────────────────────────
    (
        "■ Affects self.Critical Rate ▲ 11.34% continuously.",
        {
            "skill_name": "Sharp Eye",
            "skill_slot": "s1",
            "raw_text": "■ Affects self.Critical Rate ▲ 11.34% continuously.",
            "groups": [_group(
                {"event": "passive"},
                {"target": "self"},
                [{
                    "stat": "crit_rate", "action": "buff", "value": 11.34,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": None, "duration": None,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 3. 치명타 대미지 버프 — B2, skill_cast, 시간 제한 ────────────────────
    (
        "■ Affects all allies.Critical Damage ▲ 15.55% for 10 sec.",
        {
            "skill_name": "Lethal Shot",
            "skill_slot": "s2",
            "raw_text": "■ Affects all allies.Critical Damage ▲ 15.55% for 10 sec.",
            "groups": [_group(
                {"event": "skill_cast"},
                {"target": "all_allies"},
                [{
                    "stat": "crit_dmg", "action": "buff", "value": 15.55,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b2_crit_core", "duration": 10.0,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 4. 코어 힛 대미지 버프 — B2, burst_active, condition_on=full_burst ───
    (
        "■ Activates during Full Burst. Affects all allies.Core Hit Damage ▲ 7.97% continuously.",
        {
            "skill_name": "Bullseye",
            "skill_slot": "burst",
            "raw_text": "■ Activates during Full Burst. Affects all allies.Core Hit Damage ▲ 7.97% continuously.",
            "groups": [_group(
                {"event": "burst_active", "condition_on": "full_burst"},
                {"target": "all_allies"},
                [{
                    "stat": "core_hit_buff", "action": "buff", "value": 7.97,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b2_crit_core", "duration": None,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 5. 공격 대미지 증가 — B3, 패시브 ─────────────────────────────────────
    (
        "■ Affects self.Attack Damage ▲ 14.33% continuously.",
        {
            "skill_name": "Aggression",
            "skill_slot": "s1",
            "raw_text": "■ Affects self.Attack Damage ▲ 14.33% continuously.",
            "groups": [_group(
                {"event": "passive"},
                {"target": "self"},
                [{
                    "stat": "attack_dmg", "action": "buff", "value": 14.33,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b3_attack_dmg", "duration": None,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 6. 관통 대미지 — B3, condition_on=piercing_attack ────────────────────
    (
        "■ Affects self.Pierce Damage ▲ 21.06% continuously.",
        {
            "skill_name": "Armor Piercer",
            "skill_slot": "s1",
            "raw_text": "■ Affects self.Pierce Damage ▲ 21.06% continuously.",
            "groups": [_group(
                {"event": "passive", "condition_on": "piercing_attack"},
                {"target": "self"},
                [{
                    "stat": "pierce_dmg", "action": "buff", "value": 21.06,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b3_attack_dmg", "duration": None,
                    "notes": "B3 가산, 관통탄 발사 시에만 적용.",
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 7. 파츠 대미지 — B3, condition_on=hitting_parts ──────────────────────
    (
        "■ Affects self.Damage to Parts ▲ 9.56% continuously.",
        {
            "skill_name": "Weak Spot",
            "skill_slot": "s1",
            "raw_text": "■ Affects self.Damage to Parts ▲ 9.56% continuously.",
            "groups": [_group(
                {"event": "passive", "condition_on": "hitting_parts"},
                {"target": "self"},
                [{
                    "stat": "parts_dmg", "action": "buff", "value": 9.56,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b3_attack_dmg", "duration": None,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 8. 지속 대미지 — B3, condition_on=dot_instance ───────────────────────
    (
        "■ Affects self.Continuous Damage ▲ 15.46% continuously.",
        {
            "skill_name": "Toxin",
            "skill_slot": "s2",
            "raw_text": "■ Affects self.Continuous Damage ▲ 15.46% continuously.",
            "groups": [_group(
                {"event": "passive", "condition_on": "dot_instance"},
                {"target": "self"},
                [{
                    "stat": "dot_dmg", "action": "buff", "value": 15.46,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b3_attack_dmg", "duration": None,
                    "notes": "B3 가산, DoT 틱 시에만. pierce/parts 는 DoT 에 미적용.",
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 9. 순차 대미지 — B3, condition_on=sequential_hit ─────────────────────
    (
        "■ Affects self.Sequential Damage ▲ 12.80% continuously.",
        {
            "skill_name": "Momentum",
            "skill_slot": "s1",
            "raw_text": "■ Affects self.Sequential Damage ▲ 12.80% continuously.",
            "groups": [_group(
                {"event": "passive", "condition_on": "sequential_hit"},
                {"target": "self"},
                [{
                    "stat": "sequential_dmg", "action": "buff", "value": 12.80,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b3_attack_dmg", "duration": None,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 10. 분배 대미지 버프 — B4(예외!), condition_on=distribution_attack ──
    (
        "■ Affects self.Distributed Damage ▲ 18.34% continuously.",
        {
            "skill_name": "Scatter",
            "skill_slot": "s2",
            "raw_text": "■ Affects self.Distributed Damage ▲ 18.34% continuously.",
            "groups": [_group(
                {"event": "passive", "condition_on": "distribution_attack"},
                {"target": "self"},
                [{
                    "stat": "distrib_dmg", "action": "buff", "value": 18.34,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b4_dmg_taken", "duration": None,
                    "notes": "attack_dmg 계열이지만 유일하게 B4. damage_taken 과 같은 브래킷에서 가산.",
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 11. 받는 대미지 증가 (적 디버프) — B4 ────────────────────────────────
    (
        "■ Affects all enemies.Damage Taken ▲ 5.79% for 10 sec.",
        {
            "skill_name": "Vulnerability",
            "skill_slot": "s2",
            "raw_text": "■ Affects all enemies.Damage Taken ▲ 5.79% for 10 sec.",
            "groups": [_group(
                {"event": "skill_cast"},
                {"target": "all_enemies"},
                [{
                    "stat": "damage_taken", "action": "debuff", "value": 5.79,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b4_dmg_taken", "duration": 10.0,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 12. 마지막 탄환 명중 시 ATK 버프 ─────────────────────────────────────
    (
        "■ Activates when the last bullet hits the target. Affects all allies.ATK ▲ 15.22% for 10 sec.",
        {
            "skill_name": "Final Round",
            "skill_slot": "s1",
            "raw_text": "■ Activates when the last bullet hits the target. Affects all allies.ATK ▲ 15.22% for 10 sec.",
            "groups": [_group(
                {"event": "last_bullet_hit"},
                {"target": "all_allies"},
                [{
                    "stat": "atk_pct", "action": "buff", "value": 15.22,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": None, "duration": 10.0,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 13. HP 조건부 자신 ATK 버프 ──────────────────────────────────────────
    (
        "■ Activates when own HP falls below 30%. Affects self.ATK ▲ 25.74% continuously.",
        {
            "skill_name": "Last Stand",
            "skill_slot": "s1",
            "raw_text": "■ Activates when own HP falls below 30%. Affects self.ATK ▲ 25.74% continuously.",
            "groups": [_group(
                {
                    "event": "hp_drops_below",
                    "condition_on": "hp_below_pct",
                    "condition_threshold_pct": 30.0,
                },
                {"target": "self"},
                [{
                    "stat": "atk_pct", "action": "buff", "value": 25.74,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": None, "duration": None,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 14. 스택 분기 — Once/Twice/Three times 누적형 (Previous effects...) ──
    (
        "■ Activates when using Burst Skill. Affects all allies."
        "Effect changes according to the number of activation time(s). Previous effects trigger repeatedly:"
        "Once: ATK ▲ 5.93% continuously."
        "Twice: ATK ▲ 8.69% continuously."
        "Three times: ATK ▲ 10.52% continuously",
        {
            "skill_name": "Overcharge",
            "skill_slot": "s2",
            "raw_text": (
                "■ Activates when using Burst Skill. Affects all allies."
                "Effect changes according to the number of activation time(s). Previous effects trigger repeatedly:"
                "Once: ATK ▲ 5.93% continuously."
                "Twice: ATK ▲ 8.69% continuously."
                "Three times: ATK ▲ 10.52% continuously"
            ),
            "groups": [],
            "stack_conditions": [
                {
                    "threshold": 1,
                    "groups": [_group(
                        {"event": "stack_threshold"},
                        {"target": "all_allies"},
                        [{
                            "stat": "atk_pct", "action": "buff", "value": 5.93,
                            "scale": "pct", "scale_base": "none",
                            "formula_bracket": None, "duration": None, "max_stacks": 3,
                        }],
                    )],
                },
                {
                    "threshold": 2,
                    "groups": [_group(
                        {"event": "stack_threshold"},
                        {"target": "all_allies"},
                        [{
                            "stat": "atk_pct", "action": "buff", "value": 8.69,
                            "scale": "pct", "scale_base": "none",
                            "formula_bracket": None, "duration": None, "max_stacks": 3,
                        }],
                    )],
                },
                {
                    "threshold": 3,
                    "groups": [_group(
                        {"event": "stack_threshold"},
                        {"target": "all_allies"},
                        [{
                            "stat": "atk_pct", "action": "buff", "value": 10.52,
                            "scale": "pct", "scale_base": "none",
                            "formula_bracket": None, "duration": None, "max_stacks": 3,
                        }],
                    )],
                },
            ],
            "stack_mode": "cumulative",
            "stack_trigger": "burst_use",
            "parsing_notes": (
                "'Previous effects trigger repeatedly' → cumulative. "
                "'when using Burst Skill' → stack_trigger=burst_use (skill_cast 금지, "
                "이 스킬 자체 발동과 혼동됨). groups=[] 비우고 stack_conditions 에만 기재."
            ),
        },
    ),

    # ── 15. caster's ATK 전이 — stat=atk_flat + scale_base=caster_atk ────────
    #       v2 의 atk_ratio_of_caster 는 삭제됨. 이 조합이 교체.
    (
        "■ Affects all allies within attack range.ATK ▲ 27.82% of caster's ATK continuously.",
        {
            "skill_name": "Battle Sync",
            "skill_slot": "s2",
            "raw_text": "■ Affects all allies within attack range.ATK ▲ 27.82% of caster's ATK continuously.",
            "groups": [_group(
                {"event": "passive"},
                {"target": "all_allies", "target_filter": "within_attack_range"},
                [{
                    "stat": "atk_flat", "action": "buff", "value": 27.82,
                    "scale": "pct", "scale_base": "caster_atk",
                    "formula_bracket": None, "duration": None,
                    "notes": (
                        "'27.82% of caster's ATK' → scale_base=caster_atk. "
                        "런타임: (caster.FinalAtk × 27.82%) 을 아군 FinalAtk 에 평탄 가산."
                    ),
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 16. 회복 — caster's Max HP 기반 ──────────────────────────────────────
    (
        "■ Affects all allies.Recovers 3.46% of caster's Max HP as HP.",
        {
            "skill_name": "Field Medic",
            "skill_slot": "burst",
            "raw_text": "■ Affects all allies.Recovers 3.46% of caster's Max HP as HP.",
            "groups": [_group(
                {"event": "skill_cast"},
                {"target": "all_allies"},
                [{
                    "stat": "heal", "action": "heal", "value": 3.46,
                    "scale": "pct", "scale_base": "caster_max_hp",
                    "formula_bracket": None, "duration": None,
                    "notes": "'of caster's Max HP' → scale_base=caster_max_hp. target 의 MaxHP 와 다름.",
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 17. 버스트 게이지 충전 — enter_battle ────────────────────────────────
    (
        "■ Activates when entering battle. Affects self.Burst Gauge ▲ 17.28%.",
        {
            "skill_name": "Energy Surge",
            "skill_slot": "s1",
            "raw_text": "■ Activates when entering battle. Affects self.Burst Gauge ▲ 17.28%.",
            "groups": [_group(
                {"event": "enter_battle"},
                {"target": "self"},
                [{
                    "stat": "burst_gauge", "action": "fill_burst_gauge", "value": 17.28,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": None, "duration": None,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 18. 복합 효과 — 한 ■ 안 여러 스탯 → 같은 group 의 effects 로 묶임 ────
    (
        "■ Affects all allies.Critical Damage ▲ 15.55% for 10 sec.Attack Damage ▲ 11.32% for 10 sec.",
        {
            "skill_name": "Double Edge",
            "skill_slot": "s2",
            "raw_text": "■ Affects all allies.Critical Damage ▲ 15.55% for 10 sec.Attack Damage ▲ 11.32% for 10 sec.",
            "groups": [_group(
                {"event": "skill_cast"},
                {"target": "all_allies"},
                [
                    {
                        "stat": "crit_dmg", "action": "buff", "value": 15.55,
                        "scale": "pct", "scale_base": "none",
                        "formula_bracket": "b2_crit_core", "duration": 10.0,
                    },
                    {
                        "stat": "attack_dmg", "action": "buff", "value": 11.32,
                        "scale": "pct", "scale_base": "none",
                        "formula_bracket": "b3_attack_dmg", "duration": 10.0,
                    },
                ],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 19. 트루 대미지 — 방어 무시 ──────────────────────────────────────────
    (
        "■ Affects 1 enemy.Deals 128.93% of final ATK as True Damage.",
        {
            "skill_name": "Null Buster",
            "skill_slot": "burst",
            "raw_text": "■ Affects 1 enemy.Deals 128.93% of final ATK as True Damage.",
            "groups": [_group(
                {"event": "skill_cast"},
                {"target": "single_enemy", "target_count": 1},
                [{
                    "stat": "true_dmg", "action": "deal_damage", "value": 128.93,
                    "scale": "pct", "scale_base": "caster_atk",
                    "formula_bracket": None, "duration": None,
                    "notes": (
                        "방어 무시. 브래킷 없음. FinalAtk × 128.93% 단독 계산. "
                        "deal_damage 는 반드시 scale_base=caster_atk."
                    ),
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 20. 버스트 쿨다운 감소 — ▼ 표기, scale=seconds ───────────────────────
    (
        "■ Affects self.Cooldown of Burst Skill ▼ 2.58 sec.",
        {
            "skill_name": "Rush",
            "skill_slot": "s1",
            "raw_text": "■ Affects self.Cooldown of Burst Skill ▼ 2.58 sec.",
            "groups": [_group(
                {"event": "passive"},
                {"target": "self"},
                [{
                    "stat": "burst_cooldown", "action": "reduce_cooldown", "value": 2.58,
                    "scale": "seconds", "scale_base": "none",
                    "formula_bracket": None, "duration": None,
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 21. 스택 분기 — 교체형 (Previous effects... '없음'), 각 분기 다른 stat ─
    (
        "■ Activates after Full Burst ends. Affects all allies."
        "Effect changes according to the activation time(s)."
        "Once: Hit Rate ▲ 10.13% for 10 sec."
        "Twice: ATK ▲ 35.02% of caster's ATK for 10 sec."
        "Three times: Reloading Speed ▲ 40.04% for 15 sec.",
        {
            "skill_name": "Rotating Buff",
            "skill_slot": "burst",
            "raw_text": (
                "■ Activates after Full Burst ends. Affects all allies."
                "Effect changes according to the activation time(s)."
                "Once: Hit Rate ▲ 10.13% for 10 sec."
                "Twice: ATK ▲ 35.02% of caster's ATK for 10 sec."
                "Three times: Reloading Speed ▲ 40.04% for 15 sec."
            ),
            "groups": [],
            "stack_conditions": [
                {
                    "threshold": 1,
                    "groups": [_group(
                        {"event": "stack_threshold"},
                        {"target": "all_allies"},
                        [{
                            "stat": "crit_rate", "action": "buff", "value": 10.13,
                            "scale": "pct", "scale_base": "none",
                            "formula_bracket": None, "duration": 10.0, "max_stacks": 3,
                            "notes": "'Hit Rate' 는 스키마상 최근접 crit_rate. 런타임에서 주의.",
                        }],
                    )],
                },
                {
                    "threshold": 2,
                    "groups": [_group(
                        {"event": "stack_threshold"},
                        {"target": "all_allies"},
                        [{
                            "stat": "atk_flat", "action": "buff", "value": 35.02,
                            "scale": "pct", "scale_base": "caster_atk",
                            "formula_bracket": None, "duration": 10.0, "max_stacks": 3,
                            "notes": "v2 의 atk_ratio_of_caster 대체 — atk_flat + scale_base=caster_atk.",
                        }],
                    )],
                },
                {
                    "threshold": 3,
                    "groups": [_group(
                        {"event": "stack_threshold"},
                        {"target": "all_allies"},
                        [{
                            "stat": "reload_speed", "action": "buff", "value": 40.04,
                            "scale": "pct", "scale_base": "none",
                            "formula_bracket": None, "duration": 15.0, "max_stacks": 3,
                        }],
                    )],
                },
            ],
            "stack_mode": "replace",
            "stack_trigger": "burst_end",
            "parsing_notes": (
                "'Previous effects trigger repeatedly' 없음 → replace. "
                "증가 이벤트 = 'after Full Burst ends' → burst_end."
            ),
        },
    ),

    # ── 22. 분배 공격 스킬 계수 + 두 번째 ■ 는 별도 group ────────────────────
    (
        "■ Affects all enemies.Deals 2439.36% of final ATK as Distributed Damage."
        "■ Affects 1 enemy unit(s) with the highest Max HP."
        "Deals 792% of final ATK as additional damage.",
        {
            "skill_name": "Series of Attacks",
            "skill_slot": "burst",
            "raw_text": (
                "■ Affects all enemies.Deals 2439.36% of final ATK as Distributed Damage."
                "■ Affects 1 enemy unit(s) with the highest Max HP."
                "Deals 792% of final ATK as additional damage."
            ),
            "groups": [
                _group(
                    {"event": "skill_cast", "condition_on": "distribution_attack"},
                    {"target": "all_enemies"},
                    [{
                        "stat": "distrib_dmg", "action": "deal_damage", "value": 2439.36,
                        "scale": "pct", "scale_base": "caster_atk",
                        "formula_bracket": None, "duration": None,
                        "notes": (
                            "분배 공격 스킬 계수. formula_bracket=null — "
                            "B4 의 Σdistrib_dmg 버프 합산과 다른 '계수' 자리. "
                            "공격 종류는 TriggerBlock.condition_on=distribution_attack 으로만."
                        ),
                    }],
                ),
                _group(
                    {"event": "skill_cast"},
                    {
                        "target": "single_enemy", "target_count": 1,
                        "target_filter": "highest_max_hp",
                    },
                    [{
                        "stat": "attack_dmg", "action": "deal_damage", "value": 792.0,
                        "scale": "pct", "scale_base": "caster_atk",
                        "formula_bracket": None, "duration": None,
                        "notes": "'1 enemy ... with the highest Max HP' → target_count=1, target_filter=highest_max_hp.",
                    }],
                ),
            ],
            "stack_conditions": None,
        },
    ),

    # ── 23. 카운팅형 트리거 — every_n_shots, trigger_count=300 ─────────────────
    (
        "■ Activates after firing 300 time(s). Affects 1 enemy."
        "Deals 1524.72% of final ATK as damage.",
        {
            "skill_name": "Cluster Bomb",
            "skill_slot": "s2",
            "raw_text": (
                "■ Activates after firing 300 time(s). Affects 1 enemy."
                "Deals 1524.72% of final ATK as damage."
            ),
            "groups": [_group(
                {"event": "every_n_shots", "trigger_count": 300},
                {"target": "single_enemy", "target_count": 1},
                [{
                    "stat": "attack_dmg", "action": "deal_damage", "value": 1524.72,
                    "scale": "pct", "scale_base": "caster_atk",
                    "formula_bracket": None, "duration": None,
                    "notes": (
                        "'after firing N time(s)' → event=every_n_shots + trigger_count=N. "
                        "on_hit 금지 (히트마다 발동이 아니라 N회째 발사마다)."
                    ),
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 23-B. Charge Damage Multiplier — 곱셈 축 (charge_dmg_mult) ────────────
    (
        "■ Activates when attacked 20 time(s). Affects all allies."
        "Charge Damage Multiplier ▲ 9.59% for 20 sec.",
        {
            "skill_name": "Helping Hand",
            "skill_slot": "s1",
            "raw_text": (
                "■ Activates when attacked 20 time(s). Affects all allies."
                "Charge Damage Multiplier ▲ 9.59% for 20 sec."
            ),
            "groups": [_group(
                {"event": "when_attacked_n_times", "trigger_count": 20},
                {"target": "all_allies"},
                [{
                    "stat": "charge_dmg_mult", "action": "buff", "value": 9.59,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "coeff_charge_mult", "duration": 20.0,
                    "notes": (
                        "원문 'Multiplier' → 곱셈 축: charge_dmg_mult + coeff_charge_mult. "
                        "공식: chargeDmg_final = (base + Σcharge_dmg) × (1 + Σcharge_dmg_mult)."
                    ),
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 23-C. "Affects N ally units with ..." → single_ally + target_count ──
    (
        "■ Affects 2 ally unit(s) with the highest ATK."
        "Damage Taken ▼ 28.65% for 10 sec.",
        {
            "skill_name": "Kitten's Breath",
            "skill_slot": "s2",
            "raw_text": (
                "■ Affects 2 ally unit(s) with the highest ATK."
                "Damage Taken ▼ 28.65% for 10 sec."
            ),
            "groups": [_group(
                {"event": "skill_cast"},
                {
                    "target": "single_ally", "target_count": 2,
                    "target_filter": "highest_atk",
                },
                [{
                    "stat": "damage_taken", "action": "buff", "value": -28.65,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": "b4_dmg_taken", "duration": 10.0,
                    "notes": (
                        "'Affects N allies with ...' = single_ally + target_count=N. "
                        "target=all_allies + target_count=N 쓰면 INV-6 위반. "
                        "▼ → value 음수, action=buff (아군에게 이로운 감소)."
                    ),
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 23-D. caster's Charge Speed + Charge Damage (가산 축) ────────────────
    (
        "■ Activates when entering Full Burst. Affects 2 ally unit(s) with the highest ATK."
        "Charge Speed ▲ 11.67% of caster's Charge Speed for 10 sec."
        "Charge Damage ▲ 7.00% for 10 sec.",
        {
            "skill_name": "Energizing Carrot",
            "skill_slot": "s1",
            "raw_text": (
                "■ Activates when entering Full Burst. Affects 2 ally unit(s) with the highest ATK."
                "Charge Speed ▲ 11.67% of caster's Charge Speed for 10 sec."
                "Charge Damage ▲ 7.00% for 10 sec."
            ),
            "groups": [_group(
                {"event": "burst_start", "condition_on": "full_burst"},
                {
                    "target": "single_ally", "target_count": 2,
                    "target_filter": "highest_atk",
                },
                [
                    {
                        "stat": "charge_speed", "action": "buff", "value": 11.67,
                        "scale": "pct", "scale_base": "caster_charge_speed",
                        "formula_bracket": None, "duration": 10.0,
                        "notes": (
                            "'of caster's Charge Speed' → scale_base=caster_charge_speed. "
                            "런타임: target.chargeTime -= caster.chargeTime_base × 11.67%."
                        ),
                    },
                    {
                        "stat": "charge_dmg", "action": "buff", "value": 7.0,
                        "scale": "pct", "scale_base": "none",
                        "formula_bracket": "coeff_charge_add", "duration": 10.0,
                        "notes": (
                            "원문 'Charge Damage' (Multiplier 없음) → 가산 축: "
                            "charge_dmg + coeff_charge_add. 'Multiplier' 있으면 곱셈 축."
                        ),
                    },
                ],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 23-E. Gains continuous Pierce (trait) + lifesteal — 서로 다른 조건 ───
    (
        "■ Affects self. Activates when above 80% HP.Gains continuous Pierce."
        "■ Affects self. Activates when HP falls below 80%."
        "Continuously recover HP by 8.12% of attack damage.",
        {
            "skill_name": "Healthy Carrot",
            "skill_slot": "s2",
            "raw_text": (
                "■ Affects self. Activates when above 80% HP.Gains continuous Pierce."
                "■ Affects self. Activates when HP falls below 80%."
                "Continuously recover HP by 8.12% of attack damage."
            ),
            "groups": [
                _group(
                    {
                        "event": "hp_above",
                        "condition_on": "hp_above_pct",
                        "condition_threshold_pct": 80.0,
                    },
                    {"target": "self"},
                    [{
                        "stat": "trait_pierce", "action": "grant_trait", "value": 1.0,
                        "scale": "flat", "scale_base": "none",
                        "formula_bracket": None, "duration": None,
                        "notes": "'Gains continuous Pierce' → grant_trait + trait_pierce, 1.0 flat on/off.",
                    }],
                ),
                _group(
                    {
                        "event": "on_hit",
                        "condition_on": "hp_below_pct",
                        "condition_threshold_pct": 80.0,
                    },
                    {"target": "self"},
                    [{
                        "stat": "lifesteal", "action": "heal", "value": 8.12,
                        "scale": "pct", "scale_base": "damage_dealt",
                        "formula_bracket": None, "duration": None,
                        "notes": (
                            "'recover HP by X% of attack damage' = 흡혈. "
                            "scale_base=damage_dealt 필수. 'continuously' + '% of attack damage' "
                            "→ 공격마다 on_hit."
                        ),
                    }],
                ),
            ],
            "stack_conditions": None,
        },
    ),

    # ── 24. 카운팅형 — every_n_normal_attacks + 스택 ─────────────────────────
    (
        "■ Activates after 5 normal attack(s). Affects self."
        "ATK ▲ 4.00% continuously. Stacks up to 10 times.",
        {
            "skill_name": "Steady Aim",
            "skill_slot": "s1",
            "raw_text": (
                "■ Activates after 5 normal attack(s). Affects self."
                "ATK ▲ 4.00% continuously. Stacks up to 10 times."
            ),
            "groups": [_group(
                {"event": "every_n_normal_attacks", "trigger_count": 5},
                {"target": "self"},
                [{
                    "stat": "atk_pct", "action": "buff", "value": 4.00,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": None, "duration": None,
                    "max_stacks": 10, "stack_increment": 1,
                    "notes": (
                        "'after N normal attack(s)' → event=every_n_normal_attacks + trigger_count=N. "
                        "'Stacks up to M times' → max_stacks=M, stack_increment=1."
                    ),
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 25. required_token — 캐릭터 전용 상태. enum 에 없으면 자유 문자열 ────
    (
        "■ Activates when in Nano Coating status. Affects self."
        "ATK ▲ 6.16% of caster's final Max HP continuously.",
        {
            "skill_name": "Nano-Fueled Strike",
            "skill_slot": "s1",
            "raw_text": (
                "■ Activates when in Nano Coating status. Affects self."
                "ATK ▲ 6.16% of caster's final Max HP continuously."
            ),
            "groups": [_group(
                {"event": "passive", "required_token": "Nano Coating status"},
                {"target": "self"},
                [{
                    "stat": "atk_flat", "action": "buff", "value": 6.16,
                    "scale": "pct", "scale_base": "caster_max_hp",
                    "formula_bracket": None, "duration": None,
                    "notes": (
                        "'ATK ▲ X% of caster's Max HP' → stat=atk_flat + scale_base=caster_max_hp. "
                        "(target=self 라도 서로 다른 stat — ATK vs MaxHP — 이므로 collapse 대상 아님, "
                        "INV-12 통과.) "
                        "'in Nano Coating status' 는 enum 없으므로 required_token 에 원문 문구."
                    ),
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 26. 무기 변환 기믹 (Laplace Treasure Burst) ───────────────
    # 핵심 처리 원칙:
    #   (a) "Change the weapon in use" 자체는 trait_weapon_transformed 플래그.
    #       덮어쓰는 수치(Charge Time, Damage%, FC Damage%, Max Ammo, DoT 등)는
    #       notes 에 원문 그대로 보존. 시뮬레이터의 per-character override 테이블이
    #       실제 weapon 파라미터 덮어쓰기를 처리한다 (long-tail escape hatch).
    #   (b) "Additional Effect: Pierce" → 별도 group, trait_pierce.
    #   (c) "Normal damage is applied as true damage when X" → 별도 group,
    #       trait_true_dmg_conversion + required_token = "X".
    #   (d) Initial Damage / Damage Over Time 의 수치형 대미지는 일반 deal_damage
    #       그룹으로 쪼갬 (scale=pct + scale_base=caster_atk).
    (
        "■ Affects Self.Change the weapon in use:"
        "Initial Damage: 1455.72% of final ATK"
        "Damage Over Time: 22.2% of final ATK"
        "Lasts for 10 sec."
        "Additional Effect 1: Pierce."
        "Additional Effect 2: Normal damage is applied as true damage when Hero Vision is fully stacked."
        "Attention: Unable to take cover when using Burst Skill."
        "■ Affects the same enemy unit(s) when \"Hero Vision\" is fully stacked."
        "Deals 11.9% of final ATK as true damage.",
        {
            "skill_name": "Laplace Buster",
            "skill_slot": "burst",
            "raw_text": (
                "■ Affects Self.Change the weapon in use:"
                "Initial Damage: 1455.72% of final ATK"
                "Damage Over Time: 22.2% of final ATK"
                "Lasts for 10 sec."
                "Additional Effect 1: Pierce."
                "Additional Effect 2: Normal damage is applied as true damage when Hero Vision is fully stacked."
                "Attention: Unable to take cover when using Burst Skill."
                "■ Affects the same enemy unit(s) when \"Hero Vision\" is fully stacked."
                "Deals 11.9% of final ATK as true damage."
            ),
            "groups": [
                # (a) 무기 변환 플래그 — 실제 덮어쓸 파라미터는 notes 에 보존
                _group(
                    {"event": "skill_cast"},
                    {"target": "self"},
                    [{
                        "stat": "trait_weapon_transformed", "action": "grant_trait",
                        "value": 1.0, "scale": "flat", "scale_base": "none",
                        "formula_bracket": None, "duration": 10.0,
                        "notes": (
                            "Change the weapon in use for 10 sec. Overrides: "
                            "Initial Damage=1455.72% of final ATK, "
                            "Damage Over Time=22.2% of final ATK. "
                            "실제 무기 파라미터 덮어쓰기는 시뮬레이터의 per-character "
                            "override table (laplace-treasure) 이 처리한다."
                        ),
                    }],
                ),
                # (b) 부가 효과 1: Pierce
                _group(
                    {"event": "skill_cast"},
                    {"target": "self"},
                    [{
                        "stat": "trait_pierce", "action": "grant_trait",
                        "value": 1.0, "scale": "flat", "scale_base": "none",
                        "formula_bracket": None, "duration": 10.0,
                        "notes": "Additional Effect 1: Pierce (10초).",
                    }],
                ),
                # (c) 부가 효과 2: 조건부 true 변환 — required_token 에 조건 문구 보존
                _group(
                    {"event": "skill_cast", "required_token": "Hero Vision fully stacked"},
                    {"target": "self"},
                    [{
                        "stat": "trait_true_dmg_conversion", "action": "grant_trait",
                        "value": 1.0, "scale": "flat", "scale_base": "none",
                        "formula_bracket": None, "duration": 10.0,
                        "notes": (
                            "Normal damage → true damage. 조건은 required_token. "
                            "시뮬레이터는 이 플래그가 on 일 때 normal hit 들을 true 계산으로 전환."
                        ),
                    }],
                ),
                # (d) 초기 타격 대미지 (변환된 무기의 첫 발)
                _group(
                    {"event": "skill_cast"},
                    {"target": "self"},
                    [{
                        "stat": "true_dmg", "action": "deal_damage", "value": 1455.72,
                        "scale": "pct", "scale_base": "caster_atk",
                        "formula_bracket": None, "duration": None,
                        "notes": (
                            "'Initial Damage: 1455.72% of final ATK' — 변환 직후 1회 타격. "
                            "weapon override 의 초기값이자 독립 deal_damage 이벤트. "
                            "stat 선택은 true_dmg 대신 일반 공격 계수로 보느냐의 해석 문제 — "
                            "여기서는 변환된 무기의 첫 발이라는 점에서 true_dmg 로 둠 "
                            "(런타임 해석은 override table 과 합쳐서 재판정)."
                        ),
                    }],
                ),
                # (e) Hero Vision 5스택 충족 시 추가 true dmg
                _group(
                    {"event": "skill_cast", "required_token": "Hero Vision fully stacked"},
                    {"target": "hit_target"},
                    [{
                        "stat": "true_dmg", "action": "deal_damage", "value": 11.9,
                        "scale": "pct", "scale_base": "caster_atk",
                        "formula_bracket": None, "duration": None,
                        "notes": (
                            "'Deals 11.9% of final ATK as true damage' — "
                            "Hero Vision 5스택 시 같은 적에 추가."
                        ),
                    }],
                ),
            ],
            "stack_conditions": None,
            "parsing_notes": (
                "무기 변환 기믹 composite 예제. Damage Over Time(22.2%/s) 은 별도 group 으로 "
                "두려면 tick 주기 표현이 필요하지만 현재 스키마에 없으므로 (a)의 notes 에 보존. "
                "시뮬레이터 override table 이 DoT tick 을 생성하도록 처리."
            ),
        },
    ),

    # ── 20. 오매핑 방지 — Hit Rate 는 crit_rate 가 아니라 hit_rate + dps_scope=false ──
    (
        "■ Activates when number of Golden Chip stacks is 20 and above. Affects self.Hit Rate ▲ 38.91% for 15 sec.",
        {
            "skill_name": "Onward (Stage 2)",
            "skill_slot": "burst",
            "raw_text": "■ Activates when number of Golden Chip stacks is 20 and above. Affects self.Hit Rate ▲ 38.91% for 15 sec.",
            "groups": [_group(
                {"event": "passive", "required_token": "Golden Chip stacks 20+"},
                {"target": "self"},
                [{
                    "stat": "hit_rate", "action": "buff", "value": 38.91,
                    "scale": "pct", "scale_base": "none",
                    "formula_bracket": None, "duration": 15.0,
                    "dps_scope": False,
                    "notes": "명중률은 대미지 공식과 무관 → dps_scope=false. crit_rate(치명타율)로 매핑 금지.",
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 21. 미지원 stat 탈출구 — Shield Damage 를 parts_dmg 로 우겨넣지 말 것 ──
    (
        "■ Affects 1 enemy unit(s).Deals 700.5% of final ATK as damage to Shield.",
        {
            "skill_name": "Shield Breaker",
            "skill_slot": "s2",
            "raw_text": "■ Affects 1 enemy unit(s).Deals 700.5% of final ATK as damage to Shield.",
            "groups": [_group(
                {"event": "skill_cast"},
                {"target": "single_enemy", "target_count": 1},
                [{
                    "stat": "unsupported", "action": "deal_damage", "value": 700.5,
                    "scale": "pct", "scale_base": "caster_atk",
                    "formula_bracket": None, "duration": None,
                    "stat_token": "@shield_damage", "dps_scope": False,
                    "notes": "실드 전용 대미지. parts_dmg/attack_dmg(B3)에 넣으면 본체 대미지 폭발 → unsupported.",
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 22. every_n_full_charge — 'Full Charge for N time(s)' 카운팅 ──
    (
        "■ Activates when attacking with Full Charge for 8 time(s). Affects all allies.ATK ▲ 5% of the caster's Max HP for 5 sec.",
        {
            "skill_name": "Card Throw",
            "skill_slot": "s1",
            "raw_text": "■ Activates when attacking with Full Charge for 8 time(s). Affects all allies.ATK ▲ 5% of the caster's Max HP for 5 sec.",
            "groups": [_group(
                {"event": "every_n_full_charge", "trigger_count": 8},
                {"target": "all_allies"},
                [{
                    "stat": "atk_flat", "action": "buff", "value": 5.0,
                    "scale": "pct", "scale_base": "caster_max_hp",
                    "formula_bracket": None, "duration": 5.0,
                    "notes": "Full Charge for 8 time(s) → every_n_full_charge + trigger_count=8. cross-stat: caster Max HP 기준 ATK 가산.",
                }],
            )],
            "stack_conditions": None,
        },
    ),

    # ── 23. grant_status — 이름 붙은 캐릭터 고유 상태 + 내포 버프 분리 ──
    (
        "■ Activates when assigned to the back row in battle. Affects self and 2 allies on both sides.Sword Coin: Attack Damage ▲ 6.65% continuously.",
        {
            "skill_name": "Coin Flip",
            "skill_slot": "s2",
            "raw_text": "■ Activates when assigned to the back row in battle. Affects self and 2 allies on both sides.Sword Coin: Attack Damage ▲ 6.65% continuously.",
            "groups": [_group(
                {"event": "passive", "required_token": "assigned to the back row"},
                {"target": "single_ally", "target_count": 3},
                [
                    {
                        "stat": "unsupported", "action": "grant_status", "value": 1.0,
                        "scale": "flat", "scale_base": "none",
                        "formula_bracket": None, "duration": None,
                        "stat_token": "@SwordCoin",
                        "notes": "이름 붙은 상태 'Sword Coin' 부여 = grant_status (grant_trait 아님). 핸들러 소유.",
                    },
                    {
                        "stat": "attack_dmg", "action": "buff", "value": 6.65,
                        "scale": "pct", "scale_base": "none",
                        "formula_bracket": "b3_attack_dmg", "duration": None,
                        "notes": "Sword Coin 이 내포하는 수치 버프 — 별도 effect 로 분리(grant_status 에 안 넣음).",
                    },
                ],
            )],
            "stack_conditions": None,
        },
    ),
]


# ═════════════════════════════════════════════════════════════
# 5. System Prompt Builder
# ═════════════════════════════════════════════════════════════

def build_system_prompt() -> str:
    """LLM 시스템 프롬프트 생성."""
    schema_json = json.dumps(SkillParsed.model_json_schema(), ensure_ascii=False, indent=2)

    examples_text = ""
    for i, (input_text, output_dict) in enumerate(FEW_SHOT_EXAMPLES, 1):
        examples_text += f"\n--- Example {i} ---\n"
        examples_text += f"INPUT:\n{input_text}\n\n"
        examples_text += f"OUTPUT:\n{json.dumps(output_dict, ensure_ascii=False, indent=2)}\n"

    return f"""You are a structured data extractor for NIKKE: Goddess of Victory.
Parse skill descriptions into structured JSON matching the SkillParsed schema.

## Damage Formula Reference
Damage = floor( B2 × (1 + ΣB3) × (1 + ΣB4) × (1 + ΣB5) )
  P  = (FinalAtk - FinalDef) × coefficient(W) × chargeDmg_final(C)
  B2 = floor(P) + Σ_active floor(P × bracket)    ← ADDITIVE per-term FLOOR (NOT multiplicative)
       bracket in: properDist, fullBurst, (crit) Σcrit_dmg, (core) coreHitBase + Σcore_hit_buff
  B3 = 1 + Σattack_dmg [+pierce_dmg][+parts_dmg][+dot_dmg][+sequential_dmg]
  B4 = 1 + Σdamage_taken + Σdistrib_dmg
  B5 = 1 + Σstrong_elem
  (NOTE: bracket taxonomy below is what matters for parsing — which stat → which bracket.)

Full Charge (계수 자리의 별도 2-축):
  chargeDmg_final = (chargeDmg_base + Σcharge_dmg) × (1 + Σcharge_dmg_mult)
                        ├─ coeff_charge_add ─┤    ├── coeff_charge_mult ──┤
  - 'Charge Damage ▲ X%'             → charge_dmg      (가산 축)
  - 'Charge Damage Multiplier ▲ X%'  → charge_dmg_mult (곱셈 축)
  두 축은 서로 다른 연산 — 혼용 금지.

## Output Structure (3-layer)
SkillParsed
  └─ groups: List[TriggeredEffectGroup]    ← 한 ■ 불릿 단위
       ├─ trigger: TriggerBlock            (언제 — event, condition, token)
       ├─ target : TargetBlock             (누구에게)
       └─ effects: List[EffectBlock]       (무엇 — stat 수정만, trigger/target 중복 없음)
  stack_conditions: Optional (Once/Twice/Three times)

원문의 ■ 하나 = 기본적으로 하나의 TriggeredEffectGroup.
단, 같은 ■ 안에서 condition_on 이 달라지면 분리하라.

## value 해석 (scale + scale_base 직교)
  scale:      pct / flat / seconds                ← 단위
  scale_base: 기준값 소스                         ← '무엇의 X%'
    none                  = target 자기 stat 기준
    caster_atk            = value% × caster.FinalAtk (평탄 가산)
    caster_max_hp         = value% × caster.MaxHP    (평탄 가산)
    caster_charge_speed   = value% × caster.chargeSpeed_base
    target_max_hp         = value% × target.MaxHP    (회복/실드)
    target_current_hp     = value% × target.HP
    damage_dealt          = value% × inflicted damage (흡혈, stat=lifesteal 전용)

## Critical Rules

1. **B3 sub-type conditions.** pierce_dmg/parts_dmg/dot_dmg/sequential_dmg 모두 B3 sub-type.
   같은 formula_bracket="b3_attack_dmg" 이지만 trigger.condition_on 이 다르다:
     pierce_dmg     → condition_on="piercing_attack"
     parts_dmg      → condition_on="hitting_parts"
     dot_dmg        → condition_on="dot_instance"
     sequential_dmg → condition_on="sequential_hit"

2. **distrib_dmg 는 예외.** B3 가 아닌 **B4** 에 속한다:
   stat=distrib_dmg, formula_bracket="b4_dmg_taken", condition_on="distribution_attack".

3. **Once / Twice / Three times 스킬.** groups=[] 비우고 stack_conditions[] 에만 기재.
   stack_mode:
     - "cumulative" — raw_text 에 "Previous effects trigger repeatedly" 있음 (상위 활성 시 하위도 유지)
     - "replace"    — 없음 (최상위 분기만 활성)
   stack_trigger: 스택 카운터 +1 이벤트 ("when using Burst Skill" → burst_use 등).
   내부 groups 의 TriggerBlock.event 는 "stack_threshold" 고정.

4. **raw_text 원문 보존.** 수치도 원문 그대로.

5. **input 포맷.** prydwen descriptionLevel10 = '■ <trigger>. Affects <target>. <stat> ▲/▼ <value>% for <n> sec.'
   - 여러 ■ = 서로 다른 TriggeredEffectGroup.
   - 한 ■ 안 여러 스탯 = 같은 group 의 effects[] 에 나란히.
   - '▲' = 증가 (양수), '▼' = 감소 (**음수**, action 은 맥락 유지).
   - 'continuously' = duration=None.

6. **scale / scale_base 규칙 (CRITICAL).**
   - 'ATK ▲ 10%' (plain)               → scale=pct, scale_base=none
   - 'Deals 500% of final ATK'         → scale=pct, scale_base=caster_atk (deal_damage 표준)
   - 'Deals X% of ATK calculated from N% of Max HP' (HP스케일 누커: kilo/maiden 등)
                                       → deal_damage, scale_base=**caster_max_hp** (Max HP 기반)
   - 'Deals X% of the damage dealt by self' (emilia 등)
                                       → deal_damage, scale_base=**damage_dealt**
   - 'ATK ▲ X% of caster's ATK'        → stat=atk_flat, scale_base=caster_atk (v2 atk_ratio_of_caster 대체)
   - 'ATK ▲ X% of caster's Max HP'     → stat=atk_flat, scale_base=caster_max_hp (서로 다른 stat 이라도 OK)
   - 'Charge Speed ▲ X% of caster's Charge Speed' → scale_base=caster_charge_speed
   - 'Recovers X% of caster's Max HP'  → stat=heal, scale_base=caster_max_hp
   - 'Recovers X% of Max HP'           → stat=heal, scale_base=target_max_hp
   - 'Recover HP by X% of attack damage' → stat=lifesteal, scale_base=damage_dealt (INV-10)
   - 'Cooldown ▼ 2 sec'                → scale=seconds, scale_base=none

7. **formula_bracket 규칙 (CRITICAL).**
   - buff/debuff: STAT_BRACKET 에 따라 정확히 채운다 (crit_dmg→b2_crit_core, attack_dmg→b3_attack_dmg,
     damage_taken/distrib_dmg→b4_dmg_taken, charge_dmg→coeff_charge_add, charge_dmg_mult→coeff_charge_mult).
   - deal_damage: formula_bracket=**항상 null**. 스킬 계수는 공식의 '계수' 자리.
     공격 종류는 TriggerBlock.condition_on 으로만 표시 (distribution_attack / piercing_attack / ...).

8. **Counter-based triggers (trigger_count 필수).**
   - 'after firing N time(s)'           → event=every_n_shots,          trigger_count=N
   - 'after N normal attack(s)'         → event=every_n_normal_attacks, trigger_count=N
   - 'when attacked N time(s)'          → event=when_attacked_n_times,  trigger_count=N
   - 'when hitting ... with Full Charge' → event=full_charge_hit

9. **Target 필터.**
   - 'Affects 1 enemy' / 'Affects 2 allies' 의 숫자 → target_count.
   - 'Affects all allies/enemies'                   → target_count=null.
   - 복수 숫자 'Affects 2 allies with ...' → target=**single_ally** + target_count=2 + target_filter.
     target=all_allies + target_count=N 은 INV-6 위반.
   - 알려진 필터:
       'with the highest Max HP' → highest_max_hp
       'most injured' / 'lowest HP' → lowest_hp_pct
       'with the highest ATK' → highest_atk
       'with the highest DEF' → highest_def
       'nearest to the crosshair' → nearest_to_crosshair
       'nearest to the caster'    → nearest_to_caster
       'within attack range'      → within_attack_range
       'of the same squad'        → same_squad
       'Water/Fire/Wind/Iron/Electric Code allies' → same_element_code
   - enum 에 없는 필터 ('with a Shotgun', 'Fire Element', 'Defender ally', 'in Lock-On status' 등)
     → filter_token 에 **원문 문구 그대로** 자유 문자열로. target_filter=none.

10. **stack_trigger (스택 증가 이벤트) 슬롯 분리.**
    - stack_conditions 내부 groups 의 trigger.event = "stack_threshold" 고정.
    - 실제 증가 이벤트는 SkillParsed.stack_trigger:
        'when using Burst Skill'          → burst_use     (skill_cast 금지!)
        'when using Skill 1' / '2'        → skill1_use / skill2_use
        'after Full Burst ends'           → burst_end
        'when Full Burst starts'          → burst_start
        'during Full Burst'               → burst_active
        'when entering battle'            → enter_battle
        'after firing N time(s)'          → every_n_shots (+ stack_trigger_count=N)
    - skill_cast 는 "이 group 이 속한 스킬(동일 슬롯) 자체 발동 시" 로만.

11. **Charge Damage 2-축 (CRITICAL).**
    - 원문에 'Multiplier' 있음 → stat=charge_dmg_mult, formula_bracket=coeff_charge_mult (곱셈)
    - 원문에 'Multiplier' 없음 → stat=charge_dmg,      formula_bracket=coeff_charge_add  (가산)
    - 두 축은 연산 자체가 달라 혼용 금지. B3 Σattack_dmg 와도 독립.

12. **target=self + caster 기준 수식어.**
    - 'ATK ▲ X% of caster's ATK' (target=self) → scale_base=none 으로 써라 (중복 표현, INV-12).
    - **단 stat 이 다른 경우**: 'Affects self. ATK ▲ X% of caster's Max HP' 은 OK (ATK vs MaxHP 다름).
      stat=atk_flat + scale_base=caster_max_hp 가 유효.

13. **Trait 부여 ('Gains continuous X' / 'Change the weapon' / 'Normal damage as true damage').**
    모든 trait_* stat 은 **action=grant_trait + value=1.0 + scale=flat + scale_base=none** 의 순수 플래그.
    on/off 는 duration 으로 표현. 숫자 payload 는 notes 에 원문 보존.

    - 'Gains continuous Pierce' / 'Additional Effect: Pierce' → stat=**trait_pierce**.
    - 'Normal damage is applied as true damage when <조건>' → stat=**trait_true_dmg_conversion**.
      조건은 별도 group 의 trigger.required_token 에 원문 문구 보존.
    - 'Change the weapon in use: Charge Time X / Damage Y% / Full Charge Damage Z% / Max Ammo N'
      → stat=**trait_weapon_transformed**. 덮어쓸 수치(Charge Time / Damage% / FC Damage% / Max Ammo /
      DoT% 등)는 **notes 에 원문 그대로 보존**. 시뮬레이터 per-character override table 이 실 처리.
      무기 변환으로 뒤따라오는 'Initial Damage: X% of final ATK' 같은 수치형 대미지는 **별도 group 의
      deal_damage** 로 분해 (scale=pct + scale_base=caster_atk).
    - immunity / ATK 등 다른 stat 으로 대체 금지.

14. **Lifesteal (흡혈).**
    - 'Recover HP by X% of attack damage' → stat=lifesteal, action=heal, scale_base=damage_dealt.
    - 단순 heal+pct 금지 (인플릭티드 대미지 기준 정보 유실).
    - 'continuously' + '% of damage' → 공격마다 = event=on_hit.

15. **required_token (캐릭터 전용 상태).**
    - 'when in Sword Coin status', 'when in Nano Coating status', 'when Making Memories',
      'when in Wheel of Fortune status' 같은 캐릭터 고유 버프/상태 = required_token 에 **원문 문구 그대로**.
    - 알려진 enum 트리거 (when entering Full Burst 등) 가 아니면 event=passive 로 두고 required_token 채우기.
    - C# 캐릭터별 핸들러가 이 문자열을 해석. 파서는 투명 플래그로만 취급.

16. **부호 규칙 (▲ / ▼).**
    - ▲ 증가 → value 양수.
    - ▼ 감소 → value **음수**. action 은 맥락 ('Damage Taken ▼ 28.65% to allies' → action=buff, value=-28.65).

17. **CC (crowd-control) 효과는 effects 에 넣지 말 것.**
    보스는 CC 면역이라 DPS 시뮬레이터 계산에 영향이 없으므로 데이터 모델에서 제외한다.
    아래 용어는 전부 **effects 에 쓰지 말고, parsing_notes 에 원문 한 줄만 보존**하라
    (같은 group 에 dmg/buff 등 다른 의미 있는 effect 가 있으면 그것만 남기고 CC 는 제거):
      Attract / Taunt / Provoke / Knock(back|down|up) / Stun / Freeze / Shock / Pull /
      Suppress / Restrain / Silence / Sleep / Bind / Petrify / Paralyze
    예) '■ Deals 330.61% of final ATK as damage. Attract for 2 sec.'
        → deal_damage group 만 생성. 'Attract for 2 sec' 부분은 effects 에 넣지 말고,
          parsing_notes 에 "CC ignored for sim: 'Attract for 2 sec'" 기록.
    (향후 PvP/엘리트 몹 확장이 필요해지면 apply_cc 액션 신설로 승급. 현재는 YAGNI.)

18. **오매핑 방지 (CRITICAL — 빈칸을 억지로 채우지 마라).**
    스키마에 정확히 맞는 stat 이 없을 때, **비슷한 대미지축 칸에 우겨넣는 것을 절대 금지**한다.
    대미지축(crit_rate/crit_dmg/core_hit_buff/attack_dmg/pierce_dmg/parts_dmg/dot_dmg/
    sequential_dmg/damage_taken/distrib_dmg/strong_elem/charge_dmg*/atk_pct/atk_flat/true_dmg)에
    엉뚱한 효과를 넣으면 시뮬레이터가 **없는 대미지를 만들어낸다.**
    - 대미지 무관 효과 (명중률 / 공격속도 / 이동속도 / 면역 / 엄폐물 / Full Burst Time 연장 등):
        · 해당 stat 이 enum 에 있으면 그 이름 + formula_bracket=null + **dps_scope=false**.
          예: 'Hit Rate ▲ X%' → stat=**hit_rate**, dps_scope=false. (절대 crit_rate 아님!)
        · enum 에 없으면 stat=**unsupported** + **stat_token="@<원문이름>"** + dps_scope=false.
          예: 'ATK Speed' → stat=unsupported, stat_token="@atk_speed".
              'Shield Damage' → unsupported, stat_token="@shield_damage". (parts_dmg/attack_dmg 금지)
              'Explosion Range' → unsupported, stat_token="@explosion_range". (atk_pct 금지)
    - **명시적 금지 사례**: Hit Rate→crit_rate, ATK Speed→attack_dmg, Shield Damage→parts_dmg,
      Explosion Range→atk_pct. ("closest proxy / placeholder" 라는 생각이 들면 곧 하면 안 되는 신호.)
    - **명중률(Hit Rate) ≠ 치명타율(Critical Rate)**. 완전히 다른 스탯. 절대 혼동 금지.
    - 확신이 안 서면 매핑하지 말고 stat=unsupported 로 park. 틀린 매핑보다 '미지원'이 안전.

19. **카운팅 trigger ('... for N time(s)' / '... N time(s)').** 비카운팅 event(on_hit, burst_use 등)에
    trigger_count 를 붙이지 말고(INV-3b), 카운팅 전용 event 를 쓴다 + trigger_count=N:
    - 'when attacking with Full Charge for N time(s)' → **every_n_full_charge**
    - 'when hitting ... N time(s)' / 'when crit attack hits N time(s)' / 'when N pellets hit'
      → **every_n_hits** (파츠면 condition_on=hitting_parts; 크리·펠릿 등 종류는 required_token 보존)
    - 'when using Burst Skill for N time(s)' → **every_n_burst_use**
    - 'after firing N time(s)' → every_n_shots / 'after N normal attack(s)' → every_n_normal_attacks /
      'when attacked N time(s)' → when_attacked_n_times.

20. **value 가 스택 수에 비례 ('Mirrors the stack count of X').**
    → 그 effect 에 **value_scales_with_token="@<토큰>"** 설정. 런타임 실효값 = value × 토큰 스택.
    deal_damage / buff 공통. 예: 'Deals 28.9% ... Mirrors the stack count of Beautiful'
    → deal_damage, value=28.9, value_scales_with_token="@Beautiful".

21. **캐릭터 고유 '상태(named status)' 부여 → grant_status (grant_trait 아님!).**
    'Gains <상태명> ...' / '<상태명>: <효과>' 처럼 **이름 붙은 캐릭터 고유 상태**를 부여할 때:
    - 상태 플래그 자체 = action=**grant_status**, stat=**unsupported**, stat_token=**"@<상태명>"**,
      value=1.0, scale=flat. (예: 'Mute: Gains immunity...' → grant_status @Mute /
      'Sword Coin: Attack Damage ▲6.65%' → grant_status @SwordCoin)
    - 그 상태가 **내포하는 수치 버프**(위 Attack Damage ▲6.65% 등)는 **별도 buff effect** 로 분리
      (같은 group 의 effects[] 에 나란히, 또는 required_token=@상태명 으로 게이트되는 다른 group).
    - **grant_trait 는 오직 3종**(trait_pierce / trait_true_dmg_conversion / trait_weapon_transformed)
      전용. 그 외 상태/버프를 grant_trait + unsupported 로 넣지 말 것(INV-9a 위반). 상태면 grant_status.

## JSON Schema
{schema_json}

## Examples
{examples_text}

Now parse the skill text and return valid JSON only (no markdown fences, no explanation):"""
