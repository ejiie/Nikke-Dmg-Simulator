# T02 — 버스트 게이지·사이클 + 팀 5인 (구 K9)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서. 의존: T01.

## 목표
팀 5인이 버스트 사이클(1→2→3→풀버스트)을 돌리며 팀 버프가 전파되는 run.

## 확정 상수 (FACTS §5 — 전부 실측/데이터 확보됨)
- 게이지 cap = **1,000,000** (`Database/processed/burst_gauge_table.json` — 커밋됨).
  충전: ally per_sec=100 · shot_hit=4 · kill(m/e/c/b)=960/1440/1920/2880 · use_skill=200 · skill_hit=100 ·
  hurt=480 · empty_ammo=13. **burstStage 0 에서만 충전** (풀버스트 중 정지). 관통 히트 = 파츠당 추가.
- per-shot 게이지: `WeaponProfile.BurstEnergyPerShot / TargetBurstEnergyPerShot` (raw — cap 과 동일 단위),
  `FirstBurstGaugeSpeedUp`(FunctionType 102) 버프 훅.
- stage 간 딜레이 = [1, 10]프레임 uniform random. **3버스트→풀버스트 진입 = 28프레임** (0.46s 실측).
- 풀버스트 창 10s(캐릭별 `burst_duration` — 500/1000/1500cs 존재) = **진입 시점** 기산. 종료 후 재진입 쿨(einkk `reEnterBurstCd`) 확인.
- 버스트 시전 사격공백 = 모델링 안 함 (사용자 결정).

## 구현
1. BurstGaugeTracker: 게이지 누적(프레임 per_sec + 발사/히트 이벤트) → cap 도달 = 버스트 준비.
2. 버스트 시퀀스: 1버 사용자(UseBurstSkill Step1) → [1,10]f → 2버 → [1,10]f → 3버 → 28f → 풀버스트 10s.
   캐릭 `use_burst_skill`(Step1/2/3/AllStep) + `change_burst_step` 로 자격 판정. AllStep 특례(153/154) 존재.
   **버스트 담당(누가 누를지) = tactic (T03 컨트롤 정책)**: default 배치순(Tier A), 지정/번갈아 override(Tier B).
3. 팀 버프 전파: T01 의 FunctionTargetType(AllCharacter 등) 이 팀 멤버 전체에 BuffInstance 스폰.
4. 풀버스트 B2 보너스: `ctx.FullBurstBonus = 0.5` (창 내 히트만 — FACTS §1).
5. `SimulationRunner` 확장: 5 Combatant + 버스트 사이클 + 버스트 스킬(ulti) 실행.

## 수용 기준
- 사이클 타임라인 프레임 정밀 테스트 (게이지 수렴 → 1·2·3버 → 28f → 풀버 10s → 재충전).
- 풀버 창 내 히트만 FullBurstBonus. 버퍼 유무로 팀 DPS 유의 변동. `IncBurstDuration`(90)/`StatUltiGauge*`(19~26) 버프 반영.

## 함정
- 게이지 단위 = raw (cap 1M 과 동일 스케일) — 재정규화 금지.
- 충전 = stage 0 한정 + shot_hit 이 주 수입원 → 재장전이 충전 창과 겹치면 사이클 지연 —
  해법 = T03 게이지 연속성 rule (풀버 창 안 재장전 완료).
- 버스트 쿨타임 = `skill_cooltime`(1/100초 — 4000=40s), `StatBurstSkillCoolTime`(143)/`ChangeCoolTimeUlti`(83) 버프.
- 5인 팀 성능: 히트 이벤트 5× — MetricsCollector 는 O(1)/히트라 무관, FiringModel 5개 인스턴스.
