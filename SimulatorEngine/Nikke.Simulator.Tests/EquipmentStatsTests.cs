using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Stats;

namespace Nikke.Simulator.Tests;

/// <summary>
/// 장비 스탯 공식 검증 (blablalink getEquipAttr):
///   stat = round( base × (1 + 0.3·제조사일치 + 0.1·level) )  per 부위/스탯타입.
/// 기준: Attacker T10 head base ATK 6014 / HP 49181 (equip_stat_table.json).
/// </summary>
public class EquipmentStatsTests
{
    private static EquipmentPartsDto HeadOnly(int tier, int level, int corp) => new()
    {
        head = new EquipmentInfoDto { tier = tier, level = level, corp = corp },
        torso = new EquipmentInfoDto { tier = 0, level = 0, corp = 0 },
        arm = new EquipmentInfoDto { tier = 0, level = 0, corp = 0 },
        leg = new EquipmentInfoDto { tier = 0, level = 0, corp = 0 },
    };

    public EquipmentStatsTests()
    {
        StatTable.InitializeEquipment(JsonProvider.GetSmartDatabasePath("equip_stat_table.json"));
    }

    [Fact]
    public void Attacker_T10_head_L5_noCorp()
    {
        var (hp, atk, def) = StatTable.GetEquipmentStats("Attacker", "Pilgrim", HeadOnly(10, 5, 0));
        Assert.Equal(9021, atk);    // round(6014 × 1.5)
        Assert.Equal(73772, hp);    // round(49181 × 1.5)
        Assert.Equal(0, def);
    }

    [Fact]
    public void Attacker_T10_head_L5_corpMatch_adds30pct()
    {
        // corp=4 (Pilgrim) == manufacturer "Pilgrim" → ×1.8
        var (hp, atk, def) = StatTable.GetEquipmentStats("Attacker", "Pilgrim", HeadOnly(10, 5, 4));
        Assert.Equal(10825, atk);   // round(6014 × 1.8)
        Assert.Equal(88526, hp);    // round(49181 × 1.8)
    }

    [Fact]
    public void EmptyGear_returnsZero()
    {
        var (hp, atk, def) = StatTable.GetEquipmentStats("Attacker", "Pilgrim", HeadOnly(0, 0, 0));
        Assert.Equal((0, 0, 0), (hp, atk, def));
    }

    /// <summary>마이그레이션 후 merged DB(roledata static + skills dict + corp)가 RootDto 로
    /// 역직렬화되는지 확인. 유저데이터(gitignore)라 없으면 스킵.</summary>
    [Fact]
    public void MergedDb_deserializes_newShape()
    {
        string path;
        try { path = JsonProvider.GetSmartDatabasePath("nikke_merged_db_returned.json"); }
        catch { return; } // 파일 없으면 스킵
        if (!System.IO.File.Exists(path)) return;

        var db = JsonProvider.LoadJson<RootDto>(path);
        Assert.NotNull(db);
        Assert.NotEmpty(db.roster);
        var c = System.Linq.Enumerable.First(db.roster.Values);
        Assert.NotNull(c.StaticInfo);                 // roledata static
        Assert.NotNull(c.user.equipments.head);       // corp 포함 EquipmentInfoDto
    }
}
