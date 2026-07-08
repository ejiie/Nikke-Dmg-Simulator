using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine;
using Nikke.Simulator.Engine.Combat;
using Nikke.Simulator.Engine.Targets;
using CoreNikke = Nikke.Simulator.Core.Entities.Nikke;

namespace Nikke.Simulator.Tests;

/// <summary>
/// K8 — SimulationRunner.RunOnce 통합 (M1: 스킬·팀버프 없는 평타 시간축).
/// 합성 니케 + DEF 거대 타겟(<see cref="MinDamageTarget"/>)으로 히트당 대미지를 최소뎀 1에 고정
/// → **타이밍·배선**을 프레임 단위 검증 (TotalDamage == HitCount 불변식).
/// 실제 DPS 골든(in-game 대조) = M2, 사용자 실측.
/// 확률(크리/코어힛)은 INV 규칙대로 시스템 RNG **수렴**으로 검증 (고정 시드 금지).
/// </summary>
public class SimulationRunnerTests
{
    private sealed class MinRandom : IRandomSource
    {
        public double NextDouble() => 0.0;
    }

    /// <summary>
    /// DEF 거대값 타겟 — 최소뎀 규칙(DEF≥ATK → 1)으로 히트당 대미지를 1로 고정.
    /// 다른 테스트 클래스가 xUnit 병렬로 전역 StatTable/EffectTable 을 초기화해도
    /// (합성 니케 ATK 가 0이 아니게 돼도) 타이밍 불변식(TotalDamage == HitCount)이 유지된다.
    /// </summary>
    private static DummyTarget MinDamageTarget(double coreRadius = 0, double bodyRadius = 0)
        => new(finalDef: 1e12, coreRadius: coreRadius, bodyRadius: bodyRadius);

    private static CoreNikke MakeNikke(WeaponDto weapon, string weaponName, int ammo)
    {
        var dto = new CharacterDto
        {
            name_code = "9999",
            StaticInfo = new CharacterStaticDto
            {
                name = "TestUnit",
                element = "Iron",
                weapon = weaponName,
                character_class = "Attacker",
                manufacturer = "Elysion",
                ammoCapacity = ammo,
                reloadTime = weapon.reloadTimeSec,
                basicAttack = new BasicAttackDto { multiplier = 100.0 }, // W = 1.0
                weaponData = weapon,
                properRange = new ProperRangeDto { min = 25, max = 45 },
            },
            user = new CharacterUserDto { level = 1, grade = 0, core = 0, bond_level = 0 },
        };
        return new CoreNikke(dto, new GlobalStateDto { consoles = new Dictionary<string, int>() });
    }

    private static WeaponDto ArWeapon() => new()
    {
        weaponType = "AR", inputType = "DOWN", fireType = "Instant",
        fireRate = 12, endFireRate = 12, spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
        maxAmmo = 60, reloadTimeSec = 1.0, reloadBulletRate = 1.0, shotCount = 1, muzzleCount = 1,
        accuracy = new WeaponAccuracyDto { startCircle = 75, endCircle = 75 },
    };

    private static WeaponDto SgWeapon() => new()
    {
        weaponType = "SG", inputType = "DOWN", fireType = "Instant",
        fireRate = 1.5, endFireRate = 1.5, spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
        maxAmmo = 9, reloadTimeSec = 1.5, reloadBulletRate = 1.0, shotCount = 10, muzzleCount = 1,
        accuracy = new WeaponAccuracyDto { startCircle = 250, endCircle = 250 },
    };

    // ───────────────────── 타이밍·배선 (결정론 — RNG 는 크리에만 관여, 대미지 = 최소뎀 1) ─────────────────────

    [Fact]
    public void RunOnce_frame_exact_hit_timeline_with_reload_cycle()
    {
        var team = new[] { new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "u1") };
        var r = SimulationRunner.RunOnce(team, MinDamageTarget(), new MinRandom(), 10.0);

