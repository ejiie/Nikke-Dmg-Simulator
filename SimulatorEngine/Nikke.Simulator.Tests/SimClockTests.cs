using System;
using System.Collections.Generic;
using Nikke.Simulator.Engine.Clock;

namespace Nikke.Simulator.Tests;

/// <summary>
/// K2 (WORK_BREAKDOWN / ENGINE_GUIDE §5 SimClock) — 이산이벤트 큐 단위테스트.
/// 순서/동시각 tie-break/재귀예약/과거예약 거부/분할 Run 을 잠근다.
/// </summary>
public class SimClockTests
{
    [Fact]
    public void Run_ExecutesEventsInTimeOrder_RegardlessOfScheduleOrder()
    {
        var clock = new SimClock();
        var order = new List<string>();

        clock.Schedule(3.0, () => order.Add("c"));
        clock.Schedule(1.0, () => order.Add("a"));
        clock.Schedule(2.0, () => order.Add("b"));

        clock.Run(10.0);

        Assert.Equal(new[] { "a", "b", "c" }, order);
    }

    [Fact]
    public void Run_SameTimeEvents_ExecuteInScheduleOrder()
    {
        var clock = new SimClock();
        var order = new List<string>();

        clock.Schedule(5.0, () => order.Add("first"));
        clock.Schedule(5.0, () => order.Add("second"));
        clock.Schedule(5.0, () => order.Add("third"));

        clock.Run(10.0);

        Assert.Equal(new[] { "first", "second", "third" }, order);
    }

    [Fact]
    public void Run_RecursivelyScheduledEvent_ExecutesWithinSameRunWindow()
    {
        var clock = new SimClock();
        var order = new List<string>();

        // t=1 이벤트가 실행 중 t=2 이벤트를 새로 예약 (Run(10) 창 내부 → 같은 Run 이 흡수).
        clock.Schedule(1.0, () =>
        {
            order.Add("t1");
            clock.Schedule(2.0, () => order.Add("t2-spawned"));
        });

        clock.Run(10.0);

        Assert.Equal(new[] { "t1", "t2-spawned" }, order);
    }

    [Fact]
    public void Run_RecursiveScheduleAtSameTime_ExecutesAfterAlreadyQueuedSameTimeEvent()
    {
        var clock = new SimClock();
        var order = new List<string>();

        // t=5 에 두 이벤트 선예약, 첫 실행 중 t=5(현재시각=NowSec) 재귀예약 → seq 가 더 크므로 맨 뒤.
        clock.Schedule(5.0, () =>
        {
            order.Add("a");
            clock.Schedule(5.0, () => order.Add("c-spawned-at-same-time"));
        });
        clock.Schedule(5.0, () => order.Add("b"));

        clock.Run(10.0);

        Assert.Equal(new[] { "a", "b", "c-spawned-at-same-time" }, order);
    }

    [Fact]
    public void Schedule_PastTime_Throws()
    {
        var clock = new SimClock();
        clock.Schedule(5.0, () => { });
        clock.Run(5.0); // NowSec = 5.0 로 전진

        Assert.Throws<ArgumentOutOfRangeException>(() => clock.Schedule(4.0, () => { }));
    }

    [Fact]
    public void Run_SplitAcrossMultipleCalls_DefersEventsBeyondWindow()
    {
        var clock = new SimClock();
        var order = new List<string>();

        clock.Schedule(2.0, () => order.Add("early"));
        clock.Schedule(8.0, () => order.Add("late"));

        clock.Run(5.0); // [0,5] 창 → "early" 만
        Assert.Equal(new[] { "early" }, order);

        clock.Run(10.0); // [5,10] 창 → "late" 흡수
        Assert.Equal(new[] { "early", "late" }, order);
    }

    [Fact]
    public void Run_NowSecAdvancesMonotonically_AndEndsAtUntilSec()
    {
        var clock = new SimClock();
        Assert.Equal(0.0, clock.NowSec);

        clock.Schedule(3.0, () => Assert.Equal(3.0, clock.NowSec)); // 실행 시점엔 이벤트 시각으로 전진
        clock.Run(7.0);

        // 이벤트가 7.0 보다 일찍 끝나도 NowSec 은 untilSec 까지 전진(시간 경과 자체는 일어남).
        Assert.Equal(7.0, clock.NowSec);
    }

    [Fact]
    public void Run_EmptyQueue_AdvancesNowSecWithoutExecutingAnything()
    {
        var clock = new SimClock();
        clock.Run(10.0);
        Assert.Equal(10.0, clock.NowSec);
    }

    [Fact]
    public void Run_OnlyEventsBeyondWindow_DoesNotExecuteAndStillAdvancesNowSec()
    {
        var clock = new SimClock();
        var executed = false;
        clock.Schedule(20.0, () => executed = true);

        clock.Run(10.0);

        Assert.False(executed);
        Assert.Equal(10.0, clock.NowSec);
    }

    [Fact]
    public void Run_BoundaryAtUntilSec_IsInclusive_NextTickIsExclusive()
    {
        var clock = new SimClock();
        var order = new List<string>();

        clock.Schedule(10.0, () => order.Add("at-boundary"));
        clock.Schedule(10.0001, () => order.Add("just-after"));

        clock.Run(10.0);

        Assert.Equal(new[] { "at-boundary" }, order);
    }
}
