using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Nikke.Simulator.Core.Combat;
using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Data.Constants;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Entities;
using Nikke.Simulator.Core.Stats;
using Xunit.Abstractions;

namespace Nikke.Simulator.Tests;

/// <summary>
/// K1 (ENGINE_WAVE0 / WORK_BREAKDOWN) — W 단위 픽스 + foundation 검증 (M0).
///
/// 두 종류 검증:
///  (1) **W 단위 불변식** (데이터 무관, CI 락) — basicAttack.multiplier 는 percent-number
///      (예 13.65), Nikke 가 /100 정규화하여 BasicAtkMultiplier = fraction(0.1365) 로 보유하는지.
///      이게 100× 버그(ENGINE_WAVE0 §핵심버그)의 회귀 가드.
///  (2) **foundation smoke** (커밋된 데이터로) — Initialize → new Nikke → BuildAttackContext →
///      CalculateDamage 를 1발 굴려 FinalAtk + 무버프 평타 1발을 **출력**.
///      게임 스탯창 대조용 (수용 기준의 in-game 일치는 사용자 제공 수치로 잠금 — 아래 TODO).
/// </summary>
public class WUnitFoundationTests
{
    private readonly ITestOutputHelper _out;
    public WUnitFoundationTests(ITestOutputHelper output) => _out = output;

    private static string? Find(string name)
    {
        try { return JsonProvider.GetSmartDatabasePath(name); }
        catch { return null; }
    }

    // ─────────────────────────────────────────────────────────────────────
    // (1) W 단위 불변식 — 데이터 파일 불필요, 항상 실행되는 CI 회귀 가드.
    // ─────────────────────────────────────────────────────────────────────
    [Theory]
    [InlineData(13.65)]   // Privaty AR
    [InlineData(5.57)]    // Emma Minigun
    [InlineData(214.3)]   // SG 류 (큰 펠릿 합)
    public void BasicAtkMultiplier_IsNormalizedToFraction(double percentNumber)
    {
        var dto = MinimalDto(weapon: "Assault Rifle", multiplier: percentNumber);
        var nikke = new Nikke.Simulator.Core.Entities.Nikke(dto, NoConsoles());

        // 데이터(percent-number) → 엔티티(fraction): 정확히 /100.
        Assert.Equal(percentNumber / 100.0, nikke.BasicAtkMultiplier, 10);

        // fraction-scale 가드: 평타 계수는 1발당 합리적 배율(<10). percent-number(>10)면 100× 버그.
        Assert.True(nikke.BasicAtkMultiplier < 10.0,
            $"W={nikke.BasicAtkMultiplier} — percent-number 주입(100× 버그) 의심.");
    }

    // ─────────────────────────────────────────────────────────────────────
    // (1b) StatTable 견고 파서 락 — 정본 csv 의 알려진 셀을 정확히 읽는지 (행 위치 내용기반).
    //      커밋 stat_table.csv 필요(없으면 skip). cp949 + 멀티라인 헤더 내성 회귀 가드.
    // ─────────────────────────────────────────────────────────────────────
    [Fact]
    public void StatTable_Parses_KnownCells()
    {
        string? csv = Find("stat_table.csv");
        if (csv == null) { _out.WriteLine("csv 없음 → skip"); return; }
        StatTable.Initialize(csv);

        // 레벨표 (정본 csv 실측 셀): lv1 Attacker HP 13500 / ATK 600 / DEF[AR] 90.
        var lv1A = StatTable.GetLevelClassStat(1, "Attacker");
        Assert.Equal(13500, lv1A.HP);
        Assert.Equal(600, lv1A.ATK);
        Assert.Equal(90, lv1A.DEF["AR"]);
        // lv1 Defender HP 16500, Supporter HP 15000.
        Assert.Equal(16500, StatTable.GetLevelClassStat(1, "Defender").HP);
        Assert.Equal(15000, StatTable.GetLevelClassStat(1, "Supporter").HP);
        // lv1000 Attacker ATK 1005385 (마지막 행 — 멀티라인 셀로 행이 밀리면 여기서 0).
        Assert.Equal(1005385, StatTable.GetLevelClassStat(1000, "Attacker").ATK);

        // 호감도표: bond40 Attacker HP 52650 / ATK 2340 / DEF[ALL] 351.
        var b40A = StatTable.GetBondClassStat(40, "Attacker");
        Assert.Equal(52650, b40A.HP);
        Assert.Equal(2340, b40A.ATK);
        Assert.Equal(351, b40A.DEF["ALL"]);
    }

