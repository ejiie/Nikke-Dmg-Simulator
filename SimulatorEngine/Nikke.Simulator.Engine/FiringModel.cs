using System;
using Nikke.Simulator.Core.Stats;

namespace Nikke.Simulator.Engine
{
    /// <summary>컨트롤 모드 — 5인 중 1인 수동 (IRotationController 와 별개 축, ENGINE_GUIDE §5).</summary>
    public enum ControlMode
    {
        /// <summary>자동 AI: 풀차지 항상, UP형은 발사 후 강제 엄폐 복귀, 탄0 자동 재장전.</summary>
        Auto,
        /// <summary>수동: 조준 유지(발당 spotFirst 미지불), re-click 갭, 갭에서 재장전 진행(R1).</summary>
        Manual,
    }

    /// <summary>수동 발사 스타일 (차지 무기 전용 분기; 비차지는 무관).</summary>
    public enum FireStyle
    {
        /// <summary>풀차지 유지: [charge(1+ε) + reclick]×장탄.</summary>
        FullCharge,
        /// <summary>톡톡이(UP형만): [spotFirst + reclick] 반복, 비풀차지 발사. IsOnlyFullCharge 무기는 불가.</summary>
        Tap,
    }

    /// <summary>
    /// FiringModel 설정. 수동 파라미터 = 사용자 실측 확정(2026-07-08): re-click [0.02, 0.028]s.
    /// ChargeErrorMaxSec = 수동 풀차징 인간 오차 상한 (0 = perfect 프로파일, 결정론 모드).
    /// ReloadSpeedBuff = Σ재장전 속도 버프 (분수; 감산형 reload×(1−Σ), ≥1.0 → 실효 1프레임 = 즉시 장전 창발).
    /// </summary>
    public sealed class FiringControl
    {
        public ControlMode Mode { get; init; } = ControlMode.Auto;
        public FireStyle Style { get; init; } = FireStyle.FullCharge;
        public double ReclickMinSec { get; init; } = 0.02;
        public double ReclickMaxSec { get; init; } = 0.028;
        public double ChargeErrorMaxSec { get; init; } = 0.0;
        public double ReloadSpeedBuff { get; init; } = 0.0;
    }

    /// <summary>프레임 1개 진행 결과. Fired=이 프레임 발사 여부(구조적 최대 1회, 펠릿은 PelletsPerShot).</summary>
    public readonly struct FiringFrameResult
    {
        public bool Fired { get; init; }
        public bool IsFullCharge { get; init; }
        public int PelletsPerShot { get; init; }
        /// <summary>발사 시점 명중원 반지름 (AccuracyModel.RollCoreHit 입력).</summary>
        public double AccuracyCircle { get; init; }
        public int CurrentAmmo { get; init; }
        public bool IsReloading { get; init; }
    }

    /// <summary>
    /// K3 — per-캐릭 발사 상태기계 (60fps 프레임 스텝). 참조 = nikke-einkk `nikke.dart`
    /// + 사용자 실측 확정 스펙 (ENGINE_GUIDE §5, VERIFICATION_LOG 2026-07-08).
    ///
    /// 핵심 규칙:
    ///  - RPM accumulator: 매 프레임 `countdown −= rate(RPM)`, 발사 시 `+= 3600` — 구조적 1발/프레임.
    ///  - MG ramp: 발사마다 +perShot clamp[start,end]; 비사격 프레임마다 (end−start)/resetFrames 점진 감쇠.
    ///  - 상태 전이: 엄폐→조준 spotFirst(0.2s) / 조준→엄폐 spotLast(0.2s) — 전 무기.
    ///  - 재장전 R1/R2: 비사격 프레임마다 진행(발사 시 리셋), 실효 = reload×(1−Σ버프)(감산형, min 1프레임)
    ///    + 자동 탄0 재장전은 spot_last 가산(einkk). ≥100% 버프 = re-click 갭만으로 풀장전 (창발).
    ///  - SR/RL 부류 = per-char 필드: input UP(+maintain) / DOWN_Charge(only 풀차지) / DOWN(평사).
    ///  - 명중원: 발사 −changePerShot / 비사격 +changeSpeed/fps 회복 (clamp [end, start]).
    ///
    /// SimClock 배선·대미지/게이지 이벤트 발행 = K8. 이 클래스는 타이밍만 책임.
    /// </summary>
    public sealed class FiringModel
    {
        private const double Fps = WeaponProfile.EngineFrameRate;
        private const double ShootThreshold = 60.0 * Fps; // RPM×frames 단위 (einkk shootThreshold)

