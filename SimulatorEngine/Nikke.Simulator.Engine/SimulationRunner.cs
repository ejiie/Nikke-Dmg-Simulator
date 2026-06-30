using System;
using System.Collections.Generic;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine.Combat;
using Nikke.Simulator.Engine.Metrics;
using Nikke.Simulator.Engine.Targets;

namespace Nikke.Simulator.Engine
{
    /// <summary>
    /// 엔진 진입점 (WORK_BREAKDOWN K0 / ENGINE_GUIDE §0). 팀 1개를 타겟에 대고 1회 run 굴려
    /// **총대미지 표본 1개**(<see cref="RunResult"/>)를 낸다. Evaluator(Tier 3)가 N run → 분포.
    ///
    /// 임플: K8 (단일캐릭 M1+M2) → K9+ (팀). SimClock+FiringModel+SkillRuntime+BuffStore+
    /// MetricsCollector 를 배선. K0 = 동결 시그니처 스텁.
    /// </summary>
    public static class SimulationRunner
    {
        /// <summary>
        /// 팀 1개(최대 5 Combatant)를 <paramref name="target"/> 에 대고 <paramref name="durationSec"/> 초 동안
        /// 굴린다. 크리/확률은 <paramref name="rng"/> 로 샘플링(고정 시드 금지 — N run 수렴 검증).
        /// </summary>
        /// <param name="team">한 팀(같은 run 안에서 1팀). DESIGN: sim 1 run = 팀 1개.</param>
        /// <param name="target">대미지 대상 (Dummy/Boss).</param>
        /// <param name="rng">크리/확률 RNG (<see cref="IRandomSource"/>).</param>
        /// <param name="durationSec">시뮬 길이(초).</param>
        public static RunResult RunOnce(
            IReadOnlyList<Combatant> team,
            ITarget target,
            IRandomSource rng,
            double durationSec)
            => throw new NotImplementedException("엔진 루프 배선 대기 (Wave2 K8). K0 동결 계약 스텁.");
    }
}
