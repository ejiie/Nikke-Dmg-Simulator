using System;
using Nikke.Simulator.Core.Data.Dto;

namespace Nikke.Simulator.Core.Stats
{
    /// <summary>
    /// per-캐릭터 무기 프로파일 — <see cref="WeaponDto"/>(blabla_roledata `shot`)를 엔진이 쓰는
    /// 타입드 값으로 감싼다. null-safe(구 merged DB 에 weapon 블록 없으면 안전한 기본값).
    ///
    /// 역할 경계:
    ///   - 이 클래스          : 발사속도/탄창/차지/멀티펠릿/명중원 raw 보유 + 발사 타이밍 helper.
    ///   - <see cref="WeaponStatTable"/> : (구) 무기타입 하드코딩 상수 — fire-rate 는 이제 데이터(이 클래스)가 권위.
    ///   - Combat.AccuracyModel  : accuracy 원 → 코어힛/명중 확률.
    ///   - Combat.ProperDistanceTable : weaponType + dist → 적정거리 활성 여부.
    ///
    /// 단위(ETL `roledata_cleaner._weapon` 정규화 완료): FireRate=발/sec, *Sec=초, *Rate=분수,
    /// Accuracy*=raw 스프레드 반지름, Burst*EnergyPerShot=raw 게이지 단위.
    /// </summary>
    public sealed class WeaponProfile
    {
        // ── 식별 ──
        public string WeaponTypeCode { get; }   // SG/SMG/AR/MG/SR/RL (단축코드; null-safe="")
        public bool IsChargeWeapon { get; }

        // ── SR/RL 부류 판별 (per-char; ENGINE_GUIDE §5, 2026-07-08 확정) ──
        public string InputType { get; }             // "UP"=릴리즈 발사 / "DOWN_Charge"=only 풀차지 / "DOWN"=평사
        public string FireType { get; }              // "Instant"/"Projectile*" (발사 이벤트 타이밍)
        public double MaintainFireStanceSec { get; } // >0 = 발사 후 복귀 없이 자세 유지 (값=자체 후딜레이)
        public double UpTypeFireTiming { get; }      // 투사체 발사 이벤트 시점 비율 (분수)
        public int SpotProjectileSpeed { get; }

        /// <summary>only 풀차지 무기 (릴리즈/톡톡이 발사 불가 — Liberalio·Neon:VE 등).</summary>
        public bool IsOnlyFullCharge => InputType == "DOWN_Charge";

        // ── 발사속도 (발/sec). MG 는 spin-up. ──
        // ⚠ 이 값들은 **nominal(데이터 그대로)**. 실현 발사속도는 60fps 프레임 캡 적용 → FireRateAtShot 참조.
        public double FireRate { get; }            // 시작 발사속도 (nominal)
        public double EndFireRate { get; }         // 가속 후 최대 발사속도 (nominal; MG 70 → 실현 60)
        public double FireRateRampPerShot { get; } // 발당 발사속도 증가량
        // 비사격(엄폐/재장전) 동안 ramp 가 **점진 감쇠**하는 시정수 — 즉시 리셋 아님 (einkk 검증 2026-07-08):
        // 비사격 프레임마다 (End−Start)/reset_time 만큼 하강 → reset_time 프레임에 걸쳐 full ramp 소실.
        public double FireRateResetTimeSec { get; }

        /// <summary>
        /// 게임 엔진 고정 프레임레이트(fps). 단일 무기는 **프레임당 최대 1발**이라 실현 발사속도 상한 = 이 값(발/sec).
        /// MG nominal end 70/sec(4200/60)도 실현 60/sec 로 캡(accumulator 가 프레임당 1발만 발사).
        /// ⚠ 정확 프레임레이트/캡 거동은 in-game 확인 권장(60 가정).
        /// </summary>
        public const double EngineFrameRate = 60.0;

        // ── 상태 전이 모션 딜레이 (초) — semantics 확정 (einkk+사용자 실측 2026-07-08, ENGINE_GUIDE §5) ──
        // SpotFirst(0.2s 지배적): 엄폐→조준 전이 후 첫 발사/차지 시작 전 대기. 비사격 동안 재-arm.
        //   차지무기는 딜레이 종료 프레임에 charge 1프레임 선시작.
        // SpotLast(0.2s): 조준→엄폐 전이 — **전 무기** (einkk 은 UP형만 모델하나 실게임은 전 무기).
        //   SR/RL(UP, maintain=0)은 매 발사 후 강제 복귀 → 사이클 ≈ Last+First+FullCharge (84f ≈ 1.4s).
        //   SR/RL 부류는 무기타입이 아니라 per-char 필드: input_type(UP/DOWN_Charge=only풀차지/DOWN) +
        //   maintain_fire_stance(>0 = 복귀 없이 자세 유지, 값=자체 후딜레이: SBS 0.23/Raven 0.83/A2 0.84s).
        // (구 실측 0.03s 설은 spot 계열과 무관 — 폐기.)
        public double SpotFirstDelaySec { get; }
        public double SpotLastDelaySec { get; }

        // ── 탄창/재장전 ──
        public int MaxAmmo { get; }
        public double ReloadTimeSec { get; }
        public double ReloadBulletRate { get; }    // 1.0=전탄, 0.33=부분장전
        public int ReloadStartAmmo { get; }

        // ── 차지 (SR/RL) ──
        public double ChargeTimeSec { get; }
        public double FullChargeDamage { get; }    // SR 2.5 / RL 3.5 / 비차지 1.0

