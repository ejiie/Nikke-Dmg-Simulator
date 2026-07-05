# DESIGN — Nikke Damage Simulator 방향·구조 (권위)

> **역할**: 프로젝트가 *무엇을* 만들고 *어떻게* 구성되는지의 단일 권위 문서.
> **지위**: 이 문서 = 현행 ground truth. `Docs/_archive/*` 는 historical(2026-04, 일부 superseded).
> **확정일**: 2026-06-28 (사용자와 원점 재논의 후 확정).

---

## 0. 한 줄 (궁극 목적)

보유 NIKKE 로스터로 **최고 고점 덱 조합을 찾아주는 (배포 가능한) 도구.**
풀 tick 정밀 로테이션 sim 은 **최종 목적이 아니라 optimizer 의 inner loop**: 팀 1개의 대미지 **분포** 산출(sim) → 덱별 파워 평가(고점×확률) → 로스터를 K팀으로 분할한 **합딜 고점 최대 조합** 탐색 → 웹 UI/배포.

---

## 0.5 목표 계층 (tiers)

| Tier | 내용 | 상태 |
|---|---|---|
| 1 **Core** | stat 조립 + per-hit 대미지 공식 | ✅ 공식 18-golden + **stat 조립 0-error**(다캐릭·돌파불변, 사용자 검증 — VERIFICATION_LOG). 잔여=stat 공식 문서화·CI(정본 csv 대기) |
| 2 **Sim Engine** | event-driven 풀 tick 로테이션 → 팀 1개 1회 run 의 총대미지 (RNG 표본 1개) | ❌ THE GAP (§4) |
| 3 **Evaluator** | 팀별 N회 run → **분포 저장**(샘플/분위수; 평균+편차로 부족 — tail 필요). = "덱 파워" | ❌ 신규 |
| 4 **Optimizer** | 로스터 → K팀(3 or 5) 분할(캐릭 1회), **고점×확률 목적** 최대 조합 탐색 | ❌ 신규 |
| 5 **Web App** | 로스터 입력 · 결과 · 차트 | ❌ 신규 (UI 스택 보류) |
| 6 **배포** | 공개 · 멀티유저 | ❌ 신규 |

> Tier 2 가 3 의 inner loop, 3 이 4 의 inner loop. 따라서 **성능 1급** + **팀조합→파워 memoize/cache 필수** (고유 5인조 1회만 sim).

---

## 1. 확정 결정 (2026-06-28)

| 항목 | 결정 | 비고 |
|---|---|---|
| **목표** | 풀 tick 정밀 로테이션 sim | 닫힌형/평균 shortcut 안 씀 |
| **대미지 공식** | 18-golden 검증 **additive B2 + 곱셈 B3/B4/B5** (§3) | 단일 권위. 모순 표기 전부 정정/제거 |
| **스코프** | 전부 (생존/CC/힐/실드 포함). 명중률도 진입(2026-07-02, `Combat/AccuracyModel` — 명중원→면적확률; HitRate 버프 stat 배선만 잔여) | 단계적 |
| **엔진** | **event-driven** 이산이벤트 | 발사/스킬/버프만료/차지완료를 큐 예약→점프. 정밀도·효율 우위 |
| **로테이션 제어** | **2모드** — `IRotationController` ← `AutoController` / `ScriptedController` | 단순덱=자동, 기믹덱=수동 |
| **대미지 대상** | `ITarget` 추상화 ← `DummyTarget`(먼저) / `BossTarget`(나중) | |
| **빌드 순서** | 수직 슬라이스 ①단일캐릭 → ②팀버프 → ③스킬 breadth | §4 |
| **Optimizer 목적** | **고점 × 확률** (상위 tail; 예: `P(합딜 ≥ X)` 또는 고분위수). Σ평균 아님 | Evaluator 가 **분포 전체** 보관 |
| **최적화 문제** | 로스터 → K팀(3/5) 분할, 캐릭 1회, tail 목적 최대 | NP-hard → 후보풀+휴리스틱+팀파워 cache |
| **UI/컴퓨트** | **보류** (M1 단일 sim 속도 측정 후 결정) | → 엔진 = **UI·compute 무지 순수 라이브러리** 강제 (WPF/Blazor/서버 무엇이든 참조만) |
| **배포** | 공개·멀티유저 지향 | 하드코딩 개인데이터 X (유저별 로스터 입력), 개인데이터 client-side |

