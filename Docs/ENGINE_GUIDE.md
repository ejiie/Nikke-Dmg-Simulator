# ENGINE_GUIDE — 시뮬레이터 엔진 구현 가이드 (HOW · 순서)

> **역할**: Runtime 엔진(THE GAP)을 *어떤 컴포넌트로 · 어떤 순서로 · 어떤 계약으로* 구현하는지의 작업 가이드라인.
> **권위 관계**: 방향·결정·대미지 공식의 권위는 [`Docs/DESIGN.md`](DESIGN.md). 이 문서는 그걸 *어떻게 짓는지*. 충돌 시 DESIGN 우선.
> **대상**: 사람/LLM 구현자. 추측 금지 — 기존 API는 실 시그니처, 신규는 "제안 스케치" 명시.
> **작성**: 2026-06-28.

---

## 0. 범위

엔진 = `skills_parsed.json` + 검증된 대미지/스탯 코어를 **시간축 위에서 굴려** 팀 1회 run 의 총대미지(RNG 표본)를 내는 Runtime 층 = **Tier 2** (DESIGN §0.5).
목표 형태(DESIGN §1): **event-driven 풀 tick 로테이션 sim**, 2모드 제어, 타겟 추상화.

> ⚠️ 엔진은 **Tier 3(Evaluator)·4(Optimizer)·5(Web)·6(배포) 의 재사용 대상.** → **UI·compute·직렬화 무지 순수 라이브러리** 로 짓는다. 출력은 run 1회당 **총대미지 표본 1개**(Evaluator 가 N run → 분포). 절대 UI/서버 타입을 엔진에 끌어들이지 말 것.

**이미 있음(재사용, §2) → 없음(이 가이드가 짓는 것, §3) → 순서(§4) → 계약(§5) → 결정(§6) → 불변식(§7).**

---

## 1. MUST / MUST NOT (엔진 전역 규칙)

- **MUST**: 대미지는 오직 `StatCalculator.CalculateDamage(in AttackContext)` 로 계산. **공식 재구현 금지** (DESIGN §3 = 단일 권위, golden test 로 잠김).
- **MUST**: 크리/확률은 `IRandomSource` + `CritSampler.RollCrit`. **고정 시드 금지** — 검증은 N회 반복 기댓값 수렴(±ε).
- **MUST**: `StatTable.Initialize(csv)` 를 **Nikke 생성 전 1회** 호출 (안 하면 레벨/큐브 테이블 빈 채 0 반환).
- **MUST**: 히트 1회 = `CalculateDamage` 1회. 관통 본체+파츠, 멀티히트는 **인스턴스 분해** (런타임이 히트 생성, 공식은 1발만).
- **MUST**: `deal_damage` 스킬 계수는 W 슬롯(`SkillMultiplier`). `formula_bracket=null` — 브래킷 합산(B2~B5)에 **절대 더하지 말 것** (INV-2).
- **MUST**: %-버프 합산 = 니케식 **group-then-round** (값별 그룹 → 그룹별 반올림 → 합; DESIGN/archive §4.4). 합 먼저 반올림과 결과 다름.
- **MUST**: 엔진 = **UI/compute/직렬화 무지 순수 라이브러리.** UI·서버·JSON-API 타입 의존 0 (Tier 3/4/5 가 재사용).
- **MUST**: sim 1 run 출력 = **총대미지 표본 1개** (Evaluator 가 N run → 분포; **고점×확률 목적**이라 tail 추정 위해 N 충분히 — 평균만 보는 N 보다 커야).
- **MUST NOT**: `weapon_type` override. `trait_weapon_transformed` = granular 파라미터(fire_rate/charge_time/…)만 (DESIGN, archive §5.4).
- **MUST NOT**: 파서 bailout `groups: []` 에서 throw. **no-op** 처리.

---

## 2. 재사용 자산 (이미 master 에 있음 — 실 시그니처)

