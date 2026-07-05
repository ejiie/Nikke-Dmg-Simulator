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

### K3 — FiringModel
- 목표: Combatant+무기 → 발사 이벤트. 발사 간격 = `Weapon.FireIntervalSec(n)`(MG spin-up+60fps캡 내장), 사격중단 리셋, 차지 = `IsChargeWeapon`(무기타입 아님 — Pascal=비차지 RL) `ChargeTimeSec`/`Tap`, SG `ShotCount` 펠릿, 탄창→재장전(`ReloadBulletRate`), 모션 `SpotFirst/LastDelaySec`, `IsFullCharge` 세팅 + `AccuracyModel.RollCoreHit`→`IsCoreHit`.
- 스코프: `Engine/FiringModel.cs`. 입력: **`Nikke.Weapon`(WeaponProfile — fire-rate 권위, 2026-07-02 복구 통합)** + AccuracyModel + ITarget(CoreRadius/BodyRadius). WeaponStatTable 은 레거시(tap 간격 실측값만 잔존 용도). 의존: K0. 수용: 무기별 발사 타임라인이 RPS/탄창/재장전/차지/MG ramp 에 정합.

### K4 — SkillParsed DTO+Loader + Translator
- 목표: `skills_parsed.json`(v3, key=name_code) → C# DTO 역직렬화 + static/runtime 2축 분류(DESIGN §5). `groups:[]`/PARSE_ERROR = no-op.
- 스코프: `Engine/Skills/SkillParsedDto.cs`, `SkillLoader.cs`, `SkillTranslator.cs`. 입력: skills_parsed.json. 의존: K0. 수용: 134 완성분 로드 0-throw, 분류 스냅샷 테스트.

### K5 — ITarget: DummyTarget — 🟢 구현 (2026-07-01 유실→07-02 복구 통합)
- 목표: 고정 DEF/속성/거리/지오메트리 타겟 → 히트마다 AttackContext 의 DEF·`ProperDistanceBonus` 채움. ✅ `ITarget` 계약 갱신(`Distance/CoreRadius/BodyRadius`, `PopulateContext(+attackerWeaponType)`; 구 `InProperRange` 폐기 — 무기 비의존 bool 은 의미오류).
- 스코프: `Engine/Targets/DummyTarget.cs`. 의존: K0. 수용: ✅ 컨텍스트 주입 단위테스트(`WeaponDataTests`). 잔여: 속성 상성(SumStrongElem) = ElementAdvantage 보류(사용자 결정)로 미반영, 코어힛은 K3(FiringModel)가 AccuracyModel 로 샘플링.

### K6 — MetricsCollector
- 목표: 히트마다 `Record(timeSec, sourceId, amount, tags)` → `RunResult`(총대미지 + 시간축/캐릭별/브래킷 분해).
- 스코프: `Engine/Metrics/MetricsCollector.cs`. 의존: K0. 수용: 집계 정확성 테스트.

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

### KP1 — 파서 backlog (Python, ∥)
- 70 bailout(57명)+완전실패 2명 재파싱, trait_weapon_transformed granular(20), filter(62)/required(184) token enum화, distrib/sequential 브래킷, julia/ein 재분류. 산출: skills_parsed.json 품질↑(스키마 v3 동결 유지). K4 가 무중단 흡수.

### KP2 — 데이터 실측 (사용자, ∥)
- ✅ 장비표·큐브·소장품(base+특수효과): 공식 blablalink JSON 으로 **연동 완료** (Core stub 해소).
- ✅ 무기 데이터(roledata `weaponData`): 발사속도 ramp/탄창/차지/명중원/모션딜레이/버스트게이지/멀티펠릿 → `WeaponProfile`+모델 **연동 완료**(2026-07-01 유실→07-02 복구). 적정거리 구간도 공식 bonusrange 로 확보.
- 잔여 = ProperDistance **보너스 크기(0.3) 실측** + 명중 모델용 타겟 core/body 반지름 실측 + spot delay(0.2s vs 구 실측 0.03s) 캘리브레이션 + 타이밍/조건부 큐브효과(sim 루프 대기).

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
