using System.Collections.Generic;
using Nikke.Simulator.Core.Combat;
using Nikke.Simulator.Engine.Buffs;
using Nikke.Simulator.Engine.Skills;
using Xunit;

namespace Nikke.Simulator.Tests;

/// <summary>
/// T01 — BuffAggregator: 활성 버프 → AttackContext 합산.
/// ATK rate = 니케식 group-then-round (FACTS §3 — OverloadProcessor 재사용) / 가산 축 = 분수 단순합.
/// </summary>
public class BuffAggregatorTests
{
    private static BuffInstance Buff(EffectRoute route, double value, int stacks = 1)
        => new() { Route = route, Value = value, Stacks = stacks, LimitValue = stacks };

    [Fact]
    public void Empty_Buffs_NoChange()
    {
        var ctx = new AttackContext(1000, 0);
        BuffAggregator.Apply(ref ctx, new List<BuffInstance>());
        Assert.Equal(1000, ctx.FinalAtk, 12);
        Assert.Equal(0.5, ctx.SumCritDmg, 12);
    }

    [Fact]
    public void AtkRate_Uses_Group_Then_Round()
    {
        // 동일값 0.0515 × 3 항: per-term round(51.5)=52 → 156 (오답) vs
        // group-then-round: round(1000×0.0515×3) = round(154.5) = 155 (니케식 — FACTS §3)
        var ctx = new AttackContext(1000, 0);
        BuffAggregator.Apply(ref ctx, new List<BuffInstance>
        {
            Buff(EffectRoute.AtkRate, 0.0515, stacks: 3),
        });
        Assert.Equal(1155, ctx.FinalAtk, 9);
    }

    [Fact]
    public void AtkRate_Different_Values_Are_Separate_Groups()
    {
        // 0.10 그룹 round(100)=100 + 0.0515 그룹 round(51.5)=52 → 1152
        var ctx = new AttackContext(1000, 0);
        BuffAggregator.Apply(ref ctx, new List<BuffInstance>
        {
            Buff(EffectRoute.AtkRate, 0.10),
            Buff(EffectRoute.AtkRate, 0.0515),
        });
        Assert.Equal(1152, ctx.FinalAtk, 9);
    }

    [Fact]
    public void Additive_Axes_Sum_With_Stacks()
    {
        var ctx = new AttackContext(1000, 0);
        BuffAggregator.Apply(ref ctx, new List<BuffInstance>
        {
            Buff(EffectRoute.CritDmgAdd, 0.1432, stacks: 2),
            Buff(EffectRoute.ChargeDmgAdd, 0.25),
            Buff(EffectRoute.StrongElemAdd, 0.05),
            Buff(EffectRoute.CoreHitBuffAdd, 0.3),
            Buff(EffectRoute.PartsDmgAdd, 0.2),
            Buff(EffectRoute.PierceDmgAdd, 0.15),
            Buff(EffectRoute.CritRateAdd, 0.06),
        });
        Assert.Equal(0.5 + 0.2864, ctx.SumCritDmg, 12);
        Assert.Equal(0.25, ctx.SumChargeDmgAdd, 12);
        Assert.Equal(0.05, ctx.SumStrongElem, 12);
        Assert.Equal(0.3, ctx.SumCoreHitBuff, 12);
        Assert.Equal(0.2, ctx.SumPartsDmg, 12);
        Assert.Equal(0.15, ctx.SumPierceDmg, 12);
        Assert.Equal(0.15 + 0.06, ctx.BaseCritRate, 12);
    }

    [Fact]
    public void NonDps_Routes_Ignored()
    {
        var ctx = new AttackContext(1000, 500);
        BuffAggregator.Apply(ref ctx, new List<BuffInstance>
        {
            Buff(EffectRoute.DefRate, 0.5),        // 생존 — ctx 무변
            Buff(EffectRoute.HpRate, 0.5),
            Buff(EffectRoute.MaxAmmoRate, 0.5),     // FiringModel 축
            Buff(EffectRoute.SurvivalOrHeal, 0.5),
            Buff(EffectRoute.Unverified, 0.5),
        });
        Assert.Equal(1000, ctx.FinalAtk, 12);
        Assert.Equal(500, ctx.FinalDef, 12);
    }
}
