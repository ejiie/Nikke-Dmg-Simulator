// --- [파일 2: Data/Constants/CubeSkillTable.cs] ---
using System.Collections.Generic;
using System.Collections.ObjectModel;

namespace Nikke.Simulator.Core.Data.Constants
{
    /// <summary>
    /// 하모니 큐브의 TID와 1스킬 레벨을 기반으로 실제 적용되는 전투 배율을 반환하는 정적 테이블
    /// </summary>
    public static class CubeSkillTable
    {
        // 큐브 고유 TID 상수 정의 (실제 게임 데이터의 TID 매핑)
        public const int CubeResilience = 1000313;   // 재장전 (렐릭 베어)
        public const int CubeBastion = 1000314;      // 탄환 충전 (택티컬 베어)
        public const int CubePartsDamage = 1000318;  // 파츠 대미지 (예시 TID)
        public const int CubePierceDamage = 1000319; // 관통 대미지 (예시 TID)
        public const int CubeTrueDamage = 1000320;   // 트루 대미지 (예시 TID)
        public const int CubeVigor = 1000321;        // 체력 증가 (예시 TID)

        // 이중 딕셔너리: Dictionary<CubeTID, Dictionary<SkillLevel, CubeEffectDto>>
        private static readonly Dictionary<int, IReadOnlyDictionary<int, CubeEffectDto>> _internalData =
            new Dictionary<int, IReadOnlyDictionary<int, CubeEffectDto>>
        {
            {
                CubeResilience,
                new ReadOnlyDictionary<int, CubeEffectDto>(new Dictionary<int, CubeEffectDto>
                {
                    { 1, new CubeEffectDto(reload: 0.1189) },
                    { 2, new CubeEffectDto(reload: 0.1556) },
                    { 3, new CubeEffectDto(reload: 0.1989) },
                    { 4, new CubeEffectDto(reload: 0.2312) },
                    { 5, new CubeEffectDto(reload: 0.2644) },
                    { 6, new CubeEffectDto(reload: 0.2815) },
                    { 7, new CubeEffectDto(reload: 0.2988) }
                })
            },
            {
                CubeBastion,
                new ReadOnlyDictionary<int, CubeEffectDto>(new Dictionary<int, CubeEffectDto>
                {
                    { 1, new CubeEffectDto(ammoCharge: 0.10) },
                    { 2, new CubeEffectDto(ammoCharge: 0.12) },
                    { 3, new CubeEffectDto(ammoCharge: 0.15) },
                    { 4, new CubeEffectDto(ammoCharge: 0.18) },
                    { 5, new CubeEffectDto(ammoCharge: 0.21) },
                    { 6, new CubeEffectDto(ammoCharge: 0.25) },
                    { 7, new CubeEffectDto(ammoCharge: 0.29) }
                })
            },
            {
                CubePartsDamage,
                new ReadOnlyDictionary<int, CubeEffectDto>(new Dictionary<int, CubeEffectDto>
                {
                    // 파츠 대미지 증가율 (예시 수치, 실제 CSV 수치로 교체 가능)
                    { 1, new CubeEffectDto(partsDamage: 0.05) },
                    { 4, new CubeEffectDto(partsDamage: 0.10) },
                    { 7, new CubeEffectDto(partsDamage: 0.15) }
                })
            },
            {
                CubePierceDamage,
                new ReadOnlyDictionary<int, CubeEffectDto>(new Dictionary<int, CubeEffectDto>
                {
                    // 관통 대미지 증가율
                    { 1, new CubeEffectDto(pierceDamage: 0.04) },
                    { 4, new CubeEffectDto(pierceDamage: 0.08) },
                    { 7, new CubeEffectDto(pierceDamage: 0.12) }
                })
            },
            {
                CubeTrueDamage,
                new ReadOnlyDictionary<int, CubeEffectDto>(new Dictionary<int, CubeEffectDto>
                {
                    // 트루 대미지 증가율
                    { 1, new CubeEffectDto(trueDamage: 0.03) },
                    { 4, new CubeEffectDto(trueDamage: 0.06) },
                    { 7, new CubeEffectDto(trueDamage: 0.09) }
                })
            },
            {
                CubeVigor,
                new ReadOnlyDictionary<int, CubeEffectDto>(new Dictionary<int, CubeEffectDto>
                {
                    // 체력 증가율 (%)
                    { 1, new CubeEffectDto(maxHp: 0.05) },
                    { 4, new CubeEffectDto(maxHp: 0.10) },
                    { 7, new CubeEffectDto(maxHp: 0.15) }
                })
            }
        };

        public static IReadOnlyDictionary<int, IReadOnlyDictionary<int, CubeEffectDto>> Data =>
            new ReadOnlyDictionary<int, IReadOnlyDictionary<int, CubeEffectDto>>(_internalData);

        /// <summary>
        /// 큐브 장착 시 호출되어, TID와 스킬 레벨에 해당하는 실제 전투 배율 구조체를 반환합니다.
        /// </summary>
        public static CubeEffectDto GetSkillEffect(int cubeTid, int skillLevel)
        {
            if (_internalData.TryGetValue(cubeTid, out var levels) && levels.TryGetValue(skillLevel, out var effect))
            {
                return effect;
            }

            // 매칭 실패 시 더미(0) 구조체 반환
            return new CubeEffectDto();
        }
    }
}