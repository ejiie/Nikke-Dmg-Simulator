# ROADMAP — 줄기 문서 (무엇을, 어떤 순서로)

> **지위**: 작업 순서·범위의 단일 권위 (구 WORK_BREAKDOWN 을 대체 — 2026-07-08 재편).
> **필독 순서 (모든 작업자/LLM)**: 루트 `CLAUDE.md` → 이 문서 → `Docs/FACTS.md`(불변 사실) → 본인 가지 `Docs/tasks/T##`.
> 방향·공식의 권위 = `Docs/DESIGN.md`. 검증 증거 = `Docs/VERIFICATION_LOG.md`.

---

## 1. 목표 (2026-07-08 재확인)

단순 sim 이 아니다. **sim 기록을 축적해 덱별 분포(평균·표준편차·신뢰구간·tail)를 구하고,
최적 solo raid 덱 편성을 찾는 도구.**

- sim 은 사람이 하네스로 직접 돌릴 수도 있고, **background 에서 무작위 덱을 대량 sim 하여 기록 DB 에 축적**할 수도 있다.
- **MVP (ver.0) = solo raid 기반.** union raid 는 ver.0 완성 후 기능 확장 (데이터·optimizer 제약 추가).
- 배포 지향: 개인 데이터 하드코딩 금지 (로스터는 유저 입력), 게임데이터 재배포 금지 (gitignore).

## 2. 확정 기술 스택 (2026-07-08 기준 — 이전 문서와 충돌 시 이쪽이 맞음)

| 층 | 스택 |
|---|---|
| 캐릭터/무기 데이터 | blablalink roledata (공개 CDN) → `roledata_cleaner.py` → merged DB |
| 스킬 데이터 | **공식 FunctionTable** (StaticData .mpk → `memorypack_decode.py`(SharpnelXu 공개 스키마) → `staticdata_skill_chains.py` → `skill_chains.json`) — LLM 파서는 폐기(`_archive/`) |
| 보스 데이터 | solo raid 39 변종: `staticdata_solo_raid.py` → `solo_raid_boss.json` (element·레벨스탯·파츠·코어판정) |
| 엔진 | C# .NET8 — Core(공식·스탯) + Engine(60fps 프레임 상태기계, einkk 참조) |
| 스킬 런타임 모델 | nikke-einkk `function.dart` 4단계 (`Docs/SKILL_RUNTIME_REFERENCE.md`) |
| 기록 | SQLite (단일 파일, WAL, 멀티코어 runner + 단일 writer) — §5 |

## 3. 현황 스냅샷 (완료 ✅)

- **Tier 1 Core**: 대미지 공식(18골든 ≤1.3e-7) · 스탯 조립(0-error) · 라운딩 권위(OverloadProcessor) — FACTS §1~3.
- **Wave1+**: SimClock(K2) · FiringModel(K3 — 발사/모션/재장전 전 스펙) · 공식 스킬 로더/번역기(K4) ·
  DummyTarget(K5) · Metrics(K6) · **RunOnce M1 배선(K8)** · M2 하네스(`nikke-harness`).
- 테스트 129/129. 벤치: **180s run ≈ 26ms** (Release, 단일캐릭) → 코어당 ~14만 run/h.

## 4. 마일스톤 DAG (남은 작업 = 가지 문서)

```
T07 M2 골든 대조(사용자·상시) ─┐
T01 SkillRuntime(K7) ──────────┼──> T02 버스트 사이클+팀(K9) ──> T03 로테이션(K10) ─┐
T04 BossTarget(K11) ───────────┘                                                     ├─> ver.0 MVP
T05 Evaluator+기록DB(K12) ◄── (T01·T02·T04 후 실전 표본) ─────────────────────────────┤
T06 background runner ◄── T05                                                         │
T08 Optimizer(K13) ◄── T05 ───────────────────────────────────────────────────────────┘
이후(확장): union raid(데이터 복원+다팀 제약) · Web UI · 배포
```

| 가지 | 내용 | 의존 |
|---|---|---|
| [T01](tasks/T01-skill-runtime.md) | SkillRuntime — 트리거→효과 적용 루프 (THE GAP 마지막 조각) | 없음 (즉시) |
| [T02](tasks/T02-burst-team.md) | 버스트 게이지·사이클 + 팀 5인 (K9) | T01 |
| [T03](tasks/T03-rotation.md) | RotationController Auto/Scripted (K10) | T02 |
| [T04](tasks/T04-boss-target.md) | BossTarget + ElementAdvantage 통합 (K11) | 없음 (병렬 가능) |
| [T05](tasks/T05-evaluator-db.md) | Evaluator + SQLite 기록 DB (K12) | T01·T02·T04 |
| [T06](tasks/T06-background-runner.md) | 무작위 덱 background sim runner | T05 |
| [T07](tasks/T07-m2-golden.md) | M2 in-game 골든 대조 (사용자 협업, 상시) | 하네스 ✅ |
| [T08](tasks/T08-optimizer.md) | Optimizer — K팀 분할·tail 목적 (K13) | T05 |

## 5. 기록 DB 설계 (확정 방향 — 상세/DDL = T05)

- **SQLite 단일 파일, solo/union 통합** + `mode` 컬럼('solo_raid' / 'union_raid'): 스키마 동일·union 은
  확장이라 분리 시 빈 DB 이중 관리만 남. optimizer 의 union 제약(로스터 분할)은 DB 가 아닌 optimizer 층 문제.
  분리 필요해지면 SQLite ATTACH/export 로 마이그레이션 쉬움. (사용자 검토 2026-07-08 — 통합 채택)
- **run 1행 = 표본 1개** + **run_members 정규화 테이블** (run_id, slot, name_code, damage):
  "어떤 덱 조합에서 특정 니케가 강한가" 를 SQL 로 직접 질의 (사용자 요구 1).
- **버전 태깅 필수**: `engine_version`(git) + `data_version`(StaticData 태그+roledata 해시) —
  공식/데이터 갱신 시 구 기록 오염 방지. 집계는 항상 이 축으로 필터.
- 시드 저장 금지 (FACTS §7 INV) — 재현은 N-run 수렴.

## 6. 작업 규칙 (전 작업자)

1. **FACTS.md 는 불변** — 수치·공식·단위를 바꿀 발견이 나오면 코드보다 먼저 사용자 확인.
2. 미지 enum/결손 데이터 = **graceful no-op** (throw 금지).
3. 확률 = `IRandomSource`, **고정 시드 금지** — 검증은 N-run 수렴.
4. 커밋 = 청크 단위, uncommitted 방치 금지 (과거 유실 사고 2회). 로컬 master 머지 + PR.
5. 문서 갱신은 관련 행 전부 (모순 잔존 금지) — 작업 후 `git diff` 자가 점검.
6. 게임데이터 복호물 = gitignore. 재생성 = `run_pipeline.py --stage staticdata`.
