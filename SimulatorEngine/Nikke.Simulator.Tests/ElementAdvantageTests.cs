using Nikke.Simulator.Core.Combat;
using Xunit;

namespace Nikke.Simulator.Tests;

/// <summary>
/// T04 — 속성 상성 단위테스트. 순환(사용자 확정 2026-07-08): Water→Fire→Wind→Iron→Electric→Water.
/// 수용 기준: 순환 5케이스 우월 +0.1 / 역상성·무상성·자기상성 = 0 / 미지·빈 속성 graceful 0.
/// </summary>
public class ElementAdvantageTests
{
    [Theory]
    [InlineData("Water", "Fire")]
    [InlineData("Fire", "Wind")]
    [InlineData("Wind", "Iron")]
    [InlineData("Iron", "Electric")]
    [InlineData("Electric", "Water")]
    public void StrongCycle_Gives_Bonus(string attacker, string target)
    {
        Assert.True(ElementAdvantage.IsStrongAgainst(attacker, target));
        Assert.Equal(0.1, ElementAdvantage.GetBonus(attacker, target));
    }

    [Theory]
    [InlineData("Fire", "Water")]      // 역상성 — 페널티 없음(확정)
    [InlineData("Wind", "Fire")]
    [InlineData("Iron", "Wind")]
    [InlineData("Electric", "Iron")]
    [InlineData("Water", "Electric")]
    [InlineData("Fire", "Fire")]       // 동속성
    [InlineData("Water", "Iron")]      // 비인접 — 무상성
    public void NonStrong_Gives_Zero(string attacker, string target)
    {
        Assert.False(ElementAdvantage.IsStrongAgainst(attacker, target));
        Assert.Equal(0.0, ElementAdvantage.GetBonus(attacker, target));
    }

    [Theory]
    [InlineData(null, "Fire")]
    [InlineData("", "Fire")]
    [InlineData("Fire", null)]
    [InlineData("Fire", "")]
    [InlineData("Cosmic", "Fire")]     // 미지 신속성 — graceful no-op (INV-1)
    public void UnknownOrEmpty_Gives_Zero(string? attacker, string? target)
        => Assert.Equal(0.0, ElementAdvantage.GetBonus(attacker, target));

    [Fact]
    public void CaseInsensitive()
        => Assert.True(ElementAdvantage.IsStrongAgainst("water", "FIRE"));
}
