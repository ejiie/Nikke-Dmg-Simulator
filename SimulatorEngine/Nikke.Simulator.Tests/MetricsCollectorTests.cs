using System.Collections.Generic;
using Nikke.Simulator.Engine.Metrics;

namespace Nikke.Simulator.Tests;

/// <summary>K6 MetricsCollector — 집계 정확성 (WORK_BREAKDOWN K6 수용 기준).</summary>
public class MetricsCollectorTests
{
    private static Dictionary<string, object> Tags(params (string k, object v)[] kv)
    {
        var d = new Dictionary<string, object>();
        foreach (var (k, v) in kv) d[k] = v;
        return d;
    }

    [Fact]
    public void Aggregates_total_source_and_hit_count()
    {
        var m = new MetricsCollector(10.0);
        m.Record(0.5, "a", 100);
        m.Record(1.2, "a", 50);
        m.Record(2.0, "b", 25);

        var r = m.Build();
        Assert.Equal(175, r.TotalDamage, 9);
        Assert.Equal(3, r.HitCount);
        Assert.Equal(10.0, r.DurationSec, 9);
        Assert.Equal(150, r.DamageBySource["a"], 9);
        Assert.Equal(25, r.DamageBySource["b"], 9);
    }

    [Fact]
    public void Buckets_damage_per_second_including_end_boundary()
    {
        var m = new MetricsCollector(5.0);
        m.Record(0.0, "a", 1);
        m.Record(0.99, "a", 2);
        m.Record(1.0, "a", 4);   // 경계 = 다음 버킷
        m.Record(4.5, "a", 8);
        m.Record(5.0, "a", 16);  // run 종료 경계 = 마지막 버킷

        var r = m.Build();
        Assert.Equal(5, r.DamagePerSecond.Count);
        Assert.Equal(3, r.DamagePerSecond[0], 9);
        Assert.Equal(4, r.DamagePerSecond[1], 9);
        Assert.Equal(0, r.DamagePerSecond[2], 9);
        Assert.Equal(24, r.DamagePerSecond[4], 9);
    }

    [Fact]
    public void Decomposes_damage_by_tag_pairs()
    {
        var m = new MetricsCollector(10.0);
        m.Record(1, "a", 100, Tags(("crit", true), ("bracket", "b3")));
        m.Record(2, "a", 50, Tags(("crit", false)));
        m.Record(3, "b", 30, Tags(("crit", true)));
        m.Record(4, "b", 7);   // 태그 없음 — 분해 미포함

        var r = m.Build();
        Assert.Equal(130, r.DamageByTag["crit=True"], 9);
        Assert.Equal(50, r.DamageByTag["crit=False"], 9);
        Assert.Equal(100, r.DamageByTag["bracket=b3"], 9);
        Assert.Equal(187, r.TotalDamage, 9);
    }

    [Fact]
    public void Build_is_snapshot_and_collector_stays_usable()
    {
        var m = new MetricsCollector(10.0);
        m.Record(1, "a", 10);
        var r1 = m.Build();
        m.Record(2, "a", 5);
        var r2 = m.Build();

        Assert.Equal(10, r1.TotalDamage, 9); // 스냅샷 불변
        Assert.Equal(15, r2.TotalDamage, 9);
        Assert.Equal(1, r1.HitCount);
        Assert.Equal(2, r2.HitCount);
    }

    [Fact]
    public void Reset_allows_reuse_for_next_run()
    {
        var m = new MetricsCollector(10.0);
        m.Record(1, "a", 10, Tags(("crit", true)));
        m.Reset();
        m.Record(2, "b", 3);

        var r = m.Build();
        Assert.Equal(3, r.TotalDamage, 9);
        Assert.Equal(1, r.HitCount);
        Assert.False(r.DamageBySource.ContainsKey("a"));
        Assert.Empty(r.DamageByTag);
    }

    [Fact]
    public void Rejects_hits_outside_run_window_and_bad_args()
    {
        var m = new MetricsCollector(10.0);
        Assert.Throws<System.ArgumentOutOfRangeException>(() => m.Record(-0.1, "a", 1));
        Assert.Throws<System.ArgumentOutOfRangeException>(() => m.Record(10.01, "a", 1));
        Assert.Throws<System.ArgumentNullException>(() => m.Record(1, null, 1));
        Assert.Throws<System.ArgumentOutOfRangeException>(() => new MetricsCollector(0));
    }
}