        // AR 12/s: f13 첫발 +5f 주기, 60발 탄창 → f308 소진. auto 재장전 72f(f309~380) + spotFirst 12f
        // → f393 재개, 600f(10s)까지 42발 → 총 102히트. 스탯 0 → 히트당 최소뎀 1.
        Assert.Equal(102, r.HitCount);
        Assert.Equal(102.0, r.TotalDamage, 9);
        Assert.Equal(102.0, r.DamageBySource["u1"], 9);
        Assert.Equal(10.0, r.DurationSec, 9);
        Assert.Equal(10, r.DamagePerSecond.Count);
        Assert.Equal(r.TotalDamage, r.DamagePerSecond.Sum(), 9);
    }

    [Fact]
    public void RunOnce_first_second_bucket_contains_post_transition_hits()
    {
        var team = new[] { new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "u1") };
        var r = SimulationRunner.RunOnce(team, MinDamageTarget(), new MinRandom(), 2.0);

        // 2초 = 120f: f13..118 → 22발. 0초 버킷 = f13..59 (t<1.0) = 10발, 1초 버킷 = f60..118 = 12발.
        Assert.Equal(22, r.HitCount);
        Assert.Equal(10.0, r.DamagePerSecond[0], 9);
        Assert.Equal(12.0, r.DamagePerSecond[1], 9);
    }

    [Fact]
    public void RunOnce_team_of_two_records_both_sources()
    {
        var team = new[]
        {
            new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "a"),
            new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "b"),
        };
        var r = SimulationRunner.RunOnce(team, MinDamageTarget(), new MinRandom(), 2.0);

        Assert.Equal(22.0, r.DamageBySource["a"], 9);
        Assert.Equal(22.0, r.DamageBySource["b"], 9);
        Assert.Equal(44.0, r.TotalDamage, 9);
    }

    [Fact]
    public void RunOnce_shotgun_records_pellet_instances()
    {
        var team = new[] { new Combatant(MakeNikke(SgWeapon(), "Shotgun", 9), "sg") };
        var r = SimulationRunner.RunOnce(team, MinDamageTarget(), new MinRandom(), 2.0);

        // SG 1.5/s: f13 첫발 +40f 주기 → 120f 내 f13, f53, f93 = 3트리거 × 펠릿 10 = 30히트
        Assert.Equal(30, r.HitCount);
        Assert.Equal(30.0, r.TotalDamage, 9);
    }

    [Fact]
    public void RunOnce_validates_arguments()
    {
        var rng = new MinRandom();
        var team = new[] { new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "u1") };
        Assert.Throws<System.ArgumentException>(
            () => SimulationRunner.RunOnce(System.Array.Empty<Combatant>(), MinDamageTarget(), rng, 1));
        Assert.Throws<System.ArgumentNullException>(
            () => SimulationRunner.RunOnce(team, null, rng, 1));
        Assert.Throws<System.ArgumentOutOfRangeException>(
            () => SimulationRunner.RunOnce(team, MinDamageTarget(), rng, 0));
    }

    // ───────────────────── 확률 축 (시스템 RNG 수렴 — INV: 고정 시드 금지) ─────────────────────

    [Fact]
    public void Crit_rate_converges_to_base_15_percent()
    {
        var team = new[] { new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "u1") };
        var r = SimulationRunner.RunOnce(team, MinDamageTarget(), SystemRandomSource.Instance, 600.0);

        // 대미지 1/히트 → crit=True 태그 합 = 크리 히트 수. N≈6100 → 0.15 ± 0.02 (4σ+)
        double critFraction = r.DamageByTag.GetValueOrDefault("crit=True") / r.TotalDamage;
        Assert.InRange(critFraction, 0.13, 0.17);
    }

    [Fact]
    public void Core_hit_rate_converges_to_area_ratio()
    {
        var team = new[] { new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "u1") };
        // AR 명중원 75 고정, 코어 반지름 25 → P(코어힛) = (25/75)² = 1/9 ≈ 0.111
        var target = MinDamageTarget(coreRadius: 25.0);
        var r = SimulationRunner.RunOnce(team, target, SystemRandomSource.Instance, 600.0);

        double coreFraction = r.DamageByTag.GetValueOrDefault("core=True") / r.TotalDamage;
        Assert.InRange(coreFraction, 0.085, 0.14);
    }

    [Fact]
    public void Body_radius_gates_hits_by_area_probability()
    {
        var team = new[] { new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "u1") };
        // 몸체 반지름 25 vs 명중원 75 → P(명중) = 1/9. 빗맞음 = 히트 미기록.
        var target = MinDamageTarget(bodyRadius: 25.0);
        var r = SimulationRunner.RunOnce(team, target, SystemRandomSource.Instance, 600.0);

        // 총 발사 수 = 결정론(6096발@600s) — 명중만 기록되므로 비율 수렴 확인
        var deterministic = SimulationRunner.RunOnce(
            new[] { new Combatant(MakeNikke(ArWeapon(), "Assault Rifle", 60), "u2") },
            MinDamageTarget(), new MinRandom(), 600.0);
        double hitFraction = r.HitCount / (double)deterministic.HitCount;
        Assert.InRange(hitFraction, 0.085, 0.14);
    }
}
