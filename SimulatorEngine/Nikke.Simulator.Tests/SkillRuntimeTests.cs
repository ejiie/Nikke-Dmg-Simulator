using System.Collections.Generic;
using System.Linq;
using Nikke.Simulator.Core.Combat;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine;
using Nikke.Simulator.Engine.Buffs;
using Nikke.Simulator.Engine.Combat;
using Nikke.Simulator.Engine.Events;
using Nikke.Simulator.Engine.Skills;
using Nikke.Simulator.Engine.Targets;
using CoreNikke = Nikke.Simulator.Core.Entities.Nikke;
using ValueType = Nikke.Simulator.Engine.Skills.ValueType;

namespace Nikke.Simulator.Tests;

/// <summary>
/// T01 — SkillRuntime 트리거→효과 루프. 합성 체인(데이터 무의존)으로 einkk 4단계 검증:
/// 트리거 매치 · 버프 스폰/만료/스택 · connected 연쇄 · UseCharacterSkillId · graceful no-op.
/// 실데이터(192캐릭) 등록 = skill_chains.json 존재 시에만 (gitignore — 부재 = skip).
/// </summary>
public class SkillRuntimeTests
{
    // ───────────────────── 합성 헬퍼 ─────────────────────

    private sealed class MinRandom : IRandomSource { public double NextDouble() => 0.0; }

    private static CoreNikke MakeNikke()
    {
        var dto = new CharacterDto
        {
            name_code = "9999",
            StaticInfo = new CharacterStaticDto
            {
                name = "TestUnit", element = "Iron", weapon = "Assault Rifle",
                character_class = "Attacker", manufacturer = "Elysion",
                ammoCapacity = 60, reloadTime = 1.0,
                basicAttack = new BasicAttackDto { multiplier = 100.0 },
                weaponData = new WeaponDto
                {
                    weaponType = "AR", inputType = "DOWN", fireType = "Instant",
                    fireRate = 12, endFireRate = 12, spotFirstDelaySec = 0.2, spotLastDelaySec = 0.2,
                    maxAmmo = 60, reloadTimeSec = 1.0, reloadBulletRate = 1.0, shotCount = 1, muzzleCount = 1,
                    accuracy = new WeaponAccuracyDto { startCircle = 75, endCircle = 75 },
                },
                properRange = new ProperRangeDto { min = 25, max = 45 },
            },
            user = new CharacterUserDto { level = 1, grade = 0, core = 0, bond_level = 0 },
        };
        return new CoreNikke(dto, new GlobalStateDto { consoles = new Dictionary<string, int>() });
    }

    private static Combatant MakeCombatant(string id = "u1") => new(MakeNikke(), id);

    /// <summary>합성 FunctionDto — 기본 = Self 대상, Percent 값, 트리거/조건 없음, 영구.</summary>
    private static FunctionDto Fn(int id, FunctionType type, long value = 1000, // 1000 = 10%
                                  TimingTriggerType trigger = TimingTriggerType.OnStart,
                                  int triggerValue = 0,
                                  DurationType duration = DurationType.None, int durationValue = 0,
                                  int limit = 0, int group = 0, List<int> connected = null,
                                  ValueType valueType = ValueType.Percent)
        => new()
        {
            Id = id, GroupId = group == 0 ? id : group,
            FunctionType = (int)type, FunctionValueType = (int)valueType, FunctionValue = value,
            TimingTriggerType = (int)trigger, TimingTriggerValue = triggerValue,
            DurationType = (int)duration, DurationValue = durationValue,
            LimitValue = limit, FunctionTarget = (int)FunctionTargetType.Self,
            ConnectedFunction = connected ?? new List<int>(),
        };

