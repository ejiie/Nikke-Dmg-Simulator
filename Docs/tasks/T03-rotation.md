# T03 — RotationController: Auto / Scripted + 컨트롤 정책(택틱) (구 K10)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서. 의존: T02.

## 목표
`IRotationController`(K0 계약, `Engine/Rotation/`) 이행 — **스킬/버스트 + 발사/재장전 directive** 를
결정하는 컨트롤 정책 실행자. (2026-07-10 논의 확정 — 구 "로테이션은 스킬/버스트만" 을 directive 모델로 확장.)

## 컨트롤 정책 구조 (2026-07-10 사용자 확정)

**덱의 성적 = 조합 + 택틱.** 택틱은 sim 시점에 적용되어 기록 DB 에 반영된다 — deck 정의(T05)에 포함,
Optimizer(T08)는 택틱을 모르고 결과 분포만 본다.

| Tier | 내용 | 구현 위치 |
|---|---|---|
| **A 기본 (MVP)** | 계속 쏘기 · 탄0 자동 재장전 · **게이지 연속성 rule**(아래) · 버스트 = 배치순 | AutoController 내장 default — background 축적(T06)의 "기본 tactic" |
| **B 덱별 override** | 조건/이벤트 기반 directive: 사격 Hold 창(버프 유지·parts 다단히트 대기) · 장탄 관리 선제 재장전 · 버스트 담당 지정/번갈아 | ScriptedController rule-set — tactic 정의(T05)에 포함 |
| **C 비스코프** | 두 캐릭 와리가리 엄폐 전환 등 마이크로 컨트롤 | 명시 제외 (사용자 결정) |

**directive (RotationController → FiringModel)**:
- `SetFiring(member|all, bool)` — 니케 **개별** + **전체** 엄폐/해제 (실게임 조작 단위 — FACTS §5).
- `RequestReload(member)` — 명시 재장전 (장탄 관리).
- 스킬/버스트 사용 (기존 계약 유지).

**게이지 연속성 rule (Tier A 핵심 — 사용자 제기 2026-07-10)**:
버스트 게이지는 stage 0 에서만 충전(FACTS §5)되고 shot_hit 이 주 수입원 → 재장전 타이밍이 충전 창과
충돌하면 사이클 지연 (예: 풀버스트 끝자락 0.x초에 재장전 시작 → 풀버 밖 탄0 = 충전 정체).

```
조건: 풀버스트 잔여 ≤ (실효 재장전시간 + 여유 x프레임) AND 탄창 ≤ 임계 y
행동: 지금 재장전 (풀버스트 창 안에서 완료 → 종료 즉시 사격/충전 재개)
```

x·y 는 정답을 미리 고민하지 않는다 — **파라미터 sim 스윕으로 DPS 최대값을 default 채택**
(풀버 중 재장전 딜 손실 vs 사이클 지연 트레이드오프는 sim 이 자동 평가).

## 구현
1. **SimState 확정** (현 placeholder): NowSec/프레임 + per-멤버 {버스트게이지, 스킬 쿨 잔여, 탄창, HP} +
   버스트 사이클 상태(stage, 창 잔여). K0 계약 확장은 최소로.
2. **AutoController**: Tier A rule 내장 — 게이지 full → 버스트 자격자(배치순) 사용, 액티브 스킬 = 쿨 완료
   즉시 사용 (in-game 오토 근사), 게이지 연속성 rule.
3. **ScriptedController**: ① 시각(프레임)별 액션 테이블 + ② 조건/이벤트 기반 rule-set (Tier B) — 파일/객체 입력.
4. FiringModel 에 directive 수신 훅(`SetFiring`/`RequestReload`) 추가. Manual FiringControl(re-click
   프로파일)은 "손이 내는 오차" 축으로 존속 — directive 는 "무엇을 할지" 축, 서로 직교.

## 수용 기준
- 동일 덱: Auto vs Scripted(동일 타이밍 기입) 결과 일치. Scripted 로 버스트 지연 시 DPS 차이 재현.
- 단순덱 = Auto 로 손 안 대고 run 가능 (T06 background 전제).
- 게이지 연속성 rule on/off 로 사이클 타임 차이 재현 (풀버 끝자락 탄0 시나리오).
- Hold 창 directive: 사격 정지/재개가 발사·게이지·버프 타임라인에 일관 반영.

## 함정
- 스킬 사용 자체도 게이지 +200 (burst_gauge_table use_skill) — T02 트래커에 이벤트 전달.
- 버스트 자격: `use_burst_skill`(Step1/2/3/AllStep) — AllStep 캐릭(153/154 함수) 특례.
- tactic 은 deck_hash 에 포함(T05) — 같은 5인 + 다른 tactic = 다른 덱. 누락 시 기록 혼합 오염.
- directive 남발 = 실게임 조작 불가능 수준 마이크로 컨트롤 → Tier C 금지선 유지.
