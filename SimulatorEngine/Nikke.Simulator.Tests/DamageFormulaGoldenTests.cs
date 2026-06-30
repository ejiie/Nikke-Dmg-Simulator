using Nikke.Simulator.Core.Combat;

namespace Nikke.Simulator.Tests;

/// <summary>
/// 골든 회귀 테스트 — 실측 역산으로 확립된 퍼-히트 대미지 공식 (2026-06-27).
///
///   Damage = floor( B2 × (1+ΣB3) × (1+ΣB4) × (1+ΣB5) )
///     B2 = floor(P) + Σ_active floor(P × bracket_i)        P = (FinalAtk−DEF)·W·C
///
/// 테스트 리그: BASE_ATK 571218 → FinalAtk 901497 (niké式 OL), DEF 100,
///   W(계수)=4.995, C(차지)=10, 풀차지 스나 1히트.
///   표시계수: dist 0.3 / burst 0.5 / crit(0.5+0.7654) 1.2654 / core(1.0+0.1704) 1.1704.
///   B3 attack_dmg 0.484 / B4 damage_taken 0.042 / B5 strong_elem 1.4293.
///
/// 정확도: 표시계수로 in-game 측정값과 잔차 ≤1.3e-7 (계수 표시반올림). 1e-6 허용.
/// (bit-exact 0 은 datamined 계수 필요 — gap, 별도.)
/// </summary>
public class DamageFormulaGoldenTests
{
    private const double Tol = 1e-6;   // in-game 대비 상대오차 허용 (실측 잔차 ≈1.3e-7, 10x 마진)

    /// <summary>테스트 리그 컨텍스트. 플래그/브래킷만 토글.</summary>
    private static AttackContext Rig(
        bool dist = false, bool burst = false, bool crit = false, bool core = false,
        double b3 = 0.0, double b4 = 0.0, double b5 = 0.0)
    {
        var ctx = new AttackContext(901497, 100)
        {
            SkillMultiplier = 4.995,   // W (계수)
            IsFullCharge = true,
            ChargeDmgBase = 10.0,      // C (차지)
            SumCritDmg = 1.2654,       // 기본 0.5 + OL크뎀 0.7654
            SumCoreHitBuff = 0.1704,   // 콜렉션 코어업 (CoreHitBase 1.0 은 ctor)
            ProperDistanceBonus = dist ? 0.3 : 0.0,
            FullBurstBonus = burst ? 0.5 : 0.0,
            IsCrit = crit,
            IsCoreHit = core,
            SumAttackDmg = b3,
            SumDamageTaken = b4,
            SumStrongElem = b5,
        };
        return ctx;
    }

    private static void AssertWithin(double measured, double actual)
        => Assert.True(Math.Abs(actual - measured) / measured < Tol,
                       $"actual={actual:F0} measured={measured:F0} rel={Math.Abs(actual - measured) / measured:E2}");

    // ── B2 only (B3=B4=B5=0) — 10 골든 포인트 ──
    [Theory]
    [InlineData(false, false, false, false, 45024780)]
    [InlineData(true,  false, false, false, 58532212)]
    [InlineData(true,  true,  false, false, 81044602)]
    [InlineData(false, false, true,  false, 101999134)]
    [InlineData(false, false, false, true,  97721778)]
    [InlineData(false, true,  true,  false, 124511524)]
    [InlineData(true,  true,  false, true,  133741600)]
    [InlineData(false, false, true,  true,  154696132)]
    [InlineData(false, true,  false, true,  120234168)]
    [InlineData(false, true,  true,  true,  177208522)]
    public void B2_MatchesInGame(bool dist, bool burst, bool crit, bool core, long measured)
        => AssertWithin(measured, DamageCalculator.CalculateDamage(Rig(dist, burst, crit, core)));

    // ── 크로스-브래킷 B3/B4/B5 (곱셈) — in-game 골든 포인트 ──
    [Fact] public void DistB5()       => AssertWithin(142192292, DamageCalculator.CalculateDamage(Rig(dist: true, b5: 1.4293)));
    [Fact] public void CritB5()       => AssertWithin(247786478, DamageCalculator.CalculateDamage(Rig(crit: true, b5: 1.4293)));
    [Fact] public void DistCritB5()   => AssertWithin(280600080, DamageCalculator.CalculateDamage(Rig(dist: true, crit: true, b5: 1.4293)));
    [Fact] public void DistCoreB5()   => AssertWithin(270209101, DamageCalculator.CalculateDamage(Rig(dist: true, core: true, b5: 1.4293)));
    [Fact] public void FullB5()       => AssertWithin(463306234, DamageCalculator.CalculateDamage(Rig(dist: true, burst: true, crit: true, core: true, b5: 1.4293)));
    [Fact] public void DistB3()       => AssertWithin(86861800,  DamageCalculator.CalculateDamage(Rig(dist: true, b3: 0.484)));
    [Fact] public void DistB3B5()     => AssertWithin(211013357, DamageCalculator.CalculateDamage(Rig(dist: true, b3: 0.484, b5: 1.4293)));
    [Fact] public void DistB3B4B5()   => AssertWithin(219875918, DamageCalculator.CalculateDamage(Rig(dist: true, b3: 0.484, b4: 0.042, b5: 1.4293)));