        private readonly WeaponProfile _w;
        private readonly FiringControl _ctl;
        private readonly IRandomSource _rng;
        private readonly int _maxAmmo;

        private readonly int _spotFirstFrames;
        private readonly int _spotLastFrames;
        private readonly int _fullChargeFrames;
        private readonly bool _isCharge;

        // ── 런타임 카운터 (einkk 대응) ──
        private double _shootCountdown;      // RPM accumulator
        private double _rateOfFire;          // 현재 발사속도 (RPM)
        private int _spotFirstLeft;          // 엄폐→조준 잔여 프레임
        private int _spotLastLeft;           // 조준→엄폐(강제 복귀) 잔여 프레임
        private int _maintainLeft;           // maintain형 자체 후딜레이 잔여 프레임
        private int _chargeFrames;           // 현재 차지 누적 프레임
        private int _chargeTargetFrames;     // 이번 발사의 차지 목표 (풀차지 + 수동 오차)
        private int _reclickLeft;            // 수동 re-click 갭 잔여 프레임
        private int _reloadProgress;         // R1 누적 재장전 프레임 (발사 시 리셋)
        private int _reloadTargetFrames;     // 실효 재장전 프레임 (탄0 강제 재장전 시 확정)
        private bool _forceReloading;        // 탄0 강제 재장전 중
        private double _accuracyCircle;      // 현재 명중원 반지름

        public int CurrentAmmo { get; private set; }
        /// <summary>현재 발사속도 (발/sec) — ramp/감쇠 검증용.</summary>
        public double CurrentRatePerSec => _rateOfFire / 60.0;
        public double AccuracyCircle => _accuracyCircle;

        private readonly double _effectiveReloadSec; // 항별 반올림 감쇠 적용 후 재장전 시간(초)

        /// <summary>
        /// 타이밍 감쇠식 (사용자 확정 2026-07-08, in-game):
        ///   effective = base − Σᵢ round(base × buffᵢ, 2)   ← **항별** 소수 둘째자리 사사오입(AwayFromZero).
        /// B2 per-term floor 와 동류의 니케식 항별 라운딩 — Σ 후 곱셈으로 대체 금지. 하한 0.
        /// 라운딩은 decimal 경유 — 게임 원천값이 ×10000 정수(십진)라 double 이진 오차
        /// (예: 0.145 → 0.1449…9 → 오반올림 0.14)를 차단해야 사사오입이 정확.
        /// </summary>
        public static double ApplyTimingReduction(double baseSec, IEnumerable<double> buffTerms)
        {
            decimal reduced = (decimal)baseSec;
            if (buffTerms != null)
                foreach (double b in buffTerms)
                    if (b != 0)
                        reduced -= Math.Round((decimal)baseSec * (decimal)b, 2, MidpointRounding.AwayFromZero);
            return Math.Max(0.0, (double)reduced);
        }

