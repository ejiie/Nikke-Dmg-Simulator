# T08 — Optimizer: DB 기반 best-K 덱 선별 · tail 목적 (구 K13)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서. 의존: T05 (분포+DB). 표본 공급 = T06.

## 역할 (2026-07-10 사용자 확정)
**기록 DB 에 축적된 결과를 보고 best K덱을 뽑는 선별기(selector).** **K = 5 확정** (solo raid MVP —
사용자 2026-07-10; union raid 확장 시 3). 휴리스틱 분업(2026-07-11): **탐색 휴리스틱**(후보 덱
생성·샘플링·우선순위) = T06 / **선별 휴리스틱**(set packing: greedy/beam/exact) = T08.
tactic 은 sim 시점에 이미 결과에 반영됨(T03/T05) — Optimizer 는 tactic 을 모르고 분포만 본다.
**목적함수 = `E[max of n runs]`** (확정 2026-07-11 — 리트라이 낚시 직접 모델). **n default = 13,
유저 조정 가능** (덱마다 리트 횟수 다름). mean 아님 (DESIGN §1). `P(≥X)` = 컷 입력 시 옵션 모드.

## 문제
- solo raid (MVP): DB 의 덱들 중 **캐릭 비중복**(캐릭 1회 — DESIGN §1) **5덱** 조합 선택,
  합산 tail 파워 최대. 단독 1위 덱이어도 조합 최적에서 빠질 수 있음 — **단순 top-K 조회가 아니라
  weighted set packing** (비중복 제약이 조합 문제를 만든다).
- union raid (확장): 동일 구조, K=3 — 로스터 분할 제약 강화. 팀 간 독립 가정 시 분포 convolution (가정 검증 필요).

## 구현
- 덱 파워 = `E[max of n]`: N 표본 오름차순 정렬 후 `Σ x_(i) × [(i/N)^n − ((i−1)/N)^n]` (order
  statistics — 분포 가정 없음). 집계는 항상 (engine, data, duration=180) 필터.
- 선별: greedy(파워순 + 비중복 배제)로 시작 → 필요 시 beam/exact. 소규모 풀은 brute-force 대조.
- 표본 부족 덱(신뢰구간 넓음) = **T06 에 부족 신호 보고만** — 새 덱 후보 생성·sim 직접 실행 안 함.
  T06 이 신호를 선택적으로 받아 표본 우선순위 조정.
- 팀조합 → 파워 **memoize/cache** (DESIGN §0.5: 고유 5인조 1회만 sim). deck_hash 키.

## 수용 기준
- 소규모 풀에서 brute-force 와 일치. 캐시 히트로 가속. tail 목적이 mean 목적과 다른 선택 내는 케이스 재현.
- 비중복 제약 검증: top-1 덱과 캐릭 겹치는 덱 배제 후에도 합산 최적이 성립하는 케이스 재현.

## 함정
- tail ≠ mean: 고분산 고점 덱 vs 저분산 안정 덱 — 목적함수가 tail 이어야 optimizer 가 전자 선호.
- greedy 는 set packing 최적 보장 없음 — 소규모 exact 대조로 gap 측정 후 필요 시 승급.
- 표본 수 불균형: run 수 적은 덱의 tail 지표 과대평가 위험 — 최소 N 임계 or 신뢰구간 보정.
- 버전 오염: 파워 캐시는 (engine, data) 버전에 종속 — 갱신 시 무효화.
