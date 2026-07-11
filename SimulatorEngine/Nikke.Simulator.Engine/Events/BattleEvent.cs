using Nikke.Simulator.Engine.Combat;

namespace Nikke.Simulator.Engine.Events
{
    /// <summary>
    /// 전투 이벤트 종류 (T01 — einkk battle/events 대응). SimulationRunner 프레임 루프가 발행,
    /// SkillRuntime 이 TimingTrigger 매치로 소비. T01 스코프 밖 이벤트(버스트/HP)는 계약만 —
    /// 발행자는 T02(버스트 사이클)·생존 확장에서 추가.
    /// </summary>
    public enum BattleEventKind
    {
        /// <summary>전투 시작 (OnStart/None 패시브 적용 시점).</summary>
        BattleStart,
        /// <summary>발사 1회 (탄 소모 — OnUseAmmo/OnLastAmmoUse/OnFullChargeShot*).</summary>
        NikkeFire,
        /// <summary>히트 1회 (펠릿 단위 — OnHitNum/OnFullChargeHit*/OnLastShotHit).</summary>
        NikkeHit,
        /// <summary>재장전 완료 (OnEndReload).</summary>
        ReloadEnd,
        /// <summary>스킬 사용 (OnSkillUse) — 게이지 +200 은 T02 트래커가 이 이벤트 소비.</summary>
        UseSkill,
        /// <summary>버스트 스텝 진입 (OnEnterBurstStep) — 발행 = T02.</summary>
        EnterBurstStep,
        /// <summary>풀버스트 종료 (OnEndFullBurst) — 발행 = T02.</summary>
        EndFullBurst,
        /// <summary>버프(function group) 활성화 (OnFunctionOn / IsFunctionOn) — SkillRuntime 내부 발행.</summary>
        FunctionOn,
        /// <summary>버프 소멸 (OnFunctionOff) — SkillRuntime 내부 발행.</summary>
        FunctionOff,
        /// <summary>버프 스택 full_count 도달 (OnFullCount) — SkillRuntime 내부 발행.</summary>
        FunctionFull,
    }

    /// <summary>전투 이벤트 1개 — 단일 struct 다목적 (필드 의미는 Kind 별 주석).</summary>
    public readonly struct BattleEvent
    {
        public BattleEventKind Kind { get; init; }
        /// <summary>이벤트 주체 (null = 전역 — BattleStart 등).</summary>
        public Combatant Source { get; init; }
        /// <summary>NikkeFire/NikkeHit: 풀차지 발사 여부.</summary>
        public bool IsFullCharge { get; init; }
        public bool IsCrit { get; init; }
        public bool IsCoreHit { get; init; }
        /// <summary>다목적 정수 — NikkeFire/NikkeHit: 발사 후 잔탄 · EnterBurstStep: 스텝 ·
        /// FunctionOn/Off/Full: function group_id.</summary>
        public int IntValue { get; init; }
        /// <summary>발생 프레임 (60fps 격자 — FACTS §4).</summary>
        public int Frame { get; init; }
    }
}
