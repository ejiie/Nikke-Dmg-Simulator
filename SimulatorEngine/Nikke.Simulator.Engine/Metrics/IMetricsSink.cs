using System.Collections.Generic;

namespace Nikke.Simulator.Engine.Metrics
{
    /// <summary>
    /// 히트마다 대미지 인스턴스를 기록하는 싱크 (ENGINE_GUIDE §5 MetricsCollector).
    /// sim 루프가 매 히트 <see cref="Record"/> 호출 → run 종료 시 <see cref="Build"/> 가 집계.
    ///
    /// 임플: K6 <c>MetricsCollector</c>. 이 인터페이스 + <see cref="RunResult"/> 는 K0 동결 계약.
    /// DESIGN §6: **sim 1 run 출력 = 총대미지 표본 1개** (Evaluator 가 N run → 분포).
    /// </summary>
    public interface IMetricsSink
    {
        /// <summary>대미지 인스턴스 1개 기록.</summary>
        /// <param name="timeSec">발생 시각(초).</param>
        /// <param name="sourceId">가한 Combatant 식별자.</param>
        /// <param name="amount">대미지 양 (DamageCalculator 결과).</param>
        /// <param name="tags">분해용 태그(crit/core/bracket…). 키 집합은 K6 에서 확정.</param>
        void Record(double timeSec, string sourceId, double amount, IReadOnlyDictionary<string, object>? tags = null);

        /// <summary>기록을 집계해 <see cref="RunResult"/> 산출 (run 1회 종료 시).</summary>
        RunResult Build();
    }

    /// <summary>
    /// sim 1 run 결과 (ENGINE_GUIDE §5). 핵심 = <see cref="TotalDamage"/> (표본 1개).
    /// 부가 분해 필드 = K6 확정 (2026-07-08, `MetricsCollector` 가 채움).
    /// </summary>
    public sealed class RunResult
    {
        /// <summary>이 run 의 총대미지 (Evaluator 분포의 표본 1개).</summary>
        public double TotalDamage { get; init; }

        /// <summary>sim 종료 시각(초). DPS = TotalDamage / DurationSec.</summary>
        public double DurationSec { get; init; }

        /// <summary>Combatant 식별자 → 기여 대미지.</summary>
        public IReadOnlyDictionary<string, double> DamageBySource { get; init; }
            = new Dictionary<string, double>();

        /// <summary>기록된 대미지 인스턴스 수 (record-every-instance, ENGINE_GUIDE D4).</summary>
        public int HitCount { get; init; }

        /// <summary>태그별 대미지 분해 — 키 = "tag=value" (예: "crit=True", "bracket=b3"). 태그 없는 히트 = 미포함.</summary>
        public IReadOnlyDictionary<string, double> DamageByTag { get; init; }
            = new Dictionary<string, double>();

        /// <summary>시간축 분해 — 인덱스 = 초(floor), 값 = 그 1초 구간 대미지 합. 길이 = ceil(DurationSec).</summary>
        public IReadOnlyList<double> DamagePerSecond { get; init; } = System.Array.Empty<double>();
    }
}
