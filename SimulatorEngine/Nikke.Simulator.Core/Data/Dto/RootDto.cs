using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Nikke.Simulator.Core.Data.Dto
{
    /// <summary>
    /// JSON 전체를 감싸는 최상위 껍데기 DTO
    /// </summary>
    public class RootDto
    {
        // uid 는 거대 숫자 식별자라 JSON 에 문자열로 저장됨. 산술 안 하므로 string.
        public string uid { get; set; }

        public GlobalStateDto global_state { get; set; }

        // roster: key = name_code (numeric string, 예: "1010"). slug 아님.
        // 실제 캐릭터 slug 는 value.slug 에서 조회.
        public Dictionary<string, CharacterDto> roster { get; set; }
    }

    public class GlobalStateDto
    {
        public int synchro_level { get; set; }
        // [핵심 패치] 콘솔 O(1) 탐색 딕셔너리
        public Dictionary<string, int> consoles { get; set; }
    }

    public class CharacterDto
    {
        public string slug { get; set; }
        public string name_code { get; set; }

        // C# 예약어 'static' 회피 — JSON 키는 "static" 유지.
        [JsonPropertyName("static")]
        public CharacterStaticDto StaticInfo { get; set; }

        public CharacterUserDto user { get; set; }
    }

    public class CharacterStaticDto
    {
        public string name { get; set; }
        public string iconUrl { get; set; }
        public string element { get; set; }
        public string weapon { get; set; }
        [JsonPropertyName("class")]
        public string character_class { get; set; }
        public string burstType { get; set; }
        public string manufacturer { get; set; }
        public int ammoCapacity { get; set; }
        public double reloadTime { get; set; }

        public BasicAttackDto basicAttack { get; set; }

        // 무기 프로파일 (roledata_cleaner._weapon → db_merger passthrough). 발사속도/탄창/차지/
        // 명중원/버스트게이지/멀티펠릿. 구 데이터엔 없을 수 있어 nullable — WeaponProfile 이 안전 처리.
        // (위 string `weapon`(롱폼 무기타입)과 별개 — JSON 키 충돌 회피 위해 `weaponData`.)
        public WeaponDto weaponData { get; set; }

        // 스킬은 blablalink roledata 구조(skill1/skill2/burst dict). 스킬 런타임 미구현이라
        // 지금은 원본 JSON 그대로 보관(역직렬화 안 깨지게). 추후 전용 DTO 로 구조화.
        public JsonElement? skills { get; set; }

        // 스쿼드(동일 스쿼드 아군 조건 버프 스킬용). roledata squad.
        public string squad { get; set; }
        // 적정거리 보너스 범위(per-char). 사거리 안일 때 ProperDistanceBonus 적용 판정용(sim).
        public ProperRangeDto properRange { get; set; }
    }

    public class ProperRangeDto
    {
        public int? min { get; set; }
        public int? max { get; set; }
    }

    /// <summary>
    /// 무기 프로파일 DTO — blabla_roledata `shot`/top-level 의 정규화된 무기 데이터 (1:1 JSON 매핑).
    /// 단위는 ETL(`roledata_cleaner._weapon`)에서 정규화: fireRate=발/sec, *Sec=초, *Rate=분수,
    /// 명중원(accuracy)·버스트게이지(burst)는 raw 단위(스프레드 반지름 / 게이지 단위).
    /// (W 단위(raw 유지·주입측 정규화)와 달리 ETL 정규화 채택 — 필드 수가 많아 단일 docstring 로 관리.)
    /// </summary>
    public class WeaponDto
    {
        public string weaponType { get; set; }      // SG/SMG/AR/MG/SR/RL (단축코드)
        public bool isChargeWeapon { get; set; }

        // SR/RL 부류 판별 (ENGINE_GUIDE §5): UP=릴리즈 발사 / DOWN_Charge=only 풀차지 / DOWN=평사
        public string inputType { get; set; }
        public string fireType { get; set; }                 // Instant/Projectile* (발사 이벤트 타이밍)
        public double maintainFireStanceSec { get; set; }    // >0 = 복귀 없이 자세 유지(값=자체 후딜레이)
        public double upTypeFireTiming { get; set; }         // 투사체 발사 이벤트 시점 비율 (분수)
        public int spotProjectileSpeed { get; set; }

        // 발사속도 (발/sec). MG 는 spin-up: fireRate(시작)→endFireRate, 발당 fireRateRampPerShot 증가.
        public double fireRate { get; set; }
        public double endFireRate { get; set; }
        public double fireRateRampPerShot { get; set; }
        public double fireRateResetTimeSec { get; set; }

        // 발사 개시/종료 모션 딜레이 (초; 대부분 0.2 — in-game 캘리브레이션 대기)
        public double spotFirstDelaySec { get; set; }
        public double spotLastDelaySec { get; set; }

        // 탄창/재장전
        public int maxAmmo { get; set; }
        public double reloadTimeSec { get; set; }
        public double reloadBulletRate { get; set; }   // 1.0=전탄, 0.33=부분장전
        public int reloadStartAmmo { get; set; }

        // 차지 (SR/RL)
        public double chargeTimeSec { get; set; }
        public double fullChargeDamage { get; set; }   // SR 2.5 / RL 3.5 / 비차지 1.0

        // 멀티펠릿/투사체
        public int shotCount { get; set; }             // SG 펠릿 5~10
        public int muzzleCount { get; set; }
        public int penetration { get; set; }
        public int spotRadius { get; set; }
        public int spotExplosionRange { get; set; }
        public double coreDamageRate { get; set; }     // 2.0 (coreHitBonus = 이값 - 1)

        public WeaponAccuracyDto accuracy { get; set; }
        public WeaponBurstDto burst { get; set; }
    }

    /// <summary>명중원(spread 반지름) — manual + auto(조준) 2세트. AccuracyModel 이 코어힛/명중 확률로 소비.</summary>
    public class WeaponAccuracyDto
    {
        public double startCircle { get; set; }
        public double endCircle { get; set; }
        public double changePerShot { get; set; }
        public double changeSpeed { get; set; }
        public double autoStartCircle { get; set; }
        public double autoEndCircle { get; set; }
        public double autoChangePerShot { get; set; }
        public double autoChangeSpeed { get; set; }
    }

    /// <summary>버스트 게이지 — 발당 충전량(raw 단위) + 풀버스트 창 타이밍/스텝.</summary>
    public class WeaponBurstDto
    {
        public double energyPerShot { get; set; }
        public double targetEnergyPerShot { get; set; }
        public double fullChargeEnergy { get; set; }
        public double durationSec { get; set; }       // 풀버스트 창 (보통 10s)
        public double applyDelaySec { get; set; }
        public string useBurstSkill { get; set; }     // Step1/2/3/AllStep
        public string changeBurstStep { get; set; }
    }

    public class BasicAttackDto
    {
        public double multiplier { get; set; }
        public double coreHitBonus { get; set; }
        public double chargeTime { get; set; }
        public double chargeDamage { get; set; }
        public string rawText { get; set; }
    }

    public class SkillDto
    {
        public string skillId { get; set; }
        public string name { get; set; }
        public string slot { get; set; }
        public string type { get; set; }
        public int? cooldown { get; set; } // 패시브 스킬은 null이 들어오므로 Nullable 처리!
        public string descriptionLevel10 { get; set; }
    }

    public class CharacterUserDto
    {
        public int level { get; set; }
        public int grade { get; set; }
        public int core { get; set; }
        public int combat { get; set; }
        public int bond_level { get; set; }
        public int favorite_item_lv { get; set; }

        public SkillLevelsDto skills { get; set; }
        public EquipmentPartsDto equipments { get; set; }
        public CubeUserDto cube { get; set; }

        // 오버로드 DTO 재활용
        public List<OverloadOptionDto> overload_stats { get; set; }
    }

    // 장착 하모니 큐브 (Nikke 생성 시 자동 EquipCube).
    public class CubeUserDto
    {
        public int tid { get; set; }
        public int level { get; set; }
    }

    // [추가] 장비 DTO 클래스들
    public class EquipmentPartsDto
    {
        public EquipmentInfoDto head { get; set; }
        public EquipmentInfoDto torso { get; set; }
        public EquipmentInfoDto arm { get; set; }
        public EquipmentInfoDto leg { get; set; }
    }

    public class EquipmentInfoDto
    {
        public int tier { get; set; }
        public int level { get; set; }
        // 장비 제조사(0=없음, 1~7=기업). 캐릭 manufacturer 와 일치 시 +30% 보너스.
        public int corp { get; set; }
    }

    public class SkillLevelsDto
    {
        public int skill1 { get; set; }
        public int skill2 { get; set; }
        public int burst { get; set; }
    }
}