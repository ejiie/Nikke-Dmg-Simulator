using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Data.Constants;

namespace Nikke.Simulator.Tests;

/// <summary>
/// 큐브/소장품 공식 특수효과 표 로더·레벨해석·단위(percent→분수) 검증.
/// 기준: cube 1000308=Vigor(MaxHp L15 9.69% + ElemAdv 19.09%),
///       collection AR(Core L15 10.22% + Def 30%).
/// </summary>
public class EffectTableTests
{
    private const double Tol = 1e-6;

    public EffectTableTests()
    {
        EffectTable.InitializeCube(JsonProvider.GetSmartDatabasePath("cube_effect_table.json"));
        EffectTable.InitializeCollection(JsonProvider.GetSmartDatabasePath("collection_effect_table.json"));
    }

    [Fact]
    public void Cube_Vigor_L15_maxHp_and_elemAdv()
    {
        var e = EffectTable.GetCubeEffects(1000308, 15);   // Vigor
        Assert.Equal(0.0969, e[EffectType.MaxHp], Tol);              // 9.69%
        Assert.Equal(0.1909, e[EffectType.ElementAdvantageDamage], Tol); // 19.09%
    }

    [Fact]
    public void Collection_AR_L15_core_and_def()
    {
        var e = EffectTable.GetCollectionEffects("Assault Rifle", 15);
        Assert.Equal(0.1022, e[EffectType.CoreDamage], Tol);  // 10.22%
        Assert.Equal(0.30, e[EffectType.Def], Tol);           // 30%
    }

    [Fact]
    public void Collection_SR_L15_chargeMult()
    {
        var e = EffectTable.GetCollectionEffects("Sniper Rifle", 15);
        Assert.True(e[EffectType.ChargeDamageMultiplier] > 0);
        Assert.True(e[EffectType.Def] > 0);
    }

    [Fact]
    public void Conditional_cube_effects_are_noop_until_runtime_supports_them()
    {
        var bastion = EffectTable.GetCubeEffects(1000304, 15);
        var assist = EffectTable.GetCubeEffects(1000312, 15);

        Assert.DoesNotContain(EffectType.ReloadRounds, bastion.Keys);
        Assert.DoesNotContain(EffectType.MaxHp, assist.Keys);
        Assert.Equal(0.1909, assist[EffectType.ElementAdvantageDamage], Tol);
    }

    [Fact]
    public void UnknownCube_returnsEmpty()
    {
        Assert.Empty(EffectTable.GetCubeEffects(999999, 15));
    }
}
