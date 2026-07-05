using System;

namespace Nikke.Simulator.Core.Combat
{
    /// <summary>
    /// 무기타입별 **적정 거리(proper distance)** 구간 테이블 + 활성 판정.
    /// 타겟이 적정 구간 안에 있으면 per-shot 에 +30%(ProperDistanceBonus) 가 B2 에 가산된다(DESIGN §3).
    ///
    /// 구간 수치 = **공식 roledata `bonusrange_min/max`** (무기별 최빈값,
    /// `Database/processed/proper_distance_table.json` 과 동일 — 테스트가 교차검증).
    /// RL 은 bonusrange 0-0 = 거리 보너스 없음(DESIGN §6 "RL=0 확증").
    /// 거리 단위 = roledata bonusrange 단위(추상; 예 MG 35~55).
    ///
    /// per-char 예외(SR 1명 25-45)는 이 무기별 표가 못 담음 —
    /// <see cref="GetBonusPerChar"/> 오버로드에 `Nikke.ProperRangeMin/Max` 를 넘기면 정확.
    /// (K8 통합 시 per-char 경로 권장; 무기별 표는 fallback/타입 단위 검증용.)
    ///
    /// 소비: ITarget(DummyTarget/BossTarget) 이 distance 를 알고, 공격자 WeaponTypeCode 로 이 표를 조회해
    /// <see cref="AttackContext.ProperDistanceBonus"/> 를 채운다.
    /// </summary>
    public static class ProperDistanceTable
    {
        /// <summary>적정 거리 활성 시 B2 가산 보너스 (DESIGN §3 = 0.3).</summary>
        public const double ProperDistanceBonusValue = 0.3;

        /// <summary>적정 거리 구간 [Min, Max] (roledata bonusrange 단위, 양끝 포함).</summary>
        public readonly struct Band
        {
            public double Min { get; }
            public double Max { get; }
            public bool HasBonus { get; }   // false = 이 무기는 거리 보너스 없음(RL)

            public Band(double min, double max, bool hasBonus = true)
            {
                Min = min; Max = max; HasBonus = hasBonus;
            }

            public bool Contains(double dist) => HasBonus && dist >= Min && dist <= Max;

            public static readonly Band None = new Band(0, 0, hasBonus: false);
        }

        /// <summary>
        /// 무기타입 단축코드(SG/SMG/AR/MG/SR/RL) 또는 롱폼(Shotgun/Minigun/SMG/Assault Rifle/
        /// Sniper Rifle/Rocket Launcher)으로 적정거리 구간 반환. 미등록 = <see cref="Band.None"/>.
        /// </summary>
        public static Band GetBand(string weaponType)
        {
            switch (Normalize(weaponType))
            {
                // ── 공식 roledata bonusrange 최빈값 (proper_distance_table.json 동일) ──
                case "SG":  return new Band(0.0, 25.0);
                case "SMG": return new Band(15.0, 35.0);
                case "AR":  return new Band(25.0, 45.0);
                case "MG":  return new Band(35.0, 55.0);
                case "SR":  return new Band(45.0, 100.0);
                case "RL":  return Band.None;            // bonusrange 0-0 (DESIGN: RL=0 확증)
                default:    return Band.None;
            }
        }

        /// <summary>타겟이 무기 적정 구간 안인지.</summary>
        public static bool InProperRange(string weaponType, double distance)
            => GetBand(weaponType).Contains(distance);

        /// <summary>
        /// 적정거리 보너스값 반환 — 구간 안이면 <see cref="ProperDistanceBonusValue"/>, 아니면 0.
        /// (<see cref="AttackContext.ProperDistanceBonus"/> 에 그대로 대입.)
        /// </summary>
        public static double GetBonus(string weaponType, double distance)
            => InProperRange(weaponType, distance) ? ProperDistanceBonusValue : 0.0;

        /// <summary>
        /// per-char 정확 판정 — 공격자의 `Nikke.ProperRangeMin/Max`(roledata bonusrange) 사용.
        /// rangeMax ≤ 0 (RL 의 0-0) = 보너스 없음. SR 예외 캐릭(25-45) 포함 전 캐릭 정확.
        /// </summary>
        public static double GetBonusPerChar(double distance, int rangeMin, int rangeMax)
            => (rangeMax > 0 && distance >= rangeMin && distance <= rangeMax)
                ? ProperDistanceBonusValue : 0.0;

        private static string Normalize(string weaponType)
        {
            if (string.IsNullOrWhiteSpace(weaponType)) return "";
            switch (weaponType.Trim())
            {
                case "Shotgun":         return "SG";
                case "Submachine Gun":  return "SMG";
                case "Assault Rifle":   return "AR";
                case "Minigun":
                case "Machine Gun":     return "MG";
                case "Sniper Rifle":    return "SR";
                case "Rocket Launcher": return "RL";
                default:                return weaponType.Trim().ToUpperInvariant();
            }
        }
    }
}