| 컴포넌트 | 위치 | 핵심 API (실제) |
|---|---|---|
| 대미지 공식 | `Stats/StatCalculator.cs` | `double CalculateDamage(in AttackContext)` ; `struct AttackContext`(FinalAtk/FinalDef/SkillMultiplier/Is*플래그/Sum*브래킷/ChargeDmgBase…) |
| 스탯 조립 | `Stats/StatTable.cs` | `Initialize(csvPath)` ; `GetCoreAppliedStats(class,weapon,mfr,lv,grade,core,bond,consoles)→(HP,ATK,DEF)` ; `GetCubeStat(lv)` ; `GetCollectionStats(lv)` ; `GetEquipmentStats(equips)` **(stub=0)** |
| OL 합산 | `Stats/OverloadProcessor.cs` | `CalculateFinalBaseStat(native, olPercents, olFlatSum, decimals)` ; `CalculateFlatBonus(opts,type)` |
| 무기 타이밍 | `Stats/WeaponStatTable.cs` | `GetBaseFireRate(weapon)→발/sec` (AR12/MG60/SMG24/SG 5÷3; SR·RL 호출=throw) ; `GetChargeTiming(weapon)→ChargeTiming{MotionDelaySec .03, FullChargeSec 1.0, TapIntervalSec .215}` ; `IsChargeWeapon` ; weapon 문자열 상수 |
| 크리 RNG | `Stats/IRandomSource.cs` | `IRandomSource.NextDouble()` ; `SystemRandomSource.Instance` ; `CritSampler.RollCrit(rng, baseCritRate)→bool` |
| 캐릭터 | `Entities/Nikke.cs` | `new Nikke(CharacterDto, GlobalStateDto)` ; `BuildAttackContext()→AttackContext` ; `FinalBaseAtk/HP/Def/MaxAmmo` ; `EquipCube(tid,lv)` ; `BasicAtkMultiplier/ChargeTime/ChargeDamage/CoreHitBonus` ; `WeaponType/Element/Class` |
| 데이터 I/O | `Data/JsonProvider.cs` | `GetSmartDatabasePath(file)` ; `LoadJson<T>(path)` |
| DTO | `Data/Dto/RootDto.cs` | `RootDto.roster: Dictionary<name_code, CharacterDto>` ; `SkillDto.descriptionLevel10` |

> `AttackContext` 가 매 히트 입력. 엔진의 일은 **이 struct 를 매 히트 정확히 채워 `CalculateDamage` 에 넘기는 것**.

---

## 3. 짓는 것 (없음) + 의존 그래프

```
SimClock(이벤트큐) ──┬─> FiringModel ──> (히트 발생)──> BuffAggregator ──> AttackContext ──> CalculateDamage ──> MetricsCollector
                     ├─> SkillRuntime(트리거→BuffInstance/DamageInstance) ──> BuffStore ──┘
                     └─> IRotationController(Auto/Scripted) ──(스킬/버스트 명령)──> SkillRuntime
ITarget(Dummy/Boss) ──(DEF/파츠/속성/거리)──> AttackContext 채움
SkillParsed C# DTO + Loader ──(skills_parsed.json)──> SkillTranslator ──(static/runtime 2축)──> Nikke / SkillRuntime
```

핵심 신규: **SimClock · FiringModel · SkillParsed DTO+Loader · SkillTranslator · SkillRuntime · BuffStore/Aggregator · IRotationController · ITarget · MetricsCollector**.

---

## 4. 마일스톤 (순서 = 검증 가능한 수직 슬라이스)

각 M 끝에 **수용 기준(Acceptance)** 충족 + 가능하면 in-game 대조 후 다음.

### M0 — Smoke wire (foundation 증명)
- **목표**: `StatTable.Initialize` → `new Nikke` → `BuildAttackContext` → `CalculateDamage` 를 **콘솔에서 1발** 굴려 숫자 1개.
- **하는 것**: 진입점(테스트 콘솔/유닛테스트)에서 캐릭 1명 로드, 평타 컨텍스트 1개 만들어 호출.
- **여기서 확정**: **W 단위** — `BasicAtkMultiplier` 가 percent(예 11.07)인지 fraction(0.1107)인지 실데이터로 확인 → `SkillMultiplier` 주입 시 정규화 규칙 고정. (현재 `BuildAttackContext` 는 W 미주입 = TODO.)
- **Acceptance**: 0 아닌 합리적 대미지 출력 + W 단위 문서화(이 파일 §6).

