using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;

namespace Nikke.Simulator.Core.Stats
{
    /// <summary>
    /// 공격 1회(Tick)에 대한 모든 상태와 버프 합산값을 담는 컨텍스트 객체.
    /// 메모리 할당(GC) 오버헤드를 방지하기 위해 class에서 struct로 최적화됨.
    /// </summary>
    public struct AttackContext
    {
        // 1. 기본 스탯 및 계수
        public double FinalAtk;
        public double FinalDef;
        public double SkillMultiplier;

        // 2. 공격 조건 플래그 (이게 true일 때만 B2, B3의 특정 버프가 켜짐!)
        public bool IsCrit;
        public bool IsCoreHit;
        public bool IsFullCharge;
        public bool IsPierceHit;       // 관통 여부
        public bool IsPartsHit;        // 부위 타격 여부
        public bool IsDotDamage;       // 도트 대미지 여부
        public bool IsSequentialHit;   // 연속 공격 여부

        // 2-b. [H3] IsCrit 결정용 확률값. 시뮬 루프의 RNG 가 이 값과 비교하여 IsCrit 를 세팅.
        // 기본 15% + OL StatCritical + 버프 합산.
        public double BaseCritRate;

        // 3. [B2] 코어/크리/거리/버스트 브래킷
        public double FullBurstBonus;     // 풀버스트 (보통 0.5)
        public double ProperDistanceBonus;// 적정 거리 (보통 0.3)
        public double SumCritDmg;         // 기본 크뎀 50% + 크뎀증 버프 합산
        public double CoreHitBase;        // 기본 코어힛 100% (+1.0)
        public double SumCoreHitBuff;

        // 4. [B3] 대미지 증가 브래킷 (합연산)
        public double SumAttackDmg;
        public double SumPierceDmg;
        public double SumPartsDmg;
        public double SumDotDmg;
        public double SumSequentialDmg;

        // 5. [B4] 받뎀증 및 분배/추가 대미지 브래킷
        public double SumDamageTaken;     // 적에게 걸린 디버프 합산
        public double SumDistribDmg;

        // 6. [B5] 우월 코드 브래킷
        public double SumStrongElem;      // 0.1(기본 우월) + 오버로드/버프 합산

        // 7. 차지 대미지 2축 (Full Charge 전용)
        public double ChargeDmgBase;      // 무기별 기본 차지 배율 (예: 스나 2.5)
        public double SumChargeDmgAdd;    // 가산 축 (Charge Damage ▲)
        public double SumChargeDmgMult;   // 곱산 축 (Charge Damage Multiplier ▲)

        /// <summary>
        /// 구조체 초기값을 설정하는 생성자
        /// </summary>
        public AttackContext(double finalAtk, double finalDef) : this()
        {
            FinalAtk = finalAtk;
            FinalDef = finalDef;
            SkillMultiplier = 1.0;
            SumCritDmg = 0.5;
            CoreHitBase = 1.0;
            ChargeDmgBase = 1.0;
            BaseCritRate = 0.15; // [H3] 기본 크리 확률 15%

            // 나머지 숫자/논리형 필드는 struct 특성상 0 / false로 자동 초기화됨.
        }
    }

    public static class StatCalculator
    {
        /// <summary>
        /// 니케 오버로드 합산식
        /// </summary>
        /// <param name="nativeStat">기초 스탯</param>
        /// <param name="olPercents">오버로드 퍼센트 옵션 리스트 (예: { 0.1181, 0.1181, 0.089 })</param>
        /// <param name="decimals">반올림할 소수점 자리수 (공격력/장탄=0, 차지속도=1)</param>
        /// <returns>최종 오버로드 보너스 수치</returns>
        private static double CalculateNikkeOverloadBonus(double nativeStat, IEnumerable<double> olPercents, int decimals = 0)
        {
            if (olPercents == null || !olPercents.Any())
                return 0;

            double totalBonus = 0;

            // Rule 2: 수치가 동일한 옵션은 미리 합산한다 (Grouping)
            var groupedPercents = olPercents.GroupBy(p => p);

            foreach (var group in groupedPercents)
            {
                double percentValue = group.Key;
                int count = group.Count(); // 동일한 수치의 개수

                // 1. 동일 옵션의 퍼센트를 먼저 합산(percentValue * count)하여 기초 스탯에 곱함
                double groupBonus = nativeStat * (percentValue * count);

                // 2. Rule 1: 그룹 단위로 계산된 값을 지정된 소수점 자리에서 반올림 (MidpointRounding.AwayFromZero가 일반적인 사사오입)
                totalBonus += Math.Round(groupBonus, decimals, MidpointRounding.AwayFromZero);
            }

            return totalBonus;
        }

        /// <summary>
        /// 기초 스탯(Native)과 오버로드(OL) 옵션을 합산하여 전투 진입 전 최종 기초 스탯을 계산합니다.
        /// </summary>
        public static double CalculateFinalBaseStat(double nativeStat, IEnumerable<double> olPercents, double olFlatSum = 0, int decimals = 0)
        {
            // 오버로드 보너스를 니케식으로 정밀 계산
            double olBonus = CalculateNikkeOverloadBonus(nativeStat, olPercents, decimals);

            // 기초 스탯 + 정밀 반올림된 오버로드 보너스 + 고정치 보너스
            return nativeStat + olBonus + olFlatSum;
        }

        /// <summary>
        /// B1 ~ B5 브래킷을 적용하는 최종 대미지 연산기
        /// </summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static double CalculateDamage(in AttackContext ctx)
        {
            // 1. 깡 대미지 (최소 대미지 1 보정)
            double baseDamage = Math.Max(1.0, ctx.FinalAtk - ctx.FinalDef);

            // 2. [B2] 코어/크리/거리/버스트
            double b2 = 1.0 + ctx.FullBurstBonus + ctx.ProperDistanceBonus;
            if (ctx.IsCrit) b2 += ctx.SumCritDmg;
            if (ctx.IsCoreHit) b2 += (ctx.CoreHitBase + ctx.SumCoreHitBuff);

            // 3. [B3] 대미지 증가 버프 (공격 종류에 따라 조건부 활성화!)
            double b3 = 1.0 + ctx.SumAttackDmg;
            if (ctx.IsPierceHit) b3 += ctx.SumPierceDmg;
            if (ctx.IsPartsHit) b3 += ctx.SumPartsDmg;
            if (ctx.IsDotDamage) b3 += ctx.SumDotDmg;
            if (ctx.IsSequentialHit) b3 += ctx.SumSequentialDmg;

            // 4. [B4] & [B5] 받뎀증 및 우월 코드
            double b4 = 1.0 + ctx.SumDamageTaken + ctx.SumDistribDmg;
            double b5 = 1.0 + ctx.SumStrongElem;

            // 5. 차지 대미지 보정 (조건: 풀차지 공격일 때만 연산!)
            double chargeMultiplier = 1.0;
            if (ctx.IsFullCharge)
            {
                // 2-축 계산 적용
                chargeMultiplier = (ctx.ChargeDmgBase + ctx.SumChargeDmgAdd) * (1.0 + ctx.SumChargeDmgMult);
            }

            // 최종 연산: 전부 곱
            double finalDamage = baseDamage * b2 * b3 * b4 * b5 * ctx.SkillMultiplier * chargeMultiplier;

            // 실제 게임에선 여기서 최종적으로 내림/반올림 처리가 한 번 더 들어가겠지?
            return Math.Floor(finalDamage);
        }
    }
}