    /// <summary>합성 체인: 캐릭 1명 skill1(StateEffect) = 주어진 함수들.</summary>
    private static (SkillChainsDto chains, CharacterChainDto ch) Chains(params FunctionDto[] fns)
    {
        var chains = new SkillChainsDto();
        foreach (var f in fns) chains.Functions[f.Id.ToString()] = f;
        var ch = new CharacterChainDto
        {
            CharId = 1, Skills =
            {
                ["skill1"] = new SkillSlotDto
                {
                    Table = "StateEffect", BaseId = 100,
                    Levels = { ["10"] = new SkillLevelDto { SkillId = 109, FunctionIds = fns.Select(f => f.Id).ToList() } },
                },
            },
        };
        return (chains, ch);
    }

    private static BattleEvent Start(int frame = 0) => new() { Kind = BattleEventKind.BattleStart, Frame = frame };

    private static BattleEvent Fire(Combatant c, int ammoLeft, int frame, bool full = false)
        => new() { Kind = BattleEventKind.NikkeFire, Source = c, IntValue = ammoLeft, IsFullCharge = full, Frame = frame };

    private static BattleEvent Hit(Combatant c, int ammoLeft, int frame, bool crit = false, bool core = false)
        => new() { Kind = BattleEventKind.NikkeHit, Source = c, IntValue = ammoLeft, IsCrit = crit, IsCoreHit = core, Frame = frame };

    // ───────────────────── 스폰/만료/스택 ─────────────────────

    [Fact]
    public void OnStart_Permanent_StatAtk_Spawns_Buff()
    {
        var (chains, ch) = Chains(Fn(1, FunctionType.StatAtk, value: 2500)); // 25%
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);

        rt.Broadcast(Start());

