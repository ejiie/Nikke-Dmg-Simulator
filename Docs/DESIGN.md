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
| 1 **Core** | stat 조립 + per-hit 대미지 공식 | 🟡 거의 (공식 ✅ 검증) |
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
| **스코프** | 명중률(StatAccuracyCircle)만 제외, 그 외 전부 (생존/CC/힐/실드 포함) | 단계적 |
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
SimulatorEngine/Nikke.Simulator.Core (C# .NET8)
   Data/        JsonProvider(I/O 단일점) + Dto(JSON 1:1) + Constants(큐브/콜렉션)
   Stats/       StatTable(CSV) · OverloadProcessor(pre-combat OL 조립)
                · WeaponStatTable(발사속도/차지) · IRandomSource/CritSampler(크리 RNG)
   Combat/      DamageCalculator(per-tick 공식 §3) + AttackContext(tick struct)
   Entities/    Nikke(최종 기초스탯 + BuildAttackContext 팩토리)
   [신설 예정]  Runtime/ — 이벤트 클럭 + 스킬 런타임 + 버프 스토어 + 로테이션 제어 + 타겟
        │
SimulatorEngine/Nikke.Simulator.Wpf  (WPF UI; App.OnStartup 에서 StatTable.Initialize)
```

> ※ 현재 `DamageCalculator`/`AttackContext` 의 정확한 파일 위치(`Stats/` vs `Combat/`)는 §6 열린 항목.

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
  - ⚠️ 데이터 `basicAttack.multiplier` 는 **percent**(예 8.73 = "8.73% ATK"), `chargeDamage` 는 fraction(2.5) — **단위 불일치.** W 주입 시 `multiplier/100` 정규화 필수 (안 하면 100× 버그). 정규화 위치 1곳 확정해 문서화 (ENGINE_GUIDE P1).
- **C** = 차지 배율. 비차지 = 1. 풀차지: `C = (ChargeDmgBase + Σcharge_dmg) × (1 + Σcharge_dmg_mult)`.
  - `ChargeDmgBase` = per-character `basicAttack.chargeDamage` (대부분 2.5, 일부 3.5).
- **[A1] 최소 대미지**: `effectiveDef ≥ FinalAtk` → 배율 무관 즉시 **1** (중간 곱 미경유).
- **[A2] True Damage**: `effectiveDef := 0`, 그리고 B3 에 `Σtrue_dmg_buff` 조건부 가산.
- **구조 요점**: B2 내부 = 가산-per-term-floor / B2~B5 사이 = 곱셈 / 마지막 단일 floor.

**구현·검증 위치**:
- C#: `SimulatorEngine/Nikke.Simulator.Core/Stats/StatCalculator.cs` (`CalculateDamage`).
- 골든 테스트: `Nikke.Simulator.Tests/DamageFormulaGoldenTests.cs` (18점, ≤1.3e-7).
- 유도/캘리브레이션: 저장소 루트 `_dmg_probe.py`(구조 발견) + `_dmg_calibrate.py`(계수 역산).

> **이 §3 이 대미지 공식의 단일 권위.** legend / skill_schema / 그 외 문서의 공식 표기는 여기에 종속.

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

- **코드 구조**: **권장 = `Nikke.Simulator.Engine` 지금 분리** (tier 3/4/5·배포가 엔진을 라이브러리로 재사용 → 프로젝트 벽이 결합부채 차단; 컴파일러가 Core→Engine 참조 금지). 조건: Core 는 UI/compute 무지 유지. (확정 대기.)
- **`DamageCalculator`/`AttackContext` 위치**: 현재 master `Stats/`. worktree 에 `Combat/` 이동안 존재 — cosmetic, 채택 미정.
- **파서 prerequisite**: 런타임 먼저 + 결손(bailout/PARSE_ERROR) no-op + 파서 병행 (lean). skills_parsed v3 동결.
- **W 단위 정규화 위치**: `multiplier/100` 을 `atk_parser.py`(저장 시) vs `Nikke`(주입 시) 중 어디서 — 1곳 확정 (§3 ⚠️).
- **출력/Evaluator**: sim 1 run = **총대미지 표본 1개** 기록 → Evaluator 가 N run 으로 **분포** 구성(샘플/분위수; tail 필요). 부가: 시간축 DPS·캐릭별·브래킷 분해.
- **Optimizer 지표 정확형**: `P(합딜 ≥ X)` vs 고분위수(예 P90) — 그리고 X/분위수 설정 방식 (UI 입력?). 미정.
- **Optimizer 알고리즘**: 후보풀 선정 + greedy / beam / branch&bound / ILP 중 — 미정. 팀파워 memoize 전제.
- **팀 합 분포**: 팀별 분포의 합 = convolution(팀간 독립 가정) — 가정 타당성 검증 필요.
- **UI/컴퓨트 위치**: 보류 — M1 단일 sim 속도 측정 후 (client Blazor vs 서버 오프로드). 엔진은 무관하게 진행.
- **엔진**: event-driven 확정. (구현 세부 — 이벤트 큐 자료구조 등 — 슬라이스 1에서.)
- **데이터 실측**: 장비표·큐브·소장품 → **확보+C# 연동 완료** (`blabla_static_tables.json`; 장비 `round(base×(1+0.3·corp+0.1·level))` + 큐브/소장품 base·특수효과 = `GetEquipmentStats`/base JSON/`EffectTable` 배선, 34/34 테스트). 타이밍/조건부 효과만 sim 루프 대기. ProperDistance 0.3(RL=0 외 미검증)은 여전히 열림.

---

## 7. Ground truth 포인터

| 영역 | 권위 |
|---|---|
| 방향·구조 | **이 문서** (`Docs/DESIGN.md`) |
| 엔진 구현 (how/순서) | `Docs/ENGINE_GUIDE.md` |
| 병렬 작업 분담 (chunk·DAG·순서) | `Docs/WORK_BREAKDOWN.md` |
| 빌드/테스트/데이터 정합 증거 | `Docs/VERIFICATION_LOG.md` |
| 대미지 공식 | 이 문서 §3 + `Stats/StatCalculator.cs` + golden test + `_dmg_probe.py`/`_dmg_calibrate.py` |
| 스킬 스키마 | `DataPipeline/schema/skill_schema_legend.txt` + `skill_schema.py` (Pydantic) |
| 데이터 shape | C# `Data/Dto/*.cs` + 실제 JSON |
| historical (참고만) | `Docs/_archive/*` — 2026-04, 일부 superseded |
