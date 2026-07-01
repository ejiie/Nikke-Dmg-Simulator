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

        // C# 예약어 'static'을 피하는 가키짱의 우아한 테크닉 ♥
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

        // 무기 타이밍/명중원/펠릿/버스트게이지 (roledata shot 블록 raw).
        // 구 merged DB(재생성 전)에는 없어 null 가능 — 소비측 null-safe 필수.
        public WeaponDataDto weaponData { get; set; }

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
    /// roledata shot 블록 raw 값 (roledata_cleaner._weapon_data). **단위 변환 없음** —
    /// 정규화는 소비측 단일 지점 (W 단위 정규화 결정과 동일 원칙, DESIGN §6).
    ///   rate* = 발/분 (/60 = 발/초; AR 720→12/s, SMG 1440→24/s 캘리브레이션 확정)
    ///   *Delay / rateOfFireResetTime = 1/100 초
    ///   accuracy*Scale = 명중원 스케일 (작을수록 조밀)
    /// </summary>
    public class WeaponDataDto
    {
        // 발사 속도 ramp (발/분). MG 만 start≠end: 60→4200, 발당 +100, 중단 reset 후 원복.
        public int? rateOfFire { get; set; }
        public int? endRateOfFire { get; set; }
        public int? rateOfFireChangePerShot { get; set; }
        public int? rateOfFireResetTime { get; set; }

        // 발사 전/후 모션 딜레이 (1/100초; 대부분 20)
        public int? spotFirstDelay { get; set; }
        public int? spotLastDelay { get; set; }

        // 명중원 (연사 streak 수축)
        public int? startAccuracyCircleScale { get; set; }
        public int? endAccuracyCircleScale { get; set; }
        public int? accuracyChangePerShot { get; set; }
        public int? accuracyChangeSpeed { get; set; }

        // 멀티펠릿 (SG shotCount=10 — 1클릭당 펠릿 수)
        public int? shotCount { get; set; }
        public int? muzzleCount { get; set; }

        // 버스트 게이지 충전 (raw; 게이지 총량 상수 미확정)
        public int? burstEnergyPerShot { get; set; }
        public int? targetBurstEnergyPerShot { get; set; }
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