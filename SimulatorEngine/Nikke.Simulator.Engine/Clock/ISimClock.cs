using System;

namespace Nikke.Simulator.Engine.Clock
{
    /// <summary>
    /// 이산이벤트 클럭 (ENGINE_GUIDE §5 SimClock). 최소시각 이벤트 pop → clock 전진 → 실행
    /// (실행 중 새 이벤트 예약 가능). 동일시각 tie-break 는 삽입순으로 결정적.
    /// RNG 외 모든 동작 결정적.
    ///
    /// 임플: Wave1 K2 (`Engine/Clock/SimClock.cs`, min-heap 우선순위큐 — ✅ 완료). 이 인터페이스는 K0 동결 계약.
    /// </summary>
    public interface ISimClock
    {
        /// <summary>현재 시각(초). Run 진행에 따라 단조 증가.</summary>
        double NowSec { get; }

        /// <summary><paramref name="atSec"/> 시각에 이벤트를 예약. atSec &lt; NowSec 은 금지(과거 예약).</summary>
        void Schedule(double atSec, Action ev);

        /// <summary><paramref name="untilSec"/> 까지(포함) 예약된 이벤트를 시각순으로 모두 실행.</summary>
        void Run(double untilSec);
    }
}