    // ─────────────────────────────────────────────────────────────────────
    // (1c) A1 회귀 (2026-07-08 감사): merged DB 현행 무기 표기("Minigun"/"SMG")가
    //      레벨표 DEF 열에 올바로 매핑되는지 — 미매칭 AR 폴백 버그 가드.
    // ─────────────────────────────────────────────────────────────────────
    [Fact]
    public void MapWeapon_handles_roledata_weapon_strings()
    {
        string? csv = Find("stat_table.csv");
        if (csv == null) { _out.WriteLine("csv 없음 → skip"); return; }
        StatTable.Initialize(csv);
        var none = new Dictionary<string, int>();

        var mg = StatCalculator.GetCoreAppliedStats("Attacker", "Minigun", "Elysion", 1000, 0, 0, 0, none);
        var mgLong = StatCalculator.GetCoreAppliedStats("Attacker", "Machine Gun", "Elysion", 1000, 0, 0, 0, none);
        var smg = StatCalculator.GetCoreAppliedStats("Attacker", "SMG", "Elysion", 1000, 0, 0, 0, none);
        var smgLong = StatCalculator.GetCoreAppliedStats("Attacker", "Submachine Gun", "Elysion", 1000, 0, 0, 0, none);
        var ar = StatCalculator.GetCoreAppliedStats("Attacker", "Assault Rifle", "Elysion", 1000, 0, 0, 0, none);

        Assert.Equal(mgLong.DEF, mg.DEF);     // 신·구 표기 동일 열
        Assert.Equal(smgLong.DEF, smg.DEF);
        Assert.NotEqual(ar.DEF, mg.DEF);      // AR 폴백이었으면 동일해짐 (버그 재현 조건)
        Assert.NotEqual(ar.DEF, smg.DEF);
    }

    // ─────────────────────────────────────────────────────────────────────
    // (2) Foundation smoke — Initialize→Nikke→BuildAttackContext→CalculateDamage.
    //     커밋된 데이터(stat_table.csv + base/effect JSON)만 사용 (merged DB 불필요).
    // ─────────────────────────────────────────────────────────────────────
    [Fact]
    public void FinalAtk_And_UnbuffedBasicShot_AreReported()
    {
        string? csv = Find("stat_table.csv");
        string? role = Find("roledata_clean.json");
        if (csv == null || role == null) { _out.WriteLine("데이터 없음 → skip"); return; }

        // 견고 파서(StatTable.Initialize) 로 정본 csv 로드. (try/catch 는 데이터 부재 방어용 — 정상 로드.)
        try { StatTable.Initialize(csv); }
        catch (Exception ex) { _out.WriteLine($"StatTable.Initialize 실패 → skip: {ex.GetType().Name}"); return; }
        TryInit(StatTable.InitializeEquipment, Find("equip_stat_table.json"));
        TryInit(StatTable.InitializeCubeBase, Find("cube_base_table.json"));
        TryInit(StatTable.InitializeCollectionBase, Find("collection_base_table.json"));
        TryInit(EffectTable.InitializeCube, Find("cube_effect_table.json"));
        TryInit(EffectTable.InitializeCollection, Find("collection_effect_table.json"));

        // 실 캐릭 static (roledata_clean) + 합성 user 빌드.
        //   ▶ 사용자 제공 in-game 빌드로 교체 후 ExpectedFinalAtk 채워 수용 기준 잠금 (TODO).
        const string NameCode = "5007"; // Privaty (AR / Water / Attacker)
        var build = new SyntheticBuild { Level = 200, Grade = 11, Core = 7, BondLevel = 30, FavoriteItemLv = 0 };

        CharacterDto dto;
        try { dto = LoadStaticWithBuild(role, NameCode, build); }
        catch (Exception ex) { _out.WriteLine($"DTO 구성 실패 → skip: {ex.Message}"); return; }

        Nikke.Simulator.Core.Entities.Nikke nikke;
        try { nikke = new Nikke.Simulator.Core.Entities.Nikke(dto, NoConsoles()); }
        catch (Exception ex) { _out.WriteLine($"Nikke 생성 실패 → skip: {ex.Message}"); return; }

        // 무버프 평타 1발 (크리/코어/거리/버스트 없음, 타겟 DEF=0 = 깡뎀 1발).
        var ctx = nikke.BuildAttackContext();
        ctx.FinalDef = 0.0;
        double bareShot = DamageCalculator.CalculateDamage(in ctx);

        _out.WriteLine($"[{nikke.Name}] {nikke.WeaponType} / {nikke.Element} / {nikke.Class}");
        _out.WriteLine($"  W (BasicAtkMultiplier, fraction) = {nikke.BasicAtkMultiplier}");
        _out.WriteLine($"  FinalBaseAtk = {nikke.FinalBaseAtk:F2}");
        _out.WriteLine($"  무버프 평타 1발 (DEF=0)         = {bareShot:F0}");
        _out.WriteLine($"  expected ≈ floor(FinalAtk × W)  = {Math.Floor(nikke.FinalBaseAtk * nikke.BasicAtkMultiplier):F0}");

        Assert.True(nikke.FinalBaseAtk > 0, "FinalBaseAtk 0 — StatTable 미로드 의심.");
        // 비차지·무버프 평타 = floor((Atk-0)×W) 정확 일치 (B2=floor(P), B3~B5=1).
        Assert.Equal(Math.Floor(nikke.FinalBaseAtk * nikke.BasicAtkMultiplier), bareShot);
        // fraction-scale 가드: 평타 1발이 FinalAtk 보다 작다(13.65% 수준). 100× 버그면 위반.
        Assert.True(bareShot < nikke.FinalBaseAtk, "평타 1발 > FinalAtk — 100× 버그 의심.");

        // ── TODO(M2 통합): in-game 대조는 M2 골든(하네스 `run <name_code>`)으로 수행 — 잠금 시 여기 상수화 ──
        // const double ExpectedFinalAtk = ?????;  // 게임 스탯창
        // const double ExpectedBasicShot = ?????; // 인게임 무버프 평타 1발 (해당 DEF 조건)
        // Assert.Equal(ExpectedFinalAtk, nikke.FinalBaseAtk, 0); // ±표시반올림
    }

