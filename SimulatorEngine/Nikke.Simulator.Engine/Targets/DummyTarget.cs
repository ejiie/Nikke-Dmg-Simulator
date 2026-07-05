using Nikke.Simulator.Core.Combat;

namespace Nikke.Simulator.Engine.Targets
{
    /// <summary>
    /// 고정 파라미터 더미 타겟 (ENGINE_GUIDE M5 / K5). 엔진 검증·단일캐릭 슬라이스용.
    /// DEF/속성/거리/지오메트리를 생성 시 고정. BossTarget(K11) 이 같은 계약을 데이터로 구현.
    ///
    /// 거리/명중 모델을 **실제로 소비**:
    ///   - PopulateContext → ProperDistanceBonus(<see cref="ProperDistanceTable"/>).
    ///   - <see cref="CoreRadius"/>/<see cref="BodyRadius"/> 는 FiringModel 이 <see cref="AccuracyModel"/> 로 코어힛 샘플링 시 사용.
    ///   - 속성 상성(SumStrongElem) 판정은 **보류**(2026-07-02 사용자 결정, ElementAdvantage 통합 대기) — 미반영.
    /// </summary>
    public sealed class DummyTarget : ITarget
    {
        public double FinalDef { get; }
        public bool HasParts { get; }
        public string Element { get; }
        public double Distance { get; }
        public double CoreRadius { get; }
        public double BodyRadius { get; }
        public bool IsBoss { get; }

        /// <summary>
        /// 기본값 = 무속성(상성 없음)·거리 0·코어 없음 더미. 슬라이스별로 필요한 항목만 지정.
        /// </summary>
        /// <param name="finalDef">대상 DEF (effectiveDef).</param>
        /// <param name="element">대상 속성(상성 판정용; 판정 유틸 보류 중 — 현재 미소비). null/"" = 상성 없음.</param>
        /// <param name="distance">공격자와의 거리(roledata bonusrange 단위) — 적정거리 판정.</param>
        /// <param name="coreRadius">코어 반지름(명중원 대비 코어힛 확률). 0 = 코어 없음.</param>
        /// <param name="bodyRadius">몸체 반지름(명중 확률). 0 = 명중판정 생략(항상 명중 취급).</param>
        /// <param name="hasParts">파츠 보유.</param>
        /// <param name="isBoss">보스 여부.</param>
        public DummyTarget(
            double finalDef = 0.0,
            string element = null,
            double distance = 0.0,
            double coreRadius = 0.0,
            double bodyRadius = 0.0,
            bool hasParts = false,
            bool isBoss = false)
        {
            FinalDef = finalDef;
            Element = element ?? "";
            Distance = distance;
            CoreRadius = coreRadius;
            BodyRadius = bodyRadius;
            HasParts = hasParts;
            IsBoss = isBoss;
        }

        public void PopulateContext(ref AttackContext ctx, string attackerElement, string attackerWeaponType)
        {
            ctx.FinalDef = FinalDef;
            // 속성 상성(B5 기본 우월 +0.1) 판정 = 보류 (ElementAdvantage 통합 대기) — SumStrongElem 무변경.
            // OL/버프 IncElementDmg 는 BuildAttackContext 에서 이미 합산됨.
            // 적정거리 → B2 ProperDistanceBonus. 무기타입별 구간(공식 bonusrange 최빈값) + 이 타겟의 Distance.
            ctx.ProperDistanceBonus = ProperDistanceTable.GetBonus(attackerWeaponType, Distance);
        }
    }
}
