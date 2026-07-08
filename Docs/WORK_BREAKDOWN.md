# WORK_BREAKDOWN — 병렬 작업 청킹 · 순서 (멀티 에이전트용)

> **역할**: 여러 Claude(에이전트)가 각 part 를 **병렬로** 작업하도록 일을 충돌 없는 청크로 쪼개고 의존/순서를 못박는다.
> **권위**: 방향=`DESIGN.md`, 엔진 how/계약=`ENGINE_GUIDE.md`. 이 문서는 *누가 무엇을 어떤 순서로*.
> **각 에이전트 필독 순서**: DESIGN.md → ENGINE_GUIDE.md → 이 문서의 본인 청크.
> **작성**: 2026-06-28.

---

## 1. 병렬화 원칙 (반드시)

1. **Contracts-first.** Wave 0 가 모든 공유 인터페이스/DTO를 **컴파일되는 스텁**(`NotImplementedException`)으로 먼저 박고 **동결**. 이후 임플 청크는 계약에 대고 병렬 작업 + 서로를 mock/stub.
2. **파일 1개 = 청크 1주인.** 두 에이전트가 같은 파일 동시 수정 금지. 각 청크는 *자기 폴더/파일*만 만든다.
3. **계약 파일은 read-only** (Wave 0 산출). 계약 변경 필요 시 → 작업 멈추고 조정(§6).
4. **브랜치/PR 단위.** 각 청크 = master 에서 분기 → 커밋 → PR → 머지. **uncommitted 방치 금지** (과거 사고). worktree 쓰면 끝나고 prune.
5. **결손 내성.** 의존 산출물이 아직 stub 이면 no-op/mock 으로 진행, throw 금지.

---

## 2. 의존 DAG

```
                         ┌─────────────────────────── Python 독립 트랙 (언제든 병렬) ───────────┐
                         │ KP1 파서 backlog   KP2 데이터 실측(장비표·큐브·거리)                  │
                         └──────────────────────────────────┬───────────────────────────────────┘
                                                             │ (skills_parsed v3 / csv; no-op 내성)
 WAVE0 (serial, blocks all)                                  ▼
   K0 Engine 프로젝트 + 계약 스텁 ───────┬───────────────────────────────────────────┐
   K1 W단위픽스 + foundation검증(M0) ─────┤ (정확성 게이트)                            │
                                          ▼                                            ▼
 WAVE1 (K0 후 병렬)        K2 SimClock   K3 FiringModel   K4 SkillDTO+Loader+Translator   K5 ITarget(Dummy)   K6 Metrics
                                          └──────┬───────────────┬─────────────┬──────────────┬──────────────┘
 WAVE2 (W1 후)                                   ▼               ▼             ▼              ▼
                              K7 SkillRuntime+BuffStore     K8 단일캐릭 통합(M1+M2) ◄── K2,K3,K5,K6,K7
                                          └──────────────────────┬───────────────────────────┘
 WAVE3 (K8 후)                K9 팀+풀버스트(M3)   K10 RotationController(Auto/Scripted)(M4)   K11 BossTarget(M5)
                                          └──────────────────────┬───────────────────────────┘
 WAVE4                                            K12 Evaluator (N-run → 분포/캐시)
                                                             ▼
 WAVE5                                            K13 Optimizer (K팀 분할, tail 목적)
                                                             ▼
 WAVE6                                   K14 Web UI (스택 TBD)        K15 배포
```

---

## 3. 웨이브 = 동시 실행 묶음

| Wave | 동시 가능 청크 | 진입 조건 |
|---|---|---|
| 0 | K0, K1 (느슨 병렬; K0 계약이 W1 차단) | master |
| 1 | **K2, K3, K4, K5, K6** (5병렬) | K0 머지 |
| 2 | K7 ∥ (K8 은 K2/K3/K5/K6/K7 후) | Wave1 |
| 3 | K9, K10, K11 (3병렬) | K8 |
| 4 | K12 | 엔진이 RunResult 산출(K8+) |
| 5 | K13 | K12 |
| 6 | K14, K15 | K12/K13 API (UI 쉘은 계약 대고 조기 시작 가능) |
| ∥ | **KP1, KP2** (Python) | 항상 |

---

## 4. 청크 스펙 (핸드오프용)

> 각 청크: **목표 / 스코프(파일) / 입력 / 산출(계약) / 의존 / 수용기준.** 상세 컴포넌트 계약 = ENGINE_GUIDE §5.
> **즉시 착수 2 task (상세, 도메인 로컬)**: 엔진 Wave0(K0+K1) = `SimulatorEngine/ENGINE_WAVE0.md` · roledata 스킬 audit(K4 소스 결정, KP1 운명) = `DataPipeline/ROLEDATA_SKILL_AUDIT.md`.

