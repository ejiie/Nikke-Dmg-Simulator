# T01 — SkillRuntime: 트리거→효과 적용 루프 (구 K7, THE GAP 마지막 조각)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서 → `SKILL_RUNTIME_REFERENCE.md`(einkk 지도).
> 의존: 없음 (K4 로더 ✅). 병렬 가능: T04.

## 목표
공식 FunctionData 를 시뮬 루프에서 실행: 이벤트 발생 → 트리거 체크 → 버프 스폰/즉시 효과 → AttackContext 반영.
완료 시 단일 캐릭이 **자기 스킬(패시브+버스트) 포함 DPS** 를 산출한다.

## 입력 (전부 준비됨)
- `SkillChainLoader.TryLoad` → 캐릭별 skill1/skill2/burst × lv → `FunctionDto` 체인 (14,249 함수).
- `SkillTranslator.Classify`(Static/Runtime) + `Route`(EffectRoute). `OfficialSkillEnums`(공식 enum 미러).
- `BuffInstance`(컨테이너 — 이 태스크에서 공식 기준으로 확장), `Combatant.ActiveBuffs`, `MetricsCollector`.

## 구현 (einkk `function.dart` 4단계 — SKILL_RUNTIME_REFERENCE §2)
1. **이벤트 계약**: enum/record — NikkeFire·NikkeDamage(crit/core 플래그 포함)·Reload(Start/End)·UseSkill·
   ChangeBurstStep·HpChange·BurstGen·Time(주기). SimulationRunner 프레임 루프가 발행.
2. **BattleFunction 등록**: 전투 시작 시 각 Combatant 의 스킬 체인 → function 인스턴스 목록으로 전개
   (`connected_function` 은 발동 시 연쇄). `UseCharacterSkillId`(1,401건) = 다른 CharacterSkill 호출 — 필수 지원.
3. **프레임 broadcast**: 이벤트마다 등록 함수들에 대해
   TimingTrigger 매치(OnStart/OnHitNum/OnFullChargeHit/OnHpRatioUnder/OnEnterBurstStep/OnCheckTime/OnEndReload…)
   → StatusTrigger(×2) 평가 → 통과 시 효과 적용.
4. **효과 적용**: `EffectRoute` 별 —
   - Stat/Combat 축 → `BuffInstance` 스폰 (target=FunctionTargetType, standard=StandardType 로 값 기준 결정,
     duration=DurationType/Value — TimeSec 계열은 **프레임 변환**, Shots/Hits 는 카운트, limit_value=중첩 상한).
   - DealDamage → 즉시 대미지 인스턴스 (W 슬롯 = function_value/10000, FACTS §1).
   - FireTiming/ReloadTiming/AmmoRefill → FiringModel 훅 (ReduceTimeCs 재계산 — FACTS §3).
   - Unverified/Unknown/SurvivalOrHeal(DPS 밖) → no-op + 카운터 (FACTS §7-1).
5. **BuffAggregator**: 매 히트 `Combatant.BuildHitContext` 확장 — ActiveBuffs 를 EffectRoute 별로 모아
   **FACTS §3 group-then-round** 로 AttackContext 에 합산. 만료 = 프레임 tick 에서 제거.
6. `BuffInstance` 확장: FunctionType(int)·FunctionTargetType·StandardType·DurationType·남은 프레임/카운트·limit.

## 수용 기준
- Emma 스킬1 (OnHurtRatio 5% → HealCharacter) = Runtime 등록되나 DPS 무영향(no-op 카운트).
- StatAtk 패시브(Static) → FinalAtk 반영 = 하네스 스펙 출력으로 확인.
- 지속 버프 만료·스택 상한(limit_value)·connected 연쇄·UseCharacterSkillId 시나리오 단위테스트.
- 전 192캐릭 lv10 체인 로드+등록 0-throw (미지 enum graceful).

## 함정
- 시간 duration = **1/100초** → 프레임 변환 (FACTS §4). CharacterSkill 의 차지시간 skill_value 만 프레임 단위.
- 버프 값 합산 = group-then-round — Σ 후 곱 금지 (FACTS §3).
- `OnStart` + 영구 = Static 축 (이미 Classify 가 분리) — Runtime 에서 중복 적용 금지.
- ChangeWeapon(스킬타입 7) = 무기 교체 (교체 shot_id 가 skill_value_data 에) — Maxwell 버스트가 예시. FiringModel 재생성 훅 필요.
