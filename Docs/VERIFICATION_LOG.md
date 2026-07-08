# VERIFICATION LOG — 빌드/테스트/데이터 정합 증거

> **역할**: 주요 작업 묶음마다 빌드·테스트·파이프라인·데이터 불변식을 실측 캡처해 **정합함을 증거로** 남긴다.
> 날짜 내림차순. 각 항목은 그 시점의 commit 과 재현 명령을 포함한다.

---

## 2026-07-08 (8차) — M2 검증 콘솔 하네스 + 라벨 정정 (5001=Maxwell)

**범위**: `Nikke.Simulator.Harness`(신규 콘솔, sln 등록) — 실캐릭(merged DB)을 `RunOnce` 로 굴려
in-game 실측과 대조하는 M2 도구.
```
nikke-harness list [필터]
nikke-harness run <name_code> [--sec 60] [--runs N] [--manual] [--tap] [--charge-err s]
                 [--reload-buff f] [--def d] [--dist m] [--core r] [--body r] [--db 경로]
```
출력 = 캐릭 스펙(ATK/W/탄창/무기 부류) + 총딜/DPS/히트(트리거×펠릿)/크리·코어·풀차지 분해/초당
타임라인 + N-run 분포(mean/std/min/max). 데이터 로딩 = WPF `App.OnStartup` 패턴 동일.
merged DB 부재 = 안내 후 종료(재생성법 표기). 구 콘솔(`SimulatorEngine/Core`) = 레거시 그대로.

### 스모크 (합성 DB — roledata static + 가짜 유저 Lv200)
- Maxwell(SR) auto 30s: 18발(83f 사이클 ✓), 풀차지 100%, N=3 std 2.5%.
- Maxwell 수동+재장전버프 100%: **29발/30s** (61f 사이클 ✓, 재장전 무정지) — 수동컨 이득 +61% 정량화.
- Emma(MG)+타겟(core r4/body r5): 명중원 수축→빗맞음 게이트→탄진(5s@60/s) 재장전 0구간 — 타임라인 전부 정합.

### 라벨 정정 (하네스 스모크로 발견)
- **name_code 5001 = Maxwell** (Red Hood = 5101). D1~K4 문서/테스트의 "Red Hood(5001)" 라벨 오류 —
  검증 자체는 name_code 기반 bit-exact 라 **결과 유효**, 명칭만 전면 정정 (docs/tests/memory).
- 부수 확인: **crit = 전 192캐릭 (15%, 150%) 단일** — `AttackContext` 기본값과 정합, per-char crit 배선 불필요.

테스트 124/124 유지.

---

## 2026-07-08 (7차) — K8 M1: 단일캐릭 통합 배선 (SimulationRunner.RunOnce 이행)

**범위**: K0 동결 엔트리 `SimulationRunner.RunOnce(team, target, rng, durationSec)` 구현 —
SimClock(60fps tick) → FiringModel(K3) → BuildHitContext(static, Combatant 스텁 이행) →
ITarget.PopulateContext(K5) → AccuracyModel 명중/코어힛 + CritSampler 크리 → DamageCalculator →
MetricsCollector(K6, crit/core/full 태그). `Combatant.Firing`(FiringControl) 추가 = per-멤버 Auto/Manual.
스킬/버프/버스트 미포함 (M1 정의) — K7/K9 배선 자리 주석.

### 1. 테스트 — 124/124 (신규 8 = `SimulationRunnerTests`)
- **프레임 정밀 타임라인**: AR 10s = 102히트(60발+재장전 72f+spotFirst 12f+42발), 초 버킷(0초=10·1초=12),
  팀 2인 소스 분해, SG 3트리거×10펠릿=30히트, 인자 방어.
- **확률 수렴**(시스템 RNG, N≈6100): 크리 15%±2%p · 코어힛 (25/75)²=11.1% · 빗맞음 게이트 1/9 — 전부 통과.
- **테스트 격리 사고 해결**: xUnit 병렬로 타 클래스가 전역 StatTable 초기화 → 합성 니케 ATK 오염 발견.
  해법 = DEF 거대 타겟(최소뎀 1 고정) — 전역 상태 무관 타이밍 불변식(TotalDamage==HitCount). 2연속 그린.

### 2. 가정 (M2 골든 대조에서 확정)
- SG 펠릿 = 펠릿마다 독립 히트/개별 크리·코어 롤, W 계수 = 펠릿당.
- 관통(pierce 다중 히트)·버스트 게이지 충전 = 미배선 (K9).

### 3. 잔여
- **M2 = in-game DPS 골든 대조 (사용자)**: 실캐릭(merged DB) + DummyTarget 파라미터로 RunOnce ↔ 실측 DPS.
- K7 SkillRuntime 배선(ActiveBuffs 집계→ctx), K9 버스트 사이클(28f 상수 확보됨).

---

## 2026-07-08 (6차) — K6 MetricsCollector (Wave1 완결)

