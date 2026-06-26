using Nikke.Simulator.Core.Data.Constants;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Stats;
using System;
using System.Collections.Generic;
using System.Linq;

namespace Nikke.Simulator.Core.Entities
{
    public class Nikke
    {
        // --- [UI 표시 부분 정보] ---
        public string Name { get; private set; }
        public string IconUrl { get; private set; }
        public int CombatPower { get; private set; }
        public string Manufacturer { get; private set; }
        public string Element { get; private set; }
        public string WeaponType { get; private set; }
        public string Class { get; private set; }

        // --- [레벨/등급 정보] ---
        public int Level { get; private set; }
        public int Grade { get; private set; }
        public int Core { get; private set; }
        public int BondLevel { get; private set; }
        public int FavoriteItemLv { get; private set; }

        // 원본 데이터 보관 (방어용)
        private readonly CharacterDto _originDto;
        private readonly GlobalStateDto _globalState; // 게임 콘솔 정보 저장용

        // [B3] 파이프라인이 비어 있거나 slug 매핑 miss 등으로 null이 들어와도
        // LINQ/리플렉션이 터지지 않도록 생성자에서 한 번 정규화해 보관.
        // InitializeFinalStats 는 이 필드만 참조한다.
        private readonly IReadOnlyList<OverloadOptionDto> _overloadStats;
        private readonly EquipmentPartsDto _equipments;

        // --- [정적 스테이터스: 평타 정보] ---
        public double BasicAtkMultiplier { get; private set; }
        public double BasicAtkCoreHitBonus { get; private set; }
        public double BasicAtkChargeTime { get; private set; }
        public double BasicAtkChargeDamage { get; private set; }

        // --- [최종 기초 스탯] ---
        public double FinalBaseAtk { get; private set; }
        public double FinalBaseHP { get; private set; }
        public double FinalBaseDef { get; private set; }
        public double FinalBaseMaxAmmo { get; private set; }

        // --- [H3] OL 전투 modifier (combat-axis OL 옵션 사전집계) ---
        // InitializeFinalStats 말미에서 val_type 정규화 후 누적.
        // BuildAttackContext 가 이 값들을 매 tick struct 에 주입한다.
        private double _olCritRateBonus;   // StatCritical → ctx.BaseCritRate 에 가산
        private double _olCritDmgBonus;    // StatCriticalDamage → ctx.SumCritDmg 에 가산
        private double _olChargeDmgAdd;    // StatChargeDamage → ctx.SumChargeDmgAdd 에 가산 (차지무기만 의미)
        private double _olElementDmgBonus; // IncElementDmg → ctx.SumStrongElem 에 가산 (우월코드 조건부 활성, 여기선 상시 가산)

        public CubeStatDto EquippedCube { get; private set; }

