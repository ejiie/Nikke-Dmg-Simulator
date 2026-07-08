using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine;

namespace Nikke.Simulator.Tests;

/// <summary>
/// K3 FiringModel — 발사 타임라인 검증 (ENGINE_GUIDE §5 확정 스펙, 2026-07-08).
/// 프레임 기대값 출처 = nikke-einkk 발사 루프 + 사용자 실측 (VERIFICATION_LOG 2026-07-08 3차).
/// ※ 타이밍은 결정론이 정상 (RNG 는 수동 re-click/차지오차 구간 샘플에만 관여) — 하한 고정 stub 사용.
///   확률 효과(크리/코어힛)는 이 클래스 스코프 밖 (AccuracyModel/CritSampler 는 시스템 RNG 수렴 검증).
/// </summary>
public class FiringModelTests
{
    /// <summary>구간 하한 고정 stub — re-click = round(0.02×60) = 1프레임.</summary>
    private sealed class MinRandom : IRandomSource
    {
        public double NextDouble() => 0.0;
    }

    private static readonly IRandomSource Rng = new MinRandom();

    // ── 무기 프로파일 픽스처 (roledata 실값 기반) ──

    private static WeaponProfile Ar() => new(new WeaponDto
    {
        weaponType = "AR", inputType = "DOWN", fireType = "Instant",
        fireRate = 12, endFireRate = 12, spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
        maxAmmo = 60, reloadTimeSec = 1.0, reloadBulletRate = 1.0, shotCount = 1, muzzleCount = 1,
    });

    private static WeaponProfile Mg() => new(new WeaponDto
    {
        weaponType = "MG", inputType = "DOWN", fireType = "Instant",
        fireRate = 1, endFireRate = 70, fireRateRampPerShot = 100.0 / 60.0, fireRateResetTimeSec = 1.0,
        spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
        maxAmmo = 300, reloadTimeSec = 2.5, reloadBulletRate = 1.0, shotCount = 1, muzzleCount = 1,
        accuracy = new WeaponAccuracyDto { startCircle = 250, endCircle = 10, changePerShot = 7, changeSpeed = 150 },
    });

    private static WeaponProfile SrUp() => new(new WeaponDto // Maxwell 형 (UP·maintain=0·charge 1s)
    {
        weaponType = "SR", inputType = "UP", fireType = "Instant", isChargeWeapon = true,
        chargeTimeSec = 1.0, fullChargeDamage = 2.5,
        fireRate = 1, endFireRate = 1, spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
        maxAmmo = 6, reloadTimeSec = 2.0, reloadBulletRate = 1.0, shotCount = 1, muzzleCount = 1,
    });

    private static WeaponProfile RavenLike() => new(new WeaponDto // UP + maintain(0.83s)
    {
        weaponType = "RL", inputType = "UP", fireType = "ProjectileDirect", isChargeWeapon = true,
        chargeTimeSec = 1.0, fullChargeDamage = 2.5, maintainFireStanceSec = 0.83, upTypeFireTiming = 0.32,
        fireRate = 1, endFireRate = 1, spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
        maxAmmo = 6, reloadTimeSec = 2.0, reloadBulletRate = 1.0, shotCount = 1, muzzleCount = 1,
    });

    private static WeaponProfile DownCharge() => new(new WeaponDto // Liberalio 형 (only 풀차지)
    {
        weaponType = "RL", inputType = "DOWN_Charge", fireType = "Instant", isChargeWeapon = true,
        chargeTimeSec = 1.0, fullChargeDamage = 2.5,
        fireRate = 1, endFireRate = 1, spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
        maxAmmo = 6, reloadTimeSec = 2.0, reloadBulletRate = 1.0, shotCount = 1, muzzleCount = 1,
    });

    private static WeaponProfile Sg() => new(new WeaponDto
    {
        weaponType = "SG", inputType = "DOWN", fireType = "Instant",
        fireRate = 1.5, endFireRate = 1.5, spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
        maxAmmo = 9, reloadTimeSec = 1.5, reloadBulletRate = 1.0, shotCount = 10, muzzleCount = 1,
    });

    private static List<int> FireFrames(FiringModel m, int frames, List<FiringFrameResult> log = null)
    {
        var fired = new List<int>();
        for (int f = 1; f <= frames; f++)
        {
            var r = m.AdvanceFrame();
            log?.Add(r);
            if (r.Fired) fired.Add(f);
        }
        return fired;
    }

    // ───────────────────────── 비차지: accumulator ─────────────────────────