        /// <param name="reloadSpeedBuffs">재장전 속도 버프 **개별 항** (큐브/소장품 `Nikke.TimingReloadSpeedTerms`) —
        /// 정책값 <see cref="FiringControl.ReloadSpeedBuff"/> 도 1항으로 합류. 항별 반올림 감쇠식 적용.</param>
        /// <param name="chargeSpeedBuffs">차지 속도 버프 개별 항 (`Nikke.TimingChargeSpeedTerms`) — 동일 감쇠식.</param>
        public FiringModel(WeaponProfile weapon, int maxAmmo, FiringControl control, IRandomSource rng,
                           IReadOnlyList<double> reloadSpeedBuffs = null,
                           IReadOnlyList<double> chargeSpeedBuffs = null)
        {
            _w = weapon ?? throw new ArgumentNullException(nameof(weapon));
            _ctl = control ?? throw new ArgumentNullException(nameof(control));
            _rng = rng ?? throw new ArgumentNullException(nameof(rng));
            if (maxAmmo <= 0) throw new ArgumentOutOfRangeException(nameof(maxAmmo));
            if (_ctl.Style == FireStyle.Tap && _w.IsOnlyFullCharge)
                throw new ArgumentException($"'{_w.WeaponTypeCode}'(DOWN_Charge) 는 only 풀차지 — Tap 불가.");

            _maxAmmo = maxAmmo;
            CurrentAmmo = maxAmmo;
            _isCharge = _w.IsChargeWeapon;

            // 재장전: 캐릭 고유 항들 + 정책 항(수동 지정) → 항별 반올림 감쇠. ≥100% 상당 = 0초 → 하한 1프레임(즉시).
            var reloadTerms = new List<double>(reloadSpeedBuffs ?? Array.Empty<double>());
            if (_ctl.ReloadSpeedBuff != 0) reloadTerms.Add(_ctl.ReloadSpeedBuff);
            _effectiveReloadSec = ApplyTimingReduction(_w.ReloadTimeSec, reloadTerms);

            _spotFirstFrames = ToFrames(_w.SpotFirstDelaySec);
            _spotLastFrames = ToFrames(_w.SpotLastDelaySec);
            // 차지: 동일 감쇠식, 하한 1프레임
            _fullChargeFrames = Math.Max(1, ToFrames(ApplyTimingReduction(_w.ChargeTimeSec, chargeSpeedBuffs)));
            _rateOfFire = _w.FireRate * 60.0;              // 발/sec → RPM
            _spotFirstLeft = _spotFirstFrames;             // 전투 개시 = 엄폐→조준부터
            _accuracyCircle = _w.StartAccuracyCircle;
            _chargeTargetFrames = NextChargeTarget();
        }

        private static int ToFrames(double sec) => Math.Max(0, (int)Math.Round(sec * Fps));

        private int NextChargeTarget()
            => _fullChargeFrames
             + (_ctl.Mode == ControlMode.Manual && _ctl.ChargeErrorMaxSec > 0
                 ? (int)Math.Round(_rng.NextDouble() * _ctl.ChargeErrorMaxSec * Fps) : 0);

        private int SampleReclickFrames()
        {
            double sec = _ctl.ReclickMinSec + _rng.NextDouble() * (_ctl.ReclickMaxSec - _ctl.ReclickMinSec);
            return Math.Max(1, (int)Math.Round(sec * Fps));
        }

        /// <summary>실효 재장전 프레임 — 항별 반올림 감쇠 적용값, 하한 1프레임 (0초 = 즉시 장전 창발).</summary>
        private int EffectiveReloadFrames(bool addCoverReturn)
        {
            double sec = _effectiveReloadSec;
            if (addCoverReturn) sec += _w.SpotLastDelaySec; // einkk: 첫(강제) 재장전에 spot_last 가산
            return Math.Max(1, ToFrames(sec));
        }