### K0 — Engine 프로젝트 + 계약 스텁 ★blocks all  — 🟢 빌드 완료, 리뷰 동결 대기
- 목표: `Nikke.Simulator.Engine` 프로젝트(ref Core) 생성 + **모든 공유 계약을 컴파일되는 스텁으로** 박고 동결.
- 스코프: 새 csproj + sln 등록. `ISimClock`, `IRotationController`, `ITarget`, `Combatant`, `SkillParsedDto` 패밀리, `BuffInstance`, `IMetricsSink`, 엔트리 `SimulationRunner.RunOnce(teams, target, rng) → RunResult{ TotalDamage, … }`.
- 산출: 0-에러 빌드 + 동결된 계약. **이게 W1 전체를 푼다.**
- 의존: 없음. 수용: ✅ 빌드 통과(2026-06-30, 4 프로젝트 0 에러) · [~] 계약 시그니처 리뷰 승인(사용자 리뷰 후 read-only 동결).

### K1 — W단위 픽스 + foundation 검증 (M0) ★정확성 게이트  — 🟢 통과 (Wave1 착수 가능)
- 목표: `multiplier`(percent-number) → fraction `/100` 정규화 1곳 확정 + `Initialize→Nikke→BuildAttackContext→CalculateDamage` 1발 굴려 **in-game 1캐릭과 FinalAtk·무버프 평타뎀 일치**.
- 스코프: ✅ `Nikke.cs`(W주입측 `/100`) + `StatTable.Initialize` 견고 파서(cp949/멀티라인/콤마 내성, 내용기반 행탐지) + `WUnitFoundationTests`(5).
- 의존: 없음(Core). 수용: ✅ W 정규화 확정·문서화 · ✅ in-game 일치 = stat 0-error(사용자) + gap#4 평타 실측(사용자) + golden 18 + wiring 테스트. **게이트 통과 → Wave1(K2~K6) 착수 가능.**

### K2 — SimClock (이벤트 큐)  — ✅ 완료 (2026-07-01, 10 단위테스트 통과)
- 목표: 이산이벤트 클럭. `Schedule(atSec, ev)` / `Run(untilSec)`, min-heap, 동시각 삽입순.
- 스코프: `Engine/Clock/SimClock.cs`(인터페이스 옆). 의존: K0. 수용: ✅ `SimClockTests.cs` 10(순서/동시각 FIFO/재귀예약 2종/과거예약 throw/분할Run/NowSec 단조·종료=untilSec/빈큐/창밖/경계포함).
- 임플: `PriorityQueue<Action,(double,long)>` + 단조증가 seq 로 동시각 삽입순 결정적 고정(.NET PQ 동순위 불안정 보정). `Run(untilSec)` = untilSec 포함·종료 시 `NowSec=untilSec` 클램프(resumable). 계약 무수정.

### K3 — FiringModel — ✅ 완료 (2026-07-08, 15 단위테스트)
- 구현: `Engine/FiringModel.cs` — 60fps 프레임 상태기계 (SimClock 배선·대미지/게이지 이벤트 발행 = K8 몫). ENGINE_GUIDE §5 확정 스펙 전부: RPM accumulator(1발/프레임 구조 캡 → MG 실효 60/s) · MG ramp+점진 감쇠 · 전이 spot 0.2s 양방향 · SR/RL 3부류(UP 사이클 83f≈1.4s / maintain 자체후딜 / DOWN_Charge only풀차지+rate gate) · 재장전 R1/R2(감산형 공식, ≥100% 버프 = 무한탄창 **창발** 검증) · `ControlMode.Auto/Manual`(re-click [0.02,0.028]s, 수동 풀차지 61f≈1.02s·톡톡이 14f≈0.23s = 사용자 실측 재현) · SG 펠릿 · 명중원 수축/회복.
- 수용 ✅: `FiringModelTests`(15) — AR 12/s·MG 스핀업/감쇠·SR 사이클·수동 루틴·무한탄창·펠릿 전부 프레임 단위 검증. 잔여 = K8 배선(발사→AttackContext/AccuracyModel.RollCoreHit), 버스트 stage 딜레이 상수(측정① 대기).