**범위**: `Engine/Metrics/MetricsCollector.cs` — record-every-instance(D4) 수집기. `RunResult`
분해 필드 확정(K0 주석의 "K6 에서 확정" 이행): `HitCount` · `DamageByTag`("tag=value") ·
`DamagePerSecond`(초 버킷). 히트당 고정 누적(리스트 미보관) — 54k 히트/run 에도 O(고유 태그) 메모리.
`Build()` = 스냅샷(반복 호출 유효), `Reset()` = Evaluator N-run 재사용. run 창 밖 시각 = throw.

테스트 — **116/116** (신규 6): 총합/소스별/태그 분해/초 버킷 경계(0.99 vs 1.0, 종료 경계)/스냅샷 불변/Reset/인자 방어.

**Wave1 (K2~K6) 전부 완료** → 다음 = K8 통합(M1: SimClock+FiringModel+Loader+Metrics 배선, 단일캐릭
in-game 골든 대조) ∥ K7 SkillRuntime(Runtime 축 소비).

---

## 2026-07-08 (5차) — K4 공식 스킬 로더/번역기 + 버스트 전이 실측 반영

**범위**: `Engine/Skills/` K4 구현 — skill_chains.json(D3) → C# DTO/Loader/Translator.
+ 사용자 영상 실측: **3버스트→풀버스트 진입 딜레이 = 0.46s ≈ 28프레임** (ENGINE_GUIDE §5 반영, K9 상수).
버스트 시전 사격공백(측정②)은 사용자 결정으로 **무시**.

### 1. 구현
- `OfficialSkillEnums.cs`: 공식 enum 8종 미러(FunctionType 213 등) — memorypack_decode.py dict 기계생성(수기 금지).
- `SkillChainDto.cs`: JSON 1:1. enum 필드 = **원시 int 보존**(신값 graceful) + `Typed*` 캐스팅 접근,
  `ValueAsFraction`(Percent ×10000 해석).
- `SkillChainLoader.cs`: `TryLoad` — gitignore 파일 부재 = false(throw 금지, fresh clone 정상),
  로드 시 **참조 무결성**(전 체인 function id ⊆ Functions 사전) 검증.
- `SkillTranslator.cs`: DESIGN §5 **2축 분류**(트리거·상태조건 없음+영구 = Static → BuildAttackContext,
  그 외 Runtime → K7) + **EffectRoute 매핑표** — 확실 타입만 개별 슬롯(AtkRate/CritDmgAdd/StrongElemAdd/
  ReloadTiming/BurstGauge …), 브래킷 미검증 = `Unverified`(K8 골든 대조로 승격), 정의 밖 신값 = `Unknown` no-op.

### 2. 테스트 — 110/110 (신규 17 = `SkillChainLoaderTests`)
- 로드: 192캐릭·87보스·14,249함수 0-throw + 무결성 통과.
- D1 검증값 재확인: Emma s1 lv10 = HealCharacter 1077(0.1077)/OnHurtRatio 500 → Runtime 분류 ✓;
  Maxwell burst lv10 = ChangeWeapon·쿨 4000·81342·차지 120f ✓.
- 전 함수 라우팅/분류 graceful — 미지 신값 = `?214` **11개뿐**(<0.1%).
- 분포 스냅샷(우선순위 자료): StatAtk 1,763 · **UseCharacterSkillId 1,401**(연쇄 스킬 호출 — K7 필수 지원) ·
  Damage 686 · **AddDamage 620**(브래킷 미검증 최대 항목 — K8 대조 1순위) · HealCharacter 590 · StatDef 588.

### 3. 잔여
- K6 Metrics(소품) → K8 통합(M1): SimClock+FiringModel+Loader 배선, Static 주입 + 골든 대조.
- K7 SkillRuntime: Runtime 축 소비 (einkk function.dart 4단계) — UseCharacterSkillId 연쇄 포함.

---

## 2026-07-08 (4차) — K3 FiringModel 구현 (Wave1 마지막 대형 청크)

**범위**: `Engine/FiringModel.cs` — 60fps 프레임 스텝 발사 상태기계. 3차 확정 스펙(사용자 실측 + einkk)
전부 구현. SimClock 배선·대미지/게이지 이벤트 발행 = K8 몫 (이 클래스 = 타이밍 전담, `AdvanceFrame()`).

### 1. 구현 범위
- RPM accumulator(`−=RPM`/프레임, 발사 시 `+=3600`) — 구조적 1발/프레임 = MG 실효 60/s.
- MG ramp(발사당 +100RPM clamp) + **점진 감쇠**(비사격 프레임당 (end−start)/reset_time).
- 상태 전이 spot_first/last 0.2s 양방향(전 무기) · 차지무기 = 전이 말 프레임 charge 1f 선시작(einkk).
- SR/RL 3부류: UP(발사 후 강제 복귀) / UP+maintain(자체 후딜레이 = spot_first+maintain) /
  DOWN_Charge(only 풀차지, rate gate; Tap 지정 시 ctor throw).