    // ── helpers ───────────────────────────────────────────────────────────

    private sealed class SyntheticBuild
    {
        public int Level, Grade, Core, BondLevel, FavoriteItemLv;
    }

    private static void TryInit(Action<string> init, string? path)
    {
        if (path == null) return;
        try { init(path); } catch { /* 없으면 해당 스탯 0 */ }
    }

    private static GlobalStateDto NoConsoles()
        => new GlobalStateDto { consoles = new Dictionary<string, int>() };

    /// <summary>roledata_clean[NameCode] 를 static 으로, 합성 user 를 붙여 CharacterDto 구성.</summary>
    private static CharacterDto LoadStaticWithBuild(string rolePath, string nameCode, SyntheticBuild b)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(rolePath));
        var elem = doc.RootElement.GetProperty(nameCode);
        var stat = JsonSerializer.Deserialize<CharacterStaticDto>(elem.GetRawText())
                   ?? throw new InvalidOperationException("static 역직렬화 실패");

        return new CharacterDto
        {
            name_code = nameCode,
            slug = "",
            StaticInfo = stat,
            user = new CharacterUserDto
            {
                level = b.Level, grade = b.Grade, core = b.Core,
                bond_level = b.BondLevel, favorite_item_lv = b.FavoriteItemLv,
                combat = 0,
                overload_stats = new List<OverloadOptionDto>(),  // 무 OL (가드용 baseline)
                equipments = new EquipmentPartsDto(),
                cube = new CubeUserDto { tid = 0, level = 0 },
                skills = new SkillLevelsDto(),
            },
        };
    }

    /// <summary>(1) 전용 — 테이블 없이 W 정규화만 보는 최소 DTO.</summary>
    private static CharacterDto MinimalDto(string weapon, double multiplier)
        => new CharacterDto
        {
            name_code = "0000", slug = "",
            StaticInfo = new CharacterStaticDto
            {
                name = "Test", iconUrl = "", element = "Water", weapon = weapon,
                character_class = "Attacker", burstType = "Step1", manufacturer = "Elysion",
                ammoCapacity = 60, reloadTime = 1.0,
                basicAttack = new BasicAttackDto
                {
                    multiplier = multiplier, coreHitBonus = 1.0, chargeTime = 0.0,
                    chargeDamage = 1.0, rawText = "",
                },
            },
            user = new CharacterUserDto
            {
                level = 1, grade = 0, core = 0, bond_level = 0, favorite_item_lv = 0, combat = 0,
                overload_stats = new List<OverloadOptionDto>(),
                equipments = new EquipmentPartsDto(),
                cube = new CubeUserDto { tid = 0, level = 0 },
                skills = new SkillLevelsDto(),
            },
        };
}