### M1 — 단일 캐릭 발사 루프 (시간축 등장)
- **목표**: SimClock + FiringModel 로 캐릭 1명이 N초 동안 쏘는 시간축 + 누적 대미지/DPS. 스킬·팀버프 없음.
- **하는 것**: SimClock(이벤트큐), FiringModel(RPS/차지타이밍 → 발사 이벤트, 탄창 감소→재장전, 풀차지 판정), 매 발사 `BuildAttackContext`+크리RNG → `CalculateDamage` → MetricsCollector.
- **Acceptance**: 무기별(AR/SR 등) DPS 가 RPS·탄창·재장전·차지 타이밍에 정합. 크리 RNG 켜고 N회 평균이 기대 크리율 반영.

### M2 — 단일 캐릭 스킬 (브리지 + 런타임)
- **목표**: 그 캐릭 *자기* 스킬(self 버프/트리거)을 시간축에 반영.
- **하는 것**: SkillParsed C# DTO+Loader(`skills_parsed.json`), SkillTranslator(static→Nikke 주입 / runtime→트리거 등록), SkillRuntime(event→BuffInstance/DamageInstance), BuffStore + BuffAggregator(활성버프→AttackContext, 니케식 합산).
- **Acceptance**: passive/지속 버프가 컨텍스트에 반영, duration 만료 처리, `groups:[]` no-op, stack 분기(cumulative/replace) 동작.

### M3 — 팀 (버프 전파 + 풀버스트)
- **목표**: 5인 + 교차버프 + 버스트 게이지 + Full Burst 사이클.
- **하는 것**: 5 Combatant, ally-target 버프를 팀 BuffStore 로 전파, 버스트 게이지 누적→Full Burst(3인) 타임, `burst_start/active/end` 트리거.
- **Acceptance**: 팀 총 DPS 가 버퍼 유무로 유의미 변동, Full Burst 창에서 버프 on/off.

### M4 — 로테이션 제어 2모드
- **목표**: `IRotationController` ← `AutoController`(게이지/쿨다운 자동) + `ScriptedController`(타임라인 입력).
- **Acceptance**: 단순덱 자동 실행 / 기믹덱 스크립트대로 실행. 둘 다 같은 SimClock 소비.

### M5 — 타겟 모델 + 출력
- **목표**: `ITarget` ← `DummyTarget`(먼저) → `BossTarget`. MetricsCollector 리포트 확정.
- **하는 것**: 타겟이 DEF/파츠/속성/거리 → `IsCoreHit/IsPartsHit/ProperDistanceBonus/SumStrongElem/FinalDef` 를 채움. 출력 지표(§6) 산출.
- **Acceptance**: 더미로 엔진 검증 후 보스 데이터 주입 가능 구조.

---

## 5. 컴포넌트 계약 (신규 — 제안 스케치, 구현 시 확정)

> 인터페이스는 *제안*. 시그니처는 구현하며 다듬되, 책임/플러그인 지점/금지사항은 지킬 것.

**SimClock** — 이산이벤트 큐. `Schedule(double atSec, Action ev)` / `Run(double untilSec)`. 최소시각 이벤트 pop→clock 전진→실행(새 이벤트 예약 가능). 동일시각 tie-break 결정적(삽입순). RNG 외 결정적.

**FiringModel** — Combatant+무기 → 발사 이벤트 생성. 비차지: `1/GetBaseFireRate` 간격. 차지: `MotionDelaySec+FullChargeSec`(풀차지) 또는 `TapIntervalSec`(톡). 탄창(`FinalBaseMaxAmmo`) 0→`reloadTime` 후 재장전. 발사 시 `IsFullCharge` 세팅.

**SkillParsed DTO + Loader** — Pydantic `skill_schema.py` 미러: `SkillParsedDto/TriggeredEffectGroupDto/TriggerBlockDto/TargetBlockDto/EffectBlockDto/StackConditionBranchDto` + enum(또는 string + 검증). `JsonProvider.LoadJson` 로 `skills_parsed.json`(key=name_code) 로드.

