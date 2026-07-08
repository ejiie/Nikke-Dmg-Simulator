using System;

namespace Nikke.Simulator.Core.Stats
{
    /// <summary>
    /// 무기 타입별 정적 속성(기본 발사 속도 · 차지 무기 타이밍) 룩업 테이블.
    ///
    /// 출처: ARCHITECTURE.md §5.1 / §5.1a (사용자 확정 2026-04-23).
    /// 로테이션 시뮬 페이즈 (갭 페이즈 3) 진입 시 `SimulationLoop` 가 이 테이블을 소비.
    ///
    /// ※ `trait_weapon_transformed` 로 변경되는 fire_rate / charge_time 등 granular override 는
    ///   `Nikke.cs` 측 일시적 플래그로 처리 — 이 테이블은 원본 무기 기준 값만 반환 (§5.4).
    /// </summary>
    /// <remarks>
    /// ⚠️ <b>레거시 (2026-07-02).</b> 발사속도/차지 타이밍은 이제 per-캐릭 실데이터
    /// <see cref="WeaponProfile"/>(roledata `weaponData` → <c>Nikke.Weapon</c>)가 권위:
    /// <c>FireRate</c>/<c>FireRateAtShot</c>(MG spin-up)/<c>ChargeTimeSec</c>. 신규 코드는 그쪽을 쓸 것.
    /// 이 테이블의 하드코딩은 실데이터와 불일치(MG 60/s 고정=ramp 누락, SG 5/3 vs 1.5/s)하며,
    /// 무기 문자열 상수(<c>"Machine Gun"</c>/<c>"Submachine Gun"</c>)도 실데이터 롱폼
    /// (<c>"Minigun"</c>/<c>"SMG"</c>)과 <b>불일치</b> → 실데이터로 <see cref="GetBaseFireRate"/> 호출 시
    /// <see cref="NotSupportedException"/> 위험. 보존만 하고 fire-rate 경로엔 사용 금지.
    /// </remarks>
    public static class WeaponStatTable
    {
        // ──────────────────────────────────────────────────────────
        //  Canonical WeaponType 문자열 상수 (JSON staticInfo.weapon 값)
        // ──────────────────────────────────────────────────────────
        public const string AssaultRifle   = "Assault Rifle";
        public const string MachineGun     = "Machine Gun";
        public const string SubmachineGun  = "Submachine Gun";
        public const string Shotgun        = "Shotgun";
        public const string SniperRifle    = "Sniper Rifle";
        public const string RocketLauncher = "Rocket Launcher";

        /// <summary>
        /// 고정 발사 속도 (발/sec). AR / MG / SMG / SG 전용.
        /// SR / RL 은 차지 무기이므로 <see cref="GetChargeTiming"/> 참조 — 호출 시 <see cref="NotSupportedException"/>.
        /// </summary>
        /// <exception cref="NotSupportedException">차지 무기 (SR / RL) 또는 미등록 weapon 타입.</exception>
        public static double GetBaseFireRate(string weaponType)
        {
            return weaponType switch
            {
                AssaultRifle   => 12.0,
                MachineGun     => 60.0,
                SubmachineGun  => 24.0,
                Shotgun        => 5.0 / 3.0, // ≈ 1.667 발/sec
                SniperRifle    => throw new NotSupportedException(
                    $"'{weaponType}' 는 차지 무기입니다. GetChargeTiming(...) 를 사용하세요."),
                RocketLauncher => throw new NotSupportedException(
                    $"'{weaponType}' 는 차지 무기입니다. GetChargeTiming(...) 를 사용하세요."),
                _ => throw new NotSupportedException(
                    $"알 수 없는 WeaponType '{weaponType}'. ARCHITECTURE.md §5.1 참조.")
            };
        }

        /// <summary>
        /// 차지 무기 (SR / RL) 타이밍 파라미터 반환.
        /// AR / MG / SMG / SG 호출 시 <see cref="NotSupportedException"/>.
        /// </summary>
        /// <exception cref="NotSupportedException">비-차지 무기 또는 미등록 weapon 타입.</exception>
        public static ChargeTiming GetChargeTiming(string weaponType)
        {
            return weaponType switch
            {
                SniperRifle    => ChargeTiming.Default,
                RocketLauncher => ChargeTiming.Default,
                AssaultRifle or MachineGun or SubmachineGun or Shotgun
                    => throw new NotSupportedException(
                        $"'{weaponType}' 는 비-차지 무기입니다. GetBaseFireRate(...) 를 사용하세요."),
                _ => throw new NotSupportedException(
                    $"알 수 없는 WeaponType '{weaponType}'. ARCHITECTURE.md §5.1a 참조.")
            };
        }

        /// <summary>차지 무기 여부 (SR / RL).</summary>
        public static bool IsChargeWeapon(string weaponType)
            => weaponType == SniperRifle || weaponType == RocketLauncher;
    }

    /// <summary>
    /// SR / RL 차지 모드 타이밍 (초 단위).
    /// Tap (no-charge) 모드는 풀차지 경로와 별개로 측정됨 — 실측값은 사용자 제공 (2026-04-23).
    /// 현재 값은 전 차지 무기 공통 추정치; 캐릭터별 편차가 확인되면 오버로드 형태로 분기 예정.
    /// </summary>
    public readonly struct ChargeTiming
    {
        /// <summary>발사 직전 모션 딜레이 (초). 약 30ms.</summary>
        public double MotionDelaySec { get; }

        /// <summary>풀차지 완료까지 소요 시간 (초). 기본 1.0, 캐릭터별 오버라이드 가능.</summary>
        public double FullChargeSec { get; }

        /// <summary>톡톡이(no-charge) 모드에서의 발사 간격 (초). 0.21~0.22.</summary>
        public double TapIntervalSec { get; }

        public ChargeTiming(double motionDelaySec, double fullChargeSec, double tapIntervalSec)
        {
            MotionDelaySec = motionDelaySec;
            FullChargeSec = fullChargeSec;
            TapIntervalSec = tapIntervalSec;
        }

        /// <summary>
        /// ARCHITECTURE.md §5.1a 기본치.
        ///  - motion: 0.03s (~30ms)
        ///  - full charge: 1.0s
        ///  - tap interval: 0.215s (0.21~0.22 중앙값)
        /// </summary>
        public static readonly ChargeTiming Default = new(
            motionDelaySec: 0.03,
            fullChargeSec: 1.0,
            tapIntervalSec: 0.215);
    }
}
