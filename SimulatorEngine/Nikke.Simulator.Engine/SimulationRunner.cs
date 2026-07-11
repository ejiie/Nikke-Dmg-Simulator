using System;
using System.Collections.Generic;
using Nikke.Simulator.Core.Combat;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine.Buffs;
using Nikke.Simulator.Engine.Clock;
using Nikke.Simulator.Engine.Combat;
using Nikke.Simulator.Engine.Events;
using Nikke.Simulator.Engine.Metrics;
using Nikke.Simulator.Engine.Skills;
using Nikke.Simulator.Engine.Targets;

namespace Nikke.Simulator.Engine
{
    /// <summary>
    /// 엔진 진입점 — K8 통합 + T01 스킬 배선. 팀 1개를 타겟에 대고 1회 run → **총대미지 표본 1개**
    /// (<see cref="RunResult"/>). Evaluator(Tier 3)가 N run → 분포.
    ///
    /// 배선: SimClock(60fps 프레임 tick — 권위, DESIGN §6 2026-07-11) → per-Combatant FiringModel(K3)
    /// → 발사/히트 이벤트 → SkillRuntime(T01: 트리거→버프/스킬대미지) → BuildHitContext + BuffAggregator
    /// + ITarget.PopulateContext + AccuracyModel/CritSampler → DamageCalculator → MetricsCollector(K6).
    /// 잔여 배선(T02+): 버스트 게이지/사이클, 팀 5인 시퀀스, RotationController directive.
    /// </summary>
    public static class SimulationRunner
    {
        private const double Fps = WeaponProfile.EngineFrameRate;

        /// <summary>스킬 없는 평타 run (M1 계약 유지 — 기존 테스트/골든 경로).</summary>
        public static RunResult RunOnce(
            IReadOnlyList<Combatant> team,
            ITarget target,
            IRandomSource rng,
            double durationSec)
            => RunOnce(team, target, rng, durationSec, runtime: null);

        /// <summary>
        /// 팀 1개를 <paramref name="target"/> 에 대고 <paramref name="durationSec"/> 초 굴린다.
        /// <paramref name="runtime"/> = 사전 등록된 <see cref="SkillRuntime"/> (null = 스킬 없음).
        /// <paramref name="autoCastBurst"/> = 버스트 스킬을 쿨타임마다 자동 시전 — **T02(게이지/사이클) 전
        /// 근사** (게이지 무시). 크리/코어힛/수동 갭은 <paramref name="rng"/> 로 샘플링 (고정 시드 금지).
        /// </summary>
        public static RunResult RunOnce(
            IReadOnlyList<Combatant> team,
            ITarget target,
            IRandomSource rng,
            double durationSec,
            SkillRuntime runtime,
            bool autoCastBurst = true)
        {
            if (team == null || team.Count == 0) throw new ArgumentException("팀이 비었음.", nameof(team));
            if (target == null) throw new ArgumentNullException(nameof(target));
            if (rng == null) throw new ArgumentNullException(nameof(rng));
            if (durationSec <= 0) throw new ArgumentOutOfRangeException(nameof(durationSec));

            var metrics = new MetricsCollector(durationSec);
            var clock = new SimClock();
            int totalFrames = (int)Math.Round(durationSec * Fps);

            // per-Combatant 발사 상태기계 (탄창 = FinalBaseMaxAmmo — OL 장탄 반영분)
            var units = new List<Unit>(team.Count);
            foreach (var c in team)
            {
                int maxAmmo = Math.Max(1, (int)Math.Round(c.Nikke.FinalBaseMaxAmmo));
                // 큐브/소장품 타이밍 특수효과(Resilience 재장전·Adjutant 차지) = 개별 항으로 주입
                // (니케식 감쇠식 — OverloadProcessor.ReduceTimeCs)
                units.Add(new Unit
                {
                    C = c,
                    Fm = new FiringModel(c.Nikke.Weapon, maxAmmo, c.Firing ?? new FiringControl(), rng,
                                         reloadSpeedBuffs: c.Nikke.TimingReloadSpeedTerms,
                                         chargeSpeedBuffs: c.Nikke.TimingChargeSpeedTerms),
                    MaxAmmo = maxAmmo,
                });
            }

            // T01: 전투 시작 이벤트 (패시브 OnStart/None 적용) + 버스트 첫 시전 준비
            runtime?.Broadcast(new BattleEvent { Kind = BattleEventKind.BattleStart, Frame = 0 });

            void Tick(int frame)
            {
                double t = frame / Fps;

                runtime?.TickFrame(frame); // 버프 만료 + OnCheckTime 주기 (frame 도메인 — FACTS §4)

                foreach (var u in units)
                {
                    // T02 전 근사: 버스트 = 쿨타임마다 자동 시전 (게이지 무시 — 사용자 승인 범위 T01)
                    if (runtime != null && autoCastBurst && frame >= u.NextBurstFrame)
                    {
                        int cooldownFrames = runtime.CastSkill(u.C, "burst", frame);
                        u.NextBurstFrame = cooldownFrames > 0 ? frame + cooldownFrames : int.MaxValue;
                    }

                    int prevAmmo = u.Fm.CurrentAmmo;
                    var shot = u.Fm.AdvanceFrame();

                    // 재장전 완료 감지 (탄 증가 = refill) → OnEndReload
                    if (runtime != null && u.Fm.CurrentAmmo > prevAmmo)
                        runtime.Broadcast(new BattleEvent
                        {
                            Kind = BattleEventKind.ReloadEnd, Source = u.C,
                            IntValue = u.Fm.CurrentAmmo, Frame = frame,
                        });

                    if (shot.Fired)
                    {
                        runtime?.Broadcast(new BattleEvent
                        {
                            Kind = BattleEventKind.NikkeFire, Source = u.C,
                            IsFullCharge = shot.IsFullCharge, IntValue = shot.CurrentAmmo, Frame = frame,
                        });

                        // SG 멀티펠릿 = 펠릿마다 독립 히트 인스턴스(개별 코어힛/크리 롤 — 가정, T07 골든에서 확정)
                        for (int p = 0; p < Math.Max(1, shot.PelletsPerShot); p++)
                        {
                            var ctx = BuildContext(u.C, target);
                            ctx.IsFullCharge = shot.IsFullCharge;

                            // 명중/코어힛 — 타겟 지오메트리 있을 때만 (0 = 판정 생략)
                            if (target.BodyRadius > 0
                                && !AccuracyModel.RollHit(rng, shot.AccuracyCircle, target.BodyRadius))
                                continue; // 빗맞음 — 대미지 없음
                            if (target.CoreRadius > 0)
                                ctx.IsCoreHit = AccuracyModel.RollCoreHit(rng, shot.AccuracyCircle, target.CoreRadius);

                            ctx.IsCrit = CritSampler.RollCrit(rng, ctx.BaseCritRate);

                            double dmg = DamageCalculator.CalculateDamage(in ctx);
                            metrics.Record(t, u.C.Id, dmg, new Dictionary<string, object>
                            {
                                ["crit"] = ctx.IsCrit,
                                ["core"] = ctx.IsCoreHit,
                                ["full"] = ctx.IsFullCharge,
                            });

                            runtime?.Broadcast(new BattleEvent
                            {
                                Kind = BattleEventKind.NikkeHit, Source = u.C,
                                IsFullCharge = shot.IsFullCharge, IsCrit = ctx.IsCrit, IsCoreHit = ctx.IsCoreHit,
                                IntValue = shot.CurrentAmmo, Frame = frame,
                            });
                        }
                    }
                }

                // T01: 스킬 즉시 효과 drain — 대미지 인스턴스 + 탄약 효과
                if (runtime != null) DrainRuntime(runtime, units, target, metrics, t);

                if (frame + 1 < totalFrames)
                    clock.Schedule((frame + 1) / Fps, () => Tick(frame + 1));
            }

            if (totalFrames > 0)
                clock.Schedule(0.0, () => Tick(0));
            clock.Run(durationSec);

            return metrics.Build();
        }

