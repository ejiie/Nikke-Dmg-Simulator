// 공식 스킬 enum 미러 — 원본 = NIKKE il2cpp (SharpnelXu/nikke-mpk-json-converter `Skills.cs` 의
// TypeDefIndex 주석 달린 enum; MIT). 값 = 게임 wire 값과 1:1 (FunctionTable.mpk 의 int).
// ⚠ 게임이 컨버터 스냅샷보다 신버전 — **미지값 graceful 필수**: (FunctionType)raw 캐스팅은 정의 밖
//   값도 보존하므로 switch default / Enum.IsDefined 로 안전 처리 (D1 검증: 미지값 = 기지 최대 위 연속뿐).
// 생성 스크립트 = memorypack_decode.py 의 enum dict (수기 수정 금지 — 재생성으로 갱신).
namespace Nikke.Simulator.Engine.Skills
{
    public enum FunctionType
    {
        Unknown = -1, None = 0, StatAtk = 1, HealCharacter = 2,
        HealCover = 3, Attention = 4, AllAmmo = 5, Stun = 6,
        AutoTargeting = 7, StatAccuracyCircle = 8, StatCritical = 9, StatShotCount = 10,
        StatChargeDamage = 11, StatExplosion = 12, StatReloadTime = 13, StatAmmo = 14,
        StatDef = 15, StatRateOfFire = 16, SkillCooltime = 17, ImmuneStun = 18,
        StatUltiGaugeSec = 19, StatUltiGaugeKill = 20, StatUltiGaugeUseSkill = 21, StatUltiGaugeSkillHit = 22,
        StatUltiGaugeShotHit = 23, StatUltiGaugeHurt = 24, StatUltiGaugeEmptyAmmo = 25, GainUltiGauge = 26,
        GainAmmo = 27, DamageEnergy = 28, DamageMetal = 29, DamageBio = 30,
        Taunt = 31, DrainHp = 32, DrainUltiGauge = 33, ImmuneEnergy = 34,
        ImmuneMetal = 35, ImmuneBio = 36, ImmuneDamage = 37, ImmuneDamage_MainHP = 38,
        IgnoreDamage = 39, Immortal = 40, GravityBomb = 41, DamageReduction = 42,
        DamageShare = 43, DamageRatioEnergy = 44, DamageRatioMetal = 45, DamageRatioBio = 46,
        GaugeShield = 47, StatProjectileSpeed = 48, UseSkill1 = 49, UseSkill2 = 50,
        StatCriticalDamage = 51, HealVariation = 52, HealShare = 53, StatPenetration = 54,
        LinkAtk = 55, LinkDef = 56, StatFirstDelay = 57, StatEnergyResist = 58,
        StatMetalResist = 59, StatBioResist = 60, StatChargeTime = 61, DrainHpBuff = 62,
        StatHp = 63, DefIgnoreDamage = 64, AtkChangHpRate = 65, DefChangHpRate = 66,
        ForcedStop = 67, DamageRecoverHeal = 68, FullBurstDamage = 69, Infection = 70,
        Resurrection = 71, UseCharacterSkillId = 72, ImmuneForcedStop = 73, ImmuneGravityBomb = 74,
        Damage = 75, DamageRatioUp = 76, BuffRemove = 77, DebuffRemove = 78,
        IncReactTime = 79, IncElementDmg = 80, ChangeCoolTimeSkill1 = 81, ChangeCoolTimeSkill2 = 82,
        ChangeCoolTimeUlti = 83, ChangeCoolTimeAll = 84, StatEndRateOfFire = 85, StatRateOfFirePerShot = 86,
        CoreShotDamageChange = 87, CoreShotDamageRateChange = 88, DebuffImmune = 89, IncBurstDuration = 90,
        ChangeHp = 91, PlusBuffCount = 92, PlusDebuffCount = 93, StatHpHeal = 94,
        AddDamage = 95, BreakDamage = 96, HpProportionDamage = 97, NormalStatCritical = 98,
        CopyAtk = 99, CopyDef = 100, CopyHp = 101, FirstBurstGaugeSpeedUp = 102,
        InstantDeath = 103, ImmuneInstantDeath = 104, ChangeCurrentHpValue = 105, SingleBurstDamage = 106,
        Hide = 107, StatAmmoLoad = 108, CoverResurrection = 109, ImmuneOtherElement = 110,
        BurstGaugeCharge = 111, PartsDamage = 112, ProjectileDamage = 113, Silence = 114,
        WindReduction = 115, ElectronicReduction = 116, FireReduction = 117, WaterReduction = 118,
        IronReduction = 119, ChangeMaxSkillCoolTime1 = 120, ChangeMaxSkillCoolTime2 = 121, ChangeMaxSkillCoolTimeUlti = 122,
        HealDecoy = 123, Transformation = 124, Immortal_value = 125, StatMaintainFireStance = 126,
        AtkChangeMaxHpRate = 127, OverHealSave = 128, ChargeTimeChangetoDamage = 129, TimingTriggerValueChange = 130,
        TargetGroupid = 131, FinalStatHp = 132, FinalStatHpHeal = 133, CycleUse = 134,
        DamageShareInstant = 135, TargetPartsId = 136, PartsHpChangeUIOff = 137, PartsHpChangeUIOn = 138,
        StatBonusRangeMax = 139, StatBonusRangeMin = 140, Uncoverable = 141, CallingMonster = 142,
        StatBurstSkillCoolTime = 143, ImmuneChangeCoolTimeUlti = 144, ShareDamageIncrease = 145, FullChargeHitDamageRepeat = 146,
        ChargeDamageChangeMaxStatAmmo = 147, StatSpotRadius = 148, PenetrationDamage = 149, DamageShareInstantUnable = 150,
        DamageFunctionUnable = 151, StatChargeTimeImmune = 152, AllStepBurstKeepStep = 153, AllStepBurstNextStep = 154,
        IncBarrierHp = 155, HealBarrier = 156, ExplosiveCircuitAccrueDamageRatio = 157, AtkReplaceMaxHpRate = 158,
        FixStatReloadTime = 159, DefIgnoreDamageRatio = 160, ChangeNormalDefIgnoreDamage = 161, BonusRangeDamageChange = 162,
        GivingHealVariation = 163, RemoveFunctionGroup = 164, NormalDamageRatioChange = 165, NormalStatCriticalDamage = 166,
        FunctionOverlapChange = 167, DurationValueChange = 168, DurationDamageRatio = 169, RepeatUseBurstStep = 170,
        PartsImmuneDamage = 171, BarrierDamage = 172, CurrentHpRatioDamage = 173, StatReloadBulletRatio = 174,
        ImmuneAttention = 175, ImmuneInstallBarrier = 176, ImmuneTaunt = 177, FullCountDamageRatio = 178,
        AddIncElementDmgType = 179, ChangeUseBurstSkill = 180, ChangeChangeBurstStep = 181, StickyProjectileExplosion = 182,
        StickyProjectileCollisionDamage = 183, ProjectileExplosionDamage = 184, StickyProjectileInstantExplosion = 185, MinusDebuffCount = 186,
        AtkBuffChange = 187, OutBonusRangeDamageChange = 188, InstantAllBurstDamage = 189, PlusInstantSkillTargetNum = 190,
        StatInstantSkillRange = 191, DamageFunctionTargetGroupId = 192, DamageFunctionValueChange = 193, DmgReductionExcludingBreakCol = 194,
        ChangeHurtFxExcludingBreakCol = 195, FocusAttack = 196, ImmediatelyBuffCheckImmune = 197, DurationBuffCheckImmune = 198,
        ImmediatelyDebuffCheckImmune = 199, DurationDebuffCheckImmune = 200, NoOverlapStatAmmo = 201, DurationDamage = 202,
        DefIgnoreSkillDamageInstant = 203, EmptyFunction = 204, DamageShareLowestPriority = 205, ForcedReload = 206,
        StatDefNoneBreakCol = 207, ChangeHealChargeValue = 208, FixStatChargeTime = 209, GrayScale = 210,
        ChangeMaxTargetingCount = 211, InstantSequentialAttackDamageRatio = 212, BarrierImmuneDamage = 213,
    }

