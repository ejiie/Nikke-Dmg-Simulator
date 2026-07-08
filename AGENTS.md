# AGENTS.md

Codex/에이전트 진입점 = **`CLAUDE.md`** 를 읽으세요 (동일 내용). 요지:

- 프로젝트 = NIKKE 최적 solo raid 덱 편성 도구 (sim 기록 축적 → 분포 → 최적 조합).
- 필독: `CLAUDE.md` → `Docs/ROADMAP.md` → `Docs/FACTS.md` → `Docs/tasks/T##`.
- 불변 규칙: FACTS 불변(변경 = 사용자 확인), 미지값 graceful no-op, 고정 시드 금지, Engine→Core 단방향, 복호물/개인데이터 커밋 금지.
- 테스트: `dotnet test SimulatorEngine`.