- 재장전 R1/R2: 감산형 `reload×(1−Σ버프)` 하한 1프레임 + 자동 탄0 = spot_last 가산·spot_first 재지불,
  수동 탄0 = 전이 생략. 비사격 프레임(복귀/re-click 갭) 수동 재장전 진행, 발사 시 리셋.
- `ControlMode.Auto/Manual` + `FireStyle.FullCharge/Tap` + re-click [0.02,0.028]s(프레임 샘플) +
  수동 차지오차 프로파일(기본 0 = 결정론).
- 명중원 발사 수축/비사격 회복. SG 펠릿(트리거당 ShotCount, 탄약 1).

### 2. 테스트 — 93/93 (신규 15 = `FiringModelTests`, 프레임 단위 결정론 검증)
```
AR 12발/s(주기 5f) · MG 스핀업→캡(말기 60발/60f)·감쇠 곡선(50f 중간값→110f 바닥) · SG 펠릿10/탄1
SR auto 사이클 83f≈1.4s(첫발 71f) · 수동 풀차지 61f≈1.02s · 수동 톡톡이 14f≈0.23s(비풀차지)
maintain(Raven형) 121f · DOWN_Charge 60f(전 발사 풀차지, Tap=throw)
재장전: auto 탄0 f33→f118 재개(0.2+1.0+0.2) · manual f94(전이 생략) ·
버프 100% = 주기 무중단(무한탄창 창발) · SR(UP)+100% = 장탄 무소모(spot_last 창 충전)
```
사용자 실측 루틴(풀차지 1.02~1.03s/발, 톡톡이 0.22~0.26s)과 프레임 정합.

### 3. 잔여
- K8: SimClock 프레임 루프 + 발사→AttackContext(BuildAttackContext+RollCoreHit/RollCrit)→Damage→Metrics 배선.
- 버스트 stage 간 딜레이 상수 주입 자리(측정① 3버→풀버 = 사용자 영상 실측 대기).
- Wave1 잔여 = K4(공식 스킬 로더)·K6(Metrics).

---

## 2026-07-08 (2차) — D3 체인 조립 + 모션 딜레이 심층 (einkk 발사 루프 검증)

**범위**: ① 니케/보스 skill→function 체인 조립(`staticdata_skill_chains.py`), ② 모션 딜레이/발사 루프
정밀 semantics 확정 — nikke-einkk(`lib/model/battle/nikke.dart`·`utils.dart`) 정독으로 단위 모순 해소.
산출 정책(사용자): **GitHub = gitignore 준수, 로컬 master 에 전부 머지.**

### 1. D3 조립 — `assembled/skill_chains.json` (gitignore, 22MB)
```
characters 192 (스킬레벨 5,750 — 결손 = name_code 3001 스킬2 부재(base_id=0) 1명뿐)
bosses 87 (solo raid 변종 statenhance=230000; passive StateEffect 체인 + skill use/hurt 체인)
functions 14,249 (connected_function BFS 확장, Fx/아이콘 필드 제거, enum 이름 주석)
state_effects 3,381
```
스팟 재검증: Emma s1 lv10 = HealCharacter 1077/OnHurtRatio 500 · Maxwell burst lv10 = 81342 ✓.

### 2. 모션 딜레이 — 단위·semantics 확정 (einkk `timeDataToFrame(t)=t×fps/100` = **1/100초**)
| 필드 | 값(지배적) | 확정 의미 |
|---|---|---|
| `spot_first_delay` | 20=0.2s=12f | 사격 상태 진입(엄폐→조준) 후 첫 발사/차지 시작 전 대기. 비사격 동안 재-arm. 차지무기 = 종료 프레임에 charge 1f 선시작 |
| `spot_last_delay` | 20=0.2s | **SR/RL(input=UP) 발사 후 강제 엄폐 복귀** 모션. 복귀 동안 비사격 → SR 사이클 ≈ 12+12+60f = **1.4s** |
| `maintain_fire_stance` | 대부분 0 | >0 = 발사 후 복귀 없이 자세 유지, 대기 = spotFirst+maintain (einkk: A2 +9f 미해명 TODO) |
| `uptype_fire_timing` | 비율(×10000) | 투사체형: 발사 이벤트를 maintain×비율 시점으로 보정(투사체 생성 타이밍) |
| `burst_apply_delay` | 1=0.01s | einkk 미소비 — 무시 가능 |
| 버스트 시전 애니메이션 락 | **데이터 부재** | einkk 도 미모델. K8 in-game 대조에서 per-char 상수 필요성 판단 |
| 구 실측 0.03s | — | spot 계열과 무관 — **폐기** (ARCHITECTURE 레거시) |

