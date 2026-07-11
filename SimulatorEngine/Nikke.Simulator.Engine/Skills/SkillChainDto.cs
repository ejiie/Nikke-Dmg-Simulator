using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Nikke.Simulator.Engine.Skills
{
    // ─────────────────────────────────────────────────────────────────────────
    // skill_chains.json (D3, `staticdata_skill_chains.py`) → C# 역직렬화 (K4).
    // 공식 FunctionTable 계열 데이터 — 스킬 데이터원 결정(2026-07-08, DESIGN §6).
    // 파일 = gitignore(게임데이터 재배포 금지) — 로더는 부재 시 graceful (테스트 skip 패턴).
    //
    // 단위: function_value 등 = raw(×10000=100%) · 시간류 = 1/100초 · duration_value = duration_type 참조.
    // enum 필드는 **원시 int 로 보관** (신버전 미지값 보존) — 타입드 접근은 확장 프로퍼티(Typed*)로.
    // ─────────────────────────────────────────────────────────────────────────

    /// <summary>skill_chains.json 루트.</summary>
    public sealed class SkillChainsDto
    {
        [JsonPropertyName("characters")] public Dictionary<string, CharacterChainDto> Characters { get; set; } = new();
        [JsonPropertyName("bosses")] public Dictionary<string, BossChainDto> Bosses { get; set; } = new();
        [JsonPropertyName("state_effects")] public Dictionary<string, StateEffectDto> StateEffects { get; set; } = new();
        [JsonPropertyName("functions")] public Dictionary<string, FunctionDto> Functions { get; set; } = new();
        /// <summary>UseCharacterSkillId(72) 대상 CharacterSkill 전개 (key = skill_id — T01 런타임 연쇄).
        /// 구 조립본엔 없음 — 빈 사전 = graceful (해당 연쇄 no-op).</summary>
        [JsonPropertyName("character_skills")] public Dictionary<string, SkillLevelDto> CharacterSkills { get; set; } = new();
    }

    /// <summary>니케 1명 — key = name_code. 스킬 3슬롯(skill1/skill2/burst) × 레벨.</summary>
    public sealed class CharacterChainDto
    {
        [JsonPropertyName("char_id")] public int CharId { get; set; }
        [JsonPropertyName("name_localkey")] public string NameLocalkey { get; set; } = "";
        [JsonPropertyName("element_id")] public List<int> ElementId { get; set; } = new();
        [JsonPropertyName("shot_id")] public int ShotId { get; set; }
        [JsonPropertyName("use_burst_skill")] public int UseBurstSkill { get; set; }
        [JsonPropertyName("burst_duration")] public int BurstDuration { get; set; }
        /// <summary>"skill1" / "skill2" / "burst".</summary>
        [JsonPropertyName("skills")] public Dictionary<string, SkillSlotDto> Skills { get; set; } = new();
    }

    /// <summary>스킬 슬롯 1개 — StateEffect(패시브 다발) 또는 CharacterSkill(액티브/버스트).</summary>
    public sealed class SkillSlotDto
    {
        /// <summary>"StateEffect" / "CharacterSkill" (NikkeCharacterData.skill*_table).</summary>
        [JsonPropertyName("table")] public string Table { get; set; } = "";
        [JsonPropertyName("base_id")] public int BaseId { get; set; }
        /// <summary>key = 스킬 레벨 "1".."10" (레코드 id = base_id + lv − 1).</summary>
        [JsonPropertyName("levels")] public Dictionary<string, SkillLevelDto> Levels { get; set; } = new();
    }

    public sealed class SkillLevelDto
    {
        [JsonPropertyName("skill_id")] public int SkillId { get; set; }
        /// <summary>이 레벨이 발동시키는 function id 들 (connected 확장분은 Functions 사전에 포함).</summary>
        [JsonPropertyName("function_ids")] public List<int> FunctionIds { get; set; } = new();
        /// <summary>CharacterSkill 본체 (StateEffect 슬롯 = null).</summary>
        [JsonPropertyName("skill")] public CharacterSkillBodyDto Skill { get; set; }
    }

    /// <summary>CharacterSkill(액티브/버스트) 본체 수치 — SkillData 발췌.</summary>
    public sealed class CharacterSkillBodyDto
    {
        /// <summary>CharacterSkillType raw (7=ChangeWeapon, 9=InstantSkill 등).</summary>
        [JsonPropertyName("skill_type")] public int SkillType { get; set; }
        /// <summary>쿨타임 (1/100초 — 4000 = 40s).</summary>
        [JsonPropertyName("skill_cooltime")] public int SkillCooltime { get; set; }
        [JsonPropertyName("duration_type")] public int DurationType { get; set; }
        [JsonPropertyName("duration_value")] public int DurationValue { get; set; }
        /// <summary>스킬 계수/파라미터 (ChangeWeapon 이면 교체 shot_id·차지프레임 등).</summary>
        [JsonPropertyName("skill_value_data")] public List<SkillValueDto> SkillValueData { get; set; } = new();
        [JsonPropertyName("attack_type")] public int AttackType { get; set; }
        [JsonPropertyName("prefer_target")] public int PreferTarget { get; set; }
        [JsonPropertyName("prefer_target_condition")] public int PreferTargetCondition { get; set; }
        [JsonPropertyName("resource_name")] public string ResourceName { get; set; }
    }

    public sealed class SkillValueDto
    {
        /// <summary>ValueType raw (1=Integer, 2=Percent(×10000)).</summary>
        [JsonPropertyName("skill_value_type")] public int SkillValueType { get; set; }
        [JsonPropertyName("skill_value")] public long SkillValue { get; set; }
    }

    /// <summary>솔로 레이드 보스 (key = monster_id; statenhance 230000 변종).</summary>
    public sealed class BossChainDto
    {
        [JsonPropertyName("name_localkey")] public string NameLocalkey { get; set; } = "";
        [JsonPropertyName("element_id")] public List<int> ElementId { get; set; } = new();
        [JsonPropertyName("model_id")] public int ModelId { get; set; }
        [JsonPropertyName("passive_skill_id")] public int PassiveSkillId { get; set; }
        [JsonPropertyName("passive_function_ids")] public List<int> PassiveFunctionIds { get; set; }
        [JsonPropertyName("skills")] public List<BossSkillDto> Skills { get; set; } = new();
    }

    /// <summary>보스 스킬 1개 — function 체인만 (스킬 자체 수치 = MonsterSkillTable, 미디코드).</summary>
    public sealed class BossSkillDto
    {
        [JsonPropertyName("skill_id")] public int SkillId { get; set; }
        [JsonPropertyName("use_function_ids")] public List<int> UseFunctionIds { get; set; } = new();
        [JsonPropertyName("hurt_function_ids")] public List<int> HurtFunctionIds { get; set; } = new();
    }

    /// <summary>StateEffect — 패시브 스킬의 function 다발.</summary>
    public sealed class StateEffectDto
    {
        [JsonPropertyName("use_function_id_list")] public List<int> UseFunctionIdList { get; set; } = new();
        [JsonPropertyName("hurt_function_id_list")] public List<int> HurtFunctionIdList { get; set; } = new();
        [JsonPropertyName("functions")] public List<StateEffectFunctionDto> Functions { get; set; } = new();
    }

    public sealed class StateEffectFunctionDto
    {
        [JsonPropertyName("function")] public int Function { get; set; }
    }

    /// <summary>
    /// FunctionData — 효과 원자 단위 (what/when/who/how much/duration). Fx/아이콘 필드는 조립 시 제거됨.
    /// enum 필드 = 원시 int (미지값 보존) — <c>Typed*</c> 프로퍼티로 타입드 접근.
    /// </summary>
    public sealed class FunctionDto
    {
        [JsonPropertyName("id")] public int Id { get; set; }
        [JsonPropertyName("group_id")] public int GroupId { get; set; }
        [JsonPropertyName("level")] public int Level { get; set; }
        [JsonPropertyName("name_localkey")] public string NameLocalkey { get; set; }

        [JsonPropertyName("buff")] public int Buff { get; set; }
        [JsonPropertyName("buff_remove")] public int BuffRemove { get; set; }
        [JsonPropertyName("function_type")] public int FunctionType { get; set; }
        [JsonPropertyName("function_standard")] public int FunctionStandard { get; set; }
        [JsonPropertyName("function_value_type")] public int FunctionValueType { get; set; }
        /// <summary>raw — Percent(2)면 ×10000 = 100%.</summary>
        [JsonPropertyName("function_value")] public long FunctionValue { get; set; }
        [JsonPropertyName("full_count")] public int FullCount { get; set; }
        [JsonPropertyName("is_cancel")] public bool IsCancel { get; set; }
        [JsonPropertyName("delay_type")] public int DelayType { get; set; }
        [JsonPropertyName("delay_value")] public int DelayValue { get; set; }
        [JsonPropertyName("duration_type")] public int DurationType { get; set; }
        [JsonPropertyName("duration_value")] public int DurationValue { get; set; }
        /// <summary>중첩 상한.</summary>
        [JsonPropertyName("limit_value")] public int LimitValue { get; set; }
        [JsonPropertyName("function_target")] public int FunctionTarget { get; set; }
        [JsonPropertyName("timing_trigger_type")] public int TimingTriggerType { get; set; }
        [JsonPropertyName("timing_trigger_standard")] public int TimingTriggerStandard { get; set; }
        [JsonPropertyName("timing_trigger_value")] public int TimingTriggerValue { get; set; }
        [JsonPropertyName("status_trigger_type")] public int StatusTriggerType { get; set; }
        [JsonPropertyName("status_trigger_standard")] public int StatusTriggerStandard { get; set; }
        [JsonPropertyName("status_trigger_value")] public long StatusTriggerValue { get; set; }
        [JsonPropertyName("status_trigger2_type")] public int StatusTrigger2Type { get; set; }
        [JsonPropertyName("status_trigger2_standard")] public int StatusTrigger2Standard { get; set; }
        [JsonPropertyName("status_trigger2_value")] public long StatusTrigger2Value { get; set; }
        [JsonPropertyName("keeping_type")] public int KeepingType { get; set; }
        [JsonPropertyName("connected_function")] public List<int> ConnectedFunction { get; set; } = new();

        // ── 타입드 접근 (미지값 = 정의 밖 enum 값으로 보존됨 — IsDefined 로 판별 가능) ──
        [JsonIgnore] public FunctionType TypedFunctionType => (FunctionType)FunctionType;
        [JsonIgnore] public TimingTriggerType TypedTimingTrigger => (TimingTriggerType)TimingTriggerType;
        [JsonIgnore] public StatusTriggerType TypedStatusTrigger => (StatusTriggerType)StatusTriggerType;
        [JsonIgnore] public FunctionTargetType TypedTarget => (FunctionTargetType)FunctionTarget;
        [JsonIgnore] public StandardType TypedStandard => (StandardType)FunctionStandard;
        [JsonIgnore] public DurationType TypedDurationType => (DurationType)DurationType;
        [JsonIgnore] public ValueType TypedValueType => (ValueType)FunctionValueType;

        /// <summary>Percent(×10000) → 분수. Integer/기타 = raw 그대로 (소비처가 해석).</summary>
        [JsonIgnore] public double ValueAsFraction => TypedValueType == Skills.ValueType.Percent
            ? FunctionValue / 10000.0 : FunctionValue;
    }
}
