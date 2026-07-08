using System.Collections.Generic;

namespace Nikke.Simulator.Engine.Skills
{
    /// <summary>스킬 적용 2축 (DESIGN §5): static = BuildAttackContext 주입 / runtime = 시뮬 루프(K7).</summary>
    public enum EffectAxis
    {
        /// <summary>상태 독립 상시 효과 — 전투 시작 시 1회 주입.</summary>
        Static,
        /// <summary>트리거/조건/지속시간 의존 — SkillRuntime(K7)이 이벤트로 소비.</summary>
        Runtime,
    }

    /// <summary>
    /// FunctionType → 엔진 소비 슬롯. **확실한 것만 개별 슬롯** — 불확실 = <see cref="Unverified"/>
    /// (K8 in-game 대조로 승격), 미지 신값 = <see cref="Unknown"/> (graceful no-op).
    /// </summary>
    public enum EffectRoute
    {
        Unknown = 0,        // 컨버터 스냅샷 밖 신값 — no-op + 로그 대상
        Unverified,         // 알려진 타입이나 브래킷 매핑 미검증 (FullBurstDamage/AddDamage/DamageRatioUp 등)

        // ── 기초스탯 rate 버프 (base × (1 + Σ), DESIGN §3.5) ──
        AtkRate, DefRate, HpRate, MaxAmmoRate,

        // ── AttackContext 대미지 축 ──
        CritRateAdd,        // ctx.BaseCritRate +
        CritDmgAdd,         // ctx.SumCritDmg + (B2)
        ChargeDmgAdd,       // ctx.SumChargeDmgAdd
        StrongElemAdd,      // ctx.SumStrongElem + (B5) — ⚠ 기본 우월 +0.1 단일 소스 원칙 (DESIGN §6)
        CoreHitBuffAdd,     // ctx.SumCoreHitBuff + (B2)
        PartsDmgAdd,        // ctx.SumPartsDmg + (B3)
        PierceDmgAdd,       // ctx.SumPierceDmg + (B3)

        // ── 대미지 인스턴스 ──
        DealDamage,         // 스킬 누크 (W 슬롯 별도 인스턴스)
        DealDamageOverTime, // 지속 대미지 (B3 dot 게이트)

        // ── 타이밍 (FiringModel/K9) ──
        FireTiming,         // 발사속도/차지시간/first delay/maintain
        ReloadTiming,       // 재장전 시간/부분장전 비율 (감산형 — FiringControl.ReloadSpeedBuff)
        AmmoRefill,         // 즉시 장전/탄약 회복
        AccuracyCircle,     // 명중원 (AccuracyModel)
        BurstGauge,         // 버스트 게이지 충전 (K9)
        SkillCooldown,      // 스킬/버스트 쿨타임 (K7)
        ProperRangeBuff,    // bonusrange min/max 증감 (ProperDistanceTable per-char 축)

        // ── DPS 스코프 밖 ──
        SurvivalOrHeal,     // 힐/실드/받피감/면역/도발 등 (DESIGN: 단계적)
    }

    /// <summary>
    /// K4 — 공식 FunctionData 를 엔진 축/슬롯으로 번역. 데이터 로드는 <see cref="SkillChainLoader"/>.
    /// 매핑 근거 = nikke-einkk 효과 구현 + Docs/SKILL_DATA_BLABLALINK §4.1 방향 규칙.
    /// ⚠ 브래킷(B2~B5) 배정이 미검증인 타입은 **Unverified 로 남긴다** — 골든(K8) 대조 후 승격.
    /// </summary>
    public static class SkillTranslator
    {
        /// <summary>
        /// static/runtime 2축 분류 (DESIGN §5): 트리거 없음(None/OnStart) + 상태조건 없음 + 영구(duration
        /// None) = Static (BuildAttackContext 주입). 그 외 전부 Runtime (K7 이벤트 소비).
        /// </summary>
        public static EffectAxis Classify(FunctionDto f)
        {
            bool timingFree = f.TypedTimingTrigger is TimingTriggerType.None or TimingTriggerType.OnStart;
            bool statusFree = f.TypedStatusTrigger == StatusTriggerType.None
                           && (StatusTriggerType)f.StatusTrigger2Type == StatusTriggerType.None;
            bool permanent = f.TypedDurationType == DurationType.None;
            return timingFree && statusFree && permanent ? EffectAxis.Static : EffectAxis.Runtime;
        }

