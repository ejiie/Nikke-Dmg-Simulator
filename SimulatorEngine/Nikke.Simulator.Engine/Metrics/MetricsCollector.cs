using System;
using System.Collections.Generic;

namespace Nikke.Simulator.Engine.Metrics
{
    /// <summary>
    /// K6 — record-every-instance 대미지 수집기 (ENGINE_GUIDE §5 / D4). sim 루프가 히트마다
    /// <see cref="Record"/> → run 종료 시 <see cref="Build"/> 가 <see cref="RunResult"/> 집계
    /// (총대미지 / 캐릭별 / 태그별 / 시간축 초 단위).
    ///
    /// 성능 노트 (DESIGN §0.5 — 성능 1급): 히트당 고정 필드만 즉시 누적(사전 조회 1~2회),
    /// 인스턴스 리스트 보관 없음 — 180s × 60발/s × 5인 ≈ 54k 히트에도 O(고유 태그 수) 메모리.
    /// 단일 run 단일 스레드 전제 (Evaluator 의 N-run 병렬은 run 당 collector 1개).
    /// </summary>
    public sealed class MetricsCollector : IMetricsSink
    {
        private readonly double _durationSec;
        private readonly Dictionary<string, double> _bySource = new();
        private readonly Dictionary<string, double> _byTag = new();
        private readonly double[] _perSecond;
        private double _total;
        private int _hits;

        /// <param name="durationSec">run 계획 길이(초) — RunResult.DurationSec / 시간축 버킷 수 결정.</param>
        public MetricsCollector(double durationSec)
        {
            if (durationSec <= 0) throw new ArgumentOutOfRangeException(nameof(durationSec));
            _durationSec = durationSec;
            _perSecond = new double[(int)Math.Ceiling(durationSec)];
        }

        public void Record(double timeSec, string sourceId, double amount,
                           IReadOnlyDictionary<string, object> tags = null)
        {
            if (sourceId == null) throw new ArgumentNullException(nameof(sourceId));
            if (timeSec < 0 || timeSec > _durationSec)
                throw new ArgumentOutOfRangeException(nameof(timeSec),
                    $"히트 시각 {timeSec}s 가 run 창 [0, {_durationSec}] 밖 — 클럭 배선 버그 신호.");

            _total += amount;
            _hits += 1;

            _bySource.TryGetValue(sourceId, out double s);
            _bySource[sourceId] = s + amount;

            // 마지막 경계(t == duration)는 마지막 버킷으로
            int bucket = Math.Min((int)timeSec, _perSecond.Length - 1);
            _perSecond[bucket] += amount;

            if (tags != null)
                foreach (var kv in tags)
                {
                    string key = $"{kv.Key}={kv.Value}";
                    _byTag.TryGetValue(key, out double t);
                    _byTag[key] = t + amount;
                }
        }

        /// <summary>집계 스냅샷 산출 — 순수 조회 (여러 번 호출 가능, 이후 Record 도 계속 유효).</summary>
        public RunResult Build() => new()
        {
            TotalDamage = _total,
            DurationSec = _durationSec,
            HitCount = _hits,
            DamageBySource = new Dictionary<string, double>(_bySource),
            DamageByTag = new Dictionary<string, double>(_byTag),
            DamagePerSecond = (double[])_perSecond.Clone(),
        };

        /// <summary>재사용 초기화 (Evaluator N-run 루프에서 할당 회피용).</summary>
        public void Reset()
        {
            _total = 0;
            _hits = 0;
            _bySource.Clear();
            _byTag.Clear();
            Array.Clear(_perSecond, 0, _perSecond.Length);
        }
    }
}