    [Fact]
    public void Ar_fires_12_per_sec_after_spot_first()
    {
        var m = new FiringModel(Ar(), 60, new FiringControl(), Rng);
        var fired = FireFrames(m, 132); // spotFirst 12f + 120f(2초)
        Assert.Equal(13, fired[0]);                       // 0.2s 후 첫 발
        Assert.Equal(24, fired.Count);                    // 2초 × 12발/s
        Assert.All(fired.Zip(fired.Skip(1)), p => Assert.Equal(5, p.Second - p.First)); // 60fps/12
    }

    [Fact]
    public void Mg_spinup_ramps_to_frame_cap_and_nominal_70()
    {
        var m = new FiringModel(Mg(), 300, new FiringControl(), Rng);
        var fired = FireFrames(m, 300);
        // nominal 은 70/s 까지 ramp 되지만 실현은 구조적 1발/프레임 = 60/s
        Assert.Equal(70.0, m.CurrentRatePerSec, 9);
        var last60 = fired.Where(f => f > 240).ToList();
        Assert.Equal(60, last60.Count);                   // 말기 60프레임 = 매 프레임 발사
        Assert.True(fired.Count(f => f <= 72) < 10);      // 초반 1초는 스핀업으로 희소
    }

    [Fact]
    public void Mg_ramp_decays_gradually_during_reload_not_instantly()
    {
        var m = new FiringModel(Mg(), 45, new FiringControl(), Rng); // 45발 후 강제 재장전
        // 탄창 소진(45발 — 스핀업 캡 41발 도달 후)까지 진행 → 재장전 개시 프레임 포착
        int frame = 0;
        while (m.CurrentAmmo > 0) { m.AdvanceFrame(); frame++; Assert.True(frame < 1000); }
        double rampedRate = m.CurrentRatePerSec;
        Assert.Equal(70.0, rampedRate, 9);                // ramp 캡(nominal end) 도달

        // 재장전(비사격) 50프레임 = 감쇠 진행 중 (즉시 리셋 아님)
        for (int i = 0; i < 50; i++) m.AdvanceFrame();
        Assert.True(m.CurrentRatePerSec < rampedRate);
        Assert.True(m.CurrentRatePerSec > 1.0);

        // 감쇠 시정수 100프레임 경과 후 = start(1발/s) 복귀
        for (int i = 0; i < 60; i++) m.AdvanceFrame();
        Assert.Equal(1.0, m.CurrentRatePerSec, 9);
    }

    [Fact]
    public void Sg_fires_pellets_per_trigger_and_consumes_one_ammo()
    {
        var m = new FiringModel(Sg(), 9, new FiringControl(), Rng);
        var log = new List<FiringFrameResult>();
        FireFrames(m, 100, log);
        var shots = log.Where(r => r.Fired).ToList();
        Assert.NotEmpty(shots);
        Assert.All(shots, s => Assert.Equal(10, s.PelletsPerShot)); // 펠릿 10/클릭
        Assert.Equal(9 - shots.Count, m.CurrentAmmo);               // 탄약은 클릭당 1
    }

    [Fact]
    public void Mg_accuracy_circle_shrinks_to_end_with_streak()
    {
        var m = new FiringModel(Mg(), 300, new FiringControl(), Rng);
        var log = new List<FiringFrameResult>();
        FireFrames(m, 400, log);
        Assert.True(log.Count(r => r.Fired) > 40);
        Assert.Equal(10.0, m.AccuracyCircle, 9);          // 250 → 10 (발당 −7)
    }

    // ───────────────────────── SR/RL 부류별 사이클 ─────────────────────────

    [Fact]
    public void SrUp_auto_cycle_is_spotLast_spotFirst_charge()
    {
        var m = new FiringModel(SrUp(), 6, new FiringControl { Mode = ControlMode.Auto }, Rng);
        var fired = FireFrames(m, 400);
        Assert.Equal(71, fired[0]);                       // spotFirst 12 + charge 59 (전이 말 1f 선차지)
        Assert.All(fired.Zip(fired.Skip(1)),
            p => Assert.Equal(83, p.Second - p.First));   // last 12 + first 12 + charge 59 ≈ 1.4s ✓
        var log = new List<FiringFrameResult>();
        FireFrames(m, 1, log);
        Assert.All(log.Where(r => r.Fired), r => Assert.True(r.IsFullCharge));
    }

    [Fact]
    public void SrUp_manual_fullcharge_keeps_aim_and_pays_only_reclick()
    {
        var ctl = new FiringControl { Mode = ControlMode.Manual, Style = FireStyle.FullCharge };
        var m = new FiringModel(SrUp(), 6, ctl, Rng);
        var fired = FireFrames(m, 400);
        Assert.Equal(71, fired[0]);
        // 사용자 실측 모델: 발당 = reclick(1f) + charge(60f) = 61f ≈ 1.02s (spotFirst 재지불 없음)
        Assert.All(fired.Zip(fired.Skip(1)), p => Assert.Equal(61, p.Second - p.First));
    }

