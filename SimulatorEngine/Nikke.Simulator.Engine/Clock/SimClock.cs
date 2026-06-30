using System;
using System.Collections.Generic;

namespace Nikke.Simulator.Engine.Clock
{
    /// <summary>
    /// <see cref="ISimClock"/> 구현 (WORK_BREAKDOWN K2). min-heap(<see cref="PriorityQueue{TElement,TPriority}"/>)
    /// + 단조증가 시퀀스 번호로 동시각 tie-break 를 삽입순(FIFO) 결정적으로 고정.
    /// </summary>
    public sealed class SimClock : ISimClock
    {
        private readonly PriorityQueue<Action, (double AtSec, long Seq)> _queue = new(new EventComparer());
        private long _nextSeq;

        public double NowSec { get; private set; }

        public void Schedule(double atSec, Action ev)
        {
            if (atSec < NowSec)
                throw new ArgumentOutOfRangeException(nameof(atSec), atSec, $"과거 예약 금지: atSec={atSec} < NowSec={NowSec}");

            _queue.Enqueue(ev, (atSec, _nextSeq++));
        }

        public void Run(double untilSec)
        {
            while (_queue.TryPeek(out _, out var priority) && priority.AtSec <= untilSec)
            {
                var ev = _queue.Dequeue();
                NowSec = priority.AtSec;
                ev();
            }

            if (NowSec < untilSec)
                NowSec = untilSec;
        }

        private sealed class EventComparer : IComparer<(double AtSec, long Seq)>
        {
            public int Compare((double AtSec, long Seq) x, (double AtSec, long Seq) y)
            {
                int cmp = x.AtSec.CompareTo(y.AtSec);
                return cmp != 0 ? cmp : x.Seq.CompareTo(y.Seq);
            }
        }
    }
}
