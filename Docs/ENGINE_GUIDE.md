# ENGINE_GUIDE — 시뮬레이터 엔진 구현 가이드 (HOW · 순서)

> **역할**: Runtime 엔진(THE GAP)을 *어떤 컴포넌트로 · 어떤 순서로 · 어떤 계약으로* 구현하는지의 작업 가이드라인.
> **권위 관계**: 방향·결정·대미지 공식의 권위는 [`Docs/DESIGN.md`](DESIGN.md). 이 문서는 그걸 *어떻게 짓는지*. 충돌 시 DESIGN 우선.
> **대상**: 사람/LLM 구현자. 추측 금지 — 기존 API는 실 시그니처, 신규는 "제안 스케치" 명시.
> **작성**: 2026-06-28.

---

## 0. 범위

엔진 = 공식 스킬 체인(`skill_chains.json`) + 검증된 대미지/스탯 코어를 **시간축 위에서 굴려** 팀 1회 run 의 총대미지(RNG 표본)를 내는 Runtime 층 = **Tier 2** (DESIGN §0.5).
목표 형태(DESIGN §1): **event-driven 풀 tick 로테이션 sim**, 2모드 제어, 타겟 추상화.

> ⚠️ 엔진은 **Tier 3(Evaluator)·4(Optimizer)·5(Web)·6(배포) 의 재사용 대상.** → **UI·compute·직렬화 무지 순수 라이브러리** 로 짓는다. 출력은 run 1회당 **총대미지 표본 1개**(Evaluator 가 N run → 분포). 절대 UI/서버 타입을 엔진에 끌어들이지 말 것.

**이미 있음(재사용, §2) → 없음(이 가이드가 짓는 것, §3) → 순서(§4) → 계약(§5) → 결정(§6) → 불변식(§7).**

---

## 1. MUST / MUST NOT (엔진 전역 규칙)

- **MUST**: 대미지는 오직 `DamageCalculator.CalculateDamage(in AttackContext)` (`Core.Combat`) 로 계산. **공식 재구현 금지** (DESIGN §3 = 단일 권위, golden test 로 잠김).
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
| 대미지 공식 | `Combat/DamageCalculator.cs` | `double CalculateDamage(in AttackContext)` ; `struct AttackContext`(FinalAtk/FinalDef/SkillMultiplier/Is*플래그/Sum*브래킷/ChargeDmgBase…) |
| 스탯 조립 | `Stats/StatCalculator.cs` | `GetCoreAppliedStats(class,weapon,mfr,lv,grade,core,bond,consoles)` · `GetEquipmentStats` · `GetConsoleStats` (DESIGN §3.5) |
| 자료 로딩 | `Stats/StatTable.cs` | (로딩) `Initialize(csvPath)`(레벨/호감도) + `InitializeEquipment/InitializeCubeBase/InitializeCollectionBase(jsonPath)` ; (raw 접근) `GetLevelClassStat`·`GetBondClassStat`·`TryGetEquipBase`·`GetCubeStat(lv)`·`GetCollectionStats(lv)` **(전부 공식 JSON 연동 완료, stub 아님)** |
| OL 합산 | `Stats/OverloadProcessor.cs` | `CalculateFinalBaseStat(native, olPercents, olFlatSum, decimals)` ; `CalculateFlatBonus(opts,type)` |
| 무기 프로파일 (per-char) | `Stats/WeaponProfile.cs` ← `Data/Dto/RootDto.cs` `WeaponDto` → `Nikke.Weapon` | ETL 정규화(발/sec·초·분수): 발사 ramp `FireRate/EndFireRate/FireRateRampPerShot/FireRateResetTimeSec` + **`FireRateAtShot(n)`**(MG spin-up 1→70 nominal, **60fps 프레임캡→실효 60**)/`FireIntervalSec` · 모션 `SpotFirst/LastDelaySec`(0.2s 지배적) · 탄창/재장전(`ReloadBulletRate` 부분장전) · 차지(`ChargeTimeSec/FullChargeDamage`) · 펠릿(`ShotCount` SG 5\|10) · 명중원(`*AccuracyCircle*`) · 버스트게이지(`BurstEnergyPerShot/BurstDurationSec/UseBurstSkill`). null-safe(`Empty`) — 구 merged DB 호환 |
| 명중 모델 | `Combat/AccuracyModel.cs` | `CircleRadius(start,end,perShot,n)`(연사 수축) ; `CoreHitProbability/HitProbability`=**(r/R)² 면적확률** ; `RollCoreHit/RollHit(rng,…)` (CritSampler 패턴). 타겟 코어/몸체 반지름 = ITarget 설정 상수 |
| 적정 거리 | `Combat/ProperDistanceTable.cs` | `GetBand(weapon)`(공식 bonusrange 최빈값: SG 0-25·SMG 15-35·AR 25-45·MG 35-55·SR 45-100·**RL=없음**) ; `GetBonus(weapon,dist)→0.3\|0` ; `GetBonusPerChar(dist,min,max)`(per-char 정확, SR 예외 캐릭 포함). 커밋된 `proper_distance_table.json` 과 테스트 교차검증 |
| 크리 RNG | `Stats/IRandomSource.cs` | `IRandomSource.NextDouble()` ; `SystemRandomSource.Instance` ; `CritSampler.RollCrit(rng, baseCritRate)→bool` |
| 캐릭터 | `Entities/Nikke.cs` | `new Nikke(CharacterDto, GlobalStateDto)` ; `BuildAttackContext()→AttackContext` ; `FinalBaseAtk/HP/Def/MaxAmmo` ; `EquipCube(tid,lv)` ; `BasicAtkMultiplier/ChargeTime/ChargeDamage/CoreHitBonus` ; `WeaponType/Element/Class` |
| 데이터 I/O | `Data/JsonProvider.cs` | `GetSmartDatabasePath(file)` ; `LoadJson<T>(path)` |
| 공식 스킬 데이터 (K4 ✅) | `Engine/Skills/` `SkillChainLoader`·`SkillChainDto`·`SkillTranslator`·`OfficialSkillEnums` | `SkillChainLoader.TryLoad(out chains)`(skill_chains.json — gitignore, 부재=false) ; `chains.Characters[nameCode].Skills["skill1"/"skill2"/"burst"].Levels["1".."10"].FunctionIds` → `chains.Functions[fid]`(FunctionDto: Typed* enum 접근·`ValueAsFraction`) ; `SkillTranslator.Classify(fn)→Static\|Runtime` ; `SkillTranslator.Route(fn)→EffectRoute`(확실 슬롯/Unverified/Unknown) |
| DTO | `Data/Dto/RootDto.cs` | `RootDto.roster: Dictionary<name_code, CharacterDto>` ; `SkillDto.descriptionLevel10` |