    public enum TimingTriggerType
    {
        Unknown = -1, None = 0, OnStart = 1, OnShotRatio = 2,
        OnUseAmmo = 3, OnUseBurstSkill = 4, OnHitNumberOver = 5, OnFullChargeShot = 6,
        OnHurtRatio = 7, OnHurtCount = 8, OnFunctionBuffCheck = 9, OnFunctionDebuffCheck = 10,
        OnSquadHurtRatio = 11, OnSquadHurtCount = 12, OnCoverHurtRatio = 13, OnCoverHurtCount = 14,
        OnHpRatioUnder = 15, OnHpRatioUp = 16, OnAmmoRatioUnder = 17, OnAmmoRatioUp = 18,
        OnShooterCount = 19, OnKillRatio = 20, OnFunctionOn = 21, OnEnterBurstStep = 22,
        OnFullCount = 23, OnCoverDestroyRatio = 24, OnBurstSkillStep = 25, OnSpawnMonster = 26,
        OnFullChargeHit = 27, OnAttackRatio = 28, OnLastShotHit = 29, OnSkillUse = 30,
        OnHitNum = 31, OnFullBurstTimeOverRatio = 32, OnPartsHitNum = 33, OnPartsHitRatio = 34,
        OnPartsHitNumOnce = 35, OnPartsHitRatioOnce = 36, OnLastAmmoUse = 37, OnSpawnTarget = 38,
        OnHitRatio = 39, OnDead = 40, OnTeamHpRatioUnder = 41, OnResurrection = 42,
        OnEndFullBurst = 43, OnNikkeDead = 44, OnCriticalHitNum = 45, OnCriticalHitRatio = 46,
        OnCriticalHitNumOnce = 47, OnCriticalHitRatioOnce = 48, OnHealedBy = 49, OnMonsterDead = 50,
        OnFullCharge = 51, OnInstallBarrier = 52, OnHealCover = 53, OnInstantDeath = 54,
        OnCoreHitRatioOnce = 55, OnCoreHitNumOnce = 56, OnCoreHitRatio = 57, OnCoreHitNum = 58,
        OnFullChargeNum = 59, OnFullChargeShotNum = 60, OnFullChargeHitNum = 61, OnSummonMonster = 62,
        OnAfterTimeSec = 63, OnPelletHitNum = 64, OnPelletHitPerShot = 65, OnPartsBrokenNum = 66,
        OnCheckTime = 67, OnPartsHurtCount = 68, OnPartsHurtRatio = 69, OnUserPartsDestroy = 70,
        OnEnemyDead = 71, OnBurstSkillUseNum = 72, OnFullChargePartsHitNum = 73, OnKeepFullcharge = 74,
        OnEndReload = 75, OnTeamHpRatioUp = 76, OnHurtDecoyNum = 77, OnFunctionOff = 78,
        OnHitNumExceptCore = 79, OnShotNotFullCharge = 80, OnKeepFullChargeShotUnder = 81, OnSpawnEnemy = 82,
        OnUseTeamAmmo = 83, OnPelletCriticalHitNum = 84, OnSpawnMonsterExcludeNoneType = 85, OnFunctionDamageCriticalHit = 86,
        OnFullChargeBonusRangeHitNum = 87, OnKeepFullChargeShot = 88, OnDeadComplete = 89, OnFullChargeCoreHitNum = 90,
    }

