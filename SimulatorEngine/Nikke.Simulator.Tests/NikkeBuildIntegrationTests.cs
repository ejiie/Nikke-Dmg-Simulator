using System.Linq;
using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Entities;
using Nikke.Simulator.Core.Stats;

namespace Nikke.Simulator.Tests;

/// <summary>
/// 마이그레이션 후 통합 검증: 큐브/소장품/장비 base 표(공식 JSON) 로드 → merged DB 의
/// 큐브 장착 캐릭으로 Nikke 생성 → 자동 EquipCube + base 스탯이 FinalBaseHP 에 반영되는지 확인.
/// merged DB(gitignore) 없으면 스킵. (레벨/호감도 CSV 는 이 테스트 범위 밖이라 미로드.)
/// </summary>
public class NikkeBuildIntegrationTests
{
    private static string Find(string name)
    {
        try { return JsonProvider.GetSmartDatabasePath(name); }
        catch { return null; }
    }

    [Fact]
    public void Build_nikke_with_cube_from_mergedDb()
    {
        string db = Find("nikke_merged_db_returned.json");
        if (db == null || !System.IO.File.Exists(db))
            return; // 데이터 없으면 스킵

        // 레벨/호감도(stat_table.csv) 없이도 큐브/소장품/장비 base(JSON)는 적용된다.
        // (이 테스트의 범위 = 큐브 자동장착 + base JSON 반영. 코어스탯은 0 이어도 무방.)
        StatTable.InitializeEquipment(Find("equip_stat_table.json"));
        StatTable.InitializeCubeBase(Find("cube_base_table.json"));
        StatTable.InitializeCollectionBase(Find("collection_base_table.json"));
        Nikke.Simulator.Core.Data.Constants.EffectTable.InitializeCube(Find("cube_effect_table.json"));
        Nikke.Simulator.Core.Data.Constants.EffectTable.InitializeCollection(Find("collection_effect_table.json"));

        var root = JsonProvider.LoadJson<RootDto>(db);
        // 큐브 장착된 캐릭 하나
        var entry = root.roster.Values.FirstOrDefault(c => c.user?.cube != null && c.user.cube.tid > 0);
        if (entry == null) return; // 큐브 장착 캐릭 없으면 스킵

        var nikke = new Core.Entities.Nikke(entry, root.global_state);

        Assert.NotNull(nikke.EquippedCube);        // 큐브 자동 장착됨
        Assert.True(nikke.EquippedCube.HP > 0);    // 큐브 base 스탯(JSON) 로드됨
        Assert.True(nikke.FinalBaseAtk > 0);       // 기초 ATK 산출
        Assert.True(nikke.FinalBaseHP > 0);
        Assert.False(string.IsNullOrEmpty(nikke.Squad));   // roledata squad 배선
        Assert.True(nikke.ProperRangeMax >= nikke.ProperRangeMin); // 적정거리 범위 배선
    }
}