---

## 2. 시스템 레이어 (현행)

```
DataPipeline/ (Python)   크롤러+ETL+LLM 파서 → Database/*.json + skills_parsed.json
        │ (파일 경계)
SimulatorEngine/Nikke.Simulator.Core (C# .NET8)   ← 순수 라이브러리 (UI/compute 무지)
   Data/        JsonProvider(I/O 단일점) + Dto(JSON 1:1) + Constants(큐브/콜렉션)
   Stats/       StatTable(원천 자료 **로딩** CSV/JSON + raw 접근) · StatCalculator(**스탯 조립** §3.5)
                · OverloadProcessor(OL 니케식 합산) · WeaponStatTable(발사속도/차지) · IRandomSource/CritSampler(크리 RNG)
   Combat/      DamageCalculator(per-tick **대미지** 공식 §3) + AttackContext(tick struct)
   Entities/    Nikke(최종 기초스탯 + BuildAttackContext 팩토리)
   [신설 예정]  Runtime/ — 이벤트 클럭 + 스킬 런타임 + 버프 스토어 + 로테이션 제어 + 타겟
        │
SimulatorEngine/Nikke.Simulator.Engine (C# .NET8)  ← Runtime 엔진 (계약 스텁 동결, K0). Engine→Core 단방향.
        │
SimulatorEngine/Nikke.Simulator.Wpf  (WPF UI; App.OnStartup 에서 StatTable.Initialize)
```

> 역할 분리(2026-06-30 3-way split): **StatTable=로딩 / StatCalculator=스탯 계산 / DamageCalculator=대미지**.
> 이전엔 `StatCalculator`(Stats/)가 대미지를, `StatTable`이 조립까지 겸해 파일명이 역할과 괴리됐었음 — 정정 완료.

---

## 3. 대미지 공식 (권위 — 18 golden 검증)

**실측 역산 (2026-06-27), in-game 18 측정점 bit-exact 검증.** 과거 multiplicative B2 형식은 **환각/오류 — 폐기**.

```
Damage = floor( B2 × (1 + ΣB3) × (1 + ΣB4) × (1 + ΣB5) )

  P  = (FinalAtk − effectiveDef) × W × C          ← 계수·차지를 B2 floor 이전에 P 에 접음
  B2 = floor(P) + Σ_active floor(P × bracket_i)   ← B2 는 **가산 per-term FLOOR** (곱셈 아님!)
       bracket_i ∈ { properDist, fullBurst,
                     (크리 시) Σcrit_dmg,
                     (코어 시) coreHitBase(1.0) + Σcore_hit_buff }
  B3 = 1 + Σattack_dmg [+pierce][+parts][+dot][+sequential]   ← 곱셈 브래킷
  B4 = 1 + Σdamage_taken + Σdistrib_dmg                        ← 곱셈 브래킷
  B5 = 1 + Σstrong_elem                                        ← 곱셈 브래킷
```

- **W** = 평타/스킬 계수 — **fraction** (golden 리그 4.995 = 499.5%/100). deal_damage 스킬 계수도 W 슬롯.
  - ✅ 데이터 `basicAttack.multiplier` 는 **percent-number**(예 13.65 = "13.65% ATK"), `chargeDamage` 는 fraction — 단위 불일치. **`Nikke` 생성자(데이터→엔티티 경계)에서 `multiplier/100` 정규화**로 해소(2026-06-30 확정, 단일 지점 = `Nikke.cs` [4]). 그래서 엔티티 `BasicAtkMultiplier` 는 fraction. 안 하면 100× 버그. 회귀 가드 = `WUnitFoundationTests`.
- **C** = 차지 배율. 비차지 = 1. 풀차지: `C = (ChargeDmgBase + Σcharge_dmg) × (1 + Σcharge_dmg_mult)`.
  - `ChargeDmgBase` = per-character `basicAttack.chargeDamage` (대부분 2.5, 일부 3.5).
- **[A1] 최소 대미지**: `effectiveDef ≥ FinalAtk` → 배율 무관 즉시 **1** (중간 곱 미경유).
- **[A2] True Damage**: `effectiveDef := 0`, 그리고 B3 에 `Σtrue_dmg_buff` 조건부 가산.
- **구조 요점**: B2 내부 = 가산-per-term-floor / B2~B5 사이 = 곱셈 / 마지막 단일 floor.

