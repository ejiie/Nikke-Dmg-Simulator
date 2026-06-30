using Nikke.Simulator.Core.Combat;
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

        // 큐브/소장품 공식 특수효과 (enum/dict, 값=분수). EquipCube / InitializeFinalStats 에서 채움.
        private Dictionary<EffectType, double> _cubeEffects = new();
        private Dictionary<EffectType, double> _collectionEffects = new();

        private double EffSum(EffectType t)
            => (_cubeEffects.TryGetValue(t, out var a) ? a : 0.0)
             + (_collectionEffects.TryGetValue(t, out var b) ? b : 0.0);

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
                // [W 단위 정규화 — 단일 지점] 데이터 multiplier 는 **percent-number**
                // (roledata_cleaner.py: damage/100 → 예 13.65 = "13.65% ATK").
                // 공식 W 는 **fraction** (DESIGN §3, golden 4.995 = 499.5%/100) 이므로
                // 데이터→엔티티 경계에서 /100 정규화한다. 이 한 곳이 W 단위 정규화의 단일 지점.
                //   (정규화 위치 결정 2026-06-30: roledata_cleaner(저장) 대신 여기(주입측) — 엔진 로컬,
                //    ETL 재실행/merged DB 재생성 불필요, 데이터 DTO 는 raw 유지. DESIGN §6 항목 확정.)
                // ※ chargeDamage 는 이미 fraction(cleaner /10000)이라 변환 안 함.
                BasicAtkMultiplier = dto.StaticInfo.basicAttack.multiplier / 100.0;
                BasicAtkCoreHitBonus = dto.StaticInfo.basicAttack.coreHitBonus;
                BasicAtkChargeTime = dto.StaticInfo.basicAttack.chargeTime;
                BasicAtkChargeDamage = dto.StaticInfo.basicAttack.chargeDamage;
            }

            // [5] 큐브 자동 장착 (유저데이터에 cube tid 있으면) — 내부에서 InitializeFinalStats 호출.
            //     없으면 큐브 미장착 상태로 초기화.
            if (dto.user.cube != null && dto.user.cube.tid > 0)
                EquipCube(dto.user.cube.tid, dto.user.cube.level);
            else
                InitializeFinalStats();
        }

        /// <summary>
        /// [장착] 큐브 base 스탯 + 공식 특수효과를 캐싱하고 최종 스탯을 재계산한다.
        /// </summary>
        /// <param name="cubeTid">큐브 고유 ID (예: 1000308=Vigor)</param>
        /// <param name="levelOverride">큐브 레벨 (기본값 15)</param>
        public void EquipCube(int cubeTid, int levelOverride = 15)
        {
            EquippedCube = StatTable.GetCubeStat(levelOverride);              // base ATK/HP/DEF
            _cubeEffects = EffectTable.GetCubeEffects(cubeTid, levelOverride); // 공식 특수효과 (enum/dict)
            InitializeFinalStats();
        }

        private void InitializeFinalStats()
        {
            // [A] Core 보정까지 적용된 기초 스탯 (레벨 + 등급 + 콘솔 + 호감도 + 코어)
            var (coreHP, coreAtk, coreDef) = StatCalculator.GetCoreAppliedStats(
                Class, WeaponType, Manufacturer, Level, Grade, Core, BondLevel, _globalState.consoles);

            // [B] Consts 요소들 가져오기 (애용품, 장비, 큐브)
            var (collHP, collAtk, collDef) = StatTable.GetCollectionStats(FavoriteItemLv);
            var (equipHP, equipAtk, equipDef) = StatCalculator.GetEquipmentStats(Class, Manufacturer, _equipments);

            double cubeHP = EquippedCube?.HP ?? 0;
            double cubeAtk = EquippedCube?.Atk ?? 0;
            double cubeDef = EquippedCube?.Def ?? 0;

            // [H1] 큐브/소장품 공식 특수효과 중 **기초스탯 rate 버프**: stat × (1 + Σrate).
            //  - MaxHp(Vigor), Def(Endurance), MaxAmmo(Wingman/콜렉션) — 큐브+콜렉션 합산.
            //  (ElemAdv/Charge/Parts 등 대미지 효과는 BuildAttackContext 에서 소비.
            //   ReloadSpeed/DamageTaken 등 타이밍·생존 효과는 미소비.)
            _collectionEffects = EffectTable.GetCollectionEffects(WeaponType, FavoriteItemLv);
            double hpRate = EffSum(EffectType.MaxHp);
            double defRate = EffSum(EffectType.Def);
            double ammoRate = EffSum(EffectType.MaxAmmo);

            // [C] Consts 합산 (Effective Native Stat: baseAtk = atk_core + consts)
            double effectiveNativeHP = (coreHP + collHP + equipHP + cubeHP) * (1.0 + hpRate);
            double effectiveNativeAtk = coreAtk + collAtk + equipAtk + cubeAtk;
            double effectiveNativeDef = (coreDef + collDef + equipDef + cubeDef) * (1.0 + defRate);
            double nativeAmmo = _originDto.StaticInfo.ammoCapacity * (1.0 + ammoRate);

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
        /// 가변 버프/디버프/크리 여부 등을 추가하여 DamageCalculator.CalculateDamage 에 넘긴다.
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

            // [계수 W] 평타 무기 계수를 P 에 접기 위해 주입 (DamageCalculator 가 P=깡뎀×W×C 로 사용).
            //   BasicAtkMultiplier 은 생성자 [4] 에서 이미 /100 정규화된 **fraction** (예 0.1365).
            //   스킬 누크 계수는 런타임이 별도 오버라이드 (gap#5).
            ctx.SkillMultiplier = (BasicAtkMultiplier > 0) ? BasicAtkMultiplier : 1.0;

            // [H3] OL 전투축 주입 — InitializeFinalStats 에서 val_type 정규화까지 끝난 값을 가산.
            ctx.BaseCritRate += _olCritRateBonus;
            ctx.SumCritDmg += _olCritDmgBonus;
            ctx.SumChargeDmgAdd += _olChargeDmgAdd;
            ctx.SumStrongElem += _olElementDmgBonus;

            // 차지 기본 배율 (per-character JSON; 비차지 무기 = 1.0)
            ctx.ChargeDmgBase = BasicAtkChargeDamage;

            // 큐브 + 소장품 공식 특수효과(enum/dict) → 대미지 브래킷.
            // 기초스탯(MaxHp/Def/MaxAmmo)은 InitializeFinalStats 에서, 타이밍·생존 효과는 미소비.
            RouteEffects(ref ctx, _cubeEffects);
            RouteEffects(ref ctx, _collectionEffects);

            return ctx;
        }

        /// <summary>특수효과(분수) → AttackContext 대미지 버킷. 의미 규칙: Docs/SKILL_DATA_BLABLALINK §4.1.
        /// Parts/Pierce/True 는 DamageCalculator 가 IsPartsHit/IsPierceHit/IsTrueDamage 플래그로 게이트.</summary>
        private static void RouteEffects(ref AttackContext ctx, Dictionary<EffectType, double> eff)
        {
            foreach (var kv in eff)
            {
                double v = kv.Value;
                switch (kv.Key)
                {
                    case EffectType.ElementAdvantageDamage: ctx.SumStrongElem += v; break;   // B5
                    case EffectType.CoreDamage: ctx.SumCoreHitBuff += v; break;              // B2
                    case EffectType.PartsDamage: ctx.SumPartsDmg += v; break;                // B3
                    case EffectType.PierceDamage: ctx.SumPierceDmg += v; break;              // B3
                    case EffectType.TrueDamage: ctx.SumTrueDmgBuff += v; break;              // B3
                    case EffectType.ChargeDamage: ctx.SumChargeDmgAdd += v; break;           // charge add
                    case EffectType.ChargeDamageMultiplier: ctx.SumChargeDmgMult += v; break; // charge mult
                    case EffectType.NormalAttackMultiplier: ctx.SkillMultiplier *= (1.0 + v); break; // W
                    // MaxHp/Def/MaxAmmo → 기초스탯(InitializeFinalStats), 그 외 타이밍/생존 → 미소비
                }
            }
        }
    }
}