    [Fact]
    public void SrUp_manual_tap_cycle_matches_measured_tap_interval()
    {
        var ctl = new FiringControl { Mode = ControlMode.Manual, Style = FireStyle.Tap };
        var m = new FiringModel(SrUp(), 6, ctl, Rng);
        var log = new List<FiringFrameResult>();
        var fired = FireFrames(m, 100, log);
        Assert.Equal(13, fired[0]);                       // spotFirst 12f 직후 즉발
        // 톡톡이 사이클 = reclick(1f) + spotFirst(12f) + 발사(1f) = 14f ≈ 0.233s (실측 0.22~0.26 ✓)
        Assert.All(fired.Zip(fired.Skip(1)), p => Assert.Equal(14, p.Second - p.First));
        Assert.All(log.Where(r => r.Fired), r => Assert.False(r.IsFullCharge)); // 비풀차지
    }

    [Fact]
    public void Maintain_weapon_stays_in_stance_with_own_recovery_delay()
    {
        var m = new FiringModel(RavenLike(), 6, new FiringControl { Mode = ControlMode.Auto }, Rng);
        var fired = FireFrames(m, 600);
        Assert.Equal(71, fired[0]);
        // 복귀 없음: 사이클 = maintain(0.2+0.83 → 62f) + charge 59f = 121f (Raven ≈ 2.0s)
        Assert.All(fired.Zip(fired.Skip(1)), p => Assert.Equal(121, p.Second - p.First));
    }

    [Fact]
    public void DownCharge_fires_full_charge_only_at_rate_gate()
    {
        var m = new FiringModel(DownCharge(), 6, new FiringControl { Mode = ControlMode.Auto }, Rng);
        var log = new List<FiringFrameResult>();
        var fired = FireFrames(m, 400, log);
        Assert.Equal(71, fired[0]);
        Assert.All(fired.Zip(fired.Skip(1)),
            p => Assert.Equal(60, p.Second - p.First));   // rate 1/s gate (복귀/모션 없음)
        Assert.All(log.Where(r => r.Fired), r => Assert.True(r.IsFullCharge)); // only 풀차지
    }

    [Fact]
    public void DownCharge_rejects_tap_style()
    {
        var ctl = new FiringControl { Mode = ControlMode.Manual, Style = FireStyle.Tap };
        Assert.Throws<System.ArgumentException>(() => new FiringModel(DownCharge(), 6, ctl, Rng));
    }

    // ───────────────────────── 재장전 R1/R2 ─────────────────────────

    [Fact]
    public void Auto_empty_mag_reload_includes_cover_transitions()
    {
        var m = new FiringModel(Ar(), 5, new FiringControl { Mode = ControlMode.Auto }, Rng); // 5발 탄창
        var fired = FireFrames(m, 300);
        // 5발: f13,18,23,28,33. 탄0 → f34 재장전 개시(=첫 진행 프레임), 실효 = (1.0 + 0.2[spot_last 가산])×60 = 72f
        // → f105 충전 완료, spotFirst 12f 재지불 → 재개 첫 발 = f118
        Assert.Equal(new[] { 13, 18, 23, 28, 33 }, fired.Take(5));
        Assert.Equal(118, fired[5]);
    }

    [Fact]
    public void Manual_empty_mag_reload_skips_transitions()
    {
        var m = new FiringModel(Ar(), 5, new FiringControl { Mode = ControlMode.Manual }, Rng);
        var fired = FireFrames(m, 300);
        // 수동: 전이 없이 실효 재장전만 = 60f. f34 개시(=첫 진행) → f93 완료 → f94 재개 (spotFirst 미지불)
        Assert.Equal(33, fired[4]);
        Assert.Equal(94, fired[5]);
    }

    [Fact]
    public void Full_reload_buff_gives_instant_refill_in_reclick_gap()
    {
        // 재장전 속도 ≥100% = 실효 1프레임 (감산형 공식 하한) — "re-click 이내 장전" (사용자 3.5년 확정)
        var ctl = new FiringControl { Mode = ControlMode.Manual, ReloadSpeedBuff = 1.0 };
        var m = new FiringModel(Ar(), 5, ctl, Rng);
        var fired = FireFrames(m, 300);
        // 탄0 → 개시 프레임에 즉시 충전(실효 1f ≤ 갭) → 발사 주기(5f)가 한 번도 끊기지 않음 = 무한 탄창 창발
        Assert.All(fired.Zip(fired.Skip(1)), p => Assert.Equal(5, p.Second - p.First));
        Assert.Equal((300 - 13) / 5 + 1, fired.Count);    // 12발/s 무중단
    }

