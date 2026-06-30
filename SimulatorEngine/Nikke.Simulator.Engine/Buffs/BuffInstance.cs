namespace Nikke.Simulator.Engine.Buffs
{
    /// <summary>
    /// 런타임 버프 1개 (ENGINE_GUIDE §5 BuffStore). SkillRuntime 이 트리거 발동 시 스폰,
    /// BuffStore 가 보관, 만료 tick 에 제거. BuffAggregator 가 활성 버프를 브래킷별로
    /// 집계(니케식 group-then-round)해 <see cref="Nikke.Simulator.Core.Combat.AttackContext"/> 를 채운다.
    ///
    /// 순수 데이터 컨테이너 — 동작 없음(throw 없음). 스폰/집계/만료 로직은 Wave2 K7.
    /// enum 슬롯(Stat/Bracket)은 스킬 소스 audit 확정 전까지 string 으로 둔다
    /// (skills_parsed.json v3 wire 값 그대로; ENGINE_GUIDE §5 "string + 검증" 허용).
    /// </summary>
    public sealed class BuffInstance
    {
        /// <summary>대상 스탯 (skill_schema StatType wire 값, 예: "atk_pct", "crit_dmg").</summary>
        public string Stat { get; init; } = "";

        /// <summary>버프 수치. scale/scale_base 해석 후의 실효값(엔진 책임).</summary>
        public double Value { get; init; }

        /// <summary>대미지 공식 브래킷 (FormulaBracket wire 값, 예: "b3_attack_dmg"). 비대미지 = null.</summary>
        public string? Bracket { get; init; }

        /// <summary>만료 절대시각(초). null = 영구/패시브.</summary>
        public double? ExpirySec { get; init; }

        /// <summary>현재 스택 수. 스택 없는 버프는 1.</summary>
        public int Stacks { get; init; } = 1;

        /// <summary>버프를 건 주체 식별자 (cross-buff 추적용). 자기버프 = 본인 id.</summary>
        public string? SourceId { get; init; }
    }
}
