namespace Nikke.Simulator.Engine.Buffs
{
    /// <summary>
    /// 런타임 버프 1개 (ENGINE_GUIDE §5 BuffStore). SkillRuntime 이 트리거 발동 시 스폰,
    /// BuffStore 가 보관, 만료 tick 에 제거. BuffAggregator 가 활성 버프를 브래킷별로
    /// 집계(니케식 group-then-round)해 <see cref="Nikke.Simulator.Core.Combat.AttackContext"/> 를 채운다.
    ///
    /// 순수 데이터 컨테이너 — 동작 없음(throw 없음). 스폰/집계/만료 로직은 K7.
    /// K7 에서 공식 FunctionData 기준으로 확장 예정: Standard/FunctionTarget/DurationType 슬롯 추가
    /// (SKILL_RUNTIME_REFERENCE §2 — einkk BattleBuff 대응). 현 string 슬롯은 그때 공식 enum 으로 재정의.
    /// </summary>
    public sealed class BuffInstance
    {
        /// <summary>대상 스탯 식별자 (K7 에서 공식 FunctionType 기준으로 재정의 예정).</summary>
        public string Stat { get; init; } = "";

        /// <summary>버프 수치. scale/scale_base 해석 후의 실효값(엔진 책임).</summary>
        public double Value { get; init; }

        /// <summary>대미지 공식 브래킷 식별자 (B2~B5; K7 에서 EffectRoute 기준 재정의 예정). 비대미지 = null.</summary>
        public string? Bracket { get; init; }

        /// <summary>만료 절대시각(초). null = 영구/패시브.</summary>
        public double? ExpirySec { get; init; }

        /// <summary>현재 스택 수. 스택 없는 버프는 1.</summary>
        public int Stacks { get; init; } = 1;

        /// <summary>버프를 건 주체 식별자 (cross-buff 추적용). 자기버프 = 본인 id.</summary>
        public string? SourceId { get; init; }
    }
}