        public Nikke(CharacterDto dto, GlobalStateDto globalState)
        {
            _originDto = dto ?? throw new ArgumentNullException(nameof(dto));
            _globalState = globalState ?? new GlobalStateDto { consoles = new Dictionary<string, int>() };

            // [B3] 필수 구조체 — null이면 시뮬 불가, 즉시 throw.
            if (dto.StaticInfo == null)
                throw new ArgumentException(
                    $"CharacterDto.static is null (name_code={dto.name_code ?? "?"}). " +
                    "Prydwen 매핑 누락이나 merged_db 손상 가능성.",
                    nameof(dto));
            if (dto.user == null)
                throw new ArgumentException(
                    $"CharacterDto.user is null (name_code={dto.name_code ?? "?"}). " +
                    "user_state_clean.json 생성 단계 점검 필요.",
                    nameof(dto));

            // [B3] 빈 값으로 정규화해도 의미 보존되는 컬렉션/자식 DTO
            _overloadStats = dto.user.overload_stats ?? new List<OverloadOptionDto>();
            _equipments = dto.user.equipments ?? new EquipmentPartsDto();

            // [1] 기본 정보 세팅
            Name = dto.StaticInfo.name;
            IconUrl = dto.StaticInfo.iconUrl;
            CombatPower = dto.user.combat;
            Manufacturer = dto.StaticInfo.manufacturer;
            Element = dto.StaticInfo.element;
            WeaponType = dto.StaticInfo.weapon;
            Class = dto.StaticInfo.character_class;

            // [2] 레벨 정보 세팅
            Level = dto.user.level;
            Grade = dto.user.grade;
            Core = dto.user.core;
            BondLevel = dto.user.bond_level;

            // [3] 애용품/보물품 특수 처리 (보물 캐릭은 자동으로 15레벨 고정)
            if (!string.IsNullOrEmpty(dto.slug) && dto.slug.Contains("treasure"))
                FavoriteItemLv = 15;
            else
                FavoriteItemLv = dto.user.favorite_item_lv;

            // [4] 평타(BasicAttack) 스테이터스 로드
            if (dto.StaticInfo.basicAttack != null)
            {
                BasicAtkMultiplier = dto.StaticInfo.basicAttack.multiplier;
                BasicAtkCoreHitBonus = dto.StaticInfo.basicAttack.coreHitBonus;
                BasicAtkChargeTime = dto.StaticInfo.basicAttack.chargeTime;
                BasicAtkChargeDamage = dto.StaticInfo.basicAttack.chargeDamage;
            }

            // [5] 스탯 초기화 (큐브 미장착 상태)
            InitializeFinalStats();
        }

        // [추가] 전투 연산 시점(AttackContext)에 참조될 큐브 특수 효과 (장착 시 갱신)
        public CubeEffectDto CurrentCubeEffect { get; private set; }

        /// <summary>
        /// [장착] 큐브를 교체하고 스탯 + 특수 전투 효과를 동시에 캐싱한다.
        /// </summary>
        /// <param name="cubeTid">장착할 큐브의 고유 ID (예: 1000313)</param>
        /// <param name="levelOverride">큐브 레벨 (기본값 15)</param>
        public void EquipCube(int cubeTid, int levelOverride = 15)
        {
            // 1. 큐브의 스탯을 가져옴 (내부에 1스킬 레벨 포함)
            EquippedCube = StatTable.GetCubeStat(levelOverride);

            // 2. 큐브 TID + 스킬 레벨로 '전투 연산 구조체' 가져옴
            CurrentCubeEffect = CubeSkillTable.GetSkillEffect(cubeTid, EquippedCube.SkillLevel);

            // 3. 재장전/탄약/피해증가 관련 효과는 AttackContext 단계에서 합산되지만,
            //    "체력 증가율(MaxHpBonusRate)"만은 전투 이전의 최종 기초 스탯
            //    (EffectiveNativeHP)에 반영되어야 하므로 여기서 전체 재계산을 트리거한다.
            InitializeFinalStats();
        }

        // [추가] 애용품의 특수 스킬 계수들을 담는 불변 객체
        public CollectionEffectDto CurrentCollectionEffect { get; private set; }

