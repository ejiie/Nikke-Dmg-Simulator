using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Combat;
using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine.Targets;

namespace Nikke.Simulator.Tests;

/// <summary>
/// roledata weaponData 소비 검증 (2026-07-01 유실분 복구 + 2026-07-02 재통합):
/// WeaponProfile 파싱·발사속도 ramp, AccuracyModel 코어힛/명중 면적확률,
/// ProperDistanceTable 적정거리(공식 bonusrange), DummyTarget 컨텍스트 주입,
/// 커밋된 roledata_clean.json 192캐릭 전수 데이터 불변식.
/// ※ 속성 상성(ElementAdvantage) = 보류(2026-07-02 사용자 결정) — 상성 테스트 없음.
/// </summary>
public class WeaponDataTests
{
    // ───────────────────────── AccuracyModel ─────────────────────────

    [Fact]
    public void CoreHit_prob_is_area_ratio_user_example()
    {
        // 사용자 예시: 명중원 R=5, 코어 rc=4 → 16/25.
        Assert.Equal(16.0 / 25.0, AccuracyModel.CoreHitProbability(5.0, 4.0), 12);
    }

    [Theory]
    [InlineData(10.0, 10.0, 1.0)]   // 코어 ≥ 원 → 항상 코어
    [InlineData(10.0, 20.0, 1.0)]   // 코어 더 큼 → clamp 1
    [InlineData(10.0, 0.0, 0.0)]    // 코어 없음 → 0
    [InlineData(0.0, 4.0, 1.0)]     // 원 핀포인트(0) → 항상 코어
    public void CoreHit_prob_clamps(double circle, double core, double expected)
        => Assert.Equal(expected, AccuracyModel.CoreHitProbability(circle, core), 12);

    [Fact]
    public void Hit_prob_is_one_when_circle_within_body()
        => Assert.Equal(1.0, AccuracyModel.HitProbability(3.0, 5.0), 12);

    [Fact]
    public void CircleRadius_shrinks_with_shots_MG_spinup_then_clamps_at_end()
    {
        // MG: start 250 → end 10, changePerShot 7.
        Assert.Equal(250.0, AccuracyModel.CircleRadius(250, 10, 7, 0), 9);
        Assert.Equal(250.0 - 7 * 10, AccuracyModel.CircleRadius(250, 10, 7, 10), 9); // 180
        Assert.Equal(10.0, AccuracyModel.CircleRadius(250, 10, 7, 1000), 9);          // clamp end
    }

    [Fact]
    public void CircleRadius_constant_when_no_change_per_shot()
        => Assert.Equal(75.0, AccuracyModel.CircleRadius(75, 75, 0, 50), 9); // AR 고정

    [Fact]
    public void RollCoreHit_converges_to_area_ratio()
    {
        // R=5, rc=4 → 0.64. N=200k 수렴(±0.01). 고정 시드 금지 → 시스템 RNG.
        const int n = 200_000;
        int core = 0;
        var rng = SystemRandomSource.Instance;
        for (int i = 0; i < n; i++)
            if (AccuracyModel.RollCoreHit(rng, 5.0, 4.0)) core++;
        double p = (double)core / n;
        Assert.InRange(p, 0.63, 0.65);
    }

    // ──────────────────────── ProperDistanceTable ────────────────────

    [Theory]
    [InlineData("SG", 10.0, true)]    // SG [0,25]
    [InlineData("SG", 30.0, false)]
    [InlineData("SR", 80.0, true)]    // SR [45,100]
    [InlineData("SR", 10.0, false)]
    [InlineData("AR", 30.0, true)]    // AR [25,45]
    public void ProperRange_band_membership(string wt, double dist, bool inRange)
        => Assert.Equal(inRange, ProperDistanceTable.InProperRange(wt, dist));

    [Fact]
    public void RL_has_no_distance_bonus()
    {
        // roledata bonusrange 0-0 = 거리 보너스 없음 (DESIGN: RL=0 확증).
        Assert.False(ProperDistanceTable.InProperRange("RL", 45.0));
        Assert.Equal(0.0, ProperDistanceTable.GetBonus("RL", 45.0), 12);
    }