        // ── 멀티펠릿/투사체 ──
        public int ShotCount { get; }              // SG 펠릿 5~10 (한 트리거당 히트 인스턴스 수)
        public int MuzzleCount { get; }
        public int Penetration { get; }
        public int SpotRadius { get; }             // RL 스플래시
        public int SpotExplosionRange { get; }
        public double CoreDamageRate { get; }      // 2.0 (coreHitBonus = 이값 - 1)

        // ── 명중원 (manual aim) — AccuracyModel 이 소비 ──
        public double StartAccuracyCircle { get; }
        public double EndAccuracyCircle { get; }
        public double AccuracyChangePerShot { get; }
        public double AccuracyChangeSpeed { get; }

        // ── 버스트 게이지 ──
        public double BurstEnergyPerShot { get; }
        public double TargetBurstEnergyPerShot { get; }
        public double FullChargeBurstEnergy { get; }
        public double BurstDurationSec { get; }    // 풀버스트 창 (보통 10s)
        public string UseBurstSkill { get; }       // Step1/2/3/AllStep
        public string ChangeBurstStep { get; }

        /// <summary>weapon 블록이 없는(구) 데이터용 안전 기본 프로파일.</summary>
        public static readonly WeaponProfile Empty = new WeaponProfile(null);

        public WeaponProfile(WeaponDto dto)
        {
            if (dto == null)
            {
                WeaponTypeCode = "";
                InputType = "";
                FireType = "";
                FullChargeDamage = 1.0;
                FireRate = 0.0;
                EndFireRate = 0.0;
                UseBurstSkill = "";
                ChangeBurstStep = "";
                return;
            }

            WeaponTypeCode = dto.weaponType ?? "";
            IsChargeWeapon = dto.isChargeWeapon;

            InputType = dto.inputType ?? "";
            FireType = dto.fireType ?? "";
            MaintainFireStanceSec = dto.maintainFireStanceSec;
            UpTypeFireTiming = dto.upTypeFireTiming;
            SpotProjectileSpeed = dto.spotProjectileSpeed;

            FireRate = dto.fireRate;
            EndFireRate = dto.endFireRate > 0 ? dto.endFireRate : dto.fireRate;
            FireRateRampPerShot = dto.fireRateRampPerShot;
            FireRateResetTimeSec = dto.fireRateResetTimeSec;

            SpotFirstDelaySec = dto.spotFirstDelaySec;
            SpotLastDelaySec = dto.spotLastDelaySec;

            MaxAmmo = dto.maxAmmo;
            ReloadTimeSec = dto.reloadTimeSec;
            ReloadBulletRate = dto.reloadBulletRate;
            ReloadStartAmmo = dto.reloadStartAmmo;

            ChargeTimeSec = dto.chargeTimeSec;
            FullChargeDamage = dto.fullChargeDamage > 0 ? dto.fullChargeDamage : 1.0;

            ShotCount = dto.shotCount > 0 ? dto.shotCount : 1;
            MuzzleCount = dto.muzzleCount > 0 ? dto.muzzleCount : 1;
            Penetration = dto.penetration;
            SpotRadius = dto.spotRadius;
            SpotExplosionRange = dto.spotExplosionRange;
            CoreDamageRate = dto.coreDamageRate;

            var acc = dto.accuracy;
            if (acc != null)
            {
                StartAccuracyCircle = acc.startCircle;
                EndAccuracyCircle = acc.endCircle;
                AccuracyChangePerShot = acc.changePerShot;
                AccuracyChangeSpeed = acc.changeSpeed;
            }

            var b = dto.burst;
            if (b != null)
            {
                BurstEnergyPerShot = b.energyPerShot;
                TargetBurstEnergyPerShot = b.targetEnergyPerShot;
                FullChargeBurstEnergy = b.fullChargeEnergy;
                BurstDurationSec = b.durationSec;
                UseBurstSkill = b.useBurstSkill ?? "";
                ChangeBurstStep = b.changeBurstStep ?? "";
            }
            else
            {
                UseBurstSkill = "";
                ChangeBurstStep = "";
            }
        }

        /// <summary>
        /// 연사 중 N번째 발사 시점의 **실현(realized) 발사속도**(발/sec). MG spin-up 모델:
        /// <c>min(EndFireRate, FireRate + ramp×shots)</c> 위에 **60fps 프레임 캡**(<see cref="EngineFrameRate"/>).
        /// ramp=0(대부분 무기)이면 상수.  MG: nominal 1→70 이지만 실현 1→**60**(프레임당 1발 상한).
        /// </summary>
        /// <param name="shotsFiredInRamp">현재 연사 streak 에서 이미 발사한 탄 수(0-기준).</param>
        public double FireRateAtShot(int shotsFiredInRamp)
        {
            if (shotsFiredInRamp < 0) shotsFiredInRamp = 0;
            double rate;
            if (FireRateRampPerShot <= 0.0 || EndFireRate <= FireRate)
                rate = FireRate;
            else
            {
                double ramped = FireRate + FireRateRampPerShot * shotsFiredInRamp;
                rate = ramped < EndFireRate ? ramped : EndFireRate;
            }
            // 60fps 프레임 캡 — 단일 무기 프레임당 1발 상한 (MG nominal 70 → 실현 60).
            return rate < EngineFrameRate ? rate : EngineFrameRate;
        }

        /// <summary>N번째 발사 간격(초) = 1 / <see cref="FireRateAtShot"/>. 발사속도 0 이면 +∞.</summary>
        public double FireIntervalSec(int shotsFiredInRamp)
        {
            double r = FireRateAtShot(shotsFiredInRamp);
            return r > 0.0 ? 1.0 / r : double.PositiveInfinity;
        }
    }
}
