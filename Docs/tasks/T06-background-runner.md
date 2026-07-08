# T06 — 무작위 덱 background sim runner

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서. 의존: T05.

## 목표
로스터에서 무작위 덱을 뽑아 background 로 대량 sim → 기록 DB(T05) 축적. Optimizer(T08) 의 표본 공급원.

## 구현
- 로스터 입력 → 유효 5인 덱 무작위 샘플링(중복 캐릭 없음, 배치 포함). 이미 축적된 (deck,boss,version) 은 N 부족분만 보충.
- 멀티코어: `Parallel.ForEach(decks)`, 코어당 sim. 배치 INSERT (WAL 단일 writer). 26ms/run × 코어 병렬.
- 실행 제어: 시간/run수 예산, 중단·재개(축적 상태 = DB). 진행률 로그.
- 표본 우선순위(옵션): 유망 덱(부분 결과 고점) 집중 vs uniform 탐색 — MVP 는 uniform.

## 수용 기준
- 지정 예산 내 N run 축적, 버전 태그 정확, 재실행 시 중복 최소(부족분만).
- 코어 수 스케일링 확인 (1 vs 8코어 처리량).

## 함정
- 덱 공간 폭발 (로스터 100명 → C(100,5) ≈ 7500만) — 전수 불가. 후보풀/휴리스틱은 T08 소관, T06 은 표본 공급.
- DB 잠금: sim(병렬 읽기 없음) → 결과 큐 → 단일 writer flush. writer 병목 안 되게 배치.
