using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Data.Constants;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace Nikke.Simulator.Core.Stats
{
    public static class StatTable
    {
        // 1. 레벨별 기본 스탯 (Level -> Class -> Stats)
        private static Dictionary<int, ClassStats> _levelStats = new Dictionary<int, ClassStats>();

        // 2. 호감도 보너스 (BondLevel -> Class -> Stats)
        private static Dictionary<int, ClassStats> _bondStats = new Dictionary<int, ClassStats>();

        // 3. 소장품 base 스탯 (CollLevel -> ATK/HP/DEF). blablalink collection_base_table.json.
        private static Dictionary<int, (double atk, double hp, double def)> _collBase = new();

        public class ClassStats
        {
            public FlatStats Attacker { get; set; } = new FlatStats();
            public FlatStats Defender { get; set; } = new FlatStats();
            public FlatStats Supporter { get; set; } = new FlatStats();
        }

        public class FlatStats
        {
            public double HP { get; set; }
            public double ATK { get; set; }
            // 무기별 방어력이 다르므로 딕셔너리로 관리
            public Dictionary<string, double> DEF { get; set; } = new Dictionary<string, double>();
        }

        // 4. 큐브 base 스탯 (CubeLevel -> ATK/HP/DEF). blablalink cube_base_table.json.
        private static Dictionary<int, (double atk, double hp, double def)> _cubeBase = new();

        /// <summary>레벨/호감도 테이블을 stat_table.csv 에서 로드 (큐브/소장품 base 는 별도 JSON).</summary>
        public static void Initialize(string csvPath)
        {
            if (!File.Exists(csvPath)) throw new FileNotFoundException("CSV 파일이 없어, 허접군!");

            var lines = File.ReadAllLines(csvPath);

            // --- [1. 호감도 테이블 파싱 (Row 3-42, Col 26-36)] ---
            for (int i = 3; i <= 42; i++)
            {
                var cols = SplitCsvLine(lines[i]);
                int bondLv = ParseInt(cols[26]);
                _bondStats[bondLv] = new ClassStats
                {
                    Attacker = new FlatStats { HP = ParseDouble(cols[28]), ATK = ParseDouble(cols[29]), DEF = { ["ALL"] = ParseDouble(cols[30]) } },
                    Defender = new FlatStats { HP = ParseDouble(cols[31]), ATK = ParseDouble(cols[32]), DEF = { ["ALL"] = ParseDouble(cols[33]) } },
                    Supporter = new FlatStats { HP = ParseDouble(cols[34]), ATK = ParseDouble(cols[35]), DEF = { ["ALL"] = ParseDouble(cols[36]) } }
                };
            }

            // --- [2. 레벨 테이블 파싱 (Row 6-1005, Col 0-24)] ---
            for (int i = 6; i <= 1005; i++)
            {
                var cols = SplitCsvLine(lines[i]);
                int lv = ParseInt(cols[0]);
                _levelStats[lv] = new ClassStats
                {
                    Attacker = CreateClassStat(cols, 1, 2, 3),
                    Defender = CreateClassStat(cols, 9, 10, 11),
                    Supporter = CreateClassStat(cols, 17, 18, 19)
                };
            }

            // 큐브/소장품 base 스탯 + 특수효과는 stat_table.csv 가 아니라 blablalink 공식 JSON 으로 이전됨
            // (cube_base_table / collection_base_table / cube_effect_table / collection_effect_table).
            // Initialize 는 레벨/호감도(섹션 1~2)만 CSV 에서 읽는다. base 표는 InitializeCubeBase/
            // InitializeCollectionBase 가 별도 로드.
        }

        // 큐브/소장품 base 표 JSON 로더 ({"<level>": {"ATK","HP","DEF"}}).
        private static Dictionary<int, (double atk, double hp, double def)> LoadBase(string jsonPath)
        {
            var result = new Dictionary<int, (double, double, double)>();
            if (string.IsNullOrEmpty(jsonPath) || !File.Exists(jsonPath)) return result;
            var raw = JsonSerializer.Deserialize<Dictionary<string, Dictionary<string, double>>>(File.ReadAllText(jsonPath));
            if (raw == null) return result;
            foreach (var kv in raw)
                if (int.TryParse(kv.Key, out int lv))
                {
                    var s = kv.Value;
                    result[lv] = (s.GetValueOrDefault("ATK"), s.GetValueOrDefault("HP"), s.GetValueOrDefault("DEF"));
                }
            return result;
        }

        public static void InitializeCubeBase(string jsonPath) => _cubeBase = LoadBase(jsonPath);
        public static void InitializeCollectionBase(string jsonPath) => _collBase = LoadBase(jsonPath);

        /// <summary>큐브 레벨의 base 스탯 (없으면 15레벨 폴백, 그래도 없으면 0).</summary>
        public static CubeStatDto GetCubeStat(int level = 15)
        {
            if (!_cubeBase.TryGetValue(level, out var b) && !_cubeBase.TryGetValue(15, out b))
                return new CubeStatDto();
            return new CubeStatDto { Level = level, Atk = b.atk, HP = b.hp, Def = b.def };
        }

        /// <summary>소장품(generic 컬렉션) 레벨의 base 스탯 (HP, ATK, DEF).</summary>
        public static (double HP, double ATK, double DEF) GetCollectionStats(int collLv)
        {
            return _collBase.TryGetValue(collLv, out var b) ? (b.hp, b.atk, b.def) : (0, 0, 0);
        }

        /// <summary>
        /// 2차 피드백 공식 완벽 적용: Grade(내림)와 Core(반올림)의 분리 연산 및 정확한 Grade Flat 보너스 반영
        /// </summary>
        /// <param name="className">니케 클래스 (Attacker, Defender, Supporter)</param>
        /// <param name="weaponType">니케 무기 종류</param>
        /// <param name="manufacturer">니케 소속 기업</param>
        /// <param name="level">니케 레벨</param>
        /// <param name="grade">한계돌파 횟수</param>
        /// <param name="core">코어강화 횟수</param>
        /// <param name="bond">호감도 레벨</param>
        /// <param name="consoles">전역 콘솔 딕셔너리</param>
        /// <returns>코어강화까지 수학적으로 적용이 완료된 순수 육성 스탯 튜플</returns>
        public static (double HP, double ATK, double DEF) GetCoreAppliedStats(
            string className, string weaponType, string manufacturer,
            int level, int grade, int core, int bond,
            Dictionary<string, int> consoles)
        {
            var baseClass = GetClassStatFromTable(_levelStats, level, className);
            var (consoleHP, consoleAtk, consoleDef) = GetConsoleStats(className, manufacturer, consoles);
            var bondStat = GetClassStatFromTable(_bondStats, bond, className);

            double gradeFlatHP = 3000 * grade;
            double gradeFlatAtk = 20 * grade;
            double gradeFlatDef = 100 * grade;

            // --- Step 1. Pre-Core Stat 산출 ---
            // 공식: lvStat + ROUNDDOWN(lvStat * grade * 0.02) + (gradeFlatStat) + bondStat + consoleStat
            double lvHP = baseClass.HP;
            double lvAtk = baseClass.ATK;
            double lvDef = baseClass.DEF[MapWeapon(weaponType)];

            double preCoreHP = lvHP + Math.Floor(lvHP * grade * 0.02) + gradeFlatHP + bondStat.HP + consoleHP;
            double preCoreAtk = lvAtk + Math.Floor(lvAtk * grade * 0.02) + gradeFlatAtk + bondStat.ATK + consoleAtk;
            double preCoreDef = lvDef + Math.Floor(lvDef * grade * 0.02) + gradeFlatDef + bondStat.DEF["ALL"] + consoleDef;

            // --- Step 2. Final Core Stat 산출 (baseAtk 중 consts 합산 전) ---
            // 공식: atk + ROUND(atk * 0.02 * core, 0)
            double finalHP = preCoreHP + Math.Round(preCoreHP * core * 0.02, MidpointRounding.AwayFromZero);
            double finalAtk = preCoreAtk + Math.Round(preCoreAtk * core * 0.02, MidpointRounding.AwayFromZero);
            double finalDef = preCoreDef + Math.Round(preCoreDef * core * 0.02, MidpointRounding.AwayFromZero);

            return (finalHP, finalAtk, finalDef);
        }

        // --- [내부 헬퍼 함수들] ---
        private static FlatStats CreateClassStat(string[] cols, int hpIdx, int atkIdx, int defStartIdx) => new FlatStats
        {
            HP = ParseDouble(cols[hpIdx]),
            ATK = ParseDouble(cols[atkIdx]),
            DEF = new Dictionary<string, double>
            {
                ["AR"] = ParseDouble(cols[defStartIdx]),
                ["SR"] = ParseDouble(cols[defStartIdx + 1]),
                ["SMG"] = ParseDouble(cols[defStartIdx + 2]),
                ["SG"] = ParseDouble(cols[defStartIdx + 3]),
                ["RL"] = ParseDouble(cols[defStartIdx + 4]),
                ["MG"] = ParseDouble(cols[defStartIdx + 5])
            }
        };

        private static FlatStats GetClassStatFromTable(Dictionary<int, ClassStats> table, int key, string className)
        {
            if (!table.TryGetValue(key, out var cs)) return new FlatStats { DEF = { ["ALL"] = 0, ["AR"] = 0, ["SR"] = 0, ["SMG"] = 0, ["SG"] = 0, ["RL"] = 0, ["MG"] = 0 } };
            return (className == "Attacker") ? cs.Attacker : (className == "Defender" ? cs.Defender : cs.Supporter);
        }

        private static string MapWeapon(string w) => w switch
        {
            "Assault Rifle" => "AR",
            "Sniper Rifle" => "SR",
            "Submachine Gun" => "SMG",
            "Shotgun" => "SG",
            "Rocket Launcher" => "RL",
            "Machine Gun" => "MG",
            _ => "AR"
        };

        private static string[] SplitCsvLine(string line) => line.Split(',');
        private static double ParseDouble(string s) => double.TryParse(s.Replace("\"", "").Replace("%", "").Trim(), NumberStyles.Any, CultureInfo.InvariantCulture, out var v) ? v : 0;
        private static int ParseInt(string s) => int.TryParse(s.Trim(), out var v) ? v : 0;

        /// <summary>
        /// console_rules.txt 기반: 콘솔 레벨 딕셔너리를 순회하여 직업/기업에 맞는 고정 스탯을 합산.
        /// </summary>
        public static (double HP, double ATK, double DEF) GetConsoleStats(string className, string manufacturer, Dictionary<string, int> consoles)
        {
            double hp = 0, atk = 0, def = 0;
            if (consoles == null || consoles.Count == 0) return (hp, atk, def);

            // 1. 공용 콘솔 (1001)
            if (consoles.TryGetValue("1001", out int commonLv))
            {
                hp += commonLv * 450;
            }

            // 2. 클래스 콘솔 (1101: 화력, 1102: 방어, 1103: 지원)
            string classCode = className switch
            {
                "Attacker" => "1101",
                "Defender" => "1102",
                "Supporter" => "1103",
                _ => ""
            };
            if (!string.IsNullOrEmpty(classCode) && consoles.TryGetValue(classCode, out int classLv))
            {
                hp += classLv * 750;
                def += classLv * 5;
            }

            // 3. 기업 콘솔 (1201: 엘리시온, 1202: 미실리스, 1203: 테트라, 1204: 필그림, 1205: 어브노멀)
            string manuCode = manufacturer switch
            {
                "Elysion" => "1201",
                "Missilis" => "1202",
                "Tetra" => "1203",
                "Pilgrim" => "1204",
                "Abnormal" => "1205",
                _ => ""
            };
            if (!string.IsNullOrEmpty(manuCode) && consoles.TryGetValue(manuCode, out int manuLv))
            {
                atk += manuLv * 25;
                def += manuLv * 5;
            }

            return (hp, atk, def);
        }

        // ── 장비 base 스탯 표 (class → tier(str) → slot → {ATK,HP,DEF}) ──
        // equip_stat_table.json (blablalink ItemEquipTable 에서 ETL). 레벨 스탯은 별도표가
        // 아니라 공식(아래)으로 계산하므로 여기엔 level 0 base 만 담는다.
        public class EquipBaseStat
        {
            public double ATK { get; set; }
            public double HP { get; set; }
            public double DEF { get; set; }
        }

        private static Dictionary<string, Dictionary<string, Dictionary<string, EquipBaseStat>>> _equipTable
            = new Dictionary<string, Dictionary<string, Dictionary<string, EquipBaseStat>>>();

        private const double EquipLevelRate = 0.1;   // settings_equip_increase_bouns (레벨당 +10%)
        private const double EquipCorpBonus = 0.3;   // settings_equip_corp_bounus (제조사 일치 +30%)

        /// <summary>equip_stat_table.json 로드. 없으면 빈 표(장비 스탯 0).</summary>
        public static void InitializeEquipment(string jsonPath)
        {
            if (string.IsNullOrEmpty(jsonPath) || !File.Exists(jsonPath)) return;
            var parsed = JsonSerializer.Deserialize<
                Dictionary<string, Dictionary<string, Dictionary<string, EquipBaseStat>>>>(
                File.ReadAllText(jsonPath));
            if (parsed != null) _equipTable = parsed;
        }

        // 장비 corporation_type(int) → 기업명. 캐릭 manufacturer 와 비교용.
        private static string EquipCorpName(int corp) => corp switch
        {
            1 => "Elysion",
            2 => "Missilis",
            3 => "Tetra",
            4 => "Pilgrim",
            7 => "Abnormal",
            _ => null
        };

        /// <summary>
        /// 장비 4부위의 고정 스탯 합산. 공식(blablalink getEquipAttr):
        ///   stat = round( base × (1 + 0.3·제조사일치 + 0.1·level) )  per (부위, 스탯타입)
        /// </summary>
        public static (double HP, double ATK, double DEF) GetEquipmentStats(
            string className, string manufacturer, EquipmentPartsDto equips)
        {
            double hp = 0, atk = 0, def = 0;
            if (equips == null || className == null
                || !_equipTable.TryGetValue(className, out var tierMap))
                return (hp, atk, def);

            var parts = new (string slot, EquipmentInfoDto info)[]
            {
                ("head", equips.head), ("torso", equips.torso),
                ("arm", equips.arm), ("leg", equips.leg)
            };

            foreach (var (slot, info) in parts)
            {
                if (info == null || info.tier <= 0) continue;
                if (!tierMap.TryGetValue(info.tier.ToString(), out var slotMap)) continue;
                if (!slotMap.TryGetValue(slot, out var b)) continue;

                bool corpMatch = EquipCorpName(info.corp) == manufacturer;
                double mult = 1.0 + (corpMatch ? EquipCorpBonus : 0.0) + EquipLevelRate * info.level;

                hp += Math.Round(b.HP * mult, MidpointRounding.AwayFromZero);
                atk += Math.Round(b.ATK * mult, MidpointRounding.AwayFromZero);
                def += Math.Round(b.DEF * mult, MidpointRounding.AwayFromZero);
            }
            return (hp, atk, def);
        }
    }
}