    public enum StatusTriggerType
    {
        Unknown = -1, None = 0, IsAmmoRatioUnder = 1, IsAmmoRatioUp = 2,
        IsAmmoCount = 3, IsAmmoCountUnder = 4, IsAmmoCountUp = 5, IsShooterCount = 6,
        IsShooterUnder = 7, IsShooterUp = 8, IsSameSqaudCount = 9, IsSameSqaudUnder = 10,
        IsSameSqaudUp = 11, IsHpRatioUnder = 12, IsHpRatioUp = 13, IsStun = 14,
        IsFunctionBuffCheck = 15, IsFunctionDebuffCheck = 16, IsForcedStop = 17, IsFunctionOn = 18,
        IsFullCount = 19, IsFunctionCount = 20, IsBurstStepState = 21, AlwaysRecursive = 22,
        IsUseAmmo = 23, IsPhase = 24, IsPhaseUp = 25, IsPhaseUnder = 26,
        IsBurstSkillStep = 27, IsCheckMonster = 28, IsCover = 29, IsSearchElementId = 30,
        IsWeaponType = 31, IsClassType = 32, IsCheckTarget = 33, IsCheckDebuff = 34,
        IsHaveDecoy = 35, IsFullCharge = 36, IsHaveBarrier = 37, IsBurstMember = 38,
        IsNotBurstMember = 39, IsHighHpValue = 40, IsNotHaveBarrier = 41, IsExplosiveCircuitOff = 42,
        IsAlive = 43, IsHighMaxHpValue = 44, IsFunctionOff = 45, IsCheckFunctionOverlapUp = 46,
        IsCheckPartsId = 47, IsCheckPosition = 48, IsCheckMonsterType = 49, IsCheckTeamBurstNextStep = 50,
        IsNotCheckTeamBurstNextStep = 51, IsCharacter = 52, IsFunctionTypeOffCheck = 53, IsCheckEnemyNikke = 54,
        IsBurstStepCheck = 55, IsCheckMonsterExcludeNoneType = 56, IsNotHaveCover = 57, IsHaveCover = 58,
        IsSameSqaud = 59, IsCheckGradeUnder = 60, IsCheckCharacter = 61, IsCheckNotTarget = 62,
        IsCheckFunctionOverlap = 63, IsFirstBurstMember = 64, IsNotFirstBurstMember = 65, IsCharging = 66,
    }

    public enum StandardType
    {
        Unknown = -1, None = 0, User = 1, FunctionTarget = 2, TriggerTarget = 3,
    }

    public enum FunctionTargetType
    {
        Unknown = -1, None = 0, Self = 1, AllCharacter = 2, AllMonster = 3, Target = 4,
        UserCover = 5, TargetCover = 6, AllCharacterCover = 7,
    }

    public enum DurationType
    {
        Unknown = -1, None = 0, TimeSec = 1, Shots = 2,
        Battles = 3, Hits = 4, SkillShots = 5, TimeSecBattles = 6,
        OnStun = 7, OnRemoveFunction = 8, Hits_Ver2 = 9, TimeSec_Ver2 = 10,
        TimeSec_Ver3 = 11, ReloadAllAmmoCount = 12, UncoverableCount = 13, ChangeWeaponUseCount = 14,
    }

    public enum ValueType
    {
        Unknown = -1, None = 0, Integer = 1, Percent = 2,
    }

    public enum BuffType
    {
        Unknown = -1, Buff = 0, DeBuff = 1, Etc = 2, BuffEtc = 3, DebuffEtc = 4,
    }

}