        /// <summary>FunctionType → 엔진 슬롯. 미지 신값 = Unknown (throw 금지 — INV).</summary>
        public static EffectRoute Route(FunctionDto f) => Route(f.TypedFunctionType);

        public static EffectRoute Route(FunctionType t)
            => _routes.TryGetValue(t, out var r) ? r
             : System.Enum.IsDefined(typeof(FunctionType), t) ? EffectRoute.Unverified
             : EffectRoute.Unknown;

        // 확실 매핑만 등재. 등재 안 된 기지 타입 = Unverified, 정의 밖 = Unknown.
        private static readonly Dictionary<FunctionType, EffectRoute> _routes = new()
        {
            // 기초스탯 rate
            [FunctionType.StatAtk] = EffectRoute.AtkRate,
            [FunctionType.StatDef] = EffectRoute.DefRate,
            [FunctionType.StatHp] = EffectRoute.HpRate,
            [FunctionType.FinalStatHp] = EffectRoute.HpRate,
            [FunctionType.StatAmmo] = EffectRoute.MaxAmmoRate,
            [FunctionType.StatAmmoLoad] = EffectRoute.MaxAmmoRate,
            [FunctionType.NoOverlapStatAmmo] = EffectRoute.MaxAmmoRate,

            // 대미지 축 (SKILL_DATA_BLABLALINK §4.1 + einkk)
            [FunctionType.StatCritical] = EffectRoute.CritRateAdd,
            [FunctionType.NormalStatCritical] = EffectRoute.CritRateAdd,
            [FunctionType.StatCriticalDamage] = EffectRoute.CritDmgAdd,
            [FunctionType.NormalStatCriticalDamage] = EffectRoute.CritDmgAdd,
            [FunctionType.StatChargeDamage] = EffectRoute.ChargeDmgAdd,
            [FunctionType.IncElementDmg] = EffectRoute.StrongElemAdd,
            [FunctionType.CoreShotDamageChange] = EffectRoute.CoreHitBuffAdd,
            [FunctionType.CoreShotDamageRateChange] = EffectRoute.CoreHitBuffAdd,
            [FunctionType.PartsDamage] = EffectRoute.PartsDmgAdd,
            [FunctionType.PenetrationDamage] = EffectRoute.PierceDmgAdd,

            // 대미지 인스턴스
            [FunctionType.Damage] = EffectRoute.DealDamage,
            [FunctionType.DurationDamage] = EffectRoute.DealDamageOverTime,

            // 타이밍
            [FunctionType.StatRateOfFire] = EffectRoute.FireTiming,
            [FunctionType.StatEndRateOfFire] = EffectRoute.FireTiming,
            [FunctionType.StatRateOfFirePerShot] = EffectRoute.FireTiming,
            [FunctionType.StatChargeTime] = EffectRoute.FireTiming,
            [FunctionType.FixStatChargeTime] = EffectRoute.FireTiming,
            [FunctionType.StatChargeTimeImmune] = EffectRoute.FireTiming,
            [FunctionType.StatFirstDelay] = EffectRoute.FireTiming,
            [FunctionType.StatMaintainFireStance] = EffectRoute.FireTiming,
            [FunctionType.StatShotCount] = EffectRoute.FireTiming,
            [FunctionType.StatReloadTime] = EffectRoute.ReloadTiming,
            [FunctionType.FixStatReloadTime] = EffectRoute.ReloadTiming,
            [FunctionType.StatReloadBulletRatio] = EffectRoute.ReloadTiming,
            [FunctionType.ForcedReload] = EffectRoute.AmmoRefill,
            [FunctionType.GainAmmo] = EffectRoute.AmmoRefill,
            [FunctionType.AllAmmo] = EffectRoute.AmmoRefill,
            [FunctionType.StatAccuracyCircle] = EffectRoute.AccuracyCircle,
            [FunctionType.StatBonusRangeMax] = EffectRoute.ProperRangeBuff,
            [FunctionType.StatBonusRangeMin] = EffectRoute.ProperRangeBuff,

            // 버스트 게이지 / 쿨다운
            [FunctionType.StatUltiGaugeSec] = EffectRoute.BurstGauge,
            [FunctionType.StatUltiGaugeKill] = EffectRoute.BurstGauge,
            [FunctionType.StatUltiGaugeUseSkill] = EffectRoute.BurstGauge,
            [FunctionType.StatUltiGaugeSkillHit] = EffectRoute.BurstGauge,
            [FunctionType.StatUltiGaugeShotHit] = EffectRoute.BurstGauge,
            [FunctionType.StatUltiGaugeHurt] = EffectRoute.BurstGauge,
            [FunctionType.StatUltiGaugeEmptyAmmo] = EffectRoute.BurstGauge,
            [FunctionType.GainUltiGauge] = EffectRoute.BurstGauge,
            [FunctionType.DrainUltiGauge] = EffectRoute.BurstGauge,
            [FunctionType.BurstGaugeCharge] = EffectRoute.BurstGauge,
            [FunctionType.FirstBurstGaugeSpeedUp] = EffectRoute.BurstGauge,
            [FunctionType.SkillCooltime] = EffectRoute.SkillCooldown,
            [FunctionType.ChangeCoolTimeSkill1] = EffectRoute.SkillCooldown,
            [FunctionType.ChangeCoolTimeSkill2] = EffectRoute.SkillCooldown,
            [FunctionType.ChangeCoolTimeUlti] = EffectRoute.SkillCooldown,
            [FunctionType.ChangeCoolTimeAll] = EffectRoute.SkillCooldown,
            [FunctionType.StatBurstSkillCoolTime] = EffectRoute.SkillCooldown,

            // 생존/힐 (DPS 스코프 밖 — 단계적)
            [FunctionType.HealCharacter] = EffectRoute.SurvivalOrHeal,
            [FunctionType.HealCover] = EffectRoute.SurvivalOrHeal,
            [FunctionType.HealBarrier] = EffectRoute.SurvivalOrHeal,
            [FunctionType.HealDecoy] = EffectRoute.SurvivalOrHeal,
            [FunctionType.HealShare] = EffectRoute.SurvivalOrHeal,
            [FunctionType.HealVariation] = EffectRoute.SurvivalOrHeal,
            [FunctionType.GivingHealVariation] = EffectRoute.SurvivalOrHeal,
            [FunctionType.StatHpHeal] = EffectRoute.SurvivalOrHeal,
            [FunctionType.FinalStatHpHeal] = EffectRoute.SurvivalOrHeal,
            [FunctionType.DamageReduction] = EffectRoute.SurvivalOrHeal,
            [FunctionType.ImmuneDamage] = EffectRoute.SurvivalOrHeal,
            [FunctionType.Immortal] = EffectRoute.SurvivalOrHeal,
            [FunctionType.DamageShare] = EffectRoute.SurvivalOrHeal,
            [FunctionType.GaugeShield] = EffectRoute.SurvivalOrHeal,
            [FunctionType.IncBarrierHp] = EffectRoute.SurvivalOrHeal,
            [FunctionType.DrainHp] = EffectRoute.SurvivalOrHeal,
            [FunctionType.DrainHpBuff] = EffectRoute.SurvivalOrHeal,
            [FunctionType.Taunt] = EffectRoute.SurvivalOrHeal,
            [FunctionType.Attention] = EffectRoute.SurvivalOrHeal,
            [FunctionType.CoverResurrection] = EffectRoute.SurvivalOrHeal,
            [FunctionType.Resurrection] = EffectRoute.SurvivalOrHeal,
        };
    }
}
