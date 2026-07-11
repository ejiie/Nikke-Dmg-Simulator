using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Combat;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine.Combat;
using Nikke.Simulator.Engine.Skills;

namespace Nikke.Simulator.Engine.Buffs
{
    /// <summary>
    /// T01 — 활성 버프 → <see cref="AttackContext"/> 합산. 매 히트 <c>BuildHitContext</c> 직후 적용.
    ///
    /// 합산 규칙 (FACTS §3):
    ///  - 기초스탯 rate(ATK) = **니케식 group-then-round** (동일값 선합산 → 그룹 사사오입 → 합; 정수 스탯
    ///    decimals=0) — <see cref="OverloadProcessor.CalculateFinalBaseStat"/> 재사용 (OL 과 동일 규칙).
    ///  - AttackContext 가산 축(SumCritDmg 등) = 분수 단순합 (raw ×10000 정수 유래 = 이진 오차 없음).
    ///  - 스택 = 스택 수 × 항 (동일값 group 에 스택 수만큼 기여).
    ///
    /// DPS 무관 route(DefRate/HpRate = 생존, MaxAmmoRate/타이밍 = FiringModel 축)는 여기서 소비 안 함.
    /// </summary>
    public static class BuffAggregator
    {
        /// <summary>ctx 에 활성 버프 반영. buffs 비었으면 무변 (구 경로와 동일).</summary>
        public static void Apply(ref AttackContext ctx, IReadOnlyList<BuffInstance> buffs)
        {
            if (buffs == null || buffs.Count == 0) return;

            List<double> atkTerms = null;

            foreach (var b in buffs)
            {
                switch (b.Route)
                {
                    case EffectRoute.AtkRate:
                        (atkTerms ??= new List<double>()).AddRange(
                            Enumerable.Repeat(b.Value, b.Stacks)); // 스택 = 동일값 항 반복 (그룹 합산 대상)
                        break;
                    case EffectRoute.CritRateAdd:
                        ctx.BaseCritRate += b.Value * b.Stacks;
                        break;
                    case EffectRoute.CritDmgAdd:
                        ctx.SumCritDmg += b.Value * b.Stacks;
                        break;
                    case EffectRoute.ChargeDmgAdd:
                        ctx.SumChargeDmgAdd += b.Value * b.Stacks;
                        break;
                    case EffectRoute.StrongElemAdd:
                        ctx.SumStrongElem += b.Value * b.Stacks; // 별축 가산 — 기본 +0.1 은 ElementAdvantage 단일 소스
                        break;
                    case EffectRoute.CoreHitBuffAdd:
                        ctx.SumCoreHitBuff += b.Value * b.Stacks;
                        break;
                    case EffectRoute.PartsDmgAdd:
                        ctx.SumPartsDmg += b.Value * b.Stacks;
                        break;
                    case EffectRoute.PierceDmgAdd:
                        ctx.SumPierceDmg += b.Value * b.Stacks;
                        break;
                    // 그 외 (DefRate/HpRate/MaxAmmoRate/타이밍/생존/Unverified…) = 이 집계 밖
                }
            }

            if (atkTerms != null)
                ctx.FinalAtk = OverloadProcessor.CalculateFinalBaseStat(ctx.FinalAtk, atkTerms, 0, decimals: 0);
        }
    }
}