    [Fact]
    public void Charge_speed_buff_shortens_full_charge_subtractively()
    {
        // Adjutant 류 차지속도 버프: 1.0 − round(1.0×0.5, 2) = 0.5s = 30f
        var m = new FiringModel(SrUp(), 6, new FiringControl { Mode = ControlMode.Auto }, Rng,
                                chargeSpeedBuffs: new[] { 0.5 });
        var fired = FireFrames(m, 200);
        Assert.Equal(41, fired[0]);                       // spotFirst 12 + charge 29 (선차지 1f)
        Assert.All(fired.Zip(fired.Skip(1)),
            p => Assert.Equal(53, p.Second - p.First));   // last 12 + first 12 + charge 29
    }

    [Fact]
    public void Timing_reduction_rounds_each_term_to_2_decimals()
    {
        // 감쇠식 = base − Σᵢ round(base×buffᵢ, 2) — **항별** 사사오입 (사용자 확정, in-game).
        // 항별: 1.0 − (round(0.145,2)+round(0.145,2)) = 1.0 − 0.30 = 0.70  (Σ 후 곱셈이면 0.71 — 다름!)
        Assert.Equal(0.70, FiringModel.ApplyTimingReduction(1.0, new[] { 0.145, 0.145 }), 12);
        // 사사오입(AwayFromZero) 확인: banker's 라면 round(0.145,2)=0.14 → 0.72 가 됐을 것
        Assert.Equal(0.85, FiringModel.ApplyTimingReduction(1.0, new[] { 0.145 }), 12);
        // 하한 0 (과잉 버프)
        Assert.Equal(0.0, FiringModel.ApplyTimingReduction(1.0, new[] { 0.7, 0.7 }), 12);

        // 프레임 반영: charge 1.0s + [0.145, 0.145] → 0.70s = 42f (Σ곱셈식이면 0.71s → 43f)
        var m = new FiringModel(SrUp(), 6, new FiringControl { Mode = ControlMode.Auto }, Rng,
                                chargeSpeedBuffs: new[] { 0.145, 0.145 });
        var fired = FireFrames(m, 100);
        Assert.Equal(53, fired[0]);                       // spotFirst 12 + charge 41 (선차지 1f)
    }

    [Fact]
    public void Character_reload_buff_stacks_with_control_policy_buff()
    {
        // 캐릭 고유 항(큐브 0.5) + 정책 항(0.5): 1.0 − (0.5+0.5) = 0초 → 하한 1f = 즉시 장전
        var ctl = new FiringControl { Mode = ControlMode.Manual, ReloadSpeedBuff = 0.5 };
        var m = new FiringModel(Ar(), 5, ctl, Rng, reloadSpeedBuffs: new[] { 0.5 });
        var fired = FireFrames(m, 300);
        Assert.All(fired.Zip(fired.Skip(1)), p => Assert.Equal(5, p.Second - p.First)); // 무중단
    }

    [Fact]
    public void Reload_reduction_also_rounds_per_term()
    {
        // AR reload 1.0s + 항 [0.145, 0.145] (수동, 전이 없음): 실효 0.70s = 42f
        // 5발: f13..33 → f34 재장전 개시(=첫 진행) → f75 완료 → f76 재개 (Σ곱셈식이면 43f → f77)
        var ctl = new FiringControl { Mode = ControlMode.Manual };
        var m = new FiringModel(Ar(), 5, ctl, Rng, reloadSpeedBuffs: new[] { 0.145, 0.145 });
        var fired = FireFrames(m, 300);
        Assert.Equal(33, fired[4]);
        Assert.Equal(76, fired[5]);
    }

    [Fact]
    public void SrUp_with_full_reload_buff_never_depletes_ammo()
    {
        // UP형 + ≥100%: 발사 후 spot_last 창(비사격)에서 즉시 충전 → 장탄 무소모 (자동/수동 동일 — 사용자 확정)
        var ctl = new FiringControl { Mode = ControlMode.Auto, ReloadSpeedBuff = 1.0 };
        var m = new FiringModel(SrUp(), 6, ctl, Rng);
        var log = new List<FiringFrameResult>();
        var fired = FireFrames(m, 600, log);
        Assert.True(fired.Count >= 6);                    // 탄창(6) 이상 발사했지만
        Assert.Equal(6, m.CurrentAmmo);                   // 매 사이클 충전 → 풀탄 유지
        Assert.DoesNotContain(log, r => r.IsReloading && r.CurrentAmmo == 0); // 강제 재장전 없음
    }
}