### 3. 발사 루프 정밀 사실 (einkk 검증 → K3 스펙 = ENGINE_GUIDE §5 갱신)
- **RPM accumulator**: 매 프레임(비사격 포함) `countdown −= rateOfFire(RPM)`, 발사 시 `+= 60×fps`(=3600).
  구조적 1발/프레임 → MG nominal 70/s = **실효 60/s** (`WeaponProfile.FireRateAtShot` 60fps 캡과 일치 ✓).
- **ramp 리셋 = 점진 감쇠** (교정): 비사격 프레임마다 `(end−start)/reset_time` 하강 — "중단 1s 후 즉시 리셋" 아님.
- 명중원: 발사 `−changePerShot` / 비사격 `+changeSpeed/fps` per frame 회복 (MG 250→10→회복).
- 재장전: 엄폐 상태에서 진행(잔탄<max 자동), `reload_bullet` 비율 부분장전.
- 버스트 게이지: burstStage 0 에서만 충전, 관통 히트 = 파츠당 추가 게이지 이벤트.

### 4. 잔여
- K4: skill_chains.json → C# DTO/로더 (공식 enum 미러 + 미지값 graceful). K3: 위 스펙 구현.
- 브랜치 → 로컬 master 머지 (사용자 지시, 이 커밋 후 수행).

### 5. 후속 확정 (2026-07-08 3차 — 사용자 실측 ground truth + 데이터 판별)
- **상태 전이 0.2s = 전 무기 양방향** (einkk 은 aim→cover 를 UP형에만 — 실게임 관측으로 교정).
- **재장전**: 공식 = `reload_time×(1−Σ버프)` 감산형(사용자 확정; einkk 버프 음수 percent 정합 + 첫 재장전에
  spot_last 가산). **≥100% = re-click([0.02,0.028]s) 이내 즉시 장전**(3.5년 플레이 확정) — 톡톡이 무소모/
  탄0 즉시충전 전부 "비사격 프레임 재장전 진행" 원시 규칙(R1/R2)에서 창발. 특례 하드코딩 금지.
- **SR/RL 3부류 = 데이터 필드로 판별** (roledata shot 전수):
  `UP+maintain=0` 68명(강제 복귀) / `UP+maintain>0` = SBS(0.23s)·Raven(0.83s)·A2(0.84s) — **자체 후딜레이 =
  maintain_fire_stance 값** + uptype_fire_timing 보정 / `DOWN_Charge` = Liberalio·Neon:VE·Vesti:TU·Anis:Star·
  Cinderella — **only 풀차지**(릴리즈 발사 불가) / `DOWN` = Pascal. 사용자 관측과 필드가 1:1 대응.
- **풀버스트 10s = 진입 시점 기산**(확정). 버스트 stage 간 딜레이 상수 = ConfigBattle 에 **없음**
  (`burst_duration_time=0`; step 배율 10000/15000 뿐) → [0.01,0.17]s 실측 채택, 3버→풀버 = 실측 대기.
- ConfigBattle 신규 참고: `RLV2SwitchDelayTime=20`(0.2s) — DOWN_Charge(V2) 연관 추정, 의미 미확정.

---

## 2026-07-08 — D1: 공식 스킬 테이블 디코드 (FunctionTable — THE GAP 데이터원 확보)

**범위**: 사용자 결정(공식 FunctionTable 채택, skills_parsed v3 강등)에 따라 SharpnelXu 공개 스키마
(`NikkeMpkConverter/model/Skills.cs`·`CharacterData.cs`)를 `memorypack_decode.py` 에 이식, StaticData
qa-260702 디코드+검증. 복호 산출물 = gitignore(스크립트/스키마만 커밋).

### 1. 디코드 — 8표 전부 clean (off==len)
```
FunctionTable 19459 · CharacterSkillTable 4387 · StateEffectTable 5155 · SkillInfoTable 9280
· CharacterTable 1905 · (기존) MonsterParts 669 · Monster 2043 · MonsterStatEnhance 30671
```
- CharacterTable 필드셋 drift: 실직렬화 40멤버 = 모델 41 − `surface_category`. 후보 drop 자동탐색(구조 통과
  5~14 전부) → 의미 배제(class=0 불능) + **roledata 192캐릭 전수 교차검증 mismatch 0**(element/bonusrange/
  critical_ratio·damage/burst_duration·apply_delay)으로 확정.
- 과거 RE 실패 root cause 규명: FunctionData 의 long 3개(function_value/status_trigger_value/×2)를 int 로
  읽어 member index 가 밀렸었음(관측 Buff_icon@33 = Order30 + 3).

### 2. 풀루프 검증 (FUNCTIONTABLE_DECODE_PLAN §4) — 통과
- Maxwell(5001) 버스트(ChangeWeapon) lv10 `skill_value=81342` ↔ roledata 설명 `813.42%` **bit-exact**.
  부가 발견: value_data 에 교체 무기 `shot_id=1010202` + 차지시간 `120`(=2초×60fps) — weapon-swap 의 실체.
