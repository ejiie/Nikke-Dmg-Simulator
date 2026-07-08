using System;
using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Data.Dto;

namespace Nikke.Simulator.Core.Stats
{
    /// <summary>
    /// 오버로드(OL) + 런타임 %-버프의 니케식 합산 전담 프로세서.
    ///
    /// 규칙 정의: 니케식 group-then-round (동일값 그룹핑 → 그룹별 반올림 → 합산). 권위 = Docs/DESIGN.md §3
    /// (구 ARCHITECTURE.md §4.4 는 Docs/_archive/ 로 이동).
    ///
    /// 책임 분리 (2026-06-30 · 3-way split):
    ///   - OverloadProcessor       : OL %-버프 니케식 합산 (이 클래스).
    ///   - Stats.StatCalculator    : 최종 기초스탯 조립 (레벨/돌파/코어/콘솔/장비).
    ///   - Combat.DamageCalculator : per-tick 대미지 공식 (B2~B5 + True Damage + 차지 2축).
    ///   - Stats.StatTable         : 원천 자료 로딩 + raw 테이블 접근.
    /// </summary>
    public static class OverloadProcessor
    {
        /// <summary>
        /// 기초 스탯(Native)과 오버로드(OL) 옵션을 합산하여 전투 진입 전 최종 기초 스탯을 계산합니다.
        /// 니케식 동일값 선합산 반올림 규칙 (ARCHITECTURE.md §4.4) 적용.
        /// </summary>
        /// <param name="nativeStat">기초 스탯 (Effective Native)</param>
        /// <param name="olPercents">오버로드 퍼센트 옵션 리스트 (예: { 0.1181, 0.1181, 0.089 })</param>
        /// <param name="olFlatSum">추가 고정치 합 (현재 호출부 전부 0)</param>
        /// <param name="decimals">반올림 자릿수 (정수 스탯=0, 차지 시간=2)</param>
        /// <returns>nativeStat + OL 보너스 + 고정치</returns>
        public static double CalculateFinalBaseStat(
            double nativeStat,
            IEnumerable<double> olPercents,
            double olFlatSum = 0,
            int decimals = 0)
        {
            double olBonus = CalculateNikkeOverloadBonus(nativeStat, olPercents, decimals);
            return nativeStat + olBonus + olFlatSum;
        }

        /// <summary>
        /// 특정 스탯의 '고정치(Integer)' 옵션 총합 계산 (예: 크리티컬 데미지 등).
        /// /10000 정규화는 소비자 책임 — `val_type` 해석은 `Nikke.InitializeFinalStats` 의 Normalize 람다.
        /// </summary>
        public static double CalculateFlatBonus(IEnumerable<OverloadOptionDto> allOptions, string targetType)
        {
            if (allOptions == null) return 0;

            return allOptions
                .Where(opt => opt.type == targetType && opt.val_type == "Integer")
                .Sum(opt => opt.value);
        }

        /// <summary>
        /// 시간(1/100초 **정수**) 니케식 감쇠 — 차지/재장전 속도 버프용 (사용자 확정 2026-07-08).
        ///   effectiveCs = baseCs − Σ_group round(baseCs × value × count)   ← group-then-round, 사사오입
        /// <see cref="CalculateNikkeOverloadBonus"/> 와 동일 규칙(동일값 선합산 → 그룹 사사오입)의
        /// 정수 도메인 판: 시간은 게임 원천이 1/100초 정수(timeData)이므로 **cs 정수로 유지**하고,
        /// buff 분수는 ×10000 정수로 복원(원천 = 십진 정수) → 순수 정수 연산 = 이진 부동소수 오차 원천 차단.
        /// (초 단위 "소수 둘째자리 반올림" 과 동치 — decimals=2 를 cs 정수 사사오입으로 구현.)
        /// </summary>
        /// <param name="baseCs">기준 시간 (1/100초 정수, 예: 재장전 2.5s = 250).</param>
        /// <param name="buffFractions">속도 버프 분수 목록 (예: 0.2969 = 29.69%). 음수 = 시간 증가 디버프.</param>
        public static int ReduceTimeCs(int baseCs, IEnumerable<double> buffFractions)
        {
            long reduced = baseCs;
            if (buffFractions != null)
            {
                var groups = buffFractions
                    .Select(b => (long)Math.Round(b * 10000.0, MidpointRounding.AwayFromZero))
                    .Where(x => x != 0)
                    .GroupBy(x => x);
                foreach (var g in groups)
                {
                    long num = (long)baseCs * g.Key * g.Count();      // cs × (버프×10000 정수 합)
                    long delta = num >= 0 ? (num + 5000) / 10000      // 사사오입 (정수 나눗셈)
                                          : (num - 5000) / 10000;
                    reduced -= delta;
                }
            }
            return (int)Math.Max(0, reduced);
        }

        /// <summary>
        /// 니케식 OL 합산 (내부 헬퍼).
        /// 알고리즘:
        ///   1. 동일 value 그룹핑 (GroupBy).
        ///   2. 그룹별 델타 = Round(native × value × count, decimals, AwayFromZero).
        ///   3. 그룹 결과 합산.
        /// </summary>
        private static double CalculateNikkeOverloadBonus(double nativeStat, IEnumerable<double> olPercents, int decimals = 0)
        {
            if (olPercents == null || !olPercents.Any())
                return 0;

            double totalBonus = 0;

            // Rule: 수치가 동일한 옵션은 미리 합산한다 (Grouping)
            var groupedPercents = olPercents.GroupBy(p => p);

            foreach (var group in groupedPercents)
            {
                double percentValue = group.Key;
                int count = group.Count(); // 동일한 수치의 개수

                // 1. 동일 옵션의 퍼센트를 먼저 합산(percentValue * count)하여 기초 스탯에 곱함
                double groupBonus = nativeStat * (percentValue * count);

                // 2. 그룹 단위 반올림 (Korean 사사오입 = MidpointRounding.AwayFromZero)
                totalBonus += Math.Round(groupBonus, decimals, MidpointRounding.AwayFromZero);
            }

            return totalBonus;
        }
    }
}