**구현·검증 위치**:
- C#: `SimulatorEngine/Nikke.Simulator.Core/Combat/DamageCalculator.cs` (`CalculateDamage`). (2026-06-30 `Stats/StatCalculator.cs` 에서 개명·이동.)
- 골든 테스트: `Nikke.Simulator.Tests/DamageFormulaGoldenTests.cs` (18점, ≤1.3e-7).
- 유도/캘리브레이션: 저장소 루트 `_dmg_probe.py`(구조 발견) + `_dmg_calibrate.py`(계수 역산).

> **이 §3 이 대미지 공식의 단일 권위.** legend / skill_schema / 그 외 문서의 공식 표기는 여기에 종속.

---

## 3.5 스탯 조립 공식 (FinalBaseStat — 권위)

> §3 대미지의 입력인 `FinalAtk/HP/Def/MaxAmmo` 를 **어떻게 조립**하는지. **불변식**: 실 crawl 데이터로
> 다캐릭·돌파(grade)불변 in-game **0-error** 검증됨 (VERIFICATION_LOG §5). 구현: `Entities/Nikke.InitializeFinalStats`
> + `Stats/StatCalculator`(조립) + `Stats/OverloadProcessor`(OL) + `Stats/StatTable`(로딩).

스탯(HP·ATK·DEF)별 파이프라인:

1. **Core-applied native** — `StatCalculator.GetCoreAppliedStats`:
   - `lvStat` = 레벨표[level][class] (DEF 는 무기 매핑 컬럼; HP/ATK 공통)
   - `preCore = lvStat + floor(lvStat × grade × 0.02) + gradeFlat + bondStat + consoleStat`
     - gradeFlat: HP `3000·grade`, ATK `20·grade`, DEF `100·grade`
     - bondStat = 호감도표[bond][class] (DEF="ALL")
     - consoleStat = `GetConsoleStats`: 공용(1001) HP `+450·lv`; 클래스(1101/02/03) HP `+750·lv`·DEF `+5·lv`; 기업(1201~1205) ATK `+25·lv`·DEF `+5·lv`
   - `coreStat = preCore + round(preCore × core × 0.02, AwayFromZero)`
   - ※ **grade=내림(floor) / core=반올림(round, 사사오입)** 분리가 핵심.
2. **소장품 base** — `StatTable.GetCollectionStats(favLv)` (collection_base_table.json).
3. **장비** — `StatCalculator.GetEquipmentStats`: 부위별 `round(base × (1 + 0.3·제조사일치 + 0.1·level), AwayFromZero)` 합 (equip_stat_table.json[class][tier][slot]).
4. **큐브 base** — `StatTable.GetCubeStat(cubeLv)` (cube_base_table.json).
5. **base (native)** = `core + collection + equip + cube` (스탯별 합; 위 1~4).
6. **버프 적용 — `Final = base × (1 + Σ buff)`** (모든 스탯 공통 모델):
   - **buff = 항상 켜진 buff** (OL%, 큐브/소장품 rate 효과 `MaxHp/Def/MaxAmmo`) **+ sim 중 런타임 스킬 %-버프**. → OL 도 "sim 내내 켜진 buff" 의 일종.
   - **니케식 group-then-round**: 동일 value buff 끼리 그룹 → 그룹별 `round(base × (value×count), 0, AwayFromZero)` → 합. (라인별 반올림 후 합과 결과 다름.)
   - 정수 스탯(HP/ATK/DEF/MaxAmmo) decimals=0. **차지시간/재장전시간만 비정수**(decimals=2).
   - ATK 도 동일 모델 — 큐브/소장품이 base ATK rate 를 안 줄 뿐, OL ATK%·스킬 ATK% 가 buff.
   - OL 매핑: ATK=`StatAtk%` / HP=`StatMaxHP%` / DEF=`StatDef%` / MaxAmmo=`StatAmmoLoad%`.
   → `FinalBaseAtk/HP/Def/MaxAmmo` = §3 의 입력.
   - ⚠️ **구현 메모**: 현 코드는 큐브/소장품 rate 를 base 에 먼저 곱하고(`Nikke.InitializeFinalStats`) OL 을 그 위에 group-then-round(`OverloadProcessor`) — 2-step. in-game **0-error 검증**됨. 런타임 스킬 buff 가 같은 `(1+Σbuff)` 브래킷에 합류할 때 rate/OL/런타임의 그룹 경계는 M2 배선 시 확정.