- Emma(5005) 스킬1 lv10: `HealCharacter(2) val=1077`(10.77%) + `OnHurtRatio(7) trig=500`(5%) ↔ 설명값 일치.
- value 스케일 = ×10000(10000=100%) 확정. 시간류 = 60fps 프레임 단위 존재 확인.
- 보스 passive(StateEffect 7252022/7252002) = Immune{Stun/ForcedStop/GravityBomb}(+ImmuneDamage_MainHP) — 정합.
- enum 미지값 = function_type 214~218 · timing 91~94 · status 67~73 (기지 최대 바로 위 연속) = 게임 신버전
  추가분 → 엔진 graceful-unknown 대상. 오정렬 증거 없음.

### 3. 잔여
- D3 조립: 니케/보스 skill→function 체인 JSON (+스킬 레벨 축). 소비처 = K4(공식 FunctionData 로더).
- 조립 JSON 커밋 정책(복호 raw 는 gitignore 확정) = D3 착수 시 확정.

---

## 2026-07-02 (2차) — 유실 무기 레이어 복구 통합 (WeaponProfile/AccuracyModel/DummyTarget)

**범위**: `.claude/worktrees/vibrant-kirch-db3d48` 에서 **uncommitted 방치**로 유실됐던 2026-07-01
무기 레이어를 발굴·통합. 아래 1단계(같은 날 1차 엔트리)의 flat raw `weaponData` shape 을
유실판(중첩+ETL 정규화, 발/sec·초·분수)으로 **대체**. ⚠ `ElementAdvantage`(속성 상성 유틸)는
**보류**(사용자 결정) — DummyTarget 상성 미반영.

### 1. 통합 내용
- ETL `_weapon`: 30+필드 정규화(+ 유실판에 없던 `spotFirst/LastDelaySec` 모션 딜레이 병합 추가).
- `WeaponDto`(+Accuracy/Burst 중첩) → `Stats/WeaponProfile`(`Nikke.Weapon`, null-safe Empty):
  `FireRateAtShot(n)` = MG spin-up(1→70 nominal) + **60fps 프레임캡 → 실효 60발/s**.
- `Combat/AccuracyModel`: 명중원 발당 수축 + P(코어힛)=(rc/R)² 면적확률 + `RollCoreHit/RollHit`.
- `Combat/ProperDistanceTable`: 유실판 PLACEHOLDER 구간 → **공식 bonusrange 최빈값**으로 교체
  (SG 0-25·SMG 15-35·AR 25-45·MG 35-55·SR 45-100·RL=없음) + per-char 오버로드(SR 예외 25-45 대응)
  + 커밋된 `proper_distance_table.json` 교차검증 테스트.
- `ITarget` 계약 갱신(K0 동결 해제 승인, 2026-07-02): 구 `InProperRange` bool(무기 비의존=의미오류) 폐기
  → `Distance/CoreRadius/BodyRadius` + `PopulateContext(+attackerWeaponType)`. `DummyTarget`(K5) 구현.
- `WeaponStatTable` 레거시 배너(remarks) + `EffectType.HitRate` 주석(명중률 스코프 진입, 버프 배선 잔여).

### 2. 빌드 — 0 errors / 테스트 — 77/77 통과 (기존 53 → 77; 유실 16 중 상성 2 제외 복구 + 데이터 전수 6)
```
dotnet test SimulatorEngine
→ 실패: 0, 통과: 77, 건너뜀: 0.
```
- 신규 데이터 발견: **Pascal(5096) = 비차지 RL**(charge_time=0, 1.5발/s 평사, fullChargeDamage=1.0)
  → "SR/RL=차지"도 무기타입 상수 불가. 차지 판정 = per-char `isChargeWeapon`.
- 전수 불변식(192): 비차지 116명 fullChargeDamage=1.0 / 차지 76명 {2.5×68, 2.0×2, 3.5×5, 1.5×1}.

### 3. 잔여
- ElementAdvantage 통합(보류 해제 시) → DummyTarget 상성 배선 + 상성 테스트 2종 복원.
- K3 FiringModel(소비), HitRate 버프→AccuracyModel 배선, spot delay 0.2s vs 구 실측 0.03s 캘리브레이션,
  타겟 코어/몸체 반지름 상수 확정, merged DB 재생성(파이프라인 재실행).
- 유실 원본 worktree(`vibrant-kirch-db3d48`) = 통합 확인 후 정리 권장 (백업: 세션 scratchpad).

---

## 2026-07-02 — 무기 타이밍 데이터 레이어 1단계 (ETL weaponData → DTO)

**범위**: roledata `shot` 블록의 발사 ramp/명중원/모션딜레이/펠릿/버스트게이지 14필드를
ETL 이 추출(`roledata_cleaner._weapon_data` → clean/merged `weaponData` 키) → C# `WeaponDataDto`
→ `Nikke.WeaponData` (raw 보존, 정규화=소비측 단일 지점). 소비처 K3 FiringModel 은 다음 단계.
※ 동일 스코프 선행 구현(WeaponProfile/AccuracyModel 등, 2026-07-01)이 **미머지 유실**되어 재구현.