> `AttackContext` 가 매 히트 입력. 엔진의 일은 **이 struct 를 매 히트 정확히 채워 `CalculateDamage` 에 넘기는 것**.

---

## 3. 짓는 것 (없음) + 의존 그래프

```
SimClock(이벤트큐) ──┬─> FiringModel ──> (히트 발생)──> BuffAggregator ──> AttackContext ──> CalculateDamage ──> MetricsCollector
                     ├─> SkillRuntime(트리거→BuffInstance/DamageInstance) ──> BuffStore ──┘
                     └─> IRotationController(Auto/Scripted) ──(스킬/버스트 명령)──> SkillRuntime
ITarget(Dummy/Boss) ──(DEF/파츠/속성/거리)──> AttackContext 채움
SkillChainLoader ──(skill_chains.json, 공식)──> SkillTranslator ──(static/runtime 2축)──> Nikke / SkillRuntime
```

핵심 신규: **SimClock · FiringModel · SkillParsed DTO+Loader · SkillTranslator · SkillRuntime · BuffStore/Aggregator · IRotationController · ITarget · MetricsCollector**.

---

## 4. 마일스톤 (순서 = 검증 가능한 수직 슬라이스)

각 M 끝에 **수용 기준(Acceptance)** 충족 + 가능하면 in-game 대조 후 다음.

### M0 — Smoke wire (foundation 증명)
- **목표**: `StatTable.Initialize` → `new Nikke` → `BuildAttackContext` → `CalculateDamage` 를 **콘솔에서 1발** 굴려 숫자 1개.
- **하는 것**: 진입점(테스트 콘솔/유닛테스트)에서 캐릭 1명 로드, 평타 컨텍스트 1개 만들어 호출.
- **확정됨(2026-06-30)**: **W 단위** — 데이터 `multiplier` 는 percent-number(예 13.65); `Nikke` 생성자에서 `/100` 정규화 → `BasicAtkMultiplier`(엔티티)=fraction. `BuildAttackContext` 가 `SkillMultiplier` 에 주입(더는 TODO 아님). 회귀 가드 = `WUnitFoundationTests`.
- **Acceptance**: ✅ W 정규화+주입 동작(fraction-scale 가드 통과) + 문서화(§6 D2). ⏸ **in-game FinalAtk 대조 대기** — 커밋 `stat_table.csv` 파싱 결함(cp949+비-quote-aware split)으로 실 FinalAtk 산출 막힘 + 사용자 제공 in-game 수치 필요. **이 게이트 통과 전 Wave1+ 착수 금지(ENGINE_WAVE0 K1).**

