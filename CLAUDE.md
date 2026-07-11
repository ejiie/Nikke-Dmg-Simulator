# CLAUDE.md — 프로젝트 작업 진입점 (Claude Code / Codex 자동 로드)

> 이 저장소에서 작업하는 모든 LLM/에이전트가 **가장 먼저** 읽는다. Codex 는 `AGENTS.md`(동일 내용) 참조.

## 이 프로젝트는

**NIKKE 보유 로스터로 최적 solo raid 덱 편성을 찾아주는 도구.** 단순 sim 이 아니라 — sim 기록을
축적해 덱별 **분포(평균·표준편차·신뢰구간·tail)** 를 구하고, 그걸로 최적 조합을 탐색한다.
sim 은 사람이 직접(하네스) 또는 background 대량 자동 실행. **MVP(ver.0) = solo raid**, union 은 확장.

## 필독 순서 (맥락 유실 방지 — 반드시)

1. **이 파일** — 규칙·진입점.
2. **`Docs/ROADMAP.md`** — 목표·기술스택·마일스톤 DAG·현황. (줄기)
3. **`Docs/FACTS.md`** — 수년 연구로 **증명된 불변 사실** (공식·단위·라운딩·발사 스펙). 여기와 어긋나면 그쪽이 틀림.
4. 본인 작업 = **`Docs/tasks/T##-*.md`** (가지 — self-contained).
5. 방향 권위 = `Docs/DESIGN.md`, 검증 증거 = `Docs/VERIFICATION_LOG.md`, 엔진 계약 = `Docs/ENGINE_GUIDE.md`.

## 절대 규칙 (INV — FACTS §7 상세)

- **FACTS.md 는 불변.** 수치·공식을 바꿀 발견 = 코드보다 **먼저 사용자 확인**.
- 미지 enum / 결손 데이터 = **graceful no-op** (throw 금지). 게임 신버전 값 존재 전제.
- RNG = `IRandomSource`, **고정 시드 금지**. 검증은 N-run 수렴.
- 엔진 = UI/compute 무지 순수 라이브러리. **Engine→Core 단방향.**
- **게임데이터 복호물·개인 로스터 = 커밋 금지** (gitignore). 재생성 = `python DataPipeline/run_pipeline.py --stage staticdata`.
- 라운딩 = **OverloadProcessor 니케식 group-then-round**. 시간류 = 1/100초 정수(`ReduceTimeCs`). Σ 후 곱 금지.

## 작업 위생

- 청크 단위 커밋, **uncommitted 방치 금지** (과거 유실 사고 2회 — worktree 미머지 소실).
- 로컬 master 머지 + PR. 커밋 후 `git diff` 자가 점검 (문서 모순 잔존 금지).
- 테스트 green 유지 (현 129/129). 데이터 의존 테스트 = 부재 시 graceful skip.

## 스택 한눈에

- **데이터**: blablalink roledata/static(공개 CDN) + NIKKE StaticData(.mpk, MemoryPack) → Python ETL → `Database/`.
  스킬 = **공식 FunctionTable** (LLM 파서는 폐기 — `_archive/`).
- **엔진**: C# .NET8. Core(공식·스탯·대미지) + Engine(60fps 프레임 상태기계, nikke-einkk 참조).
- **하네스**: `nikke-harness`(콘솔, M2 대조). **기록**: SQLite (T05).
- **테스트**: `dotnet test SimulatorEngine`.

## 현황 (2026-07-11)

Tier 1 Core ✅ (공식·스탯 검증). 엔진 Wave1+K8 M1 ✅. **T01 SkillRuntime ✅ + T04 BossTarget ✅**
(THE GAP 코어 닫힘 — 트리거→효과 루프·상성·보스 39변종, 테스트 169/169).
다음 = **T02 버스트+팀** → T03 로테이션 → T05 기록DB → T06/T08. 상시 = T07 골든 대조.