### K4 — 스킬 데이터 Loader + Translator — ✅ 완료 (2026-07-08, 17 테스트)
- **데이터원 = 공식 FunctionTable** (사용자 결정; `FUNCTIONTABLE_DECODE_PLAN.md` §0). skills_parsed v3 는 검증 참조.
- 구현: `Engine/Skills/` — `OfficialSkillEnums.cs`(공식 enum 미러 8종, memorypack_decode dict 기계생성) · `SkillChainDto.cs`(skill_chains.json 1:1, enum=원시 int 보존+Typed* 접근, `ValueAsFraction` ×10000 해석) · `SkillChainLoader.cs`(TryLoad — 파일 부재=graceful false, 참조 무결성 검증) · `SkillTranslator.cs`(**2축 분류** Classify: 트리거·조건 無+영구=Static/그 외 Runtime + **EffectRoute 매핑표**: 확실 타입만 슬롯 배정, 미검증=Unverified(K8 승격 대상), 신값=Unknown no-op).
- 수용 ✅: `SkillChainLoaderTests`(17) — 192캐릭/87보스/14,249함수 로드+무결성 0-throw, Emma·Red Hood D1 검증값 재확인, 전 함수 라우팅/분류 graceful(미지 신값 ?214 ×11개뿐). 분포 스냅샷: StatAtk 1763 · UseCharacterSkillId 1401(연쇄 호출 — K7 필수) · Damage 686 · AddDamage 620(브래킷 미검증 — K8 대조 우선).

### K5 — ITarget: DummyTarget — 🟢 구현 (2026-07-01 유실→07-02 복구 통합)
- 목표: 고정 DEF/속성/거리/지오메트리 타겟 → 히트마다 AttackContext 의 DEF·`ProperDistanceBonus` 채움. ✅ `ITarget` 계약 갱신(`Distance/CoreRadius/BodyRadius`, `PopulateContext(+attackerWeaponType)`; 구 `InProperRange` 폐기 — 무기 비의존 bool 은 의미오류).
- 스코프: `Engine/Targets/DummyTarget.cs`. 의존: K0. 수용: ✅ 컨텍스트 주입 단위테스트(`WeaponDataTests`). 잔여: 속성 상성(SumStrongElem) = ElementAdvantage 보류(사용자 결정)로 미반영, 코어힛은 K3(FiringModel)가 AccuracyModel 로 샘플링.

### K6 — MetricsCollector — ✅ 완료 (2026-07-08, 6 테스트)
- 구현: `Engine/Metrics/MetricsCollector.cs` — record-every-instance(D4), 히트당 고정 누적(인스턴스 리스트 미보관 = O(고유 태그) 메모리). `RunResult` 분해 필드 확정: `HitCount`·`DamageByTag`("tag=value" 키)·`DamagePerSecond`(초 버킷). `Build()`=스냅샷(반복 호출 가능)·`Reset()`(N-run 재사용). run 창 밖 시각 = throw(클럭 배선 버그 조기 검출).
- 수용 ✅: `MetricsCollectorTests`(6) — 총합/소스별/태그분해/초버킷 경계/스냅샷 불변/Reset/인자 방어.

### K7 — SkillRuntime + BuffStore + BuffAggregator
- 목표: 트리거 등록→이벤트 발생 시 조건평가→effects 적용(BuffInstance 스폰 / deal_damage 인스턴스). 활성버프 → AttackContext 합산(니케식 group-then-round). duration 만료, stack 분기.
- 스코프: `Engine/Skills/SkillRuntime.cs`, `Engine/Buffs/*.cs`. 의존: K0, K4. 수용: passive/지속/스택/만료 시나리오 테스트.

### K8 — 단일 캐릭 통합 (M1+M2) ★integration
- 목표: K2+K3+K5+K6(+K7) 배선 → `SimulationRunner.RunOnce` 가 캐릭 1명 시간축 DPS 산출. 크리 RNG 포함.
- 스코프: `Engine/SimulationRunner.cs`(엔트리 구현). 의존: K2,K3,K5,K6,K7,K1. 수용: 단일캐릭 DPS in-game 대조 + N회 크리 수렴.

### K9 — 팀 + 풀버스트 (M3)
- 목표: 5 Combatant, ally-target 버프 팀 전파, 버스트 게이지→Full Burst, `burst_*` 트리거.
- 스코프: `Engine/Team/*.cs`. 의존: K8. 수용: 버퍼 유무로 팀 DPS 유의 변동, FB 창 on/off.

### K10 — RotationController (Auto/Scripted) (M4)
- 목표: `IRotationController` ← `AutoController`(게이지/쿨다운) + `ScriptedController`(타임라인 입력).
- 스코프: `Engine/Rotation/*.cs`. 의존: K8. 수용: 단순덱 자동 / 기믹덱 스크립트 동일 클럭 소비.

### K11 — BossTarget (M5)
- 목표: HP/파츠/DEF/속성 데이터 기반 `ITarget`. 스코프: `Engine/Targets/BossTarget.cs`. 의존: K0(계약), K5(패턴). 수용: 보스 데이터 주입 → 컨텍스트 정합.

### K12 — Evaluator
- 목표: 팀 1개 N-run → **분포**(샘플/분위수; tail), 팀조합→파워 **캐시/저장**.
- 스코프: 별 프로젝트/네임스페이스 `Evaluator/`. 의존: K8(RunResult). 수용: 분포 통계 정확, 캐시 히트.