    [Fact]
    public void Bonus_is_design_constant_in_band()
        => Assert.Equal(0.3, ProperDistanceTable.GetBonus("AR", 30.0), 12);

    [Fact]
    public void ProperRange_accepts_longform_weapon_string()
        => Assert.True(ProperDistanceTable.InProperRange("Sniper Rifle", 80.0));

    [Fact]
    public void ProperRange_per_char_overload_handles_exceptions()
    {
        // per-char 경로: Nikke.ProperRangeMin/Max 직접 — SR 예외 캐릭(25-45)도 정확.
        Assert.Equal(0.3, ProperDistanceTable.GetBonusPerChar(30.0, 25, 45), 12);
        Assert.Equal(0.0, ProperDistanceTable.GetBonusPerChar(80.0, 25, 45), 12);
        Assert.Equal(0.0, ProperDistanceTable.GetBonusPerChar(0.0, 0, 0), 12);  // RL 0-0 → 보너스 없음
    }

    [Fact]
    public void Band_table_matches_committed_proper_distance_json()
    {
        // 하드코딩 밴드 ↔ 커밋된 proper_distance_table.json (roledata bonusrange 최빈값) 교차검증.
        string path;
        try { path = JsonProvider.GetSmartDatabasePath("proper_distance_table.json"); }
        catch { return; }
        if (!System.IO.File.Exists(path)) return;

        var table = JsonProvider.LoadJson<Dictionary<string, ProperRangeDto>>(path);
        foreach (var (weapon, range) in table)
        {
            var band = ProperDistanceTable.GetBand(weapon);
            if (weapon == "Rocket Launcher")
            {
                Assert.False(band.HasBonus);
                continue;
            }
            Assert.True(band.HasBonus);
            Assert.Equal(range.min.Value, band.Min, 9);
            Assert.Equal(range.max.Value, band.Max, 9);
        }
    }

    // ──────────────────────── WeaponProfile ──────────────────────────

    [Fact]
    public void Empty_profile_is_null_safe()
    {
        var w = WeaponProfile.Empty;
        Assert.Equal("", w.WeaponTypeCode);
        Assert.Equal(1.0, w.FullChargeDamage, 12);   // 비차지 기본
        Assert.Equal(0.0, w.FireRate, 12);
    }

    [Fact]
    public void Profile_parses_and_ramps_fire_rate()
    {
        // Emma MG: fireRate 1 → end 70, ramp 1.667/shot.
        var dto = new WeaponDto
        {
            weaponType = "MG",
            fireRate = 1.0,
            endFireRate = 70.0,
            fireRateRampPerShot = 5.0 / 3.0,
            shotCount = 1,
            muzzleCount = 1,
        };
        var w = new WeaponProfile(dto);
        Assert.Equal("MG", w.WeaponTypeCode);
        Assert.Equal(70.0, w.EndFireRate, 9);                      // nominal(데이터) 보존
        Assert.Equal(1.0, w.FireRateAtShot(0), 9);
        Assert.Equal(1.0 + (5.0 / 3.0) * 3, w.FireRateAtShot(3), 9); // 6.0 (캡 미만 — 영향 없음)
        Assert.Equal(60.0, w.FireRateAtShot(10_000), 9);           // nominal 70 → 실현 60 (60fps 프레임 캡)
        Assert.Equal(WeaponProfile.EngineFrameRate, w.FireRateAtShot(10_000), 9);
        Assert.Equal(1.0 / 60.0, w.FireIntervalSec(10_000), 9);    // 최소 1프레임 간격
        Assert.Equal(1.0, w.FireIntervalSec(0), 9);                 // 1/1
    }

    // ──────────────────────── DummyTarget wiring ─────────────────────