> **이 §3.5 가 스탯 조립의 단일 권위.** OL 의 combat-axis(크리/크뎀/차지/속성)는 스탯이 아니라 §3(대미지)로 흐른다(별 축; `Nikke._ol*` → `AttackContext`).
> ✅ 검증: stat 조립 0-error(다캐릭·다레벨·돌파불변, 사용자). 견고 파서(`StatTable.Initialize`)+셀 락 테스트(`WUnitFoundationTests.StatTable_Parses_KnownCells`)로 CI 회귀 가드.

---

## 4. 빌드 순서 (수직 슬라이스 — 검증 우선)

각 슬라이스를 in-game 실측과 대조해 잠그고 다음으로. (정확성 목적; 시간 절약 아님)

1. **단일 캐릭 풀 로테이션** — 이벤트 클럭 + 발사(RPS/차지/탭) + 탄창/재장전 + 풀차지 판정 + 크리 RNG + `DamageCalculator` 를 end-to-end 연결. 팀버프 없음. (드디어 `Initialize→Nikke→BuildAttackContext→CalculateDamage` 루프 실행.)
2. **팀 버프 전파** — 5인 교차버프(static/runtime 2축, §5) → 매 발사 tick `AttackContext` 합산. NIKKE 대미지의 8할.
3. **스킬 런타임 breadth** — `skills_parsed.json` 134 완성분 + stack/조건/required_token/filter_token dispatch 전수.

> 상세 구현 가이드(컴포넌트 계약 · 마일스톤 M0~M5 · 결정포인트): [`Docs/ENGINE_GUIDE.md`](ENGINE_GUIDE.md).

---

## 5. 스킬 적용 2축 (static / runtime)

- **Static modifier** → `Nikke.BuildAttackContext` 주입. 상태 독립/느린 값 (OL, 큐브 고정, 콜렉션 무기효과).
- **Runtime trigger** → 시뮬 루프 소비. 시간/조건/스택/쿨다운 (`trigger.event ≠ passive` 또는 `duration` non-null 또는 `stack_conditions` 존재).
- **스킬 번역기**(GAP phase 1) = `skills_parsed.json` → 두 버킷 라우팅. groups=[] (파서 bailout) = no-op, throw 금지.

---

## 6. 열린 항목 (착수하며 확정)

