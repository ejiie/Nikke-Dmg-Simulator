# FACTS — 검증된 불변 사실 시트 (모든 작업의 전제)

> **지위**: 수년간의 커뮤니티 연구 + 사용자 개인 연구 + in-game 실측으로 **증명된** 사실만 담는다.
> 여기 있는 수치·공식·규칙과 어긋나는 구현/문서 = 그쪽이 틀린 것. 바꿀 발견이 나오면 **코드보다
> 먼저 사용자 확인**. 상세 유도·검증 증거 = `VERIFICATION_LOG.md`, 방향 = `DESIGN.md`.

## 1. 대미지 공식 (per-hit — 18골든, 잔차 ≤1.3e-7)

```
Damage = floor( B2 × B3 × B4 × B5 )
  P  = (FinalAtk − effectiveDef) × M                 ← M = 이 대미지 인스턴스의 계수 × 차지배율
       M: 일반 무기 히트 = W×C · 비차지 히트 = W (C=1) · 직접 DealDamage 스킬 = function 계수 ·
          보스 공격 = 평타/스킬 지정 계수. ChangeWeapon 유래 차지 히트 = 무기 히트 → W×C.
  B2 = floor(P) + Σ_active floor(P × bracket_i)      ← 가산 per-term FLOOR
       bracket ∈ { 적정거리 0.3, 풀버스트 0.5, 크리 Σcrit_dmg(기본0.5), 코어 1.0+Σcore_buff }
  B3 = 1+Σattack_dmg[+pierce][+parts][+dot][+seq]  · B4 = 1+Σdamage_taken[+distrib] · B5 = 1+Σstrong_elem
```
- 표기 확정(2026-07-11): B3~B5 는 **(1+Σ) 팩터 자체** — 구 `(1+ΣB3)` 표기의 이중 정의 해소.
  구현 = `SkillMultiplier`(W 슬롯) × 차지 C — `DamageCalculator` 현행 구조와 일치.
- 최소뎀: `effectiveDef ≥ FinalAtk` → 무조건 1. True Damage: `effectiveDef := 0` (+B3 조건부 가산).
- C(차지) = `(ChargeDmgBase + Σadd) × (1 + Σmult)` — 2축. 비차지 = 1.
- **보스→니케 대미지 = 동일 구조** `(bossAtk − nikkeDef) × M` (사용자 확정 2026-07-10). 브래킷 세부
  적용 범위 = §8. MVP 는 딜 타겟만, 생존 시뮬은 확장(T04).
- 구현 `Core/Combat/DamageCalculator.cs` · 골든 `DamageFormulaGoldenTests`.

## 2. 스탯 조립 (0-error 검증)

`레벨표 + floor(lv×grade×0.02) + gradeFlat(3000/20/100) + 호감도 + 콘솔` → `+round(×core×0.02)` →
`+ 소장품base + 장비 + 큐브base` → `× (1+Σrate버프)` — DESIGN §3.5. **grade=floor / core=사사오입** 분리.
장비 = `round(base × (1 + 0.3·기업일치 + 0.1·강화))`.

## 3. 라운딩 권위 = OverloadProcessor 니케식 **group-then-round**

- **동일값 버프는 선합산(그룹) → 그룹 단위 사사오입(AwayFromZero) → 합산.** 항별 라운딩 아님.
- 정수 스탯 decimals=0. **시간류 = 1/100초 정수 도메인** (`ReduceTimeCs`):
  `effectiveCs = baseCs − Σ_group round(baseCs × value × count)` — 버프는 ×10000 정수 복원, 순수 정수 연산.
- 재장전·차지 속도 버프 = 이 감쇠식. ≥100% 상당 → 0cs → 하한 1프레임(즉시).

## 4. 단위표 (혼동 금지)

| 데이터 | 단위 | 변환 |
|---|---|---|
| FunctionData `function_value` 등 (Percent) | ×10000 정수 | /10000 = 분수 (81342 = 813.42%) |
| 시간류 (reload/charge/spot/burst_duration/쿨타임) | **1/100초 정수** (timeData) | 프레임 = round(cs×60/100) |
| CharacterSkill `skill_value` 의 차지시간 | **60fps 프레임** (120 = 2s) | 예외 — ChangeWeapon 계열 |
| `rate_of_fire` 계열 | **발/분(RPM)** | /60 = 발/초 (AR 720=12/s) |
| basicAttack `multiplier` | percent-number (13.65 = 13.65%) | Nikke 생성자에서 /100 = **W fraction** |
| 큐브/소장품 effect values | percent-number | EffectTable 이 /100 = 분수 |
| crit | 전 192캐릭 (15%, 150%) 단일 | AttackContext 기본값 |
| 시뮬 시간축 | **60fps 프레임 격자 = canonical** (정수 frame; 초 = frame/60 파생) | 모든 지연·이벤트 시각 = 정수 프레임 양자화. cs/초 입력 = 단일 변환 지점 |

## 5. 발사/모션/재장전 스펙 (사용자 3.5년 실측 + einkk 교차 — ENGINE_GUIDE §5 상세)

