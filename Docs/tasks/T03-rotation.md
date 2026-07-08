# T03 — RotationController: Auto / Scripted (구 K10)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서. 의존: T02.

## 목표
`IRotationController`(K0 계약, `Engine/Rotation/`) 이행 — 스킬/버스트 사용 시점 결정 2모드.

## 구현
1. **SimState 확정** (현 placeholder): NowSec/프레임 + per-멤버 {버스트게이지, 스킬 쿨 잔여, 탄창, HP} +
   버스트 사이클 상태(stage, 창 잔여). K0 계약 확장은 최소로.
2. **AutoController**: 게이지 full → 버스트 자격자(Step 순) 사용, 액티브 스킬 = 쿨 완료 즉시 사용 (in-game 오토 근사).
   버스트 순번 = 팀 배치 순 (덱 정의의 position 이 의미 갖는 지점).
3. **ScriptedController**: 시각(프레임)별 액션 테이블 입력 — 기믹덱 수동 로테이션 재현. 파일/객체 입력.
4. Manual FiringControl(발사)과 별개 축 유지 — 로테이션은 스킬/버스트만 결정.

## 수용 기준
- 동일 덱: Auto vs Scripted(동일 타이밍 기입) 결과 일치. Scripted 로 버스트 지연 시 DPS 차이 재현.
- 단순덱 = Auto 로 손 안 대고 run 가능 (T06 background 전제).

## 함정
- 스킬 사용 자체도 게이지 +200 (burst_gauge_table use_skill) — T02 트래커에 이벤트 전달.
- 버스트 자격: `use_burst_skill`(Step1/2/3/AllStep) — AllStep 캐릭(153/154 함수) 특례.
