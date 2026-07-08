using System.Globalization;
using System.Text;
using Nikke.Simulator.Core.Data;
using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Stats;
using Nikke.Simulator.Engine;
using Nikke.Simulator.Engine.Combat;
using Nikke.Simulator.Engine.Metrics;
using Nikke.Simulator.Engine.Targets;
using CoreNikke = Nikke.Simulator.Core.Entities.Nikke;

// ─────────────────────────────────────────────────────────────────────────────
// M2 검증 콘솔 하네스 — 실캐릭(merged DB) 1명을 RunOnce 로 굴려 in-game 실측과 대조.
//
//   dotnet run --project SimulatorEngine/Nikke.Simulator.Harness -- list [필터]
//   dotnet run --project SimulatorEngine/Nikke.Simulator.Harness -- run <name_code> [옵션]
//
// 옵션 (기본값):
//   --sec 60            시뮬 길이(초)
//   --runs 1            반복 횟수 (2+ = 분포 통계)
//   --manual            수동 컨트롤 (기본 = 자동)
//   --tap               수동 톡톡이 (기본 = 풀차지; --manual 함의)
//   --charge-err 0      수동 풀차징 인간 오차 상한(초)
//   --reload-buff 0     Σ재장전 속도 버프 (0.5 = 50%; ≥1.0 = 즉시 장전)
//   --def 0             타겟 DEF
//   --dist 0            타겟 거리 (적정거리 판정 — bonusrange 단위)
//   --core 0            타겟 코어 반지름 (0 = 코어힛 없음)
//   --body 0            타겟 몸체 반지름 (0 = 빗맞음 없음)
//
// 필요 데이터 (Database/processed/): stat_table.csv(필수) + nikke_merged_db_returned.json(필수)
//   + equip/cube/collection 표(있으면 반영). merged DB 재생성 = user_state → db_merger.py.
// ─────────────────────────────────────────────────────────────────────────────

Console.OutputEncoding = Encoding.UTF8;
CultureInfo.CurrentCulture = CultureInfo.InvariantCulture;

if (args.Length == 0)
{
    PrintUsage();
    return 1;
}

// ── 데이터 로드 (WPF App.OnStartup 과 동일 패턴) ──
string dbPath;
try
{
    StatTable.Initialize(JsonProvider.GetSmartDatabasePath("stat_table.csv"));
    // --db <경로> = merged DB 오버라이드 (기본 = Database/processed/nikke_merged_db_returned.json)
    int dbOpt = Array.IndexOf(args, "--db");
    dbPath = dbOpt >= 0 && dbOpt + 1 < args.Length
        ? args[dbOpt + 1]
        : JsonProvider.GetSmartDatabasePath("nikke_merged_db_returned.json");
}
catch (Exception ex)
{
    Console.WriteLine($"❌ 데이터 초기화 실패: {ex.Message}");
    Console.WriteLine("   확인: Database/processed/stat_table.csv");
    return 1;
}
TryInit(() => StatTable.InitializeEquipment(JsonProvider.GetSmartDatabasePath("equip_stat_table.json")));
TryInit(() => StatTable.InitializeCubeBase(JsonProvider.GetSmartDatabasePath("cube_base_table.json")));
TryInit(() => StatTable.InitializeCollectionBase(JsonProvider.GetSmartDatabasePath("collection_base_table.json")));
TryInit(() => Nikke.Simulator.Core.Data.Constants.EffectTable.InitializeCube(JsonProvider.GetSmartDatabasePath("cube_effect_table.json")));
TryInit(() => Nikke.Simulator.Core.Data.Constants.EffectTable.InitializeCollection(JsonProvider.GetSmartDatabasePath("collection_effect_table.json")));

if (!File.Exists(dbPath))
{
    Console.WriteLine($"❌ merged DB 없음: {dbPath}");
    Console.WriteLine("   재생성: DataPipeline (user_state → db_merger.py) — 개인 로스터 데이터라 gitignore.");
    return 1;
}
var root = JsonProvider.LoadJson<RootDto>(dbPath);

// ── 커맨드 분기 ──
switch (args[0])
{
    case "list":
        {
            string filter = args.Length > 1 ? args[1] : null;
            Console.WriteLine($"로스터 {root.roster.Count}명 (name_code | 이름 | 무기 | 레벨):");
            foreach (var (nc, c) in root.roster.OrderBy(kv => int.Parse(kv.Key)))
            {
                if (filter != null &&
                    !c.StaticInfo.name.Contains(filter, StringComparison.OrdinalIgnoreCase) &&
                    !nc.Contains(filter))
                    continue;
                Console.WriteLine($"  {nc,6} | {c.StaticInfo.name,-28} | {c.StaticInfo.weapon,-15} | Lv.{c.user.level}");
            }
            return 0;
        }

    case "run":
        {
            if (args.Length < 2) { PrintUsage(); return 1; }
            if (!root.roster.TryGetValue(args[1], out var dto))
            {
                Console.WriteLine($"❌ name_code '{args[1]}' 로스터에 없음. `list` 로 확인.");
                return 1;
            }

            double sec = OptD("--sec", 60);
            int runs = (int)OptD("--runs", 1);
            bool manual = Has("--manual") || Has("--tap");
            var ctl = new FiringControl
            {
                Mode = manual ? ControlMode.Manual : ControlMode.Auto,
                Style = Has("--tap") ? FireStyle.Tap : FireStyle.FullCharge,
                ChargeErrorMaxSec = OptD("--charge-err", 0),
                ReloadSpeedBuff = OptD("--reload-buff", 0),
            };
            var target = new DummyTarget(
                finalDef: OptD("--def", 0),
                distance: OptD("--dist", 0),
                coreRadius: OptD("--core", 0),
                bodyRadius: OptD("--body", 0));

            var nikke = new CoreNikke(dto, root.global_state);
            PrintSpec(nikke, ctl, target, sec);

            var results = new List<RunResult>(runs);
            for (int i = 0; i < runs; i++)
            {
                var team = new[] { new Combatant(nikke, dto.StaticInfo.name) { Firing = ctl } };
                results.Add(SimulationRunner.RunOnce(team, target, SystemRandomSource.Instance, sec));
            }
            PrintResults(results, nikke, sec);
            return 0;
        }

    default:
        PrintUsage();
        return 1;
}

