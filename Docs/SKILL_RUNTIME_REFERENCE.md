# 스킬 런타임 참조 — THE GAP 을 nikke-einkk 로 매운다 (2026-07-07)

> **목적**: 프로젝트 최대 갭 = 스킬 런타임(트리거 발동 + 효과 적용 + 로테이션). 현재 엔진은
> `skills_parsed.json`(v3, LLM 키워드 파싱)에 의존 → 부정확·비공식. **참조 구현 = [d34d633f/nikke-einkk](https://github.com/d34d633f/nikke-einkk)**
> — 완성된 NIKKE 데미지 시뮬(Dart, **MIT** = 참조/포팅 자유, 출처표기). 우리 계획(`Docs/DESIGN.md`
> "full tick event-driven rotation sim")을 이미 구현. 이 문서 = 무엇을 어떻게 참조할지의 지도.
> ⚠️ **코드 직접 복붙 금지**(언어 다름·라이선스 표기). 아키텍처/공식 효과모델을 우리 C#로 재구현.

## 0. 왜 nikke-einkk 인가
- **공식 효과 모델**: NIKKE 스킬 = 게임 `FunctionTable`의 함수들(function_id). 각 함수 = `FunctionType`(무엇)
  + trigger(언제) + target/standard(누구) + value(얼마) + duration. nikke-einkk 는 이 모델을 그대로 구현.
  우리 `EffectType`(키워드 파생)보다 **공식·완전**.
- **런타임 완비**: 프레임 tick + 이벤트 브로드캐스트 + 트리거 체크 + 버프 적용. 우리 K7(미구축)의 청사진.

## 1. 아키텍처 대응표 (nikke-einkk → 우리 엔진)

| nikke-einkk | 역할 | 우리 대응 (상태) |
|---|---|---|
| `battle_simulator.dart` `BattleSimulation.proceedOneFrame()` | 60fps 프레임 tick, `timeline[frame]` 이벤트 브로드캐스트 | `SimClock` (K2 ✅) — tick 루프 확장 |
| `timeline: SplayTreeMap<frame, List<BattleEvent>>` | 프레임별 예약 이벤트 큐 | 이벤트 스케줄러 (**신규 K필요**) |
| `battle/events/*` (NikkeFire·NikkeDamage·RaptureDamage·UseSkill·ChangeBurstStep·HpChange·BurstGen·Reload…) | 이벤트 타입들 | 이벤트 계약 (**신규**) — 아래 §4 |
| `battle_entity.dart` `entity.broadcast(event, sim)` | 니케/보스가 이벤트 수신 | `Nikke`/`BossTarget` 에 broadcast (**신규**) |
| `function.dart` `BattleFunction.broadcast()` | **트리거 체크 → 효과 적용** (핵심) | `SkillRuntime` (**미구축 K7 = THE GAP**) |
| `buff.dart` `BattleBuff` | 스탯 버프 1개 (duration·stack·standard) | `BuffInstance` (✅ 데이터컨테이너) + `BuffStore`/`BuffAggregator` (K7) |
| `FunctionType`(77) `TimingTriggerType` `StatusTriggerType` `StandardType` `FunctionTargetType` `DurationType` `ValueType` | 공식 enum | `EffectType`(현재 키워드파생 부분집합) → **공식 enum 으로 확장** §3 |

**핵심 통찰**: 우리는 스탯모델(`base×(1+Σbuff)`)·데미지공식(B2~B5, `DamageCalculator`)·SimClock·BuffInstance
는 있으나, **트리거→효과 적용 루프(`function.dart` 대응)가 없음**. 그게 THE GAP. nikke-einkk `function.dart`
+ event 시스템이 그 정확한 청사진.

## 2. 효과 모델 — 함수 1개의 실행 흐름 (function.dart)
```
BattleFunction.broadcast(event, simulation):
  1. TimingTrigger 체크: data.timingTriggerType 가 이 event 에 매치?
     (onStart · onHitNum(N발마다) · onFullChargeHit · onCoreHitNum/Ratio · onCriticalHitRatio ·
      onHpRatioUnder/Up · onSkillUse · onEnterBurstStep · onBurstSkillUseNum · onCheckTime(주기) ·
      onFunctionOn/Off · onEndReload · onResurrection · onDead …)  ← 값=data.timingTriggerValue
  2. StatusTrigger 체크: data.statusTriggerType/Value (추가 조건, 예 특정 버프 유무·스탯 임계)
  3. 통과 시 addBuff(): FunctionType(무엇) 을
       - 대상 FunctionTargetType (self/target/allCharacter/allMonster/userCover/targetCover)
       - 참조틀 StandardType (user=시전자 / functionTarget / triggerTarget)
       - 값 functionValue (+ functionValueType 로 %/정수 해석)
       - 지속 durationType/durationValue (timed=프레임 / count 등)
     로 계산해 BattleBuff 스폰 → 대상 엔티티 버프목록에 추가. limitValue=중첩상한.
  4. connectedFunction[]: 이 함수 발동 시 연쇄 발동할 다른 function_id 들.
```
→ 우리 `SkillRuntime` = 이 4단계를 C#로. `BuffInstance`(이미 있음)에 `StandardType`/`FunctionTarget`/
`durationType` 슬롯 추가 필요.

## 3. FunctionType 77종 (공식 효과 의미) → 우리 EffectType 확장
nikke-einkk `skills.dart` `enum FunctionType` 이 권위 목록. 우리 `EffectType`(키워드파생)을 이걸로 교체·확장.
대표:
`statAtk(1)·healCharacter(2)·statCritical(9)·statChargeDamage(11)·statDef(15)·statRateOfFire(16)·
gainUltiGauge(26)·drainHp(32)·immuneDamage(37)·immortal(40)·damageReduction(42)·statCriticalDamage(51)·
statHp(63)·atkChangHpRate(65)·fullBurstDamage(69)·resurrection(71)·useCharacterSkillId(72)·damage(75)·
damageRatioUp(76)·buffRemove(77)…` (전체는 nikke-einkk 소스). **각 FunctionType → 우리 데미지 브래킷(B2~B5)/
스탯/타이밍 매핑은 `Docs/DESIGN.md §3` 공식과 대조해 확정.** 예: statAtk→ATK rate버프, statChargeDamage→charge,
fullBurstDamage→B?, damageRatioUp→최종배수.

## 4. 이벤트 타입 (battle/events/) → 우리 이벤트 계약
`BattleStartEvent · NikkeFireEvent · NikkeDamageEvent · RaptureDamageEvent · NikkeReloadEvent ·
UseSkillEvent · SkillAttackEvent · ChangeBurstStepEvent · HpChangeEvent · BurstGenEvent ·
LaunchWeaponEvent · TimeEvent`. 트리거가 이 이벤트들을 구독. 우리 엔진에 대응 이벤트 + 디스패치 필요.

## 5. 프레임 루프 (battle_simulator.dart)
`fps=60`(기본), `maxSeconds=180`. `proceedOneFrame`: (a) 엔티티 프레임갱신, (b) `timeline[currentFrame]`
이벤트들 모든 니케/보스에 broadcast, (c) 정리. **우리 SimClock(K2)이 프레임루프 담당** → timeline 스케줄러 +
broadcast 디스패치만 추가. 버스트게이지=`Database/processed/burst_gauge_table.json`(이번 커밋) 사용.

## 6. 데이터 의존 = FunctionTable — ✅ 봉쇄 해제 (2026-07-08)
이 런타임은 **각 function_id 의 FunctionData**(functionType/value/target/standard/trigger/duration)가 필요.
보스/니케 스킬 → skill_id → function_id (우리 `MonsterTable.skill_data` clean 디코드로 확보) → FunctionData.
**✅ 디코드 완료(2026-07-08)**: SharpnelXu 공개 스키마(`NikkeMpkConverter/model/Skills.cs`) 이식 →
`memorypack_decode.py` 가 FunctionTable(19459)/CharacterSkillTable/StateEffectTable/SkillInfoTable/CharacterTable
**clean 디코드 + 풀루프 검증 통과**(니케 스킬 수치 roledata bit-exact, value=×10000, 상세 =
`DataPipeline/crawler/FUNCTIONTABLE_DECODE_PLAN.md` §0). **결정(사용자 2026-07-08): 엔진 스킬
데이터원 = 공식 FunctionTable** — skills_parsed.json(v3, LLM)은 검증 참조로 강등. 체인 조립(D3) ✅ 2026-07-08
= `staticdata_skill_chains.py` → `assembled/skill_chains.json`(gitignore). 잔여 = K4(C# 로더)/K7.

## 7. 즉시 참조 파일 (nikke-einkk)
- `lib/model/battle/function.dart` (1410줄) — **트리거+효과 적용 핵심**
- `lib/model/battle/buff.dart` — BattleBuff(duration/stack/standard)
- `lib/model/battle/battle_simulator.dart` — 프레임 tick
- `lib/model/battle/events/*` — 이벤트 타입
- `lib/model/skills.dart` — FunctionType/TimingTrigger/Standard/FunctionTarget/Duration/Value enum

## 교차링크
방향·공식 = `Docs/DESIGN.md`. 엔진 현황 = `Docs/ENGINE_GUIDE.md`. 특수효과 방향 = `Docs/SKILL_DATA_BLABLALINK.md`.
FunctionTable 디코드 = `DataPipeline/crawler/FUNCTIONTABLE_DECODE_PLAN.md`. MemoryPack = `crawler/STATICDATA_PREP.md`.
