using System;
using System.Collections.Generic;
using Nikke.Simulator.Core.Data.Dto;

namespace Nikke.Simulator.Core.Stats
{
    /// <summary>
    /// **최종 기초스탯 조립** 전담 — <see cref="StatTable"/> 가 로드한 원천 자료(레벨/호감도/장비 base 표,
    /// 콘솔 규칙)를 받아 in-game 스탯창과 일치하는 native stat 으로 계산한다.
    ///
    /// 책임 분리 (2026-06-30 · 3-way split):
    ///   - <see cref="StatTable"/>     : 원천 자료 **로딩**(CSV/JSON) + raw 테이블 접근 (I/O).
    ///   - <see cref="StatCalculator"/>: 로드된 자료 → **스탯 계산** (이 클래스: 레벨/돌파/코어/호감도/콘솔/장비).
    ///   - <see cref="OverloadProcessor"/> : OL 합산 (니케식 정밀 소수점).
    ///   - <c>Combat.DamageCalculator</c>  : per-tick **대미지** 공식 (스탯과 별개 축).
    /// (이전엔 조립 로직이 StatTable 에, 대미지가 StatCalculator 에 있어 파일명이 역할과 괴리됐었음.)
    ///
    /// ⚠️ 불변식: 실 crawl 데이터로 다캐릭·돌파불변 in-game 0-error 검증됨 (Docs/VERIFICATION_LOG §5).
    /// 공식 문서: Docs/DESIGN.md §3.5 (스탯 조립).
    /// </summary>
    public static class StatCalculator
    {
        // ── 장비 스탯 공식 상수 (blablalink getEquipAttr) ──
        private const double EquipLevelRate = 0.1;   // settings_equip_increase_bouns (레벨당 +10%)
        private const double EquipCorpBonus = 0.3;   // settings_equip_corp_bounus (제조사 일치 +30%)

        /// <summary>
        /// 2차 피드백 공식 완벽 적용: Grade(내림)와 Core(반올림)의 분리 연산 및 정확한 Grade Flat 보너스 반영.
        /// (레벨 base + 돌파 + 돌파 flat + 호감도 + 콘솔 → preCore, 그 위에 코어강화 반올림.)
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
            var baseClass = StatTable.GetLevelClassStat(level, className);
            var (consoleHP, consoleAtk, consoleDef) = GetConsoleStats(className, manufacturer, consoles);
            var bondStat = StatTable.GetBondClassStat(bond, className);

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

        /// <summary>
        /// console_rules.txt 기반: 콘솔 레벨 딕셔너리를 순회하여 직업/기업에 맞는 고정 스탯을 합산.
        /// (로드된 테이블 무관 — consoles dict + 고정 계수만 사용.)
        /// </summary>
        public static (double HP, double ATK, double DEF) GetConsoleStats(
            string className, string manufacturer, Dictionary<string, int> consoles)
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
        /// 장비 4부위의 고정 스탯 합산. 공식(blablalink getEquipAttr):
        ///   stat = round( base × (1 + 0.3·제조사일치 + 0.1·level) )  per (부위, 스탯타입)
        /// base 표는 <see cref="StatTable.TryGetEquipBase"/> 로 조회.
        /// </summary>
        public static (double HP, double ATK, double DEF) GetEquipmentStats(
            string className, string manufacturer, EquipmentPartsDto equips)
        {
            double hp = 0, atk = 0, def = 0;
            if (equips == null || className == null) return (hp, atk, def);

            var parts = new (string slot, EquipmentInfoDto info)[]
            {
                ("head", equips.head), ("torso", equips.torso),
                ("arm", equips.arm), ("leg", equips.leg)
            };

            foreach (var (slot, info) in parts)
            {
                if (info == null || info.tier <= 0) continue;
                if (!StatTable.TryGetEquipBase(className, info.tier, slot, out var b)) continue;

                bool corpMatch = EquipCorpName(info.corp) == manufacturer;
                double mult = 1.0 + (corpMatch ? EquipCorpBonus : 0.0) + EquipLevelRate * info.level;

                hp += Math.Round(b.HP * mult, MidpointRounding.AwayFromZero);
                atk += Math.Round(b.ATK * mult, MidpointRounding.AwayFromZero);
                def += Math.Round(b.DEF * mult, MidpointRounding.AwayFromZero);
            }
            return (hp, atk, def);
        }

        // 니케 무기 종류 → 레벨표 DEF 키 매핑.
        // ⚠ merged DB 의 현행 표기 = roledata_cleaner WEAPON_MAP 산출("Minigun"/"SMG") — prydwen 시절
        //   롱폼("Machine Gun"/"Submachine Gun")과 병행 수용 (2026-07-08 감사 A1: 미매칭 시 AR 폴백으로
        //   MG/SMG 캐릭 DEF 가 AR 열로 계산되던 버그 수정).
        private static string MapWeapon(string w) => w switch
        {
            "Assault Rifle" => "AR",
            "Sniper Rifle" => "SR",
            "Submachine Gun" or "SMG" => "SMG",
            "Shotgun" => "SG",
            "Rocket Launcher" => "RL",
            "Machine Gun" or "Minigun" => "MG",
            _ => "AR"
        };

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
    }
}