- **발사** = RPM accumulator (프레임당 `−=RPM`, 발사 시 `+=3600`) — 구조적 1발/프레임 → MG nominal 70/s = 실효 60/s.
- **MG ramp**: 발사당 +100RPM clamp[60,4200]. **리셋 = 점진 감쇠** (비사격 프레임당 (end−start)/reset_time).
- **상태 전이 = 전 무기 양방향**: 엄폐→조준 spot_first(0.2s) / 조준→엄폐 spot_last(0.2s).
- **SR/RL 부류 = per-char 데이터** (무기타입 상수 금지): `input=UP,maintain=0`(발사 후 강제 복귀 — 사이클 83f≈1.4s) /
  `UP,maintain>0`(복귀 없음, 자체 후딜=maintain — SBS 0.23s·Raven 0.83s·A2 0.84s) /
  `DOWN_Charge`(only 풀차지 — Liberalio·Neon:VE 등) / `DOWN`(평사 — Pascal). SG 펠릿 5|10 per-char.
- **재장전 R1/R2**: 비사격 프레임마다 진행·발사 시 리셋. 실효 = §3 감쇠식 + 자동 탄0 에 spot_last 가산.
  **재장전 속도 ≥100% = re-click 이내 즉시 장전 (확정)** → 무한탄창·SR(UP) 무소모 = 창발 (특례 코드 금지).
- **수동 컨트롤** (5인 중 1인): 조작 축 = **니케 개별 엄폐/해제 + 전체 엄폐/해제** (실게임 UI 단위 — 사용자 확정 2026-07-10). re-click 갭 **[0.02, 0.028]s** (1~2프레임). 수동 풀차지 = 발당 charge+ε (spot_first 재지불 없음, 61f≈1.02s). 톡톡이 = spot_first+ε 반복 (14f≈0.23s). 자동 = 풀차지 항상 + 전이 사이클.
- **버스트**: 풀버스트 10s = **진입 시점** 기산. 3버→풀버 진입 = **0.46s ≈ 28f** (실측). stage 간 딜레이 = [0.01,0.17]s random. 게이지 cap = 1,000,000 (`burst_gauge_table.json`), burstStage 0 에서만 충전. 버스트 시전 사격공백 = 무시(사용자 결정).
- **solo raid 전투 시간 = 180s** (사용자 확정 2026-07-10) — 표준 sim duration = DB 집계·덱 비교 기준.

## 6. 데이터 계보 (원천 → 가공 → 소비)

```
roledata(공개 CDN) ─ roledata_cleaner ─ roledata_clean.json ─┬─ db_merger(+유저) ─ merged DB ─ Nikke 엔티티
                                        (weaponData 35+필드) └─ proper_distance_table.json
blabla static(공개 CDN) ─ 4 cleaner ─ equip/cube/collection 표 ─ StatTable/EffectTable
StaticData.zip(.mpk, gitignore) ─ memorypack_decode(SharpnelXu 스키마) ─ mpk/*.json
   ├─ staticdata_skill_chains ─ skill_chains.json(gitignore) ─ SkillChainLoader(K4)
   └─ staticdata_raid_decode + solo_raid ─ solo_raid_boss.json(gitignore) ─ BossTarget(T04)
sd.bin(로컬 게임) ─ getFromLocalSdBin ─ ConfigBattle 상수 (burst_gauge_table.json 만 커밋)
재생성: run_pipeline.py (--stage all | staticdata)
```

## 7. 불변 규칙 (INV)

1. 미지 enum / 결손 데이터 = **graceful no-op**, throw 금지 (게임 신버전 값 = 기지 최대치 위 연속 추가 — D1 검증).
2. RNG = `IRandomSource`, **고정 시드 금지** — 검증은 N-run 수렴 (예: 크리 15% ±2%p @N≥5k).
3. 엔진 = UI/compute/직렬화 무지 순수 라이브러리. Engine→Core 단방향.
4. 게임데이터 복호물 재배포 금지 (gitignore). 개인 로스터 데이터 커밋 금지.
5. B5 기본 우월 +0.1 은 **단일 소스** — ElementAdvantage 통합 시 ConfigBattle `ElementBonusDamage`·OL IncElementDmg 와 중복 가산 금지 (T04).

## 8. 알려진 가정 / 미검증 (건드릴 때 주의)

- SG 펠릿 = 펠릿별 독립 히트·개별 크리/코어 롤, W=펠릿당 — **가정** (T07 골든에서 확정).
- `EffectRoute.Unverified` 타입들 (FullBurstDamage·AddDamage 620건 등) = 브래킷 미검증 — T07 대조로 승격.
- ElementAdvantage(순환 Water→Fire→Wind→Iron→Electric→Water, +0.1) = 내용 확정·**코드 통합 보류** (T04).
- 차지속도 감쇠도 §3 감쇠식으로 통일 — ÷(1+Σ) 대안은 T07 에서 반증 시에만 재론.
- 타겟 코어/몸체 반지름 = 설정 상수 (실측 미비). ProperDistance 보너스 0.3 = 미검증 (구간은 공식 데이터).
- 보스→니케 대미지: 기본 구조만 확정(§1) — 크리/코어/B3~B5 브래킷 적용 여부·계수 데이터원(MonsterSkillTable 미디코드) = 미검증.
- `RLV2SwitchDelayTime=20`(ConfigBattle) 의미 미확정.
