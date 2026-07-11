using System;
using Nikke.Simulator.Engine.Skills;

namespace Nikke.Simulator.Engine.Buffs
{
    /// <summary>
    /// 런타임 버프 1개 — 공식 FunctionData 기준 (T01 확정, 구 string 슬롯 placeholder 대체).
    /// SkillRuntime 이 트리거 발동 시 스폰/스택, 만료 = 프레임 tick 에서 제거 (FACTS §4 — frame 도메인).
    /// BuffAggregator 가 활성 버프를 EffectRoute 별로 집계해 AttackContext 를 채운다.
    /// </summary>
    public sealed class BuffInstance
    {
        /// <summary>FunctionData id (진단/추적용).</summary>
        public int FunctionId { get; init; }

        /// <summary>function group_id — 스택/갱신 동일성 키 (같은 그룹 재발동 = 스택+갱신).</summary>
        public int GroupId { get; init; }

        /// <summary>공식 FunctionType raw int (미지 신값 보존 — INV).</summary>
        public int FunctionTypeRaw { get; init; }

        /// <summary>엔진 소비 슬롯 (SkillTranslator.Route).</summary>
        public EffectRoute Route { get; init; }

        /// <summary>스택 1개당 실효값 — Percent 는 분수(ValueAsFraction), Integer 는 raw.</summary>
        public double Value { get; init; }

        /// <summary>중첩 상한 (0 = 1스택).</summary>
        public int LimitValue { get; init; }

        /// <summary>full_count — OnFullCount/IsFullCount 판정 기준 (0 = 없음).</summary>
        public int FullCount { get; init; }

        /// <summary>만료 프레임 (exclusive — 이 프레임 tick 에서 제거). null = 영구/전투 지속.</summary>
        public int? ExpiryFrame { get; set; }

        /// <summary>잔여 발사 수 (DurationType.Shots/Hits 계열). null = 시간/영구.</summary>
        public int? RemainingShots { get; set; }

        /// <summary>현재 스택 수 (1 ≤ Stacks ≤ MaxStacks).</summary>
        public int Stacks { get; set; } = 1;

        /// <summary>버프를 건 주체 식별자 (cross-buff 추적). 자기버프 = 본인 id.</summary>
        public string SourceId { get; init; }

        public int MaxStacks => Math.Max(1, LimitValue);

        /// <summary>full_count 도달 (OnFullCount 트리거/IsFullCount 조건 판정).</summary>
        public bool AtFullCount => FullCount > 0 && Stacks >= FullCount;
    }
}
