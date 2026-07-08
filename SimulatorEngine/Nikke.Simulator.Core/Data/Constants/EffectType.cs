namespace Nikke.Simulator.Core.Data.Constants
{
    /// <summary>
    /// 큐브/소장품/스킬 특수효과 종류 (description 키워드 → 이 enum). cube_effect_table.json /
    /// collection_effect_table.json 의 "type" 문자열과 1:1 (Enum.TryParse).
    /// 적용 위치·방향 규칙은 Docs/SKILL_DATA_BLABLALINK.md §4.1 참조.
    /// </summary>
    public enum EffectType
    {
        Unknown = 0,

        // 대미지 브래킷 / 무기 계수
        ElementAdvantageDamage, // B5 SumStrongElem
        CoreDamage,             // B2 SumCoreHitBuff
        PartsDamage,            // B3 SumPartsDmg
        PierceDamage,           // B3 SumPierceDmg
        TrueDamage,             // B3 SumTrueDmgBuff
        ChargeDamage,           // charge add
        ChargeDamageMultiplier, // charge mult
        NormalAttackMultiplier, // W × (1+v) — B3 아님!

        // 기초스탯 (rate 버프: stat × (1+Σrate))
        MaxHp,
        Def,
        MaxAmmo,                // 장탄수 rate

        // 무기 타이밍 (sim 루프 대기 — 파싱만)
        ReloadSpeed,
        ReloadRounds,
        ChargeSpeed,
        BurstGauge,

        // 생존 (비대미지 — 파싱만). DamageTaken = 캐릭이 받는 뎀 감소(B4 아님!)
        DamageTaken,
        HealPotency,
        CoverHp,

        // 명중률 버프 — 파싱만. 명중률은 2026-07-02 스코프 진입(Combat.AccuracyModel: 명중원→실확률);
        // 단 이 HitRate 버프 stat 을 모델에 흡수하는 배선은 미구현. (SKILL_DATA_BLABLALINK §4.2)
        HitRate
    }
}
