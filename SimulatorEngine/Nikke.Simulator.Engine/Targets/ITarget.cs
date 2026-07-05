using Nikke.Simulator.Core.Combat;

namespace Nikke.Simulator.Engine.Targets
{
    /// <summary>
    /// 대미지 대상 추상화 (ENGINE_GUIDE §5 / DESIGN §1). 히트마다 <see cref="AttackContext"/> 의
    /// 타겟 의존 항목(DEF · ProperDistanceBonus · SumStrongElem(속성 상성) 등)을 채운다.
    ///
    /// 거리/명중 모델 연동(2026-07-02, 유실분 복구):
    ///   - <see cref="Distance"/> + 공격자 무기타입 → <c>Core.Combat.ProperDistanceTable</c> 로 적정거리 보너스.
    ///   - <see cref="CoreRadius"/>/<see cref="BodyRadius"/> → <c>Core.Combat.AccuracyModel</c> 로 코어힛/명중 확률.
    ///     (roledata 에 없는 타겟 지오메트리 = **설정 가능 상수**, 사용자 결정.)
    ///   - 속성 상성 판정 유틸(ElementAdvantage)은 **보류**(2026-07-02 사용자 결정) — 계약 의미는 유지,
    ///     구현체가 상성 미반영(SumStrongElem 무변경)일 수 있음.
    ///
    /// 임플: K5 <see cref="DummyTarget"/>(고정) → K11 <c>BossTarget</c>(데이터).
    /// </summary>
    public interface ITarget
    {
        /// <summary>대상 최종 방어력 (대미지 공식 P 의 effectiveDef).</summary>
        double FinalDef { get; }

        /// <summary>파츠(부위) 보유 여부 — parts_dmg 게이트 가능 여부.</summary>
        bool HasParts { get; }

        /// <summary>대상 속성 코드 (속성 상성 판정용; 예: "Fire").</summary>
        string Element { get; }

        /// <summary>공격자와의 거리 (roledata bonusrange 단위). 적정거리 판정 입력 (무기타입별 구간).</summary>
        double Distance { get; }

        /// <summary>코어(약점) 반지름 — 명중원 대비 코어힛 확률 산정용 (AccuracyModel). roledata 외 설정 상수.</summary>
        double CoreRadius { get; }

        /// <summary>몸체 반지름 — 명중원 대비 명중(빗맞음 아님) 확률 산정용. roledata 외 설정 상수.</summary>
        double BodyRadius { get; }

        /// <summary>보스 여부 (파츠/거리 등 보스 전용 규칙 게이트).</summary>
        bool IsBoss { get; }

        /// <summary>
        /// 이번 히트의 **타겟 상태 의존** 필드를 <paramref name="ctx"/> 에 채운다:
        /// FinalDef · SumStrongElem(속성 상성; 판정 유틸 보류 중) ·
        /// ProperDistanceBonus(<paramref name="attackerWeaponType"/> + Distance).
        /// 공격자 속성/무기타입을 받아 상성·적정거리를 판정.
        ///
        /// ※ 코어힛(IsCoreHit)·명중은 <b>발사 시점·RNG 의존</b>(연사 streak 으로 명중원이 수축)이라
        ///   여기서 안 채운다 — FiringModel(M1)이 <c>AccuracyModel.RollCoreHit/RollHit</c> 로 샘플링.
        /// </summary>
        void PopulateContext(ref AttackContext ctx, string attackerElement, string attackerWeaponType);
    }
}