### M1 — 단일 캐릭 발사 루프 (시간축 등장)
- **목표**: SimClock + FiringModel 로 캐릭 1명이 N초 동안 쏘는 시간축 + 누적 대미지/DPS. 스킬·팀버프 없음.
- **하는 것**: SimClock(이벤트큐), FiringModel(RPS/차지타이밍 → 발사 이벤트, 탄창 감소→재장전, 풀차지 판정), 매 발사 `BuildAttackContext`+크리RNG → `CalculateDamage` → MetricsCollector.
- **Acceptance**: 무기별(AR/SR 등) DPS 가 RPS·탄창·재장전·차지 타이밍에 정합. 크리 RNG 켜고 N회 평균이 기대 크리율 반영.

### M2 — 단일 캐릭 스킬 (브리지 + 런타임)
- **목표**: 그 캐릭 *자기* 스킬(self 버프/트리거)을 시간축에 반영.
- **하는 것**: SkillChainLoader(공식 skill_chains.json — ✅ K4), SkillTranslator(2축 분류+EffectRoute — ✅ K4), SkillRuntime(event→BuffInstance/DamageInstance — K7), BuffStore + BuffAggregator(활성버프→AttackContext, 니케식 합산 — K7).
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

**FiringModel** — ✅ **구현 완료** (2026-07-08, `Engine/FiringModel.cs` — 60fps 프레임 상태기계 + `ControlMode.Auto/Manual`·`FireStyle` 축, 15 테스트; SimClock 배선/이벤트 발행 = K8). 발사속도 권위 = **`Nikke.Weapon`(WeaponProfile, per-char)**. 참조 구현 = nikke-einkk `nikke.dart` + **사용자 실측 확정(2026-07-08, 3.5년 플레이 ground truth)**:
- **발사 accumulator**: 매 프레임(비사격 포함) `countdown -= rateOfFire(RPM)`, 발사 시 `+= 60×fps`(=3600) — 구조적 1발/프레임 = MG nominal 70/s → 실효 60/s (`FireRateAtShot` 캡과 일치).
- **MG ramp**: 발사마다 `+changePerShot` clamp[start,end]. **리셋 = 점진 감쇠** — 비사격 프레임마다 `(end−start)/reset_time` 하강 (즉시 리셋 아님; 부분 중단 = 부분 손실).
- **상태 전이 (전 무기, 확정)**: 엄폐→조준 = `SpotFirstDelaySec`(0.2s; 비사격 동안 재-arm, 차지무기는 종료 프레임에 charge 1f 선시작) / 조준→엄폐 = `SpotLastDelaySec`(0.2s — einkk 은 UP형에만 적용하나 **실게임은 전 무기**; 데이터도 전 무기 20).
- **재장전 (원시 규칙 — 특례 금지)**: R1 = 비사격 프레임(엄폐·전이·re-click 갭)마다 진행 · R2 = 실효 시간 ≤ 창이면 그 안에서 완료. 공식 = **니케식 group-then-round, 1/100초 정수 도메인** (권위 = `OverloadProcessor.ReduceTimeCs`, 사용자 확정 2026-07-08): `effectiveCs = baseCs − Σ_group round(baseCs×value×count)` — 동일값 버프 선합산 → 그룹 사사오입, 시간은 게임 timeData(1/100초 **정수**) 유지 + 버프 ×10000 정수 복원 = 순수 정수 연산(이진 오차 원천 차단). 차지속도 동일식. + 첫 재장전에 spot_last 가산(einkk). `ReloadBulletRate` 부분장전. **≥100% 버프 = re-click 이내 즉시 장전(확정)** → 톡톡이 장탄 무소모 / 비차지·maintain형 탄0도 re-click 내 충전 — R1/R2 에서 창발, 하드코딩 금지.
- **SR/RL 3부류 (per-char 데이터 판별 — 무기타입 상수 금지 재확인)**:
  ① `input=UP, maintain=0`(68명): 발사 후 강제 엄폐 복귀 — 사이클 = last(0.2)+first(0.2)+charge (Maxwell 1.4s).
  ② `input=UP, maintain>0`(SBS 0.23s·Raven 0.83s·A2 0.84s): **복귀 없음, 자체 후딜레이 = maintain_fire_stance**(대기 = first+maintain, einkk). `uptype_fire_timing`(비율)로 투사체 발사 이벤트 시점 보정. SBS 는 charge 0.3s 라 톡톡이처럼 보임.
  ③ `input=DOWN_Charge`(Liberalio·Neon:VE·Vesti:TU·Anis:Star·Cinderella): **only 풀차지** — 홀드 시 자동 풀차지 반복, 릴리즈 발사 불가, 복귀 없음, rate_of_fire 가 사이클 gate. (④ `DOWN` = Pascal 평사 RL.)