### 1. 빌드 — 0 errors / 테스트 — 53/53 통과 (기존 49 + 신규 4)
```
dotnet test SimulatorEngine
→ 실패: 0, 통과: 53, 건너뜀: 0.
```
신규 4 = `WeaponDataTests.cs` (소스 = 커밋된 `roledata_clean.json`, 192캐릭 전수):
- 전원 weaponData 보유 + rateOfFire/spot delay/shotCount 유효.
- **MG ramp = MG 전용**: 60→4200 발/분(발당 +100, 리셋 100=1.0s), 명중원 250→10 수축; 그 외 무기 start==end·변화 0.
- 단위 앵커(발/분): AR 720(=12/s) 존재·SMG 전원 1440(=24/s)·SG 전원 90(=1.5/s).
- SG 펠릿 = per-char 5 또는 10 (무기타입 상수로 대체 불가 증거).

### 2. 데이터 불변식 (2026-07-02 전수 조사, 192명)
```
weaponData 누락 = 0 / ramp(start≠end) = MG 24명 전원, 그 외 0명
per-char 편차: AR rate 720|150 · RL 60~300 · SR 60|200 · SG shotCount 5|10 · spotFirstDelay 20(190)|33|13
```

### 3. 잔여 (의도적 미구현)
- `WeaponStatTable` 하드코딩(MG 60/s 고정 = ramp 누락, SG 5/3 vs 데이터 1.5/s)은 **미교체** — 2단계에서 weaponData 기반으로 대체.
- merged DB(`nikke_merged_db_returned.json`, gitignore)는 **파이프라인 재실행 필요** — 구 파일엔 weaponData 없음(DTO null-safe).
- spot_first_delay 단위(1/100초 추정 = 0.2s) vs 구 실측 모션딜레이 0.03s 모순 — in-game 캘리브레이션 대기.

---

## 2026-07-01 — 엔진 Wave 1 K2 (SimClock 이벤트 큐)

**범위**: K0 동결 계약 `ISimClock` 구현 — 이산이벤트 클럭(min-heap). 기준 = `WORK_BREAKDOWN.md` K2,
권위 `ENGINE_GUIDE.md` §5(SimClock)·§6 D5(min-heap 자료구조).

### 1. 빌드 — 0 errors
```
dotnet build SimulatorEngine/NikkeSimulator.sln
→ 오류 0개 (4 프로젝트). Tests.csproj 에 Engine ProjectReference 추가(Wave1 공유; 먼저 닿는 청크가 추가).
```

### 2. 테스트 — 49/49 통과 (기존 39 + K2 신규 10)
```
dotnet test SimulatorEngine/Nikke.Simulator.Tests/Nikke.Simulator.Tests.csproj
→ 실패: 0, 통과: 49, 건너뜀: 0.
```
신규 10 = `SimClockTests.cs`:
- 시각순 실행(예약순 무관) / 동시각 FIFO tie-break(seq) / 재귀예약 2종(미래·동시각) /
  과거예약(`atSec<NowSec`) `ArgumentOutOfRangeException` / 분할 Run(창 밖 이벤트 지연) /
  `NowSec` 단조증가·종료값=untilSec / 빈큐 no-op / 창밖만 no-op / 경계(==untilSec 포함, > 제외).

### 3. 구현 메모
`Engine/Clock/SimClock.cs` — `PriorityQueue<Action,(double AtSec,long Seq)>` + 단조증가 seq 로 동시각
삽입순(FIFO) 결정적 고정(.NET `PriorityQueue` 는 동순위 **불안정** → 복합키로 보정). `Run(untilSec)` =
untilSec **포함**, 종료 시 `NowSec=untilSec` 클램프(분할 Run resumable). 계약 시그니처(`ISimClock`) 무수정.

---

## 2026-06-30 — 엔진 Wave 0 (K0 계약 스텁 + K1 W 단위 픽스)

**범위**: `Nikke.Simulator.Engine` 프로젝트 신설(K0) + 공유 계약 컴파일 스텁 동결, 평타 계수 W 단위
100× 버그 픽스(K1, `Nikke` 생성자 `/100`). 기준 = `SimulatorEngine/ENGINE_WAVE0.md`,
권위 `DESIGN.md`/`ENGINE_GUIDE.md`.

### 1. 빌드 — 0 errors (4 프로젝트)
```
dotnet build SimulatorEngine/NikkeSimulator.sln
→ 오류 0개. Core / Engine / Tests / Wpf 전부 dll 산출.
  신규: Nikke.Simulator.Engine.dll (Engine→Core 단방향, Core 역참조 0).
```

