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

        /// <summary>
        /// 레벨/호감도 테이블을 stat_table.csv 에서 로드 (큐브/소장품 base 는 별도 JSON).
        ///
        /// **견고 파서**: Excel 내보내기 변형에 내성 — 인코딩(cp949/UTF-8), 따옴표, **셀 내부 줄바꿈**
        /// (Alt+Enter, 헤더 멀티라인), 천단위 콤마("13,500") 모두 처리.
        /// 행 위치는 **내용 기반 탐지**: 레벨표 = col0 가 "1" 인 행부터, 호감도표 = col26 가 "1" 인 행부터.
        /// → 선두 헤더 행 수가 바뀌어도 안전(과거: 하드코딩 행번호가 멀티라인 셀로 어긋나 IndexOutOfRange).
        /// 열 매핑은 고정(검증된 0-error 레이아웃): 레벨 Att(1,2,3-8)/Def(9,10,11-16)/Sup(17,18,19-24);
        /// 호감도 Att(28,29,30)/Def(31,32,33)/Sup(34,35,36), DEF=무기무관 "ALL".
        /// </summary>
        public static void Initialize(string csvPath)
        {
            if (!File.Exists(csvPath)) throw new FileNotFoundException($"stat_table.csv 없음: {csvPath}");

            // Latin1 = 바이트 1:1 디코딩(절대 throw 안 함). 숫자 셀은 ASCII 라 안전; 한글 헤더는 미사용.
            var rows = ParseCsv(File.ReadAllText(csvPath, System.Text.Encoding.Latin1));

            // --- [1] 레벨 테이블: col0 == "1" 부터 col0 가 양의 정수인 동안 ---
            int lvStart = FindRow(rows, r => r.Length > 24 && r[0].Trim() == "1" && IsNum(r, 1) && IsNum(r, 2));
            for (int i = lvStart; i >= 0 && i < rows.Count; i++)
            {
                var cols = rows[i];
                if (cols.Length < 25 || !int.TryParse(cols[0].Trim(), out int lv) || lv <= 0) break;
                _levelStats[lv] = new ClassStats
                {
                    Attacker = CreateClassStat(cols, 1, 2, 3),
                    Defender = CreateClassStat(cols, 9, 10, 11),
                    Supporter = CreateClassStat(cols, 17, 18, 19)
                };
            }

            // --- [2] 호감도 테이블: col26 == "1" 부터 col26 가 양의 정수인 동안 ---
            int bStart = FindRow(rows, r => r.Length > 36 && r[26].Trim() == "1" && IsNum(r, 27));
            for (int i = bStart; i >= 0 && i < rows.Count; i++)
            {
                var cols = rows[i];
                if (cols.Length < 37 || !int.TryParse(cols[26].Trim(), out int bondLv) || bondLv <= 0) break;
                _bondStats[bondLv] = new ClassStats
                {
                    Attacker = new FlatStats { HP = ParseDouble(cols[28]), ATK = ParseDouble(cols[29]), DEF = { ["ALL"] = ParseDouble(cols[30]) } },
                    Defender = new FlatStats { HP = ParseDouble(cols[31]), ATK = ParseDouble(cols[32]), DEF = { ["ALL"] = ParseDouble(cols[33]) } },
                    Supporter = new FlatStats { HP = ParseDouble(cols[34]), ATK = ParseDouble(cols[35]), DEF = { ["ALL"] = ParseDouble(cols[36]) } }
                };
            }

            // 큐브/소장품 base 스탯 + 특수효과는 stat_table.csv 가 아니라 blablalink 공식 JSON 으로 이전됨
            // (cube_base_table / collection_base_table / cube_effect_table / collection_effect_table).
            // Initialize 는 레벨/호감도(섹션 1~2)만 CSV 에서 읽는다. base 표는 InitializeCubeBase/
            // InitializeCollectionBase 가 별도 로드.
        }

        // ── 견고 CSV 파서 (RFC4180 핵심): 따옴표 필드 안의 콤마·줄바꿈을 보존, "" = 이스케이프 따옴표 ──
        private static List<string[]> ParseCsv(string text)
        {
            var rows = new List<string[]>();
            var row = new List<string>();
            var field = new System.Text.StringBuilder();
            bool inQuotes = false, rowHasContent = false;

            void EndField() { row.Add(field.ToString()); field.Clear(); }
            void EndRow() { EndField(); rows.Add(row.ToArray()); row = new List<string>(); rowHasContent = false; }

            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                if (inQuotes)
                {
                    if (c == '"')
                    {
                        if (i + 1 < text.Length && text[i + 1] == '"') { field.Append('"'); i++; }
                        else inQuotes = false;
                    }
                    else field.Append(c); // 따옴표 안의 콤마/줄바꿈은 그대로 필드 내용
                }
                else
                {
                    switch (c)
                    {
                        case '"': inQuotes = true; rowHasContent = true; break;
                        case ',': EndField(); rowHasContent = true; break;
                        case '\r': break;                 // \r\n 의 \r 무시
                        case '\n': EndRow(); break;       // 따옴표 밖 줄바꿈 = 행 종료
                        default: field.Append(c); rowHasContent = true; break;
                    }
                }
            }
            if (rowHasContent || field.Length > 0) EndRow();
            return rows;
        }

        private static int FindRow(List<string[]> rows, Func<string[], bool> pred)
        {
            for (int i = 0; i < rows.Count; i++) if (pred(rows[i])) return i;
            return -1;
        }

        private static bool IsNum(string[] cols, int idx)
            => idx < cols.Length
               && double.TryParse(cols[idx].Replace("\"", "").Replace(",", "").Replace("%", "").Trim(),
                                  NumberStyles.Any, CultureInfo.InvariantCulture, out _)
               && cols[idx].Trim().Length > 0;

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

        /// <summary>레벨표의 (레벨, 클래스) raw 기초 스탯. 미존재 = 0 채움. (계산은 StatCalculator 책임.)</summary>
        public static FlatStats GetLevelClassStat(int level, string className)
            => GetClassStatFromTable(_levelStats, level, className);

        /// <summary>호감도표의 (호감도레벨, 클래스) raw 보너스 스탯. 미존재 = 0 채움.</summary>
        public static FlatStats GetBondClassStat(int bond, string className)
            => GetClassStatFromTable(_bondStats, bond, className);

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

        private static double ParseDouble(string s) => double.TryParse(s.Replace("\"", "").Replace(",", "").Replace("%", "").Trim(), NumberStyles.Any, CultureInfo.InvariantCulture, out var v) ? v : 0;

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

        /// <summary>equip_stat_table.json 로드. 없으면 빈 표(장비 스탯 0).</summary>
        public static void InitializeEquipment(string jsonPath)
        {
            if (string.IsNullOrEmpty(jsonPath) || !File.Exists(jsonPath)) return;
            var parsed = JsonSerializer.Deserialize<
                Dictionary<string, Dictionary<string, Dictionary<string, EquipBaseStat>>>>(
                File.ReadAllText(jsonPath));
            if (parsed != null) _equipTable = parsed;
        }

        /// <summary>(class, tier, slot) 의 raw 장비 base 스탯 조회. 미존재 = false.
        /// 레벨/제조사 보정 공식은 StatCalculator.GetEquipmentStats 책임.</summary>
        public static bool TryGetEquipBase(string className, int tier, string slot, out EquipBaseStat baseStat)
        {
            baseStat = null;
            return className != null
                && _equipTable.TryGetValue(className, out var tierMap)
                && tierMap.TryGetValue(tier.ToString(), out var slotMap)
                && slotMap.TryGetValue(slot, out baseStat);
        }
    }
}