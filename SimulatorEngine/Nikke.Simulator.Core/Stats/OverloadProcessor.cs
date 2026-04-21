using System;
using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Data.Dto;

namespace Nikke.Simulator.Core.Stats
{
    /// <summary>
    /// 오버로드(OL) 장비의 스탯 추출, 합산 및 특수 반올림 처리를 전담하는 프로세서
    /// </summary>
    public static class OverloadProcessor
    {
        /// <summary>
        /// 특정 스탯(예: StatAtk)의 '퍼센트(Percent)' 옵션만 추출하여 니케식으로 합산 (동일 옵션 선합산 후 반올림)
        /// </summary>
        /// <param name="nativeStat">기초 스탯</param>
        /// <param name="allOptions">캐릭터가 가진 오버로드 옵션 전체 리스트</param>
        /// <param name="targetType">필터링할 스탯 타입 (예: "StatAtk")</param>
        /// <param name="decimals">반올림할 소수점 자리수</param>
        /// <returns>최종 오버로드 퍼센트 보너스 수치</returns>
        public static double CalculatePercentBonus(double nativeStat, IEnumerable<OverloadOptionDto> allOptions, string targetType, int decimals = 0)
        {
            if (allOptions == null || !allOptions.Any())
                return 0;

            // 1. 타겟 스탯이면서 "Percent" 타입인 옵션의 수치만 추출
            var percentValues = allOptions
                .Where(opt => opt.type == targetType && opt.val_type == "Percent")
                .Select(opt => opt.value);

            if (!percentValues.Any())
                return 0;

            double totalBonus = 0;

            // 2. Rule: 수치가 동일한 옵션은 미리 합산 (Grouping)
            var groupedPercents = percentValues.GroupBy(p => p);

            foreach (var group in groupedPercents)
            {
                double percentValue = group.Key;
                int count = group.Count();

                // 동일 옵션 선합산
                double groupBonus = nativeStat * (percentValue * count);

                // 소수점 반올림 처리
                totalBonus += Math.Round(groupBonus, decimals, MidpointRounding.AwayFromZero);
            }

            return totalBonus;
        }

        /// <summary>
        /// 특정 스탯의 '고정치(Integer)' 옵션 총합 계산 (예: 크리티컬 데미지 등)
        /// </summary>
        public static double CalculateFlatBonus(IEnumerable<OverloadOptionDto> allOptions, string targetType)
        {
            if (allOptions == null || !allOptions.Any())
                return 0;

            return allOptions
                .Where(opt => opt.type == targetType && opt.val_type == "Integer")
                .Sum(opt => opt.value);
        }
    }
}