- **컨트롤 정책 축 (Auto 4명 / Manual 1명, IRotationController 와 별개)**: Manual profile = re-click 갭 **[0.02, 0.028]s**(확정; 프레임 반올림 1~2f) + 차지 오차 ε(프로파일 구간, 정수 프레임; δ=0 결정론 모드 필수). Manual 풀차지 루틴 = first(0.2)+[charge(1+ε)+reclick]×장탄+last(0.2) — 조준 유지로 발당 first 미지불. Manual 톡톡이 = [first(0.2)+reclick] 반복(UP형; 구 실측 0.215 와 부합).
- **명중원**: 발사마다 `−accuracyChangePerShot`, 비사격 프레임마다 `+changeSpeed/fps` 회복.
- **버스트**: 게이지 = burstStage 0 에서만 충전(관통 히트 = 파츠당 추가). stage 간 딜레이 = [0.01, 0.17]s random(사용자 실측; 데이터 상수 없음 — ConfigBattle 확인). **풀버스트 10s = 진입 시점 기산(확정)**. **3버→풀버 진입 딜레이 = 0.46s ≈ 28프레임(사용자 영상 실측 2026-07-08)** — K9 버스트 사이클 상수. 발사 시 `IsFullCharge` 세팅 + `AccuracyModel.RollCoreHit` 로 `IsCoreHit` 샘플링. (참고: ConfigBattle `RLV2SwitchDelayTime=20` — DOWN_Charge(V2)형 연관 추정, 의미 미확정.)

**SkillChainLoader (✅ K4)** — 공식 skill_chains.json 로드 + 참조 무결성 검증 (§2 표 '공식 스킬 데이터' 행).

**SkillTranslator (✅ K4)** — `FunctionDto` → 2축(DESIGN §5): Classify(트리거·조건 無+영구=Static / 그 외 Runtime) + Route(EffectRoute — 확실 슬롯/Unverified/Unknown).

**SkillRuntime** — 트리거 등록부. 이벤트(skill_cast/on_hit/burst_*/every_n_shots/…) 발생 시 조건(`condition_on`/`required_token`/`hp_*`) 평가 후 effects 적용: 버프면 `BuffInstance`(stat/value/bracket/expirySec/stacks) 스폰, `deal_damage` 면 `DamageInstance`(W 슬롯, bracket=null) → 히트 인스턴스.

**BuffStore + BuffAggregator** — Combatant별 + 팀 활성 `BuffInstance` 보관(만료 tick에 제거). 매 히트: 적용대상 버프를 **브래킷별 Sum*** 로 집계(니케식 group-then-round)해 `AttackContext` 채움.

**IRotationController** — `Decide(simState) → actions(스킬사용/버스트)`. `AutoController`(게이지 full→burst, 쿨다운 만료→스킬) / `ScriptedController`(시각별 액션 테이블).

**ITarget** — `FinalDef` / `HasParts` / `Element` / `Distance` / `CoreRadius` / `BodyRadius` / `IsBoss` 제공 (2026-07-02 계약 갱신 — 구 `InProperRange` bool 폐기). `PopulateContext(ref ctx, attackerElement, attackerWeaponType)` 가 히트마다 DEF·`ProperDistanceBonus`(ProperDistanceTable)·`SumStrongElem`(상성 — 판정 유틸 보류 중) 채움. 코어힛/명중은 발사 시점 RNG 의존이라 FiringModel 이 `AccuracyModel` + `CoreRadius/BodyRadius` 로 샘플링. `DummyTarget`(고정, ✅ 2026-07-02) / `BossTarget`(데이터, K11).

