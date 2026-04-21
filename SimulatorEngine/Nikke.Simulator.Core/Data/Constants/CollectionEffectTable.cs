// --- [파일 2: Data/Constants/CollectionEffectTable.cs] ---
// 역할: StatTable.cs가 CSV를 읽을 때, 소장품 특수 효과 데이터를 넘겨받아 보관하는 전용 저장소

using System.Collections.Generic;

namespace Nikke.Simulator.Core.Data.Constants
{
    public static class CollectionEffectTable
    {
        // Key: 소장품 레벨 (1~15 등)
        private static readonly Dictionary<int, CollectionEffectDto> _effects = new Dictionary<int, CollectionEffectDto>();

        /// <summary>
        /// StatTable.cs의 파서가 추출한 배율 데이터를 저장소에 등록 (초기화 1회용)
        /// </summary>
        public static void RegisterEffect(int level, CollectionEffectDto effectDto)
        {
            _effects[level] = effectDto;
        }

        /// <summary>
        /// 전투 연산 시(AttackContext 등) 특정 무기와 레벨에 맞는 특수 효과만 반환
        /// </summary>
        public static CollectionEffectDto GetEffect(int level)
        {
            return _effects.TryGetValue(level, out var effect) ? effect : new CollectionEffectDto();
        }
    }
}