### 2. 테스트 — 39/39 통과 (기존 34 + K1 신규 5)
```
dotnet test SimulatorEngine/Nikke.Simulator.Tests/Nikke.Simulator.Tests.csproj
→ 실패: 0, 통과: 39, 건너뜀: 0.
```
신규 5 = W 불변식 ×3 + 파서 셀 락(`StatTable_Parses_KnownCells`) + foundation smoke(엔드투엔드).
- `WUnitFoundationTests.BasicAtkMultiplier_IsNormalizedToFraction` (Theory ×3: 13.65/5.57/214.3)
  — multiplier(percent-number) → `BasicAtkMultiplier`(fraction) `/100` 정규화 + fraction-scale 가드.
  **100× 버그 회귀 락.**
- `…FinalAtk_And_UnbuffedBasicShot_AreReported` — Initialize→Nikke→BuildAttackContext→CalculateDamage
  엔드투엔드. 견고 파서로 정본 csv 로드 → Privaty FinalBaseAtk 산출, bareShot==floor(FinalAtk×W) 통과(§4).
- 골든 18점 포함 기존 34 불변 — W 픽스는 `Nikke` 주입측만 건드려 대미지 공식 무영향.

### 3. K0 계약 스텁 (동결 대기)
`Engine/{Clock/ISimClock, Rotation/IRotationController(+SimState/RotationAction), Targets/ITarget,
Combat/Combatant, Skills/SkillParsedDto 패밀리, Buffs/BuffInstance, Metrics/IMetricsSink·RunResult,
SimulationRunner.RunOnce}`. 임플 = `throw NotImplementedException`(데이터 DTO 는 throw 없음).
enum 슬롯 = string(roledata audit/KP1 흡수 전 선잠금 회피).

### 4. K1 게이트 — ✅ 통과 (블로커 해소)
- **csv 파싱**: `StatTable.Initialize` 를 **견고 파서**로 교체 — cp949/UTF-8(Latin1 바이트디코딩) + 따옴표 +
  **셀 내부 줄바꿈**(Excel Alt+Enter 헤더 6개가 원래 crasher) + 천단위 콤마 내성, **행 위치 내용기반 탐지**
  (레벨표=col0 "1"부터, 호감도표=col26 "1"부터 → 헤더 행수 변동 무관). 옛 하드코딩 행번호(레벨 6~1005,
  bond 3~42) 제거. 사용자도 정본 csv master 업로드(`d4899ff`). WPF 시작 로딩도 정상화. 셀 락 테스트
  `WUnitFoundationTests.StatTable_Parses_KnownCells`(lv1=13500/600/90, lv1000 ATK 1005385, bond40=52650/2340/351).
