using System;
using Nikke.Simulator.Core.Combat;

namespace Nikke.Simulator.Engine.Targets
{
    /// <summary>
    /// solo raid 보스 타겟 (T04 / 구 K11) — <see cref="SoloRaidBossDto"/> 데이터 기반 <see cref="ITarget"/>.
    ///
    /// MVP 스코프(사용자 확정 2026-07-10): 스탯/파츠 존재/상성만. 기믹(QTE·상태 변화·무적 페이즈)
    /// = 기초 완성 후 확장. 보스 가해 대미지(생존 시뮬)·파츠별 HP 트래킹 = 확장 단계.
    ///
    /// 지오메트리(코어/몸체 반지름) = roledata 에 없는 설정 상수 (FACTS §8) — 생성 파라미터.
    /// 기본 0 = 판정 생략 (코어힛 없음 / 항상 명중) — SimulationRunner 계약과 동일.
    /// </summary>
    public sealed class BossTarget : ITarget
    {
        public double FinalDef { get; }
        public bool HasParts { get; }
        public string Element { get; }
        public double Distance { get; }
        public double CoreRadius { get; }
        public double BodyRadius { get; }
        public bool IsBoss => true;

        /// <summary>보스 HP (Lv 스케일) — 생존/킬타임 확장용 노출 (MVP 대미지 계산엔 미사용).</summary>
        public double MaxHp { get; }
        /// <summary>보스 ATK (Lv 스케일) — 보스→니케 대미지(동일 구조, FACTS §1) 확장용 노출.</summary>
        public double Attack { get; }
        /// <summary>변종 코드 (예 "ebg001_island_zeus").</summary>
        public string Code { get; }
        /// <summary>MonsterTable id — skill_chains.json `bosses` 섹션 키 (보스 passive/스킬 체인 연결).
        /// 미링크 변종(xba001_psid) = null.</summary>
        public long? MonsterId { get; }
        public int Level { get; }

        public BossTarget(SoloRaidBossDto dto, int level,
                          double distance = 0.0, double coreRadius = 0.0, double bodyRadius = 0.0)
        {
            if (dto == null) throw new ArgumentNullException(nameof(dto));
            if (!dto.Stats.TryGetValue(level.ToString(), out var st))
                throw new ArgumentOutOfRangeException(nameof(level),
                    $"'{dto.Code}' 레벨 {level} 없음 — 유효 레벨: [{string.Join(", ", dto.Levels)}]");

            Code = dto.Code;
            MonsterId = dto.MonsterId;
            Level = level;
            FinalDef = st.Defence;
            MaxHp = st.Hp;
            Attack = st.Attack;
            Element = dto.Elements != null && dto.Elements.Count > 0 ? dto.Elements[0] : "";
            HasParts = dto.PartsCount > 0;
            Distance = distance;
            CoreRadius = coreRadius;
            BodyRadius = bodyRadius;
        }

        /// <summary>
        /// 데이터 파일에서 변종 검색 후 생성. 데이터 부재/미발견 = false (graceful — INV).
        /// <paramref name="codeOrMonsterId"/> = code("ebg001_island_zeus") 또는 monster_id.
        /// </summary>
        public static bool TryCreate(string codeOrMonsterId, int level, out BossTarget target,
                                     double distance = 0.0, double coreRadius = 0.0, double bodyRadius = 0.0,
                                     string explicitPath = null)
        {
            target = null;
            if (!SoloRaidBossTable.TryLoad(out var bosses, explicitPath)) return false;
            var dto = SoloRaidBossTable.Find(bosses, codeOrMonsterId);
            if (dto == null || !dto.Stats.ContainsKey(level.ToString())) return false;
            target = new BossTarget(dto, level, distance, coreRadius, bodyRadius);
            return true;
        }

        public void PopulateContext(ref AttackContext ctx, string attackerElement, string attackerWeaponType)
        {
            ctx.FinalDef = FinalDef;
            // 속성 상성 — 단일 소스 = ElementAdvantage (FACTS §7-5; OL IncElementDmg 등은 별축).
            ctx.SumStrongElem += ElementAdvantage.GetBonus(attackerElement, Element);
            ctx.ProperDistanceBonus = ProperDistanceTable.GetBonus(attackerWeaponType, Distance);
        }
    }
}
