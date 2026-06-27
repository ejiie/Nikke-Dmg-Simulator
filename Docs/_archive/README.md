# Docs/_archive — 보존 자료 (현재 ground-truth 아님)

제거된 worktree에서 건져낸 과거 산출물. **참고용 보존**이며 **현재 진실원(ground truth)이 아니다.**

## 출처
2026-06-27 repo 정리 중, 더 이상 안 쓰는 worktree를 제거하기 전에 master에 없던 unique 파일만 salvage.

| 파일 | 출처 worktree | 베이스 | 비고 |
|---|---|---|---|
| `ARCHITECTURE.md` | `claude/magical-benz` | `1e9e917` (~2026-04) | 시스템 구조·대미지 공식·무기 규칙 |
| `DATA_SCHEMA.md` | `claude/magical-benz` | `1e9e917` (~2026-04) | JSON/CSV 스키마·enum·DTO 대응 |
| `DEVLOG.md` | `claude/magical-benz` | `1e9e917` (~2026-04) | phase 현황·결정 로그·backlog |
| `_dmg_probe2.py` | `claude/great-margulis` | `f609a75` | 대미지 probe 변종 (29줄) |

## ⚠️ 주의 — 신뢰도
- **April-era 문서.** 이후 프로젝트는 schema v3 + reverse-engineered additive 대미지 공식으로 크게 바뀜.
- 프로젝트 이력상 과거 설계 문서들은 **hallucination 때문에 한 번 폐기**된 적 있음. 이 archive 내용도 일부 부정확/outdated 가능.
- 코드·수치·경로를 그대로 신뢰하지 말 것. 교차검증 필수.

## 현재 진실원 (이걸 봐라)
- **`Docs/DESIGN.md` — 방향·구조·대미지 공식의 단일 권위 (2026-06-28 확정). 최우선.**
- `DataPipeline/schema/skill_schema_legend.txt` — 스킬 스키마 v3 레전드
- `Docs/` (상위, `_archive` 제외) — 현행 문서
- `_dmg_probe.py` / `_dmg_calibrate.py` (repo 루트) — 검증된 대미지 공식 유도/캘리브레이션
- `SimulatorEngine/` 코드 — 실제 구현