    [Fact]
    public void DummyTarget_populates_def_and_proper_distance()
    {
        var ctx = new AttackContext(finalAtk: 1000, finalDef: 50);
        // AR 로 거리 30 (AR 적정구간 [25,45]) 에서. Water 공격자 vs Fire 타겟 = 우월.
        var tgt = new DummyTarget(finalDef: 200, element: "Fire", distance: 30.0);
        tgt.PopulateContext(ref ctx, attackerElement: "Water", attackerWeaponType: "AR");

        Assert.Equal(200, ctx.FinalDef, 9);                 // DEF 덮어씀
        Assert.Equal(0.1, ctx.SumStrongElem, 9);            // 상성 통합(T04, 2026-07-11) — 기본 우월 +0.1
        Assert.Equal(0.3, ctx.ProperDistanceBonus, 9);      // 적정거리 +0.3
    }

    [Fact]
    public void DummyTarget_no_bonus_out_of_range()
    {
        var ctx = new AttackContext(1000, 50);
        var tgt = new DummyTarget(element: "Water", distance: 10.0); // AR 적정구간 [25,45] 밖
        tgt.PopulateContext(ref ctx, attackerElement: "Fire", attackerWeaponType: "AR");
        Assert.Equal(0.0, ctx.SumStrongElem, 9);
        Assert.Equal(0.0, ctx.ProperDistanceBonus, 9);
    }

    // ─────────────── 데이터 전수 불변식 (roledata_clean.json 192캐릭) ───────────────

    private static Dictionary<string, CharacterStaticDto> Load()
    {
        string path;
        try { path = JsonProvider.GetSmartDatabasePath("roledata_clean.json"); }
        catch { return null; }
        if (!System.IO.File.Exists(path)) return null;
        return JsonProvider.LoadJson<Dictionary<string, CharacterStaticDto>>(path);
    }

    [Fact]
    public void All_characters_have_weaponData_with_fire_rate()
    {
        var db = Load();
        if (db == null) return; // 데이터 없으면 스킵

        Assert.True(db.Count >= 190); // 2026-07 기준 192명
        Assert.All(db.Values, c =>
        {
            Assert.NotNull(c.weaponData);
            Assert.True(c.weaponData.fireRate > 0);
            Assert.True(c.weaponData.endFireRate > 0);
            Assert.True(c.weaponData.spotFirstDelaySec > 0);   // 발사 개시 모션 (대부분 0.2s)
            Assert.True(c.weaponData.spotLastDelaySec > 0);
            Assert.True(c.weaponData.shotCount >= 1);
            Assert.NotNull(c.weaponData.accuracy);
            Assert.NotNull(c.weaponData.burst);
        });
    }

    [Fact]
    public void Machine_gun_has_ramp_and_others_do_not()
    {
        var db = Load();
        if (db == null) return;

        var mg = db.Values.Where(c => c.weapon == "Minigun").ToList();
        Assert.NotEmpty(mg);
        Assert.All(mg, c =>
        {
            // MG spin-up: 1→70 발/sec (raw 60→4200 RPM), 발당 +100/60, 사격 중단 1.0s 후 리셋.
            Assert.Equal(1.0, c.weaponData.fireRate, 9);
            Assert.Equal(70.0, c.weaponData.endFireRate, 9);
            Assert.Equal(100.0 / 60.0, c.weaponData.fireRateRampPerShot, 9);
            Assert.Equal(1.0, c.weaponData.fireRateResetTimeSec, 9);
            // 명중원 연사 수축 250→10
            Assert.Equal(250.0, c.weaponData.accuracy.startCircle, 9);
            Assert.Equal(10.0, c.weaponData.accuracy.endCircle, 9);
        });

        // ramp 는 MG 전용 — 그 외 무기는 start == end, 발당 변화 0
        Assert.All(db.Values.Where(c => c.weapon != "Minigun"), c =>
        {
            Assert.Equal(c.weaponData.fireRate, c.weaponData.endFireRate, 9);
            Assert.Equal(0.0, c.weaponData.fireRateRampPerShot, 9);
        });
    }

