using System;
using System.Collections.Generic;
using Nikke.Simulator.Core.Combat;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine.Clock;
using Nikke.Simulator.Engine.Combat;
using Nikke.Simulator.Engine.Metrics;
using Nikke.Simulator.Engine.Targets;

namespace Nikke.Simulator.Engine
{
    /// <summary>
    /// 엔진 진입점 — K8 통합 (M1: 스킬·팀버프 없는 평타 시간축 DPS). 팀 1개를 타겟에 대고
    /// 1회 run → **총대미지 표본 1개**(<see cref="RunResult"/>). Evaluator(Tier 3)가 N run → 분포.
    ///
    /// 배선: SimClock(60fps 프레임 tick) → per-Combatant FiringModel(K3) → 발사 시
    /// BuildHitContext(static 주입) + ITarget.PopulateContext(DEF/적정거리) + AccuracyModel 코어힛
    /// + CritSampler 크리 → DamageCalculator → MetricsCollector(K6).
    /// 잔여 배선(K7+): SkillRuntime 이벤트 브로드캐스트, 버프 집계, 버스트 게이지/사이클(K9).
    /// </summary>
    public static class SimulationRunner
    {
        private const double Fps = WeaponProfile.EngineFrameRate;

        /// <summary>
        /// 팀 1개(최대 5 Combatant)를 <paramref name="target"/> 에 대고 <paramref name="durationSec"/> 초 동안
        /// 굴린다. 크리/코어힛/수동 갭은 <paramref name="rng"/> 로 샘플링(고정 시드 금지 — N run 수렴 검증).
        /// </summary>
        /// <param name="team">한 팀(같은 run 안에서 1팀). DESIGN: sim 1 run = 팀 1개.</param>
        /// <param name="target">대미지 대상 (Dummy/Boss). CoreRadius=0 이면 코어힛 없음, BodyRadius=0 이면 빗맞음 없음.</param>
        /// <param name="rng">확률 RNG (<see cref="IRandomSource"/>).</param>
        /// <param name="durationSec">시뮬 길이(초).</param>
        public static RunResult RunOnce(
            IReadOnlyList<Combatant> team,
            ITarget target,
            IRandomSource rng,
            double durationSec)
        {
            if (team == null || team.Count == 0) throw new ArgumentException("팀이 비었음.", nameof(team));
            if (target == null) throw new ArgumentNullException(nameof(target));
            if (rng == null) throw new ArgumentNullException(nameof(rng));
            if (durationSec <= 0) throw new ArgumentOutOfRangeException(nameof(durationSec));

            var metrics = new MetricsCollector(durationSec);
            var clock = new SimClock();
            int totalFrames = (int)Math.Round(durationSec * Fps);

            // per-Combatant 발사 상태기계 (탄창 = FinalBaseMaxAmmo — OL 장탄 반영분)
            var units = new List<(Combatant C, FiringModel Fm)>(team.Count);
            foreach (var c in team)
            {
                int maxAmmo = Math.Max(1, (int)Math.Round(c.Nikke.FinalBaseMaxAmmo));
                units.Add((c, new FiringModel(c.Nikke.Weapon, maxAmmo, c.Firing ?? new FiringControl(), rng)));
            }

            void Tick(int frame)
            {
                double t = frame / Fps;
                foreach (var (c, fm) in units)
                {
                    var shot = fm.AdvanceFrame();
                    if (!shot.Fired) continue;

                    // SG 멀티펠릿 = 펠릿마다 독립 히트 인스턴스(개별 코어힛/크리 롤 — 가정, K8 골든에서 확정)
                    for (int p = 0; p < Math.Max(1, shot.PelletsPerShot); p++)
                    {
                        var ctx = c.BuildHitContext();
                        target.PopulateContext(ref ctx, c.Nikke.Element, c.Nikke.WeaponType);
                        ctx.IsFullCharge = shot.IsFullCharge;

                        // 명중/코어힛 — 타겟 지오메트리 있을 때만 (0 = 판정 생략)
                        if (target.BodyRadius > 0
                            && !AccuracyModel.RollHit(rng, shot.AccuracyCircle, target.BodyRadius))
                            continue; // 빗맞음 — 대미지 없음
                        if (target.CoreRadius > 0)
                            ctx.IsCoreHit = AccuracyModel.RollCoreHit(rng, shot.AccuracyCircle, target.CoreRadius);

                        ctx.IsCrit = CritSampler.RollCrit(rng, ctx.BaseCritRate);

                        double dmg = DamageCalculator.CalculateDamage(in ctx);
                        metrics.Record(t, c.Id, dmg, new Dictionary<string, object>
                        {
                            ["crit"] = ctx.IsCrit,
                            ["core"] = ctx.IsCoreHit,
                            ["full"] = ctx.IsFullCharge,
                        });
                    }
                }

                if (frame + 1 < totalFrames)
                    clock.Schedule((frame + 1) / Fps, () => Tick(frame + 1));
            }

            if (totalFrames > 0)
                clock.Schedule(0.0, () => Tick(0));
            clock.Run(durationSec);

            return metrics.Build();
        }
    }
}