    // ── 구조 불변식: B2 는 가산 per-term (정수 정확) ──
    [Fact]
    public void B2_IsAdditivePerTerm()
    {
        double none = DamageCalculator.CalculateDamage(Rig());
        double dist = DamageCalculator.CalculateDamage(Rig(dist: true));
        double burst = DamageCalculator.CalculateDamage(Rig(burst: true));
        double distBurst = DamageCalculator.CalculateDamage(Rig(dist: true, burst: true));
        // burst 증가분이 컨텍스트 무관하게 동일 ⟺ 가산 구조
        Assert.Equal(burst - none, distBurst - dist);
    }

    // ── 구조 불변식: B5 는 B2 를 곱셈으로 감싼다 (정수 정확) ──
    [Fact]
    public void B5_IsMultiplicativeWrap()
    {
        double dist = DamageCalculator.CalculateDamage(Rig(dist: true));
        double distB5 = DamageCalculator.CalculateDamage(Rig(dist: true, b5: 1.4293));
        Assert.Equal(Math.Floor(dist * (1.0 + 1.4293)), distB5);
    }

    // ── 구조 불변식: B3 와 B5 는 서로 곱한다 (합 아님) ──
    [Fact]
    public void B3_B5_MultiplyEachOther()
    {
        double dist = DamageCalculator.CalculateDamage(Rig(dist: true));
        double distB3B5 = DamageCalculator.CalculateDamage(Rig(dist: true, b3: 0.484, b5: 1.4293));
        double multiply = Math.Floor(dist * (1.0 + 0.484) * (1.0 + 1.4293));
        double shareSum = Math.Floor(dist * (1.0 + 0.484 + 1.4293));
        Assert.Equal(multiply, distB3B5);
        Assert.NotEqual(shareSum, distB3B5);
    }

    // ── #8 최소 대미지: 깡뎀(FinalAtk−DEF) ≤ 0 이면 크리/코어/우월/브래킷 무관 무조건 1 ──
    [Fact]
    public void MinDamage_AtkBelowDef_AlwaysOne()
    {
        var ctx = new AttackContext(50, 100)   // FinalAtk < FinalDef
        {
            SkillMultiplier = 4.995, IsFullCharge = true, ChargeDmgBase = 10.0,
            IsCrit = true, IsCoreHit = true, SumCritDmg = 1.2654, SumCoreHitBuff = 0.1704,
            ProperDistanceBonus = 0.3, FullBurstBonus = 0.5, SumStrongElem = 1.4293,
        };
        Assert.Equal(1.0, DamageCalculator.CalculateDamage(ctx));
    }

    // ── #6 true_dmg: DEF 무시 (DEF=0 으로 계산) — DEF 값과 무관, 비-true DEF=0 과 동일 ──
    [Fact]
    public void TrueDamage_IgnoresDef()
    {
        double trueHi = DamageCalculator.CalculateDamage(new AttackContext(901497, 5000)
            { SkillMultiplier = 4.995, IsFullCharge = true, ChargeDmgBase = 10.0, IsTrueDamage = true });
        double trueZero = DamageCalculator.CalculateDamage(new AttackContext(901497, 0)
            { SkillMultiplier = 4.995, IsFullCharge = true, ChargeDmgBase = 10.0, IsTrueDamage = true });
        double normalZeroDef = DamageCalculator.CalculateDamage(new AttackContext(901497, 0)
            { SkillMultiplier = 4.995, IsFullCharge = true, ChargeDmgBase = 10.0 });
        Assert.Equal(trueZero, trueHi);          // DEF 무관
        Assert.Equal(normalZeroDef, trueHi);     // = 일반 DEF0
    }

    // ── #2 distrib: IsDistributionHit 플래그일 때만 B4 가산 (damage_taken 상속+제약) ──
    [Fact]
    public void Distrib_GatedByFlag()
    {
        AttackContext Mk(bool distrib, double dval) => new AttackContext(901497, 100)
        {
            SkillMultiplier = 4.995, IsFullCharge = true, ChargeDmgBase = 10.0,
            ProperDistanceBonus = 0.3, SumDistribDmg = dval, IsDistributionHit = distrib,
        };
        double off = DamageCalculator.CalculateDamage(Mk(false, 0.5));
        double on = DamageCalculator.CalculateDamage(Mk(true, 0.5));
        double noBuff = DamageCalculator.CalculateDamage(Mk(false, 0.0));
        Assert.True(on > off);            // 분배 공격일 때만 증가
        Assert.Equal(noBuff, off);        // 미발동 시 distrib 값 무시
    }
}
