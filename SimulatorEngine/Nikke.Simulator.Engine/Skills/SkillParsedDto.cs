using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Nikke.Simulator.Engine.Skills
{
    // ─────────────────────────────────────────────────────────────────────────
    // skills_parsed.json (v3) → C# 역직렬화 계약. Pydantic `skill_schema.py` 미러.
    //   SkillParsed → groups[TriggeredEffectGroup{trigger,target,effects[]}] (+ stack_conditions)
    //
    // ⚠️ enum 슬롯(event/stat/action/scale/scale_base/formula_bracket/condition_on/
    //    target/target_filter)은 **string 으로 둔다** — 스킬 소스 audit(ROLEDATA_SKILL_AUDIT)
    //    확정 + KP1 파서 backlog 흡수 전까지 enum 값 집합을 선잠그지 않기 위함.
    //    ENGINE_GUIDE §5 "enum (또는 string + 검증)" 의 후자. K4(Loader) 가 검증/매핑 책임.
    //
    // 순수 DTO — 동작 없음. v3 스키마 동결(DESIGN §6). 이 파일 = K0 동결 계약.
    // ─────────────────────────────────────────────────────────────────────────

    /// <summary>LLM 스킬 파서 최상위 출력. 한 스킬(s1/s2/burst)에 대응. (Pydantic SkillParsed)</summary>
    public sealed class SkillParsedDto
    {
        [JsonPropertyName("skill_name")] public string SkillName { get; set; } = "";

        /// <summary>"s1" / "s2" / "burst".</summary>
        [JsonPropertyName("skill_slot")] public string SkillSlot { get; set; } = "";

        /// <summary>원문 그대로. 수치 교차검증용.</summary>
        [JsonPropertyName("raw_text")] public string RawText { get; set; } = "";

        /// <summary>무조건/기본 효과 그룹. 파서 bailout = 빈 목록(no-op, throw 금지 — INV).</summary>
        [JsonPropertyName("groups")] public List<TriggeredEffectGroupDto> Groups { get; set; } = new();

        /// <summary>Once/Twice/Three times 분기. 없으면 null.</summary>
        [JsonPropertyName("stack_conditions")] public List<StackConditionBranchDto>? StackConditions { get; set; }

        /// <summary>"replace" / "cumulative". stack_conditions 있을 때만.</summary>
        [JsonPropertyName("stack_mode")] public string? StackMode { get; set; }

        /// <summary>스택 카운터 +1 이벤트 (TriggerType wire 값).</summary>
        [JsonPropertyName("stack_trigger")] public string? StackTrigger { get; set; }

        [JsonPropertyName("stack_trigger_count")] public int? StackTriggerCount { get; set; }

        [JsonPropertyName("parsing_notes")] public string? ParsingNotes { get; set; }
    }

    /// <summary>한 ■ 불릿 단위. (trigger, target, effects[]). (Pydantic TriggeredEffectGroup)</summary>
    public sealed class TriggeredEffectGroupDto
    {
        [JsonPropertyName("trigger")] public TriggerBlockDto Trigger { get; set; } = new();
        [JsonPropertyName("target")] public TargetBlockDto Target { get; set; } = new();
        [JsonPropertyName("effects")] public List<EffectBlockDto> Effects { get; set; } = new();
    }

    /// <summary>'언제/어떤 조건에서'. (Pydantic TriggerBlock)</summary>
    public sealed class TriggerBlockDto
    {
        /// <summary>TriggerType wire 값 (예: "passive", "burst_active", "every_n_shots").</summary>
        [JsonPropertyName("event")] public string Event { get; set; } = "passive";

        /// <summary>카운팅형 event 의 N (every_n_*). 비카운팅 = null.</summary>
        [JsonPropertyName("trigger_count")] public int? TriggerCount { get; set; }

        /// <summary>ConditionOn wire 값 (예: "none", "full_burst", "hitting_parts").</summary>
        [JsonPropertyName("condition_on")] public string ConditionOn { get; set; } = "none";

        [JsonPropertyName("condition_threshold_pct")] public double? ConditionThresholdPct { get; set; }

        /// <summary>enum 외 캐릭터 전용 상태/토큰 (투명 플래그; C# 캐릭터별 핸들러가 해석).</summary>
        [JsonPropertyName("required_token")] public string? RequiredToken { get; set; }

        /// <summary>트리거 최소 간격(초, ICD).</summary>
        [JsonPropertyName("internal_cooldown")] public double? InternalCooldown { get; set; }
    }

    /// <summary>'누구에게'. (Pydantic TargetBlock)</summary>
    public sealed class TargetBlockDto
    {
        /// <summary>TargetType wire 값 (예: "self", "all_allies", "all_enemies").</summary>
        [JsonPropertyName("target")] public string Target { get; set; } = "self";

        [JsonPropertyName("target_count")] public int? TargetCount { get; set; }

        /// <summary>TargetFilter wire 값 (예: "none", "highest_atk").</summary>
        [JsonPropertyName("target_filter")] public string TargetFilter { get; set; } = "none";

        /// <summary>enum 외 커스텀 필터 (C# 캐릭터별 핸들러가 해석).</summary>
        [JsonPropertyName("filter_token")] public string? FilterToken { get; set; }
    }

    /// <summary>'무엇을' — 단일 스탯 수정 하나. (Pydantic EffectBlock)</summary>
    public sealed class EffectBlockDto
    {
        /// <summary>StatType wire 값 (예: "atk_pct", "attack_dmg", "charge_dmg").</summary>
        [JsonPropertyName("stat")] public string Stat { get; set; } = "";

        /// <summary>ActionType wire 값 (예: "buff", "debuff", "deal_damage").</summary>
        [JsonPropertyName("action")] public string Action { get; set; } = "buff";

        [JsonPropertyName("value")] public double Value { get; set; }

        /// <summary>Scale wire 값 ("pct"/"flat"/"seconds").</summary>
        [JsonPropertyName("scale")] public string Scale { get; set; } = "pct";

        /// <summary>ScaleBase wire 값 ("none"/"caster_atk"/…).</summary>
        [JsonPropertyName("scale_base")] public string ScaleBase { get; set; } = "none";

        /// <summary>FormulaBracket wire 값. 비대미지 스탯 = null. (deal_damage = null, INV-1)</summary>
        [JsonPropertyName("formula_bracket")] public string? FormulaBracket { get; set; }

        /// <summary>지속시간(초). null = 영구/패시브.</summary>
        [JsonPropertyName("duration")] public double? Duration { get; set; }

        [JsonPropertyName("max_stacks")] public int? MaxStacks { get; set; }
        [JsonPropertyName("stack_increment")] public int? StackIncrement { get; set; }

        /// <summary>DPS 영향 여부. 명중률/이동속도/면역 등은 false.</summary>
        [JsonPropertyName("dps_scope")] public bool DpsScope { get; set; } = true;

        /// <summary>stat=unsupported 시 원문 stat 이름(@접두).</summary>
        [JsonPropertyName("stat_token")] public string? StatToken { get; set; }

        /// <summary>'Mirrors the stack count of @X' — value 가 비례하는 토큰명.</summary>
        [JsonPropertyName("value_scales_with_token")] public string? ValueScalesWithToken { get; set; }

        [JsonPropertyName("notes")] public string? Notes { get; set; }
    }

    /// <summary>Once/Twice/Three times 분기. (Pydantic StackConditionBranch)</summary>
    public sealed class StackConditionBranchDto
    {
        [JsonPropertyName("threshold")] public int Threshold { get; set; }
        [JsonPropertyName("groups")] public List<TriggeredEffectGroupDto> Groups { get; set; } = new();
    }
}
