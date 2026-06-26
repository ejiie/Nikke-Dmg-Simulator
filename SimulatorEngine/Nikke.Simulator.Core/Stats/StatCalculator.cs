using System;
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
        public bool IsDistributionHit; // 분배 공격 여부 (B4 distrib_dmg 게이트)
        public bool IsTrueDamage;      // [A2] 방어 무시 공격 여부 (FinalDef := 0 로 치환)

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
        public double SumTrueDmgBuff;  // [A2] IsTrueDamage 시에만 B3 에 가산되는 트루 대미지 증가 (큐브 TrueDamageBonus 등)

        // 5. [B4] 받뎀증 및 분배/추가 대미지 브래킷
        public double SumDamageTaken;     // 적에게 걸린 디버프 합산
        public double SumDistribDmg;

        // 6. [B5] 우월 코드 브래킷
        public double SumStrongElem;      // 0.1(기본 우월) + 오버로드/버프 합산

        // 7. 차지 대미지 2축 (Full Charge 전용)
        public double ChargeDmgBase;      // 차지 기본 배율. JSON basicAttack.chargeDamage per-character (대부분 2.5, 일부 3.5 등). 비차지 무기는 1.0.
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

    /// <summary>
    /// per-tick 대미지 공식 전담 (B2~B5 + True Damage + 차지 2축).
    ///
    /// 책임 분리 (2026-04-23 · Option D 리팩토링):
    ///   - StatCalculator    : per-tick 대미지 공식 (이 클래스)
    ///   - OverloadProcessor : pre-combat native stat 조립 (OL 합산)
    /// 이전까지 OL 합산 로직이 이 클래스에 혼재되어 있었으나 OverloadProcessor 로 이관됨.
    /// </summary>
    public static class StatCalculator
    {
        /// <summary>
        /// 실측 역산으로 확립된 NIKKE per-tick 대미지 공식 (2026-06-27, in-game bit-exact).
        ///
        ///   Damage = floor( B2 × (1+ΣB3) × (1+ΣB4) × (1+ΣB5) )
        ///     B2 = floor(P) + Σ_active floor(P × bracket_i)      ← B2 는 **가산** per-term FLOOR (곱셈 아님!)
        ///     P  = (FinalAtk − effectiveDef) × W(계수) × C(차지)   ← 계수·차지는 B2 floor *이전* 에 P 에 접힘
        ///   B3/B4/B5 는 서로 곱해지는 독립 곱셈 브래킷; 마지막에 단일 floor.
        ///
        /// [A1] 최소 대미지: effectiveDef >= FinalAtk 이면 배율 무관 즉시 1 (중간 곱 경유 안 함).
        /// [A2] True Damage: effectiveDef := 0, 그리고 B3 에 SumTrueDmgBuff 조건부 가산.
        ///
        /// 검증(bit-exact, 잔차 ≤1e-7 = 계수 표시반올림): 차지 스나 풀차지 1히트 + B2(크리/코어/거리/버스트)
        ///   + B3(attack_dmg) + B4(damage_taken) + B5(strong_elem).
        /// 구조 확정(도메인): B3 pierce/parts/dot/seq = attack_dmg 상속+제약; B4 distrib = damage_taken 상속+제약;
        ///   차지 2-축; 비차지=C1; 스킬계수=W슬롯; true_dmg=DEF0; 최소뎀1.
        /// 실측 대기: [gap#4] 비차지 무기 W·C 접힘 / [gap#7] nested-vs-single floor 경계.
        /// </summary>
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static double CalculateDamage(in AttackContext ctx)
        {
            // [A2] True Damage 는 방어 무시 — effectiveDef := 0
            double effectiveDef = ctx.IsTrueDamage ? 0.0 : ctx.FinalDef;

            // [A1] 최소 대미지 규칙: DEF ≥ ATK 면 모든 배율 무시하고 최종 1 고정.
            //      True Damage 경로에서는 effectiveDef=0 이므로 FinalAtk > 0 인 한 이 분기를 타지 않음.
            if (effectiveDef >= ctx.FinalAtk)
                return 1.0;

            double baseDamage = ctx.FinalAtk - effectiveDef;

            // 차지 배율 C. 비차지/미차지 = 1. 풀차지 시 2-축: (base + Σadd) × (1 + Σmult).
            double chargeMult = 1.0;
            if (ctx.IsFullCharge)
                chargeMult = (ctx.ChargeDmgBase + ctx.SumChargeDmgAdd) * (1.0 + ctx.SumChargeDmgMult);

            // P: 계수(W=평타/스킬 계수)·차지(C) 를 B2 floor 이전에 접는다.
            //   [gap#4] 비차지 무기(AR/SMG/MG/SG) W·C 접힘은 실측 검증 대기 (구조 확정).
            double p = baseDamage * ctx.SkillMultiplier * chargeMult;

            // [B2] 크리/코어/거리/버스트 = 가산 per-term FLOOR ──  B2 = floor(P) + Σ floor(P × bracket_i)
            //   (보너스 0 → floor(0)=0 이므로 거리/버스트는 무조건 가산해도 안전)
            double b2 = Math.Floor(p)
                      + Math.Floor(p * ctx.ProperDistanceBonus)
                      + Math.Floor(p * ctx.FullBurstBonus);
            if (ctx.IsCrit) b2 += Math.Floor(p * ctx.SumCritDmg);
            if (ctx.IsCoreHit) b2 += Math.Floor(p * (ctx.CoreHitBase + ctx.SumCoreHitBuff));

            // [B3] 공격 대미지 곱셈 브래킷. pierce/parts/dot/seq = attack_dmg 상속 + 발동제약(플래그) → 같은 합산.
            double b3 = 1.0 + ctx.SumAttackDmg;
            if (ctx.IsPierceHit) b3 += ctx.SumPierceDmg;
            if (ctx.IsPartsHit) b3 += ctx.SumPartsDmg;
            if (ctx.IsDotDamage) b3 += ctx.SumDotDmg;
            if (ctx.IsSequentialHit) b3 += ctx.SumSequentialDmg;
            if (ctx.IsTrueDamage) b3 += ctx.SumTrueDmgBuff;   // [A2] 트루 대미지 조건부 증가

            // [B4] 받는 대미지 곱셈 브래킷. distrib = damage_taken 상속 + 분배공격 제약.
            double b4 = 1.0 + ctx.SumDamageTaken;
            if (ctx.IsDistributionHit) b4 += ctx.SumDistribDmg;

            // [B5] 속성 유리 곱셈 브래킷
            double b5 = 1.0 + ctx.SumStrongElem;

            // 브래킷 곱 후 단일 FLOOR. [gap#7] nested-vs-single 중 single 이 전 데이터 일치.
            return Math.Floor(b2 * b3 * b4 * b5);
        }
    }
}