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

### K0 — Engine 프로젝트 + 계약 스텁 ★blocks all
- 목표: `Nikke.Simulator.Engine` 프로젝트(ref Core) 생성 + **모든 공유 계약을 컴파일되는 스텁으로** 박고 동결.
- 스코프: 새 csproj + sln 등록. `ISimClock`, `IRotationController`, `ITarget`, `Combatant`, `SkillParsedDto` 패밀리, `BuffInstance`, `IMetricsSink`, 엔트리 `SimulationRunner.RunOnce(teams, target, rng) → RunResult{ TotalDamage, … }`.
- 산출: 0-에러 빌드 + 동결된 계약. **이게 W1 전체를 푼다.**
- 의존: 없음. 수용: 빌드 통과, 계약 시그니처 리뷰 승인.

### K1 — W단위 픽스 + foundation 검증 (M0) ★정확성 게이트
- 목표: `multiplier`(percent) → fraction `/100` 정규화 1곳 확정 + `Initialize→Nikke→BuildAttackContext→CalculateDamage` 1발 굴려 **in-game 1캐릭과 FinalAtk·무버프 평타뎀 일치**.
- 스코프: `Nikke.cs`(W주입) 또는 `atk_parser.py`(저장) 중 1곳 + 검증 콘솔/테스트.
- 의존: 없음(Core). 수용: 알려진 빌드의 in-game 수치와 일치(±표시반올림). **불일치면 W2+ 착수 금지.**

### K2 — SimClock (이벤트 큐)
- 목표: 이산이벤트 클럭. `Schedule(atSec, ev)` / `Run(untilSec)`, min-heap, 동시각 삽입순.
- 스코프: `Engine/SimClock.cs`. 의존: K0. 수용: 단위테스트(순서/동시각/재귀예약).

### K3 — FiringModel
- 목표: Combatant+무기 → 발사 이벤트. 비차지 `1/GetBaseFireRate`, 차지 `Motion+FullCharge`/`Tap`, 탄창→재장전, `IsFullCharge` 세팅.
- 스코프: `Engine/FiringModel.cs`. 입력: WeaponStatTable, Nikke. 의존: K0. 수용: 무기별 발사 타임라인이 RPS/탄창/재장전/차지에 정합.

### K4 — SkillParsed DTO+Loader + Translator
- 목표: `skills_parsed.json`(v3, key=name_code) → C# DTO 역직렬화 + static/runtime 2축 분류(DESIGN §5). `groups:[]`/PARSE_ERROR = no-op.
- 스코프: `Engine/Skills/SkillParsedDto.cs`, `SkillLoader.cs`, `SkillTranslator.cs`. 입력: skills_parsed.json. 의존: K0. 수용: 134 완성분 로드 0-throw, 분류 스냅샷 테스트.

### K5 — ITarget: DummyTarget
- 목표: 고정 DEF/파츠없음/속성중립/적정거리 → 히트마다 AttackContext 의 DEF·`IsCoreHit/IsPartsHit`·`ProperDistanceBonus`·`SumStrongElem` 채우는 헬퍼.
- 스코프: `Engine/Targets/DummyTarget.cs`. 의존: K0. 수용: 컨텍스트 필드 채움 단위테스트.

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
- ✅ 장비표·큐브·소장품(base+특수효과): 공식 blablalink JSON 으로 **연동 완료** (Core stub 해소). 잔여 = ProperDistance, 그리고 타이밍/조건부 큐브효과(sim 루프 대기).

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