**MetricsCollector** — ✅ **구현 완료** (2026-07-08, `Engine/Metrics/MetricsCollector.cs`, 6 테스트). `Record(timeSec, sourceId, amount, tags{crit,core,bracket…})` → `Build()` = `RunResult{TotalDamage, DurationSec, HitCount, DamageBySource, DamageByTag("tag=value"), DamagePerSecond(초 버킷)}`. 스냅샷 반복 호출 가능 + `Reset()`(N-run 재사용). run 창 밖 시각 = throw (배선 버그 조기 검출).

---

## 6. 결정 포인트 (내 권장 — 확정/수정 요)

| # | 결정 | 권장 | 비고 |
|---|---|---|---|
| D1 | 엔진 코드 위치 | ✅ **`Nikke.Simulator.Engine` 분리 완료**(2026-06-30, K0) | Engine→Core 단방향(컴파일러가 Core→Engine 금지). 계약 스텁 동결. 조건: Core/Engine UI·compute 무지 유지 |
| D2 | W 단위 | ✅ **확정 = `Nikke` 생성자 `/100`**(2026-06-30) | 데이터 `multiplier`=percent-number → 엔티티 `BasicAtkMultiplier`=fraction. golden 리그 W=4.995(fraction)와 정합. ETL 무수정 |
| D3 | 파서 prerequisite | **런타임 먼저, 134 완성분 + 결손 no-op, 파서 병행** | 닭달걀 차단 |
| D4 | 출력 지표 | record-every-instance MetricsCollector | 총/DPS곡선/캐릭별/브래킷 전부 사후 집계 |
| D5 | SimClock 자료구조 | min-heap 우선순위큐 | 동시각 삽입순 tie-break |
| D6 | 스킬 enum | ✅ 공식 enum 미러(`OfficialSkillEnums.cs`, 기계생성) + 미지값 graceful | 게임 신버전 값 = Unknown no-op (D1 검증: 신값은 연속 추가뿐) |

---

## 7. 데이터/검증 의존 (블로커 아닌 항목 — 병행)
- ✅ 장비표·큐브·소장품 base/특수효과: **공식 blablalink JSON 연동 완료** (`GetEquipmentStats` + cube/collection base JSON + `EffectType`/`EffectTable`). 옛 "stub/예시 수치" 는 해소됨. 잔여 = 타이밍/조건부 효과(sim 루프 대기, `SKILL_DATA_BLABLALINK.md` §4.2).
- ProperDistance: ✅ 무기별 **범위** 확보(`proper_distance_table.json`; roledata bonusrange → MG 35-55·AR 25-45·SMG 15-35·SG 0-25·RL 0-0·SR 45-100). 보너스 **크기**(0.3?)만 미검증. (per-char `properRange` 도 merged DB 에 있어 SR 예외 보존.)
- ✅ 무기 타이밍/명중원 데이터+모델(2026-07-01 유실→07-02 복구 통합): roledata shot 블록 → `weaponData`(clean/merged, ETL 정규화) → `WeaponDto`/`Nikke.Weapon`(WeaponProfile) + AccuracyModel/ProperDistanceTable/DummyTarget + `WeaponDataTests`(192캐릭 전수 불변식 포함). ⚠ 속성 상성 유틸(ElementAdvantage) 보류(사용자 결정). 잔여 = K3 소비(FiringModel) · HitRate 버프 배선 · merged DB 재생성(구 파일 weaponData 없음) · spot delay(0.2s) vs 구 실측 0.03s 캘리브레이션 · 타겟 코어/몸체 반지름 상수 확정.
- 검증 전략: 슬라이스별 in-game 대조 + RNG 는 N회 수렴.

---

## 8. 참조
- 병렬 작업 청킹·순서(멀티 에이전트): [`Docs/WORK_BREAKDOWN.md`](WORK_BREAKDOWN.md)
- 방향·공식 권위: [`Docs/DESIGN.md`](DESIGN.md)
- 스킬 데이터: `Docs/SKILL_RUNTIME_REFERENCE.md` + `Engine/Skills/OfficialSkillEnums.cs` (공식 enum 미러)
- 공식 유도: 루트 `_dmg_probe.py` / `_dmg_calibrate.py`, golden: `Nikke.Simulator.Tests/DamageFormulaGoldenTests.cs`
- 폐기 레거시(참고만): `_archive/` (LLM 파서·il2cpp 루트·완료 태스크 문서)