### K13 — Optimizer
- 목표: 로스터→K팀 분할(캐릭1회), **고점×확률 목적**(P(≥X)/고분위수) 최대 탐색. 팀파워 memoize.
- 스코프: `Optimizer/`. 의존: K12. 수용: 소규모 풀에서 최적해 brute-force 와 일치, 캐시로 가속.

### K14 / K15 — Web UI / 배포
- 목표: 로스터 입력·결과·차트 / 공개 호스팅. 스코프: 별 앱. 의존: K12/K13 API(쉘은 계약 대고 조기). UI 스택 = M1 벤치 후 결정(보류).

### KP1 — 파서 backlog (Python, ∥) — ⏸ 사실상 종료 (2026-07-08)
- 데이터원이 공식 FunctionTable 로 재결정되어 LLM 재파싱 backlog 은 중단. skills_parsed.json(v3)은 현상태로 검증 참조만. (구 스코프: bailout 재파싱·token enum화 등 — 기록용으로 보존.)

### KP3 — 공식 스킬 데이터 디코드+조립 (Python, ★D1 — K4/K7 데이터원)
- **디코드+검증 ✅ (2026-07-08, D1)**: 스키마 이식 완료 → FunctionTable(19459)/CharacterSkillTable(4387)/StateEffectTable(5155)/SkillInfoTable(9280)/CharacterTable(1905, surface_category drift 교정) **전부 clean**. 검증 통과: 니케 스킬 수치 roledata bit-exact(Red Hood 813.42%/Emma 10.77%+5%트리거), value=×10000, 보스 passive 정합, enum 미지값=신값뿐. 상세 = `FUNCTIONTABLE_DECODE_PLAN.md` §0.
- **조립(D3) ✅ (2026-07-08)**: `staticdata_skill_chains.py` → `assembled/skill_chains.json`(**gitignore** — 사용자 결정: GitHub=gitignore, 로컬 생성). 니케 192(스킬레벨 5,750; 결손=3001 스킬2 부재 1명뿐) + 솔로레이드 보스 87(statenhance 230000; passive+use/hurt 체인) + 사용 함수 14,249(connected BFS, Fx 필드 제거+enum 이름 주석) + state_effects 3,381.
- 의존: StaticData zip(qa-260702, 로컬). 소비처 = K4(다음).

### KP2 — 데이터 실측 (사용자, ∥)
- ✅ 장비표·큐브·소장품(base+특수효과): 공식 blablalink JSON 으로 **연동 완료** (Core stub 해소).
- ✅ 무기 데이터(roledata `weaponData`): 발사속도 ramp/탄창/차지/명중원/모션딜레이/버스트게이지/멀티펠릿 → `WeaponProfile`+모델 **연동 완료**(2026-07-01 유실→07-02 복구). 적정거리 구간도 공식 bonusrange 로 확보.
- ✅ 발사/모션/재장전 스펙 확정(2026-07-08, 사용자 실측+einkk+데이터 — ENGINE_GUIDE §5): 전이 0.2s 전 무기 · 재장전 감산형 공식+R1/R2 · SR/RL 3부류(input/maintain 필드) · re-click [0.02,0.028]s · 풀버 10s=진입 기산.
- ✅ ①3버스트→풀버스트 진입 딜레이 = **0.46s ≈ 28프레임** (사용자 영상 실측 2026-07-08). ②버스트 시전 사격공백 = **무시 결정**(사용자).
- 잔여 실측 = ProperDistance 보너스 크기(0.3) + 타겟 core/body 반지름 + `RLV2SwitchDelayTime`(=0.2s, ConfigBattle) 의미 + 타이밍/조건부 큐브효과(sim 루프 대기).

---

## 5. 코디네이션 규칙

- **K0 계약 동결**: 머지 후 계약 파일은 read-only. 변경 필요 = 이슈로 올리고 의존 청크에 통지 후 일괄.
- **충돌 회피**: 청크별 전용 폴더(`Engine/Skills`, `Engine/Targets`, …). 공유 파일(.sln, .csproj) 편집은 K0 만.
- **머지 위생**: 각 청크 PR = 빌드+테스트 green. bin/obj/.vs 커밋 금지(gitignore 됨). 개인데이터 커밋 금지.
- **검증 게이트**: K1 통과 전 damage 신뢰 금지. K8 통과 전 팀/Evaluator 착수 금지.
- **에이전트 시작 체크**: 최신 master 에서 분기했는지(과거 frozen-master 사고 방지), DESIGN/ENGINE_GUIDE 읽었는지.

---

## 6. 참조
- 방향·목표·tier: `Docs/DESIGN.md` (§0.5 tiers, §6 열린항목)
- 엔진 컴포넌트 계약·마일스톤·MUST: `Docs/ENGINE_GUIDE.md`
- 스킬 스키마: `DataPipeline/schema/skill_schema_legend.txt`
