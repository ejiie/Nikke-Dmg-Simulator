using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Data.Dto;

namespace Nikke.Simulator.Tests;

/// <summary>
/// weaponData 블록 (roledata_cleaner._weapon_data → RootDto.WeaponDataDto) 검증.
/// 소스 = 커밋된 Database/processed/roledata_clean.json (192캐릭, name_code 키).
/// 값 불변식은 2026-07-02 전수 조사로 확정 (raw 단위: rate*=발/분, delay=1/100초).
/// </summary>
public class WeaponDataTests
{
    private static Dictionary<string, CharacterStaticDto> Load()
    {
        string path;
        try { path = JsonProvider.GetSmartDatabasePath("roledata_clean.json"); }
        catch { return null; }
        if (!System.IO.File.Exists(path)) return null;
        return JsonProvider.LoadJson<Dictionary<string, CharacterStaticDto>>(path);
    }

    [Fact]
    public void All_characters_have_weaponData_with_fire_rate()
    {
        var db = Load();
        if (db == null) return; // 데이터 없으면 스킵

        Assert.True(db.Count >= 190); // 2026-07 기준 192명
        Assert.All(db.Values, c =>
        {
            Assert.NotNull(c.weaponData);
            Assert.True(c.weaponData.rateOfFire > 0);
            Assert.True(c.weaponData.endRateOfFire > 0);
            Assert.True(c.weaponData.spotFirstDelay > 0);
            Assert.True(c.weaponData.spotLastDelay > 0);
            Assert.True(c.weaponData.shotCount >= 1);
        });
    }

    [Fact]
    public void Machine_gun_has_ramp_and_others_do_not()
    {
        var db = Load();
        if (db == null) return;

        var mg = db.Values.Where(c => c.weapon == "Minigun").ToList();
        Assert.NotEmpty(mg);
        Assert.All(mg, c =>
        {
            // MG ramp: 60→4200 발/분, 발당 +100, 사격 중단 1.0s(=100) 후 리셋
            Assert.Equal(60, c.weaponData.rateOfFire);
            Assert.Equal(4200, c.weaponData.endRateOfFire);
            Assert.Equal(100, c.weaponData.rateOfFireChangePerShot);
            Assert.Equal(100, c.weaponData.rateOfFireResetTime);
            // 명중원 연사 수축 250→10
            Assert.Equal(250, c.weaponData.startAccuracyCircleScale);
            Assert.Equal(10, c.weaponData.endAccuracyCircleScale);
        });

        // ramp 는 MG 전용 — 그 외 무기는 start == end, 발당 변화 0
        Assert.All(db.Values.Where(c => c.weapon != "Minigun"), c =>
        {
            Assert.Equal(c.weaponData.rateOfFire, c.weaponData.endRateOfFire);
            Assert.Equal(0, c.weaponData.rateOfFireChangePerShot);
        });
    }

    [Fact]
    public void Fire_rate_units_are_shots_per_minute()
    {
        var db = Load();
        if (db == null) return;

        // 단위 캘리브레이션 앵커 (발/분): 표준 AR 720(=12/s), SMG 1440(=24/s), SG 90(=1.5/s).
        // AR 은 150(변형 1명) 존재 — 720 이 최빈. SMG/SG 는 전원 단일값.
        var arRates = db.Values.Where(c => c.weapon == "Assault Rifle")
                               .Select(c => c.weaponData.rateOfFire.Value).ToList();
        Assert.Contains(720, arRates);
        Assert.All(db.Values.Where(c => c.weapon == "SMG"),
            c => Assert.Equal(1440, c.weaponData.rateOfFire));
        Assert.All(db.Values.Where(c => c.weapon == "Shotgun"),
            c => Assert.Equal(90, c.weaponData.rateOfFire));
    }

    [Fact]
    public void Shotgun_pellet_count_is_per_character()
    {
        var db = Load();
        if (db == null) return;

        var sg = db.Values.Where(c => c.weapon == "Shotgun").ToList();
        Assert.NotEmpty(sg);
        // 전수 조사: 펠릿 5 또는 10 (per-char — 무기타입 상수로 대체 불가)
        Assert.All(sg, c => Assert.True(c.weaponData.shotCount == 5 || c.weaponData.shotCount == 10));
        Assert.Contains(sg, c => c.weaponData.shotCount == 10);
    }
}
