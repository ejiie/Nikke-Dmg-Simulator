using System;
using System.Collections.Generic;
using Nikke.Simulator.Engine.Buffs;
using CoreNikke = Nikke.Simulator.Core.Entities.Nikke;
using Nikke.Simulator.Core.Combat;

namespace Nikke.Simulator.Engine.Combat
{
    /// <summary>
    /// 전투 1회 동안의 캐릭터 런타임 상태 (ENGINE_GUIDE §5).
    /// Core <see cref="CoreNikke"/> 를 래핑한다. **Core Nikke 는 static(불변 최종 기초스탯) 유지** —
    /// 가변 런타임 상태(활성 버프/탄창/차지/버스트 게이지/스택 토큰)는 전부 이 클래스가 보유.
    ///
    /// K0 = 동결 계약 스텁. 실 배선(버프 집계→ctx, 탄창/차지 진행)은 Wave1~2 (K3/K7/K8).
    /// </summary>
    public sealed class Combatant
    {
        /// <summary>래핑된 Core 캐릭 (static 최종 기초스탯 + BuildAttackContext 팩토리).</summary>
        public CoreNikke Nikke { get; }

        /// <summary>팀 내 고유 식별자 (메트릭 sourceId / cross-buff 대상 지정용).</summary>
        public string Id { get; }

        /// <summary>이 캐릭에게 현재 적용 중인 버프(자기 + 팀 전파). 만료 tick 에 제거. (K7 이 채움)</summary>
        public List<BuffInstance> ActiveBuffs { get; } = new();

        public Combatant(CoreNikke nikke, string id)
        {
            Nikke = nikke ?? throw new ArgumentNullException(nameof(nikke));
            Id = id ?? throw new ArgumentNullException(nameof(id));
        }

        /// <summary>
        /// 이번 히트의 <see cref="AttackContext"/> 를 만든다: Nikke 의 static 주입분 +
        /// 활성 버프 집계(니케식 group-then-round) + 타겟/플래그.
        /// 임플 = Wave2 K7/K8 (BuffAggregator). K0 스텁.
        /// </summary>
        public AttackContext BuildHitContext()
            => throw new NotImplementedException("BuffAggregator 배선 대기 (Wave2 K7/K8).");
    }
}
