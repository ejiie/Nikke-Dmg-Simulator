using Nikke.Simulator.Core.Combat;

namespace Nikke.Simulator.Engine.Targets
{
    /// <summary>
    /// 대미지 대상 추상화 (ENGINE_GUIDE §5 / DESIGN §1). 히트마다 <see cref="AttackContext"/> 의
    /// 타겟 의존 항목(DEF · IsCoreHit/IsPartsHit · ProperDistanceBonus · SumStrongElem(속성 상성))을 채운다.
    ///
    /// 임플: K5 <c>DummyTarget</c>(고정) → K11 <c>BossTarget</c>(데이터). 이 인터페이스는 K0 동결 계약.
    /// </summary>
    public interface ITarget
    {
        /// <summary>대상 최종 방어력 (대미지 공식 P 의 effectiveDef).</summary>
        double FinalDef { get; }

        /// <summary>파츠(부위) 보유 여부 — parts_dmg 게이트 가능 여부.</summary>
        bool HasParts { get; }

        /// <summary>대상 속성 코드 (속성 상성 판정용; 예: "Fire").</summary>
        string Element { get; }

        /// <summary>적정 거리 안인지 (ProperDistanceBonus 0.3 적용 여부).</summary>
        bool InProperRange { get; }

        /// <summary>보스 여부 (파츠/거리 등 보스 전용 규칙 게이트).</summary>
        bool IsBoss { get; }

        /// <summary>
        /// 이번 히트의 타겟 의존 필드를 <paramref name="ctx"/> 에 채운다
        /// (FinalDef / IsCoreHit / IsPartsHit / ProperDistanceBonus / SumStrongElem 등).
        /// 공격자 속성은 <paramref name="attackerElement"/> 로 전달받아 상성을 판정.
        /// </summary>
        void PopulateContext(ref AttackContext ctx, string attackerElement);
    }
}