**SkillTranslator** — `SkillParsedDto` → 2축(DESIGN §5): static modifier(→ Nikke 사전집계 주입) / runtime trigger(→ SkillRuntime 등록). 분기 기준: `trigger.event≠passive` || `duration≠null` || `stack_conditions` 존재 → runtime.

**SkillRuntime** — 트리거 등록부. 이벤트(skill_cast/on_hit/burst_*/every_n_shots/…) 발생 시 조건(`condition_on`/`required_token`/`hp_*`) 평가 후 effects 적용: 버프면 `BuffInstance`(stat/value/bracket/expirySec/stacks) 스폰, `deal_damage` 면 `DamageInstance`(W 슬롯, bracket=null) → 히트 인스턴스.

**BuffStore + BuffAggregator** — Combatant별 + 팀 활성 `BuffInstance` 보관(만료 tick에 제거). 매 히트: 적용대상 버프를 **브래킷별 Sum*** 로 집계(니케식 group-then-round)해 `AttackContext` 채움.

**IRotationController** — `Decide(simState) → actions(스킬사용/버스트)`. `AutoController`(게이지 full→burst, 쿨다운 만료→스킬) / `ScriptedController`(시각별 액션 테이블).

**ITarget** — `FinalDef` / `HasParts` / `Element` / `InProperRange` / `IsBoss` 제공 → 히트마다 `AttackContext` 의 DEF·`IsCoreHit/IsPartsHit`·`ProperDistanceBonus`·`SumStrongElem`(속성 상성) 결정. `DummyTarget`(고정) / `BossTarget`(데이터).

**MetricsCollector** — 히트마다 `Record(timeSec, sourceId, amount, tags{crit,core,bracket…})`. 집계: 총대미지 / 시간축 DPS / 캐릭별 기여 / 브래킷 분해.

---

## 6. 결정 포인트 (내 권장 — 확정/수정 요)

| # | 결정 | 권장 | 비고 |
|---|---|---|---|
| D1 | 엔진 코드 위치 | **`Nikke.Simulator.Engine` 프로젝트 지금 분리** (권장 수정) | tier 3/4/5(evaluator/optimizer/web)+배포가 엔진을 라이브러리로 재사용 → 프로젝트 벽이 결합부채 차단(컴파일러가 Core→Engine 금지). 선비용 작음. 조건: Core/Engine UI·compute 무지 |
| D2 | W 단위 | M0에서 실측 확인 후 고정 | `BasicAtkMultiplier` percent면 `/100`. golden 리그는 W=4.995(fraction) |
| D3 | 파서 prerequisite | **런타임 먼저, 134 완성분 + 결손 no-op, 파서 병행** | 닭달걀 차단 |
| D4 | 출력 지표 | record-every-instance MetricsCollector | 총/DPS곡선/캐릭별/브래킷 전부 사후 집계 |
| D5 | SimClock 자료구조 | min-heap 우선순위큐 | 동시각 삽입순 tie-break |
| D6 | 스킬 enum | C# enum 미러 + 미지값 graceful | legend/`skill_schema.py` 와 동기 (드리프트 시 §11 체크리스트) |

---

## 7. 데이터/검증 의존 (블로커 아닌 항목 — 병행)
- 장비표: `GetEquipmentStats`=0 stub. tier×lv→HP/ATK/DEF 표 필요(사용자 실측).
- 큐브 TID 1000318–1000321 "예시 수치" → 실측 교체.
- ProperDistance 0.3 (RL=0 외 미검증).
- 검증 전략: 슬라이스별 in-game 대조 + RNG 는 N회 수렴.

---

## 8. 참조
- 병렬 작업 청킹·순서(멀티 에이전트): [`Docs/WORK_BREAKDOWN.md`](WORK_BREAKDOWN.md)
- 방향·공식 권위: [`Docs/DESIGN.md`](DESIGN.md)
- 스킬 스키마/enum: `DataPipeline/schema/skill_schema_legend.txt` + `skill_schema.py`
- 공식 유도: 루트 `_dmg_probe.py` / `_dmg_calibrate.py`, golden: `Nikke.Simulator.Tests/DamageFormulaGoldenTests.cs`
- 과거 설계 배경(참고만): `Docs/_archive/DEVLOG.md` (배너·날짜 확인)