// ── 헬퍼 ──

void PrintUsage()
{
    Console.WriteLine("사용법:");
    Console.WriteLine("  nikke-harness list [필터]");
    Console.WriteLine("  nikke-harness run <name_code> [--sec 60] [--runs 1] [--manual] [--tap]");
    Console.WriteLine("      [--charge-err 0] [--reload-buff 0] [--def 0] [--dist 0] [--core 0] [--body 0]");
}

static void TryInit(Action a)
{
    try { a(); } catch { /* 표 없으면 해당 스탯 0 — WPF 와 동일 정책 */ }
}

double OptD(string key, double dflt)
{
    int i = Array.IndexOf(args, key);
    return i >= 0 && i + 1 < args.Length && double.TryParse(args[i + 1], out var v) ? v : dflt;
}

bool Has(string key) => Array.IndexOf(args, key) >= 0;

static void PrintSpec(CoreNikke n, FiringControl ctl, DummyTarget t, double sec)
{
    var w = n.Weapon;
    Console.WriteLine("─────────────────────────────────────────────");
    Console.WriteLine($"캐릭터   : {n.Name}  ({n.WeaponType} · {n.Class} · {n.Element})");
    Console.WriteLine($"스탯     : ATK {n.FinalBaseAtk:N2} | 탄창 {n.FinalBaseMaxAmmo:N0} | W {n.BasicAtkMultiplier:P2}");
    Console.WriteLine($"무기     : input={w.InputType} rate={w.FireRate:0.##}→{w.EndFireRate:0.##}/s " +
                      $"charge={w.ChargeTimeSec:0.##}s reload={w.ReloadTimeSec:0.##}s pellets={w.ShotCount} " +
                      $"maintain={w.MaintainFireStanceSec:0.##}s");
    Console.WriteLine($"컨트롤   : {ctl.Mode}" +
                      (ctl.Mode == ControlMode.Manual ? $" ({ctl.Style}, chargeErr≤{ctl.ChargeErrorMaxSec}s)" : "") +
                      (ctl.ReloadSpeedBuff > 0 ? $" | 재장전버프(수동지정) {ctl.ReloadSpeedBuff:P0}" : ""));
    if (n.TimingReloadSpeed > 0 || n.TimingChargeSpeed > 0 || n.TimingBurstGauge > 0)
        Console.WriteLine($"큐브효과 : 재장전 {n.TimingReloadSpeed:P2} | 차지 {n.TimingChargeSpeed:P2} | " +
                          $"게이지 {n.TimingBurstGauge:P2}(K9 대기)");
    Console.WriteLine($"타겟     : DEF {t.FinalDef:N0} | dist {t.Distance} | core r{t.CoreRadius} | body r{t.BodyRadius}");
    Console.WriteLine($"적정거리 : {n.ProperRangeMin}~{n.ProperRangeMax} → 보너스 {(t.Distance >= n.ProperRangeMin && t.Distance <= n.ProperRangeMax ? "적용권" : "밖")} (판정은 무기표 기준)");
    Console.WriteLine($"길이     : {sec}s ({sec * 60:N0} frames)");
    Console.WriteLine("─────────────────────────────────────────────");
}

static void PrintResults(List<RunResult> results, CoreNikke n, double sec)
{
    var r = results[0];
    int pellets = Math.Max(1, n.Weapon.ShotCount);

    Console.WriteLine($"[run 1] 총대미지 : {r.TotalDamage:N0}");
    Console.WriteLine($"        DPS      : {r.TotalDamage / r.DurationSec:N1}");
    Console.WriteLine($"        히트 수  : {r.HitCount:N0} (트리거 ≈ {r.HitCount / (double)pellets:N0}" +
                      (pellets > 1 ? $" × 펠릿 {pellets}" : "") + ")");
    double crit = r.DamageByTag.GetValueOrDefault("crit=True");
    double core = r.DamageByTag.GetValueOrDefault("core=True");
    double full = r.DamageByTag.GetValueOrDefault("full=True");
    Console.WriteLine($"        분해     : 크리 {crit:N0} ({Pct(crit, r.TotalDamage)}) | " +
                      $"코어 {core:N0} ({Pct(core, r.TotalDamage)}) | 풀차지 {full:N0} ({Pct(full, r.TotalDamage)})");

    int show = (int)Math.Min(10, r.DamagePerSecond.Count);
    Console.WriteLine($"        초당(첫 {show}s): " +
                      string.Join(" ", r.DamagePerSecond.Take(show).Select(d => d.ToString("N0"))));

    if (results.Count > 1)
    {
        var totals = results.Select(x => x.TotalDamage).OrderBy(x => x).ToList();
        double mean = totals.Average();
        double std = Math.Sqrt(totals.Sum(x => (x - mean) * (x - mean)) / totals.Count);
        Console.WriteLine("─────────────────────────────────────────────");
        Console.WriteLine($"[N={results.Count}] mean {mean:N0} | std {std:N0} ({std / mean:P2}) | " +
                          $"min {totals.First():N0} | max {totals.Last():N0}");
    }
}

static string Pct(double part, double whole) => whole > 0 ? (part / whole).ToString("P1") : "-";