    [Fact]
    public void Fire_rate_units_are_shots_per_second()
    {
        var db = Load();
        if (db == null) return;

        // 단위 캘리브레이션 앵커 (발/sec): 표준 AR 12, SMG 24, SG 1.5.
        // AR 은 2.5(변형 1명) 존재 — 12 가 최빈. SMG/SG 는 전원 단일값.
        var arRates = db.Values.Where(c => c.weapon == "Assault Rifle")
                               .Select(c => c.weaponData.fireRate).ToList();
        Assert.Contains(12.0, arRates);
        Assert.All(db.Values.Where(c => c.weapon == "SMG"),
            c => Assert.Equal(24.0, c.weaponData.fireRate, 9));
        Assert.All(db.Values.Where(c => c.weapon == "Shotgun"),
            c => Assert.Equal(1.5, c.weaponData.fireRate, 9));
    }

    [Fact]
    public void Shotgun_pellet_count_is_per_character()
    {
        var db = Load();
        if (db == null) return;

        var sg = db.Values.Where(c => c.weapon == "Shotgun").ToList();
        Assert.NotEmpty(sg);
        // 전수 조사: 펠릿 5 또는 10 (per-char — 무기타입 상수로 대체 불가)
        Assert.All(sg, c => Assert.True(c.weaponData.shotCount == 5 || c.weaponData.shotCount == 10));
        Assert.Contains(sg, c => c.weaponData.shotCount == 10);
    }

    [Fact]
    public void SrRl_subtypes_are_identified_by_per_char_fields()
    {
        var db = Load();
        if (db == null) return;

        var srRl = db.Values.Where(c => c.weapon == "Sniper Rifle" || c.weapon == "Rocket Launcher").ToList();
        Assert.All(srRl, c => Assert.Contains(c.weaponData.inputType, new[] { "UP", "DOWN", "DOWN_Charge" }));

        // ① UP + maintain>0 = 복귀 없는 자체 후딜레이형 (SBS 0.23s / Raven 0.83s / A2 0.84s)
        var maintain = srRl.Where(c => c.weaponData.maintainFireStanceSec > 0).ToList();
        Assert.True(maintain.Count >= 3);
        Assert.All(maintain, c => Assert.Equal("UP", c.weaponData.inputType));
        Assert.Contains(maintain, c => System.Math.Abs(c.weaponData.maintainFireStanceSec - 0.23) < 1e-9); // SBS

        // ② DOWN_Charge = only 풀차지 (Liberalio·Neon:VE·Vesti:TU·Anis:Star·Cinderella)
        Assert.True(srRl.Count(c => c.weaponData.inputType == "DOWN_Charge") >= 3);

        // ③ DOWN = 비차지 평사 (Pascal) — 차지 플래그와 정합
        Assert.All(srRl.Where(c => c.weaponData.inputType == "DOWN"),
            c => Assert.False(c.weaponData.isChargeWeapon));
    }

    [Fact]
    public void Charge_flag_is_consistent_with_charge_timing()
    {
        var db = Load();
        if (db == null) return;

        // 차지 플래그 일관성: isChargeWeapon ⇔ chargeTimeSec>0, 차지면 fullChargeDamage>1 (SR 2.5/RL 3.5 등).
        // ⚠ "SR/RL=차지" 는 무기타입 상수 아님 — Pascal(RL 서포터)은 charge_time=0 비차지 평사(1.5발/s).
        //    per-char 편차 또 하나 (SG 펠릿 5|10, AR 12|2.5 와 동일 결론: per-char 데이터가 권위).
        Assert.All(db.Values, c =>
        {
            Assert.Equal(c.weaponData.isChargeWeapon, c.weaponData.chargeTimeSec > 0);
            if (c.weaponData.isChargeWeapon)
                Assert.True(c.weaponData.fullChargeDamage > 1.0);
            else
                Assert.Equal(1.0, c.weaponData.fullChargeDamage, 9);
        });

        // 비차지 4종은 전원 비차지 + 차지 SR/RL 이 다수 존재(모델 소비 대상 확인).
        Assert.All(db.Values.Where(c => c.weapon == "Assault Rifle" || c.weapon == "SMG"
                                     || c.weapon == "Minigun" || c.weapon == "Shotgun"),
            c => Assert.False(c.weaponData.isChargeWeapon));
        Assert.True(db.Values.Count(c => c.weaponData.isChargeWeapon) >= 70); // SR 36 + RL 41 - 예외
    }
}