        private void InitializeFinalStats()
        {
            // [추가] 애용품/보물품 레벨 기반으로 O(1) 효과 객체 로드
            CurrentCollectionEffect = CollectionEffectTable.GetEffect(FavoriteItemLv);


            // [A] Core 보정까지 적용된 기초 스탯 (레벨 + 등급 + 콘솔 + 호감도 + 코어)
            var (coreHP, coreAtk, coreDef) = StatTable.GetCoreAppliedStats(
                Class, WeaponType, Manufacturer, Level, Grade, Core, BondLevel, _globalState.consoles);

            // [B] Consts 요소들 가져오기 (애용품, 장비, 큐브)
            var (collHP, collAtk, collDef) = StatTable.GetCollectionStats(FavoriteItemLv);
            var (equipHP, equipAtk, equipDef) = StatTable.GetEquipmentStats(_equipments);

            double cubeHP = EquippedCube?.HP ?? 0;
            double cubeAtk = EquippedCube?.Atk ?? 0;
            double cubeDef = EquippedCube?.Def ?? 0;

            // [H1] 큐브 효과 중 % 증가치는 별도 버킷. 미장착 시 struct 기본값 0으로 안전.
            //  - MaxHpBonusRate (Vigor): EffectiveNativeHP에 곱산으로 반영
            //    → OL의 StatMaxHP 퍼센트는 이 증가된 native 위에 올라탄다.
            //  (AmmoChargeRate, PartsDamageBonus 등 전투 중 효과는 AttackContext 단계에서 소비)
            double cubeHpRate = CurrentCubeEffect.MaxHpBonusRate;

            // [H2] 콜렉션 MG 전용 MaxAmmoIncreaseRate — MG 캐만 native ammo에 곱산.
            // 그 외 무기는 0.
            double collMaxAmmoRate = (WeaponType == "Machine Gun")
                ? CurrentCollectionEffect.MaxAmmoIncreaseRate : 0.0;

            // [C] Consts 합산 (Effective Native Stat: baseAtk = atk_core + consts)
            double effectiveNativeHP = (coreHP + collHP + equipHP + cubeHP) * (1.0 + cubeHpRate);
            double effectiveNativeAtk = coreAtk + collAtk + equipAtk + cubeAtk;
            double effectiveNativeDef = coreDef + collDef + equipDef + cubeDef;
            double nativeAmmo = _originDto.StaticInfo.ammoCapacity * (1.0 + collMaxAmmoRate);

            // [D] 오버로드 프로세서 적용 (니케식 정밀 소수점 연산)
            FinalBaseAtk = OverloadProcessor.CalculateFinalBaseStat(
                effectiveNativeAtk,
                _overloadStats.Where(o => o.type == "StatAtk").Select(o => o.value),
                0, 0);

            FinalBaseHP = OverloadProcessor.CalculateFinalBaseStat(
                effectiveNativeHP,
                _overloadStats.Where(o => o.type == "StatMaxHP").Select(o => o.value),
                0, 0);

            FinalBaseDef = OverloadProcessor.CalculateFinalBaseStat(
                effectiveNativeDef,
                _overloadStats.Where(o => o.type == "StatDef").Select(o => o.value),
                0, 0);

            // [H3] OL 장탄수 옵션의 실제 JSON type 은 "StatAmmoLoad" (과거 "StatMaxAmmo" 는 dead code 였음).
            FinalBaseMaxAmmo = OverloadProcessor.CalculateFinalBaseStat(
                nativeAmmo,
                _overloadStats.Where(o => o.type == "StatAmmoLoad").Select(o => o.value),
                0, 0);

            // [H3] OL 전투축 옵션 사전집계.
            // ETL 은 val_type="Percent" 인 경우에만 value 를 /10000 스케일하여 저장한다.
            // val_type="Integer" 는 원시값이 그대로 들어오므로 C# 측에서 /10000 정규화가 필요.
            //   예) StatCriticalDamage=1644(Integer)  → 0.1644
            //       StatAtk=0.1181(Percent)          → 0.1181 (이미 스케일됨)
            double Normalize(OverloadOptionDto o)
                => (o.val_type == "Integer") ? o.value / 10000.0 : o.value;

            _olCritRateBonus = _overloadStats
                .Where(o => o.type == "StatCritical").Sum(Normalize);
            _olCritDmgBonus = _overloadStats
                .Where(o => o.type == "StatCriticalDamage").Sum(Normalize);
            _olChargeDmgAdd = _overloadStats
                .Where(o => o.type == "StatChargeDamage").Sum(Normalize);
            _olElementDmgBonus = _overloadStats
                .Where(o => o.type == "IncElementDmg").Sum(Normalize);
        }