- **in-game 일치**: stat 조립 0-error(§5) + 비차지 평타 W·C 실측(gap#4, 사용자) + 공식 golden 18 +
  엔드투엔드 wiring 테스트(`FinalAtk_And_UnbuffedBasicShot_AreReported`: Privaty FinalBaseAtk 로드 → bareShot
  == floor(FinalAtk×W) 통과). → **게이트 통과, Wave 1(K2~K6) 착수 가능.**

### 5b. Stats/Combat 3-way split 리팩토링 (2026-06-30)
파일명-역할 괴리 정정: `Stats/StatCalculator`(실은 대미지) → `Combat/DamageCalculator` 개명·이동(namespace
`Core.Combat`, `AttackContext` 동반). 스탯 조립(`GetCoreAppliedStats`/`GetEquipmentStats`/`GetConsoleStats`)
은 `StatTable`→`StatCalculator`(스탯 계산 전용) 이관. `StatTable`=로딩+raw(`GetLevelClassStat`/`GetBondClassStat`/
`TryGetEquipBase`) 전용. **순수 code-motion** — 빌드 0에러, 38/38 그린(골든 18=DamageCalculator, 장비 4=StatCalculator
경유로 거동 보존 확인). 참조 갱신: Nikke/WPF/Engine/테스트 + 문서(DESIGN §2·§3·§3.5·§6·§7, ENGINE_GUIDE §1·§2).

### 5. 스탯 조립(FinalBaseStat) 불변식 — 사용자 검증 (2026-06-30 보고)
실제 crawl 데이터 주입 후 검증: **서로 다른 여러 캐릭터에서 스탯 오차 0** (in-game 스탯창 대조).
**돌파(grade/limit-break)를 임의로 올리거나 내려도 오차 0.** → `StatTable.GetCoreAppliedStats`
(+`OverloadProcessor` OL group-then-round + 장비/큐브/소장품 base·rate) 조립이 in-game 과 **bit 일치하는
불변식**으로 확립. (per-hit 대미지 공식 §3 와 별개의 Core 축.)
> ✅ 재현: 견고 파서 + 정본 csv(`d4899ff`)로 CI 로드 가능 — 셀 락 테스트로 파서 회귀 가드(§4). 스탯 조립
> 공식은 **DESIGN §3.5** 로 문서화 완료. (모델: `Final = base × (1+Σbuff)`; OL·큐브/소장품 rate·런타임 스킬 = buff.)

---

## 2026-06-30 — 장비/큐브/소장품 데이터 연동 + 문서 정합

**범위**: 장비 스탯 + 하모니 큐브·소장품 (base ATK/HP/DEF + 특수효과) 를 공식 blablalink JSON
으로 C# 엔진에 배선. 옛 CSV "예시 수치" / `stub=0` 경로 제거. 병행 로컬 문서(deck-optimizer)와의
모순·중복 정정.

**관련 commit**: `69210f2`(장비 배선) · `f1256f2`/`8d63e68`(큐브·소장품 effect ETL) ·
`273f777`(EffectType enum/dict 배선) · `1358e0c`(base→JSON + 큐브 자동장착 + 데드코드 제거 + 파이프라인) · 본 문서/문서정정 commit.

### 1. 빌드 — 0 errors
```
dotnet build SimulatorEngine/NikkeSimulator.sln
→ 오류 0개
```

### 2. 단위/통합 테스트 — 34/34 통과
```
dotnet test SimulatorEngine/Nikke.Simulator.Tests/Nikke.Simulator.Tests.csproj
→ 실패: 0, 통과: 34, 건너뜀: 0, 전체: 34
```

| 파일 | 검증 대상 | 케이스 |
|---|---|---|
| `DamageFormulaGoldenTests.cs` | 대미지 공식 §3 (in-game 18 golden + 브래킷 구조/최소뎀/TrueDamage) | 골든 Theory + 구조 단위 |
| `EquipmentStatsTests.cs` | `GetEquipmentStats` 공식 `round(base×(1+0.3·corp+0.1·lv))`, 제조사 일치 +30%, 빈 장비=0, merged DB 신 shape 역직렬화 | 4 |
| `EffectTableTests.cs` | 큐브/소장품 특수효과 표 로드 (Vigor MaxHp 9.69%·ElemAdv 19.09%, AR Core·Def, SR chargeMult, 미지 큐브=빈 dict) | 4 |
| `NikkeBuildIntegrationTests.cs` | merged DB 의 큐브 장착 캐릭 → `Nikke` 생성 시 자동 `EquipCube` + base 스탯이 `FinalBaseHP` 에 반영 | 1 |

> 골든 회귀: 대미지 공식 결과는 모든 배선 변경 후에도 불변(bit-exact). 라우팅/스탯 변경이 공식을 건드리지 않음을 보장.

### 3. ETL 파이프라인 — 7단계 전부 exit 0
```
python DataPipeline/run_pipeline.py --stage etl
→ etl:equip_table · static_base · cube_effect · collection_effect
  · blabla_merger · roledata_cleaner · db_merger   (전부 exit 0)
→ 전체 7단계 성공.
```

### 4. 데이터 불변식 (마이그레이션 전제 검증)
```
cube base signatures        = 1   (전 큐브 공통 → base 표 = {level:{ATK,HP,DEF}} 로 단순화 정당)
collection(R) base signatures = 1 (전 무기 공통 → 동일)
cube_base_table levels      = 15
collection_base_table levels = 16
merged roster = 185 | cube-equipped chars = 61  (큐브 tid 가 merged DB→자동장착 경로로 흐름 확인)
```

### 5. 문서 정합성 정정 (병행 로컬 작업과의 모순 해소)
deck-optimizer 방향 확장 문서(`67bc8ed`/`737966b`)가 장비·큐브 작업 **이전 스냅샷** 기준이라,
merge 후 아래 stale 주장·중복이 남아 정정함:
- `DESIGN.md` §6: 중복 블록(코드구조/DamageCalculator/파서/출력 각 2회) 제거 + `장비표=0 stub, 큐브=예시 수치, 실측 필요` (stale) 삭제 → `확보+C# 연동 완료` 단일화.
- `ENGINE_GUIDE.md`: `GetEquipmentStats(equips) (stub=0)` → 실 시그니처 `(class,mfr,equips)` + JSON 연동 완료. §7 데이터 의존 항목도 해소 반영.
- `WORK_BREAKDOWN.md` KP2: `Core stub 교체 필요` → 연동 완료(잔여 = ProperDistance, 타이밍/조건부 효과).

> 코드/데이터는 merge 로 훼손되지 않았음(우리 브랜치 = master 조상 → fast-forward, 0 코드 diff). 정정은 **문서 텍스트 한정**.

### 6. 잔여 (의도적 미구현 — sim 루프 대기)
타이밍(Reload/Charge/Burst/Bastion)·조건부(Assist)·생존(받피감/Heal/Cover) 큐브·소장품 효과는
표에 **파싱만** 되고 엔진 미소비. 사유·소비처: [`SKILL_DATA_BLABLALINK.md`](SKILL_DATA_BLABLALINK.md) §4.2.