        private sealed class Unit
        {
            public Combatant C;
            public FiringModel Fm;
            public int MaxAmmo;
            public int NextBurstFrame; // autoCastBurst 스케줄 (0 = 개전 즉시 — T02 전 근사)
        }

        /// <summary>히트 컨텍스트 = static 주입(BuildHitContext) + 활성 버프 집계(T01) + 타겟 채움.</summary>
        private static AttackContext BuildContext(Combatant c, ITarget target)
        {
            var ctx = c.BuildHitContext();
            BuffAggregator.Apply(ref ctx, c.ActiveBuffs); // 빈 목록 = no-op (구 경로 동일)
            target.PopulateContext(ref ctx, c.Nikke.Element, c.Nikke.WeaponType);
            return ctx;
        }

        private static void DrainRuntime(SkillRuntime runtime, List<Unit> units, ITarget target,
                                         MetricsCollector metrics, double t)
        {
            var ammoOps = runtime.DrainAmmo();
            if (ammoOps != null)
                foreach (var op in ammoOps)
                {
                    var u = units.Find(x => ReferenceEquals(x.C, op.Owner));
                    if (u == null) continue;
                    switch (op.Kind)
                    {
                        case SkillRuntime.AmmoOpKind.FullReload: u.Fm.RefillFull(); break;
                        case SkillRuntime.AmmoOpKind.AddCount: u.Fm.AddAmmo((int)Math.Round(op.Amount)); break;
                        case SkillRuntime.AmmoOpKind.AddRatio:
                            u.Fm.AddAmmo((int)Math.Round(op.Amount * u.MaxAmmo)); break;
                    }
                }

            var dmgs = runtime.DrainDamage();
            if (dmgs != null)
                foreach (var pd in dmgs)
                {
                    // 스킬 대미지 인스턴스: M = function 계수 (W 슬롯 대체 — FACTS §1). 차지 C=1,
                    // 크리/코어/명중 롤 없음 (스킬 누크 = 확정 히트 — 브래킷 게이트는 컨텍스트 플래그로).
                    var ctx = BuildContext(pd.Source, target);
                    ctx.SkillMultiplier = pd.Multiplier;
                    ctx.IsFullCharge = false;

                    double dmg = DamageCalculator.CalculateDamage(in ctx);
                    metrics.Record(t, pd.Source.Id, dmg, new Dictionary<string, object>
                    {
                        ["crit"] = false,
                        ["core"] = false,
                        ["full"] = false,
                        ["skill"] = true,
                    });
                }
        }
    }
}
