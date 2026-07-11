using Nikke.Simulator.Core.Combat;
using Nikke.Simulator.Engine.Targets;
using Xunit;

namespace Nikke.Simulator.Tests;

/// <summary>
/// T04 — BossTarget 데이터 정합 테스트. solo_raid_boss.json = gitignore(복호물) —
/// 부재 시 graceful skip (fresh clone 정상, INV). 재생성 = run_pipeline.py --stage staticdata.
/// </summary>
public class BossTargetTests
{
    [Fact]
    public void Loader_Absent_Is_Graceful()
    {
        // 존재하지 않는 명시 경로 → false, throw 없음
        Assert.False(SoloRaidBossTable.TryLoad(out var bosses, explicitPath: "Z:/no/such/file.json"));
        Assert.Null(bosses);
        Assert.False(BossTarget.TryCreate("ebg001_island_zeus", 200, out var t, explicitPath: "Z:/no/such/file.json"));
        Assert.Null(t);
    }

    [Fact]
    public void Zeus_Lv200_Stats_And_Element()
    {
        if (!SoloRaidBossTable.TryLoad(out var bosses)) return; // 데이터 부재 = skip

        Assert.True(BossTarget.TryCreate("ebg001_island_zeus", 200, out var boss, distance: 40));
        // T04 수용 기준: DEF 9107 주입, Electric 속성
        Assert.Equal(9107, boss.FinalDef);
        Assert.Equal("Electric", boss.Element);
        Assert.True(boss.IsBoss);
        Assert.True(boss.MaxHp > 1e8); // Lv200 HP = 329,190,234

        // Iron 공격자 = Electric 에 우월 → B5 +0.1 (단일 소스 — ElementAdvantage)
        var ctx = new AttackContext(10000, 0);
        boss.PopulateContext(ref ctx, attackerElement: "Iron", attackerWeaponType: "AR");
        Assert.Equal(9107, ctx.FinalDef);
        Assert.Equal(0.1, ctx.SumStrongElem, 12);
        // AR 적정거리 구간(25-45) 안의 40 → +0.3
        Assert.Equal(0.3, ctx.ProperDistanceBonus, 12);

        // 무상성 공격자 (Electric vs Electric) → +0 (중복 가산 없음)
        var ctx2 = new AttackContext(10000, 0);
        boss.PopulateContext(ref ctx2, "Electric", "AR");
        Assert.Equal(0.0, ctx2.SumStrongElem, 12);
    }

    [Fact]
    public void MonsterId_Lookup_And_All_Variants_Constructible()
    {
        if (!SoloRaidBossTable.TryLoad(out var bosses)) return;

        Assert.Equal(39, bosses.Count); // solo raid 39 변종 (데이터 계보 — FACTS §6)
        foreach (var dto in bosses)
        {
            // 모든 변종 × 모든 레벨 = 생성 0-throw + DEF > 0
            foreach (int lv in dto.Levels)
            {
                var b = new BossTarget(dto, lv);
                Assert.True(b.FinalDef > 0, $"{dto.Code} Lv{lv} DEF 0");
                // 미링크 변종(xba001_psid)만 속성 없음 허용 — 상성 = graceful 0
                if (dto.MonsterId.HasValue)
                    Assert.False(string.IsNullOrEmpty(b.Element), $"{dto.Code} 속성 없음");
            }
            // monster_id 문자열 검색도 동작 (링크된 변종만)
            if (dto.MonsterId.HasValue)
                Assert.True(BossTarget.TryCreate(dto.MonsterId.Value.ToString(), dto.Levels[0], out _));
        }
    }

    [Fact]
    public void Invalid_Level_Throws_ArgumentOutOfRange()
    {
        if (!SoloRaidBossTable.TryLoad(out var bosses)) return;
        var dto = SoloRaidBossTable.Find(bosses, "ebg001_island_zeus");
        Assert.NotNull(dto);
        Assert.Throws<System.ArgumentOutOfRangeException>(() => new BossTarget(dto, 1)); // 사다리 밖 레벨
    }
}