        /// <summary>프레임 1개 진행. 발사/재장전/전이/차지 상태 갱신 후 결과 반환.</summary>
        public FiringFrameResult AdvanceFrame()
        {
            // accumulator 는 모든 프레임에서 감소 (einkk: 비사격 포함)
            if (_shootCountdown > 0) _shootCountdown -= _rateOfFire;

            // ── 탄0 강제 재장전 (개시 프레임부터 진행 — einkk 첫 프레임 카운트와 동일) ──
            if (_forceReloading)
                return ForceReloadTick();

            // ── 수동 re-click 갭 (비사격 — R1 재장전 진행) ──
            if (_reclickLeft > 0)
            {
                _reclickLeft -= 1;
                NonFiringFrameUpkeep();
                PassiveReloadTick();
                return Idle(reloading: CurrentAmmo < _maxAmmo);
            }

            // ── 조준→엄폐 강제 복귀 (UP형 발사 후) — 비사격, R1 재장전 진행 ──
            if (_spotLastLeft > 0)
            {
                _spotLastLeft -= 1;
                NonFiringFrameUpkeep();
                PassiveReloadTick();
                return Idle(reloading: CurrentAmmo < _maxAmmo);
            }

            // ── 엄폐→조준 (spotFirst) ──
            if (_spotFirstLeft > 0)
            {
                _spotFirstLeft -= 1;
                if (_spotFirstLeft == 0 && _isCharge)
                    _chargeFrames = 1; // einkk: 전이 마지막 프레임에 charge 1f 선시작
                return Idle(reloading: false);
            }

            // ── maintain형 자체 후딜레이 (자세 유지 — 사격 자세이므로 재장전 미진행) ──
            if (_maintainLeft > 0)
            {
                _maintainLeft -= 1;
                if (_maintainLeft == 0 && _isCharge)
                    _chargeFrames = 1;
                return Idle(reloading: false);
            }

            // ── 발사 시도 ──
            if (CurrentAmmo <= 0)
            {
                BeginForceReload();
                return ForceReloadTick(); // 개시 프레임 = 첫 재장전 프레임
            }

            if (!_isCharge)
                return TryFireNonCharge();
            return TryFireCharge();
        }

        // ── 비차지 (AR/SMG/MG/SG + Pascal): accumulator 발사 ──
        private FiringFrameResult TryFireNonCharge()
        {
            if (_shootCountdown > 0) return Idle(reloading: false);
            while (_shootCountdown <= 0) _shootCountdown += ShootThreshold;
            return Fire(isFullCharge: false);
        }

        // ── 차지 (SR/RL): UP / DOWN_Charge / maintain형 ──
        private FiringFrameResult TryFireCharge()
        {
            bool tap = _ctl.Mode == ControlMode.Manual && _ctl.Style == FireStyle.Tap;
            _chargeFrames += 1;

            if (!tap && _chargeFrames < _chargeTargetFrames)
                return Idle(reloading: false);

            // DOWN_Charge: 풀차지 완료 + rate gate (einkk downCharge)
            if (_w.IsOnlyFullCharge && _shootCountdown > 0)
                return Idle(reloading: false);

            bool full = _chargeFrames >= _fullChargeFrames;
            var result = Fire(isFullCharge: tap ? _chargeFrames >= _fullChargeFrames : full);
            _chargeFrames = 0;
            _chargeTargetFrames = NextChargeTarget();

            // 발사 후 시퀀스 (부류별)
            if (_w.IsOnlyFullCharge)
            {
                while (_shootCountdown <= 0) _shootCountdown += ShootThreshold; // rate gate 만
            }
            else if (_w.MaintainFireStanceSec > 0)
            {
                // 복귀 없음 — 자체 후딜레이 = spotFirst + maintain (einkk; 수동으로 스킵 불가한 무기 모션)
                _maintainLeft = ToFrames(_w.SpotFirstDelaySec + _w.MaintainFireStanceSec);
            }
            else if (_ctl.Mode == ControlMode.Auto)
            {
                // UP형 자동: 강제 엄폐 복귀 → 재조준 (사이클 = last+first+charge ≈ 1.4s)
                _spotLastLeft = _spotLastFrames;
                _spotFirstLeft = _spotFirstFrames;
            }
            else if (_ctl.Style == FireStyle.Tap)
            {
                // 수동 톡톡이: [spotFirst + reclick] 반복 (사용자 실측; 구 0.215s 와 부합)
                _spotFirstLeft = _spotFirstFrames;
                _reclickLeft = SampleReclickFrames();
            }
            else
            {
                // 수동 풀차지: 조준 유지 — reclick 갭만 (발당 spotFirst 미지불)
                _reclickLeft = SampleReclickFrames();
            }
            return result;
        }

