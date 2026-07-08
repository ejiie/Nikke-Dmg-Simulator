using System.Linq;
using Nikke.Simulator.Engine.Skills;

namespace Nikke.Simulator.Tests;

/// <summary>
/// K4 — 공식 스킬 데이터 로더/번역기 검증. 소스 = skill_chains.json(gitignore, 로컬 생성)
/// — 부재 시 데이터 의존 테스트는 skip (기존 merged DB 패턴). 번역기 단위 테스트는 무의존.
/// 기대값 출처 = D1 검증 (roledata bit-exact, VERIFICATION_LOG 2026-07-08).
/// </summary>
public class SkillChainLoaderTests
{
    private static SkillChainsDto Load()
        => SkillChainLoader.TryLoad(out var c) ? c : null;

    // ───────────────────────── 로더 (데이터 의존 — skip if absent) ─────────────────────────

    [Fact]
    public void Loads_full_roster_with_reference_integrity()
    {
        var c = Load();
        if (c == null) return; // 데이터 없는 환경 = 정상 skip

        Assert.True(c.Characters.Count >= 190);            // 2026-07 기준 192
        Assert.True(c.Functions.Count >= 14_000);          // 사용 함수 14,249
        Assert.True(c.Bosses.Count >= 80);                 // 솔로 레이드 87 변종
        // 무결성은 TryLoad 내 Validate 가 보장 (위반 시 여기 도달 전 throw)
    }

    [Fact]
    public void Emma_skill1_lv10_resolves_to_verified_function()
    {
        var c = Load();
        if (c == null) return;

        var lv10 = c.Characters["5005"].Skills["skill1"].Levels["10"];
        var fn = c.Functions[lv10.FunctionIds[0].ToString()];
        // D1 검증값: HealCharacter 1077(=10.77%) · OnHurtRatio 500(=5% 확률)
        Assert.Equal(FunctionType.HealCharacter, fn.TypedFunctionType);
        Assert.Equal(1077, fn.FunctionValue);
        Assert.Equal(0.1077, fn.ValueAsFraction, 9);
        Assert.Equal(TimingTriggerType.OnHurtRatio, fn.TypedTimingTrigger);
        Assert.Equal(500, fn.TimingTriggerValue);
        // 피격 트리거 = Runtime 축
        Assert.Equal(EffectAxis.Runtime, SkillTranslator.Classify(fn));
    }

    [Fact]
    public void Maxwell_burst_lv10_is_weapon_swap_with_verified_value()
    {
        var c = Load();
        if (c == null) return;

        var lv10 = c.Characters["5001"].Skills["burst"].Levels["10"];
        Assert.NotNull(lv10.Skill);
        Assert.Equal(7, lv10.Skill.SkillType);             // CharacterSkillType.ChangeWeapon
        Assert.Equal(4000, lv10.Skill.SkillCooltime);      // 40s (1/100초)
        Assert.Equal(81342, lv10.Skill.SkillValueData[0].SkillValue); // 813.42% (roledata bit-exact)
        Assert.Equal(120, lv10.Skill.SkillValueData[1].SkillValue);   // 차지 2초 = 120프레임(60fps)
    }

    [Fact]
    public void All_functions_route_and_classify_without_throw()
    {
        var c = Load();
        if (c == null) return;

        int unknown = 0, unverified = 0;
        foreach (var fn in c.Functions.Values)
        {
            var route = SkillTranslator.Route(fn);         // 미지 신값 포함 throw 금지 (INV)
            _ = SkillTranslator.Classify(fn);
            if (route == EffectRoute.Unknown) unknown++;
            if (route == EffectRoute.Unverified) unverified++;
        }
        // 미지 신값(컨버터 스냅샷 밖)은 존재하되 소수 — 전부 graceful 처리됨
        Assert.True(unknown < c.Functions.Count / 20);
        Assert.True(unverified < c.Functions.Count);       // 집계 자체가 성립 (스냅샷 지표)
    }

    [Fact]
    public void Boss_passives_resolve_to_functions()
    {
        var c = Load();
        if (c == null) return;

        var withPassive = c.Bosses.Values.Where(b => b.PassiveFunctionIds is { Count: > 0 }).ToList();
        Assert.NotEmpty(withPassive);
        Assert.All(withPassive, b => Assert.All(
            b.PassiveFunctionIds, fid => Assert.True(c.Functions.ContainsKey(fid.ToString()))));
    }

    // ───────────────────────── 번역기 (데이터 무의존) ─────────────────────────

    [Theory]
    [InlineData(FunctionType.StatAtk, EffectRoute.AtkRate)]
    [InlineData(FunctionType.StatCritical, EffectRoute.CritRateAdd)]
    [InlineData(FunctionType.StatCriticalDamage, EffectRoute.CritDmgAdd)]
    [InlineData(FunctionType.StatChargeDamage, EffectRoute.ChargeDmgAdd)]
    [InlineData(FunctionType.IncElementDmg, EffectRoute.StrongElemAdd)]
    [InlineData(FunctionType.PartsDamage, EffectRoute.PartsDmgAdd)]
    [InlineData(FunctionType.Damage, EffectRoute.DealDamage)]
    [InlineData(FunctionType.StatReloadTime, EffectRoute.ReloadTiming)]
    [InlineData(FunctionType.BurstGaugeCharge, EffectRoute.BurstGauge)]
    [InlineData(FunctionType.HealCharacter, EffectRoute.SurvivalOrHeal)]
    public void Route_maps_confirmed_types(FunctionType t, EffectRoute expected)
        => Assert.Equal(expected, SkillTranslator.Route(t));

    [Fact]
    public void Route_is_graceful_for_unverified_and_unknown()
    {
        // 기지 타입이나 브래킷 미검증 → Unverified (K8 대조로 승격 대상)
        Assert.Equal(EffectRoute.Unverified, SkillTranslator.Route(FunctionType.FullBurstDamage));
        // 컨버터 스냅샷 밖 신값 (D1 관측: 214~218) → Unknown, throw 없음
        Assert.Equal(EffectRoute.Unknown, SkillTranslator.Route((FunctionType)216));
        Assert.Equal(EffectRoute.Unknown, SkillTranslator.Route((FunctionType)9999));
    }

    [Fact]
    public void Classify_static_vs_runtime_axis()
    {
        // 트리거·조건 없음 + 영구 = Static (BuildAttackContext 주입)
        var passive = new FunctionDto
        {
            FunctionType = (int)FunctionType.StatAtk,
            TimingTriggerType = (int)TimingTriggerType.OnStart,
        };
        Assert.Equal(EffectAxis.Static, SkillTranslator.Classify(passive));

        // 지속시간 있는 버프 = Runtime
        var timed = new FunctionDto
        {
            FunctionType = (int)FunctionType.StatAtk,
            TimingTriggerType = (int)TimingTriggerType.OnStart,
            DurationType = (int)DurationType.TimeSec,
            DurationValue = 500,
        };
        Assert.Equal(EffectAxis.Runtime, SkillTranslator.Classify(timed));

        // 상태 조건(풀버스트 중 등) = Runtime
        var conditional = new FunctionDto
        {
            FunctionType = (int)FunctionType.StatAtk,
            StatusTriggerType = (int)StatusTriggerType.IsBurstStepState,
        };
        Assert.Equal(EffectAxis.Runtime, SkillTranslator.Classify(conditional));
    }
}
