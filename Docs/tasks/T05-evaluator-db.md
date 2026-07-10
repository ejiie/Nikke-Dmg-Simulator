# T05 — Evaluator + SQLite 기록 DB (구 K12)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서. 의존: T01·T02·T04 (실전 표본 필요).

## 목표
팀 1개를 N회 run → **분포** 산출 + **기록 DB 축적**. "덱 파워" = 분포(평균·std·신뢰구간·tail).

## 분포 산출
- `RunResult` N개 → mean/std/분위수(P50/P90/P99)/`P(합딜 ≥ X)`. SQLite stdev 없음 → `SUM(x),SUM(x²),COUNT` 앱 계산.
- Optimizer 목적함수 확정(2026-07-11) = **`E[max of n]`** (n=13 default, 유저 조정 — DESIGN §6) —
  run 표본 정렬(order statistics)로 계산. mean/std/P90/P99 는 표시용 전부 산출.
- N-run 병렬: run 독립 → `Parallel.For`, 코어당 MetricsCollector/FiringModel 인스턴스. 26ms/run (FACTS: 벤치).

## SQLite 스키마 (사용자 검토 2026-07-08 — 통합 채택)
```sql
CREATE TABLE decks (
  deck_hash    TEXT PRIMARY KEY,   -- (members_json + tactic_json) 정규화(슬롯순·키순 고정) SHA256
  members_json TEXT NOT NULL,      -- [{slot, name_code, level, grade, core, bond, skill_lvs[3],
                                   --   cube{tid,lv}, fav_lv, equips, ol, control} ×5]
  tactic_json  TEXT NOT NULL,      -- 덱 레벨 tactic (T03): 버스트 담당 정책 + directive rule-set/파라미터.
                                   -- Tier A default = 명명 식별자(예 "auto_v1"). 같은 5인+다른 tactic = 다른 덱.
  team_size    INTEGER NOT NULL
);
CREATE TABLE runs (
  id             INTEGER PRIMARY KEY,
  ts             TEXT NOT NULL,
  mode           TEXT NOT NULL,      -- 'solo_raid'(MVP) | 'union_raid'(확장). 통합 DB + 이 컬럼으로 분기.
  deck_hash      TEXT NOT NULL REFERENCES decks,
  boss_id        INTEGER NOT NULL, boss_level INTEGER NOT NULL,
  duration_sec   REAL NOT NULL,      -- 표준 = 180 (solo raid 전투 시간 — FACTS §5). 덱 비교 = 동일 duration 전제.
  engine_version TEXT NOT NULL,      -- git commit (엔진)
  data_version   TEXT NOT NULL,      -- StaticData 태그(qa-260702) + roledata 스냅샷 해시
  total_damage   REAL NOT NULL, hit_count INTEGER NOT NULL,
  crit_damage    REAL, core_damage REAL, full_damage REAL
);
CREATE TABLE run_members (              -- 사용자 요구 1: 덱 조합별 니케 성능
  run_id  INTEGER NOT NULL REFERENCES runs,
  slot    INTEGER NOT NULL,             -- 1~5 (배치 위치)
  name_code INTEGER NOT NULL,
  damage  REAL NOT NULL,                -- 이 run 에서 이 니케 기여 (RunResult.DamageBySource)
  PRIMARY KEY (run_id, slot)
);
CREATE INDEX ix_runs_key ON runs(mode, boss_id, boss_level, engine_version, data_version, deck_hash);
CREATE INDEX ix_member_perf ON run_members(name_code);
```
- **버전 태깅 필수** (FACTS: 공식/데이터 갱신 시 구 기록 오염) — 집계는 항상 (engine, data) 필터
  + **duration_sec = 180 필터** (다른 duration 표본 혼입 방지 — 사용자 확정 2026-07-10).
- 시드 저장 금지 (FACTS §7-2). 쓰기 = WAL + 단일 writer(배치 INSERT), 계산은 병렬 코어.

## 수용 기준
- N-run 분포 통계 정확 (알려진 결정론 케이스 대조). deck_hash 재현성(같은 덱 = 같은 해시).
- run_members 로 "니케 X 가 덱 A 에서 B 보다 damage 높음" 질의 성립. 버전 필터 격리.

## 함정
- members_json/tactic_json 정규화: 슬롯순·키순 고정 안 하면 같은 덱이 다른 해시 → 축적 파편화.
- tactic 을 해시에서 빼면 다른 택틱의 기록이 한 덱으로 혼합 오염 (2026-07-10 확정 — T03).
- union_raid = 다팀 동시 → run 이 팀 단위인지 편성 단위인지 확장 시 재설계 (MVP 는 solo 단일팀).