        private FiringFrameResult Fire(bool isFullCharge)
        {
            CurrentAmmo -= 1;
            _reloadProgress = 0; // R1: 사격 시 수동 재장전 누적 리셋

            // 명중원 수축 + ramp 증가 (발사 시)
            if (_w.AccuracyChangePerShot > 0)
                _accuracyCircle = Math.Max(_w.EndAccuracyCircle, _accuracyCircle - _w.AccuracyChangePerShot);
            if (_w.FireRateRampPerShot > 0)
                _rateOfFire = Math.Clamp(_rateOfFire + _w.FireRateRampPerShot * 60.0,
                                         _w.FireRate * 60.0, _w.EndFireRate * 60.0);

            return new FiringFrameResult
            {
                Fired = true,
                IsFullCharge = isFullCharge,
                PelletsPerShot = _w.ShotCount,
                AccuracyCircle = _accuracyCircle,
                CurrentAmmo = CurrentAmmo,
                IsReloading = false,
            };
        }

        private void BeginForceReload()
        {
            _forceReloading = true;
            _reloadProgress = 0;
            bool coverTransition = _ctl.Mode == ControlMode.Auto; // 수동 = 전이 없이 갭 재장전 (사용자 확정)
            _reloadTargetFrames = EffectiveReloadFrames(addCoverReturn: coverTransition);
            if (coverTransition)
                _spotFirstLeft = _spotFirstFrames; // 재장전 후 엄폐→조준 재지불 (auto: 0.2+reload+0.2)
            else
                _reclickLeft = 0;
        }

        private FiringFrameResult ForceReloadTick()
        {
            NonFiringFrameUpkeep();
            _reloadProgress += 1;
            if (_reloadProgress >= _reloadTargetFrames)
            {
                RefillAmmo();
                _forceReloading = false;
                _reloadProgress = 0;
            }
            return Idle(reloading: true);
        }

        /// <summary>R1: 비사격 프레임의 수동/기회 재장전 진행 — 실효 프레임 도달 시 충전, 사격 시 리셋.</summary>
        private void PassiveReloadTick()
        {
            if (CurrentAmmo >= _maxAmmo) return;
            _reloadProgress += 1;
            if (_reloadProgress >= EffectiveReloadFrames(addCoverReturn: false))
            {
                RefillAmmo();
                _reloadProgress = 0;
            }
        }

        private void RefillAmmo()
        {
            double ratio = Math.Max(0.0001, _w.ReloadBulletRate); // 빈 장전 방지 (einkk max(1,…))
            CurrentAmmo = Math.Min(_maxAmmo, CurrentAmmo + (int)Math.Round(ratio * _maxAmmo));
        }

        /// <summary>비사격 프레임 공통: ramp 점진 감쇠 + 명중원 회복.</summary>
        private void NonFiringFrameUpkeep()
        {
            if (_w.FireRateResetTimeSec > 0 && _w.EndFireRate > _w.FireRate)
            {
                double resetFrames = _w.FireRateResetTimeSec * 100.0; // einkk: raw reset_time = 감쇠 프레임 수
                double decay = (_w.EndFireRate - _w.FireRate) * 60.0 / resetFrames;
                _rateOfFire = Math.Max(_w.FireRate * 60.0, _rateOfFire - decay);
            }
            if (_w.AccuracyChangeSpeed > 0)
                _accuracyCircle = Math.Min(_w.StartAccuracyCircle,
                                           _accuracyCircle + _w.AccuracyChangeSpeed / Fps);
        }

        private FiringFrameResult Idle(bool reloading) => new()
        {
            Fired = false,
            AccuracyCircle = _accuracyCircle,
            CurrentAmmo = CurrentAmmo,
            IsReloading = reloading,
        };
    }
}
