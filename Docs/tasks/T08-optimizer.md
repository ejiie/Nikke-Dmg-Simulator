# T08 — Optimizer: K팀 분할 · tail 목적 (구 K13)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서. 의존: T05 (분포+DB).

## 목표
로스터 → 최적 solo raid 덱 편성 탐색. **목적 = 고점×확률(tail)** — mean 아님 (DESIGN §1).

## 문제
- solo raid (MVP): 로스터에서 보스별 최적 5인 덱 = 덱 파워(tail 지표) 최대 조합.
- union raid (확장): 로스터를 K팀 분할(캐릭 1회 사용), 팀별 파워 합 최대 — NP-hard.

## 구현
- 덱 파워 = T05 분포의 tail 지표 (P(≥X) 또는 P90). DB 축적분 우선 조회, 부족분 = T06 로 sim 요청.
- 팀조합 → 파워 **memoize/cache** (DESIGN §0.5: 고유 5인조 1회만 sim). deck_hash 키.
- 탐색: 후보풀 선정(개별 강캐/시너지) + greedy/beam/branch&bound. 소규모는 brute-force 대조.
- union: 분할 제약(캐릭 1회) 하 팀 파워 합 최대 — 팀 간 독립 가정 시 분포 convolution (가정 검증 필요).

## 수용 기준
- 소규모 풀에서 brute-force 와 일치. 캐시 히트로 가속. tail 목적이 mean 목적과 다른 선택 내는 케이스 재현.

## 함정
- tail ≠ mean: 고분산 고점 덱 vs 저분산 안정 덱 — 목적함수가 tail 이어야 optimizer 가 전자 선호.
- 덱 공간 폭발 → 전수 불가 (T06 함정 참조). 후보풀 없이는 탐색 불가.
- 버전 오염: 파워 캐시는 (engine, data) 버전에 종속 — 갱신 시 무효화.
