using System;

namespace Nikke.Simulator.Core.Combat
{
    /// <summary>
    /// 속성 상성 판정 (T04 통합 — 내용 사용자 확정 2026-07-08, 코드 통합 2026-07-11).
    ///
    /// 순환(공격자 → 열세 대상): Water→Fire→Wind→Iron→Electric→Water.
    /// StaticData ElementTable weak cycle 및 ConfigBattle `ElementBonusDamage`(+10%)와 일치.
    ///
    /// ⚠ B5 기본 우월 +0.1 의 소스는 <see cref="StrongElementBonus"/> **하나뿐** (FACTS §7-5):
    ///  - ConfigBattle `ElementBonusDamage` 를 별도로 더하면 중복 가산 — 금지.
    ///  - OL `IncElementDmg`/스킬 상성버프(AddIncElementDmgType 등)는 **별축 가산**(버프) — 역할 구분.
    ///  - 골든 리그의 SumStrongElem(예 1.4293)은 이미 기본 0.1 포함 형태로 검증된 값.
    /// </summary>
    public static class ElementAdvantage
    {
        /// <summary>기본 우월 보너스 (B5 SumStrongElem 의 상성 기본항).</summary>
        public const double StrongElementBonus = 0.1;

        /// <summary>
        /// 공격자 속성이 대상 속성에 우월한가. 미지/빈 속성 = false (graceful — 상성 없음 취급).
        /// </summary>
        public static bool IsStrongAgainst(string attackerElement, string targetElement)
        {
            if (string.IsNullOrEmpty(attackerElement) || string.IsNullOrEmpty(targetElement))
                return false;
            // Water→Fire→Wind→Iron→Electric→Water (화살표 = 이긴다)
            return Beats(attackerElement) is string weak
                && string.Equals(weak, targetElement, StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>상성 보너스 (우월 = +0.1, 그 외 0). 역상성 페널티는 존재하지 않음(확정).</summary>
        public static double GetBonus(string attackerElement, string targetElement)
            => IsStrongAgainst(attackerElement, targetElement) ? StrongElementBonus : 0.0;

        private static string Beats(string element) => element.ToLowerInvariant() switch
        {
            "water" => "Fire",
            "fire" => "Wind",
            "wind" => "Iron",
            "iron" => "Electric",
            "electric" => "Water",
            _ => null, // 미지 속성 (신버전) — 상성 없음 (graceful no-op, INV-1)
        };
    }
}