- **코드 구조**: ✅ **`Nikke.Simulator.Engine` 프로젝트 분리 완료**(2026-06-30, K0). Engine→Core 단방향(컴파일러가 Core→Engine 역참조 차단). 공유 계약(ISimClock/IRotationController/ITarget/Combatant/SkillParsedDto 패밀리/BuffInstance/IMetricsSink·RunResult/SimulationRunner)을 컴파일되는 스텁으로 동결. 조건(Core UI/compute 무지) 유지.
- **`DamageCalculator`/`AttackContext` 위치**: ✅ 확정(2026-06-30) = `Combat/`, namespace `Nikke.Simulator.Core.Combat`. 동시에 3-way split: `Stats/StatCalculator`(대미지) → `Combat/DamageCalculator` 개명·이동, 스탯 조립(`GetCoreAppliedStats`/`GetEquipmentStats`/`GetConsoleStats`)은 `StatTable`→`StatCalculator` 로 이관, `StatTable`=로딩+raw 전용. 38/38 테스트 그린.
- **파서 prerequisite**: 런타임 먼저 + 결손(bailout/PARSE_ERROR) no-op + 파서 병행 (lean). skills_parsed v3 동결.
- **W 단위 정규화 위치**: ✅ 확정(2026-06-30) = `Nikke` 생성자(주입측, `Nikke.cs` [4]). 엔진 로컬 — ETL 재실행/merged DB 재생성 불필요, 데이터 DTO 는 raw(percent-number) 유지 (§3 ✅). (구 `atk_parser.py` 폐기; 현 multiplier 생산처 = `roledata_cleaner.py`.)
- **출력/Evaluator**: sim 1 run = **총대미지 표본 1개** 기록 → Evaluator 가 N run 으로 **분포** 구성(샘플/분위수; tail 필요). 부가: 시간축 DPS·캐릭별·브래킷 분해.
- **Optimizer 지표 정확형**: `P(합딜 ≥ X)` vs 고분위수(예 P90) — 그리고 X/분위수 설정 방식 (UI 입력?). 미정.
- **Optimizer 알고리즘**: 후보풀 선정 + greedy / beam / branch&bound / ILP 중 — 미정. 팀파워 memoize 전제.
- **팀 합 분포**: 팀별 분포의 합 = convolution(팀간 독립 가정) — 가정 타당성 검증 필요.
- **UI/컴퓨트 위치**: 보류 — M1 단일 sim 속도 측정 후 (client Blazor vs 서버 오프로드). 엔진은 무관하게 진행.
- **엔진**: event-driven 확정. (구현 세부 — 이벤트 큐 자료구조 등 — 슬라이스 1에서.)
- **데이터 실측**: 장비표·큐브·소장품 → **확보+C# 연동 완료** (`blabla_static_tables.json`; 장비 `round(base×(1+0.3·corp+0.1·level))` + 큐브/소장품 base·특수효과 = `GetEquipmentStats`/base JSON/`EffectTable` 배선, 34/34 테스트). 타이밍/조건부 효과만 sim 루프 대기. ProperDistance: 무기별 **범위** 확보(roledata bonusrange → `proper_distance_table.json`; MG 35-55·AR 25-45·SMG 15-35·SG 0-25·RL 0-0·SR 45-100, **RL=0 확증**) — 보너스 **크기**(0.3?)만 미검증.
- **무기 타이밍/명중원 데이터+모델** (2026-07-01 작업 유실→2026-07-02 복구 통합): roledata shot 블록(발사 ramp·모션딜레이·명중원·펠릿·재장전·버스트게이지, ETL 정규화: 발/sec·초·분수) → `weaponData` → `WeaponDto`/`Nikke.Weapon`(`WeaponProfile`, null-safe) **배선 완료**. 모델: `Combat/AccuracyModel`(명중원 발당 수축 + P(코어힛)=(rc/R)² 면적확률 + RNG 샘플), `Combat/ProperDistanceTable`(공식 bonusrange 구간 + per-char 오버로드, RL=무보너스), `Targets/DummyTarget`(K5) + `ITarget` 계약 갱신(`Distance/CoreRadius/BodyRadius`, `PopulateContext(+attackerWeaponType)`; 구 `InProperRange` bool 폐기). MG spin-up = 1→70발/s nominal, 발당 +100/60, **60fps 프레임캡→실효 60/s**(`FireRateAtShot`), 중단 1s 리셋. per-char 편차 확증: AR 12|2.5, RL 탭 1~5/s, SG 펠릿 5|10, **Pascal=비차지 RL**(charge_time=0, 1.5발/s 평사) → 무기타입 상수 금지, per-char 데이터가 권위. ⚠ **속성 상성 판정 유틸(ElementAdvantage) = 보류**(2026-07-02 사용자 결정) — DummyTarget 상성 미반영. 잔여 = K3 소비(FiringModel) + HitRate 버프 배선 + spot delay(0.2s) vs 구 실측 0.03s 캘리브레이션 + 타겟 지오메트리(코어/몸체 반지름) 상수 확정.

---

## 7. Ground truth 포인터

| 영역 | 권위 |
|---|---|
| 방향·구조 | **이 문서** (`Docs/DESIGN.md`) |
| 엔진 구현 (how/순서) | `Docs/ENGINE_GUIDE.md` |
| 병렬 작업 분담 (chunk·DAG·순서) | `Docs/WORK_BREAKDOWN.md` |
| 빌드/테스트/데이터 정합 증거 | `Docs/VERIFICATION_LOG.md` |
| 대미지 공식 | 이 문서 §3 + `Combat/DamageCalculator.cs` + golden test + `_dmg_probe.py`/`_dmg_calibrate.py` |
| 스탯 조립 공식 | 이 문서 §3.5 + `Stats/StatCalculator.cs`(+`OverloadProcessor`/`StatTable`) + VERIFICATION_LOG §5 불변식 |
| 데이터 shape | C# `Data/Dto/*.cs` + 실제 JSON |