        /// <summary>
        /// [H2] 캐릭터 고정 modifier(큐브 + 콜렉션 무기별 효과)가 미리 주입된
        /// AttackContext 를 반환한다. 시뮬레이터 루프는 이 struct 에 매 tick
        /// 가변 버프/디버프/크리 여부 등을 추가하여 StatCalculator.CalculateDamage 에 넘긴다.
        ///
        /// 여기서 주입되는 것:
        ///  - FinalBaseAtk / FinalBaseDef
        ///  - 큐브 고정 전투 효과 (Parts/Pierce 대미지 보너스 등)
        ///  - 콜렉션 무기별 고정 보너스 (Core/Charge/Normal 등)
        ///  - 무기 타입에 따른 ChargeDmgBase 기본 배율
        ///  - [H3] OL 전투축 — StatCritical / StatCriticalDamage /
        ///         StatChargeDamage / IncElementDmg (val_type 정규화 완료)
        ///  - [A2] 큐브 TrueDamageBonus → ctx.SumTrueDmgBuff (IsTrueDamage 시 B3 조건부 가산)
        ///
        /// 아직 반영하지 않는 것 (TODO):
        ///  - AmmoChargeRate / ReloadTimeReduction (시간 축, 로테이션 시뮬에서 소비)
        ///  - DefIncreaseRate / DamageTakenReduction / CoverHpIncreaseRate (자기 생존 — DPS 스코프 외)
        /// </summary>
        public AttackContext BuildAttackContext()
        {
            var ctx = new AttackContext(FinalBaseAtk, FinalBaseDef);

            // [계수 W] 평타 무기 계수를 P 에 접기 위해 주입 (StatCalculator 가 P=깡뎀×W×C 로 사용).
            //   기존 공식은 W 를 누락했었음. 스킬 누크 계수는 런타임이 별도 오버라이드 (gap#5).
            ctx.SkillMultiplier = (BasicAtkMultiplier > 0) ? BasicAtkMultiplier : 1.0;

            var cube = CurrentCubeEffect;
            var coll = CurrentCollectionEffect;

            // [H3] OL 전투축 주입 — BaseCritRate/SumCritDmg/SumChargeDmgAdd/SumStrongElem
            // InitializeFinalStats 에서 val_type 정규화까지 끝난 값을 그대로 가산한다.
            ctx.BaseCritRate += _olCritRateBonus;
            ctx.SumCritDmg += _olCritDmgBonus;
            ctx.SumChargeDmgAdd += _olChargeDmgAdd;
            ctx.SumStrongElem += _olElementDmgBonus;

            // [H2] 큐브 고정 전투 효과
            ctx.SumPartsDmg += cube.PartsDamageBonus;
            ctx.SumPierceDmg += cube.PierceDamageBonus;
            // Parts/Pierce 는 IsPartsHit/IsPierceHit 플래그가 true 일 때만 B3 에 가산됨 (StatCalculator 참조)

            // [A2] 큐브 트루 대미지 증가 — IsTrueDamage 플래그가 true 일 때만 B3 에 가산됨
            ctx.SumTrueDmgBuff += cube.TrueDamageBonus;

            // [H2] 콜렉션 무기별 고정 효과 — 해당 무기에만 적용
            switch (WeaponType)
            {
                case "Assault Rifle":
                    ctx.SumCoreHitBuff += coll.CoreDamageBonus;
                    break;
                case "Sniper Rifle":
                case "Rocket Launcher":
                    ctx.SumChargeDmgMult += coll.ChargeDamageMultiplier;
                    // 차지 무기 기본 배율은 JSON (basicAttack.chargeDamage) per-character.
                    // 대부분 2.5 (Full Charge 250%), 일부 3.5 (350%) 등 값이 다양.
                    // 환각 하드코딩 (2.5) 제거, BasicAtkChargeDamage 로 교체 (2026-04-23).
                    ctx.ChargeDmgBase = BasicAtkChargeDamage;
                    break;
                case "Submachine Gun":
                case "Shotgun":
                    ctx.SumAttackDmg += coll.NormalAttackMultiplier;
                    break;
                case "Machine Gun":
                    // MaxAmmo는 InitializeFinalStats 에서 FinalBaseMaxAmmo 로 이미 반영됨
                    break;
                // default: 알 수 없는 무기 → 기본값 유지 (ChargeDmgBase=1.0)
            }

            return ctx;
        }
    }
}