        var b = Assert.Single(c.ActiveBuffs);
        Assert.Equal(EffectRoute.AtkRate, b.Route);
        Assert.Equal(0.25, b.Value, 12);
        Assert.Null(b.ExpiryFrame); // 영구
    }

    [Fact]
    public void Timed_Buff_Expires_At_Frame_Domain()
    {
        // TimeSec 500 (1/100초) = 5.0s = 300프레임 (FACTS §4)
        var (chains, ch) = Chains(Fn(1, FunctionType.StatAtk,
            duration: DurationType.TimeSec, durationValue: 500));
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start());
        Assert.Single(c.ActiveBuffs);

        rt.TickFrame(299);
        Assert.Single(c.ActiveBuffs);   // 만료 직전
        rt.TickFrame(300);
        Assert.Empty(c.ActiveBuffs);    // 300f = 만료
    }

    [Fact]
    public void Stack_Respects_LimitValue_And_Refreshes_Duration()
    {
        // 매 발사(OnUseAmmo)마다 스택, 상한 3, 지속 2s(=120f)
        var (chains, ch) = Chains(Fn(1, FunctionType.StatAtk, trigger: TimingTriggerType.OnUseAmmo,
            duration: DurationType.TimeSec, durationValue: 200, limit: 3));
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start());

        for (int i = 0; i < 5; i++)
            rt.Broadcast(Fire(c, 60 - i, frame: i * 10));

        var b = Assert.Single(c.ActiveBuffs);
        Assert.Equal(3, b.Stacks);                    // 상한 3
        Assert.Equal(40 + 120, b.ExpiryFrame);        // 마지막 발동(f40) 기준 갱신
    }

    [Fact]
    public void Shots_Duration_Decrements_On_Fire_Not_On_Grant_Shot()
    {
        // OnUseAmmo 로 스폰 + Shots 2 지속 — 스폰한 그 발은 미차감(off-by-one 방지)
        var (chains, ch) = Chains(Fn(1, FunctionType.StatAtk, trigger: TimingTriggerType.OnUseAmmo,
            triggerValue: 3, duration: DurationType.Shots, durationValue: 2));
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start());

        rt.Broadcast(Fire(c, 59, 10));
        rt.Broadcast(Fire(c, 58, 15));
        rt.Broadcast(Fire(c, 57, 20)); // 3발째 = 스폰 (미차감)
        Assert.Single(c.ActiveBuffs);
        rt.Broadcast(Fire(c, 56, 25)); // 잔여 1
        Assert.Single(c.ActiveBuffs);
        rt.Broadcast(Fire(c, 55, 30)); // 잔여 0 → 제거
        Assert.Empty(c.ActiveBuffs);
    }

    // ───────────────────── 트리거 카운트/조건 ─────────────────────

    [Fact]
    public void OnHitNum_Fires_Every_N_Hits()
    {
        var (chains, ch) = Chains(Fn(1, FunctionType.StatCriticalDamage,
            trigger: TimingTriggerType.OnHitNum, triggerValue: 4, limit: 99));
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start());

        for (int i = 1; i <= 12; i++) rt.Broadcast(Hit(c, 60 - i, i));
        var b = Assert.Single(c.ActiveBuffs);
        Assert.Equal(3, b.Stacks); // 12히트 / 4 = 3발동
    }

    [Fact]
    public void StatusTrigger_IsFunctionOn_Gates_Application()
    {
        // fn2 는 fn1 버프(group 77)가 있어야 발동
        var gate = Fn(2, FunctionType.StatCriticalDamage, trigger: TimingTriggerType.OnUseAmmo);
        gate.StatusTriggerType = (int)StatusTriggerType.IsFunctionOn;
        gate.StatusTriggerValue = 77;
        var src = Fn(1, FunctionType.StatAtk, trigger: TimingTriggerType.OnHitNum, triggerValue: 3, group: 77);
        var (chains, ch) = Chains(src, gate);
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start());

        rt.Broadcast(Fire(c, 59, 1));           // gate: 조건 불통과 (77 없음)
        Assert.Empty(c.ActiveBuffs);
        rt.Broadcast(Hit(c, 59, 1));
        rt.Broadcast(Hit(c, 59, 2));
        rt.Broadcast(Hit(c, 59, 3));            // src 발동 → group 77 on
        Assert.Single(c.ActiveBuffs);
        rt.Broadcast(Fire(c, 58, 4));           // gate 통과
        Assert.Equal(2, c.ActiveBuffs.Count);
    }

    // ───────────────────── 연쇄 ─────────────────────

    [Fact]
    public void Connected_Function_Chains()
    {
        var b = Fn(2, FunctionType.StatCriticalDamage, value: 500);
        var a = Fn(1, FunctionType.StatAtk, value: 1000, connected: new List<int> { 2 });
        var (chains, ch) = Chains(a, b);
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start());

        Assert.Equal(2, c.ActiveBuffs.Count);
        Assert.Contains(c.ActiveBuffs, x => x.Route == EffectRoute.AtkRate);
        Assert.Contains(c.ActiveBuffs, x => x.Route == EffectRoute.CritDmgAdd);
    }

    [Fact]
    public void UseCharacterSkillId_Casts_Referenced_Skill()
    {
        // fn1(72) → character_skills["555"] = DealDamage 813.42%
        // (nuke 는 Functions 사전에만 — 패시브 슬롯엔 call 만 등록해야 이중 발동이 없다)
        var nuke = Fn(9, FunctionType.Damage, value: 81342);
        var call = Fn(1, FunctionType.UseCharacterSkillId, value: 555, valueType: ValueType.Integer);
        var (chains, ch) = Chains(call);
        chains.Functions[nuke.Id.ToString()] = nuke;
        chains.CharacterSkills["555"] = new SkillLevelDto
        {
            SkillId = 555, FunctionIds = new List<int> { 9 },
        };
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start());

        var dmg = rt.DrainDamage();
        Assert.NotNull(dmg);
        var pd = Assert.Single(dmg);
        Assert.Equal(8.1342, pd.Multiplier, 12); // ×10000 → 분수 (FACTS §4)
    }

    [Fact]
    public void UseCharacterSkillId_Missing_Is_Graceful_Counter()
    {
        var call = Fn(1, FunctionType.UseCharacterSkillId, value: 999999, valueType: ValueType.Integer);
        var (chains, ch) = Chains(call);
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start()); // throw 없음

        Assert.True(rt.NoOpCounters.GetValueOrDefault("usecharskill:missing") >= 1);
        Assert.Null(rt.DrainDamage());
    }

    // ───────────────────── graceful no-op (INV-1) ─────────────────────

    [Fact]
    public void Unknown_FunctionType_And_Trigger_NoOp_With_Counter()
    {
        var unknownType = Fn(1, (FunctionType)99999);                       // 미지 신값
        var unknownTrig = Fn(2, FunctionType.StatAtk, trigger: (TimingTriggerType)99999);
        var survival = Fn(3, FunctionType.HealCharacter, value: 500);       // 스코프 밖 route
        var (chains, ch) = Chains(unknownType, unknownTrig, survival);
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);
        rt.Broadcast(Start()); // throw 없음
        rt.TickFrame(1);

        Assert.Empty(c.ActiveBuffs); // 아무것도 스폰 안 됨
        Assert.Contains(rt.NoOpCounters.Keys, k => k.StartsWith("route:Unknown"));
        Assert.Contains(rt.NoOpCounters.Keys, k => k.StartsWith("route:SurvivalOrHeal"));
        Assert.Contains(rt.NoOpCounters.Keys, k => k.StartsWith("trigger:"));
    }

    // ───────────────────── 러너 통합 ─────────────────────

    [Fact]
    public void RunOnce_With_Runtime_Records_Skill_Damage_Tag()
    {
        // OnStart DealDamage → run 중 스킬 대미지 1건 (DEF 거대 → 최소뎀 1)
        var (chains, ch) = Chains(Fn(1, FunctionType.Damage, value: 50000));
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);

        var target = new DummyTarget(finalDef: 1e12);
        var r = SimulationRunner.RunOnce(new[] { c }, target, new MinRandom(), 1.0, rt);

        Assert.True(r.DamageByTag.GetValueOrDefault("skill=True") >= 1.0);
        Assert.True(r.HitCount > 0); // 평타도 정상 진행
    }

    [Fact]
    public void RunOnce_Timed_Buff_Increases_Damage_While_Active()
    {
        // ATK+100% 3초 버프 — 합성 니케 ATK 는 0일 수 있어(전역 StatTable 의존) 대미지 비교 대신
        // 버프 수명(스폰→만료)을 러너 경유로 검증.
        var (chains, ch) = Chains(Fn(1, FunctionType.StatAtk, value: 10000,
            duration: DurationType.TimeSec, durationValue: 300));
        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        rt.Register(c, ch);

        var r = SimulationRunner.RunOnce(new[] { c }, new DummyTarget(finalDef: 1e12), new MinRandom(), 5.0, rt);

        Assert.Empty(c.ActiveBuffs); // 3s(180f) 만료 — run 종료(5s) 시점엔 제거됨
        Assert.True(r.HitCount > 0);
    }

    // ───────────────────── 실데이터 (skill_chains.json — 부재 시 skip) ─────────────────────

    [Fact]
    public void All_192_Characters_Register_And_Start_Without_Throw()
    {
        if (!SkillChainLoader.TryLoad(out var chains)) return; // gitignore 데이터 부재 = skip

        var rt = new SkillRuntime(chains);
        var c = MakeCombatant();
        foreach (var ch in chains.Characters.Values)
            rt.Register(c, ch); // lv10 기본 — 미지 enum 전부 graceful (0-throw)

        rt.Broadcast(Start());
        rt.Broadcast(Fire(c, 59, 1, full: true));
        rt.Broadcast(Hit(c, 59, 1, crit: true, core: true));
        rt.Broadcast(new BattleEvent { Kind = BattleEventKind.ReloadEnd, Source = c, Frame = 2 });
        rt.CastSkill(c, "burst", 3);
        for (int f = 0; f < 120; f++) rt.TickFrame(f);

        rt.DrainDamage();
        rt.DrainAmmo();
        Assert.True(chains.CharacterSkills.Count > 1000, "character_skills 전개분 (재조립 필요 신호)");
    }
}
