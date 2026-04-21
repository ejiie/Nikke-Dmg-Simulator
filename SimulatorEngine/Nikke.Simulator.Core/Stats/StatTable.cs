using Nikke.Simulator.Core.Data.Dto;
using Nikke.Simulator.Core.Data.Constants;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;

namespace Nikke.Simulator.Core.Stats
{
    public static class StatTable
    {
        // 1. 레벨별 기본 스탯 (Level -> Class -> Stats)
        private static Dictionary<int, ClassStats> _levelStats = new Dictionary<int, ClassStats>();

        // 2. 호감도 보너스 (BondLevel -> Class -> Stats)
        private static Dictionary<int, ClassStats> _bondStats = new Dictionary<int, ClassStats>();

        // 3. 소장품(SR) 보너스 (CollLevel -> Stats)
        private static Dictionary<int, FlatStats> _srCollectionStats = new Dictionary<int, FlatStats>();

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

        /// <summary>
        /// 복잡한 CSV 구조를 파싱해서 메모리에 적재한다!
        /// </summary>
        private static Dictionary<int, CubeStatDto> _cubeTable = new Dictionary<int, CubeStatDto>();
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

            // --- [3. 소장품(SR) 테이블 파싱 (Row 49-64) 및 특수 효과 등록] ---
            FlatStats lastValid = null;
            for (int i = 49; i <= 64; i++)
            {
                var cols = SplitCsvLine(lines[i]);

                // Index 48(AW)까지 접근해야 하므로 컬럼 갯수 방어 코드 삽입
                if (cols.Length <= 48) continue;

                int collLv = ParseInt(cols[26]);

                // [3-A] 깡스탯 추출 (Forward Fill 유지)
                if (!string.IsNullOrWhiteSpace(cols[28]))
                {
                    lastValid = new FlatStats
                    {
                        HP = ParseDouble(cols[28]),
                        ATK = ParseDouble(cols[30]),
                        DEF = { ["ALL"] = ParseDouble(cols[32]) }
                    };
                }
                _srCollectionStats[collLv] = lastValid;

                // [3-B] 특수 스킬(배율/기믹) 데이터 추출 및 분리 저장 (요구사항 B 반영)
                // SMG(38)와 SG(40)는 둘 다 평타 배율이므로 구조체의 단일 파라미터로 병합 (어차피 동시 적용 불가)
                double smgAtk = ParseDouble(cols[38]);
                double sgAtk = ParseDouble(cols[40]);

                var effectDto = new CollectionEffectDto(
                    coreDmg: ParseDouble(cols[34]),         // AI: AR 코어 대미지 증가
                    chargeDmg: ParseDouble(cols[36]),       // AK, AQ: SR, RL 차징 배율 증가
                    normalAtk: Math.Max(smgAtk, sgAtk),     // AM, AO: SMG, SG 평타딜 배율 증가
                    maxAmmo: ParseDouble(cols[44]),         // AS: MG 장탄수 증가
                    defInc: ParseDouble(cols[46]),          // AU: 공통 방어력 증가
                    dmgTakenRed: ParseDouble(cols[47]),     // AV: 공통 받는 대미지 감소
                    coverHp: ParseDouble(cols[48])          // AW: 공통 엄폐물 체력 증가
                );

                // 정적 배율 저장소에 주입 (StatTable과 로직 완전 분리)
                CollectionEffectTable.RegisterEffect(collLv, effectDto);
            }

            // --- [4. 하모니 큐브 테이블 파싱 (Row 4~23, Col 38~42 기준)] ---
            foreach (var line in lines.Skip(4)) // 헤더 건너뛰기
            {
                var cols = line.Split(',');
                if (cols.Length < 43 || string.IsNullOrWhiteSpace(cols[38])) continue;

                int lv = ParseInt(cols[38]);
                if (lv == 0) continue;

                _cubeTable[lv] = new CubeStatDto
                {
                    Level = lv,
                    Atk = ParseDouble(cols[39]),
                    Def = ParseDouble(cols[40]),
                    HP = ParseDouble(cols[41]),
                    SuperiorCodeDmg = ParseDouble(cols[42]),
                    SkillLevel = ParseInt(cols[43]) // 1슬롯 레벨
                };

                if (lv >= 20) break; // 큐브 데이터 끝부분
            }
        }

        /// <summary>
        /// 특정 레벨의 큐브 스탯을 가져오기(없으면 15레벨을 디폴트로)
        /// </summary>
        public static CubeStatDto GetCubeStat(int level = 15)
        {
            if (_cubeTable.TryGetValue(level, out var stat)) return stat;
            return _cubeTable.ContainsKey(15) ? _cubeTable[15] : new CubeStatDto();
        }


        /// <summary>
        /// [신설] 소장품(애장품) 스탯은 consts 그룹이므로 코어 계산에서 제외하고 별도로 추출합니다.
        /// </summary>
        public static (double HP, double ATK, double DEF) GetCollectionStats(int collLv)
        {
            if (_srCollectionStats.TryGetValue(collLv, out var collStat) && collStat != null)
            {
                return (collStat.HP, collStat.ATK, collStat.DEF["ALL"]);
            }
            return (0, 0, 0);
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

        /// <summary>
        /// 장비 객체를 기반으로 부위별/티어별/레벨별 장비 고정 스탯을 합산합니다.
        /// </summary>
        public static (double HP, double ATK, double DEF) GetEquipmentStats(EquipmentPartsDto equips)
        {
            double hp = 0, atk = 0, def = 0;
            if (equips == null) return (hp, atk, def);

            // TODO: 실제 장비 스탯 CSV 테이블 연동 필요! (Tier, Level 기준)
            // 예: hp += HeadTable[equips.head.tier][equips.head.level].HP;
            // 예: atk += ArmTable[equips.arm.tier][equips.arm.level].ATK;

            return (hp, atk, def);
        }
    }
}