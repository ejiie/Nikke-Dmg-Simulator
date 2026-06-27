# ARCHITECTURE

> **역할**: 시스템 전체 구조, 데미지 공식, 무기 규칙, 경계 원칙.
> **업데이트**: 공식/브래킷/무기 규칙이 바뀔 때만. 드문 큰 변경 시.

---

## 1. 시스템 레이어

```
┌─────────────────────────────────────────────────────────────┐
│  DataPipeline/  (Python ETL + 크롤러 + LLM 스킬 파서)       │
│   crawler/   ─ getFromBlaLink.py, getFromPrydwen.py         │
│                ↳ Database/raw/ 에 생짜 API/웹 응답 저장     │
│   etl/       ─ prydwen_cleaner.py, blabla_merger.py,        │
│                auto_mapper.py, db_merger.py, atk_parser.py  │
│                ↳ Database/processed/*.json 조립             │
│   schema/    ─ skill_schema.py (Pydantic DTO),              │
│                skill_parser_llm.py (LLM 기반 파서)          │
│                ↳ skills_parsed.json 생성                    │
└─────────────────────────────────────────────────────────────┘
                          │ (파일 경계)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  SimulatorEngine/Nikke.Simulator.Core/  (C# .NET 8)         │
│   - Data/            : JsonProvider (I/O 단일 진입점)       │
│   - Data/Dto/        : JSON 1:1 매핑 POCO                   │
│   - Data/Constants/  : 하모니 큐브 TID 테이블 + 콜렉션      │
│                        효과 저장소 (불변 readonly struct)   │
│   - Stats/           : StatTable (CSV 로더),                │
│                        StatCalculator (per-tick 공식),      │
│                        OverloadProcessor (pre-combat OL),   │
│                        AttackContext (tick 컨텍스트 struct) │
│   - Entities/        : Nikke (캐릭터 집계 +                 │
│                        BuildAttackContext 팩토리)           │
└─────────────────────────────────────────────────────────────┘
                          │ (라이브러리 참조)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  SimulatorEngine/Nikke.Simulator.Wpf/  (WPF UI)             │
│   - App.OnStartup 에서 StatTable.Initialize(csvPath) 호출   │
│     (프로세스당 1회. 실패 시 MessageBox + Shutdown(1))      │
└─────────────────────────────────────────────────────────────┘
```

**계층 책임 경계**:
- **ETL**: 원본 보존 + `val_type == "Percent"` 인 OL 값만 `/10000` 스케일링 (`blabla_merger.py:138`). 의미 해석은 일절 X.
- **C# Core**: 의미 해석 + 연산. 파일 I/O는 `JsonProvider` 한 점에만.
- **WPF**: 표현 전용. Core 통해서만 로직 호출.

---

## 2. C# 네임스페이스 맵

| 네임스페이스 | 주요 타입 | 역할 |
|---|---|---|
| `Nikke.Simulator.Core.Data` | `JsonProvider` | JSON I/O 단일 출입구. `GetSmartDatabasePath` (루트 자동 탐색) + `LoadJson<T>` (typed exception chain). |
| `Nikke.Simulator.Core.Data.Dto` | `RootDto`, `GlobalStateDto`, `CharacterDto`, `CharacterStaticDto`, `CharacterUserDto`, `BasicAttackDto`, `SkillDto`, `SkillLevelsDto`, `EquipmentPartsDto`, `EquipmentInfoDto`, `OverloadOptionDto`, `CubeStatDto` | JSON shape 1:1 매핑. 로직 넣지 않음. |
| `Nikke.Simulator.Core.Data.Constants` | `CubeEffectDto`, `CollectionEffectDto` (readonly struct), `CubeSkillTable`, `CollectionEffectTable` | 불변 effect struct + 정적 저장소. 메모리 할당 0. |
| `Nikke.Simulator.Core.Stats` | `StatTable` (CSV 기반), `StatCalculator` (per-tick 데미지 공식), `OverloadProcessor` (pre-combat OL 합산), `WeaponStatTable` (발사 속도/차지 타이밍), `IRandomSource` + `SystemRandomSource` + `CritSampler` (크리 RNG), `AttackContext` | 정적 룩업 테이블 + 데미지 공식 + OL 조립 + 무기 타이밍 + RNG 추상화. |
| `Nikke.Simulator.Core.Entities` | `Nikke` | 캐릭터 단일 인스턴스. 조립된 최종 기초 스탯 보유 + `BuildAttackContext()` 팩토리. |

**초기화 순서** (위반 시 NRE):
1. WPF `App.OnStartup` → `StatTable.Initialize(csvPath)` — 프로세스당 1회. 이 호출이 `_levelStats`, `_bondStats`, `_srCollectionStats`, `_cubeTable` 를 채우고 **동시에** `CollectionEffectTable.RegisterEffect` 로 콜렉션 특수효과도 주입.
2. JSON 로드 → `Nikke(dto, globalState)` 생성자 → `InitializeFinalStats()` 자동 호출.
3. 필요 시 `Nikke.EquipCube(tid, level)` → `CubeSkillTable.GetSkillEffect` 조회 → `InitializeFinalStats()` 재실행.
4. 공격 시점마다 `Nikke.BuildAttackContext()` → `AttackContext` struct 반환 → 시뮬 루프가 가변 버프 덧붙인 후 `StatCalculator.CalculateDamage(in ctx)`.

---

## 3. 데미지 공식

> ⚠️ **SUPERSEDED (2026-06-27).** 아래 §3.1 의 multiplicative B2 형식은 **오류** — in-game 실측 역산으로 **B2 는 가산 per-term FLOOR** 임이 18 golden 검증됨. **현행 권위 공식 = `Docs/DESIGN.md` §3.** 이 섹션은 historical 보존용일 뿐 신뢰 금지.

출처: `StatCalculator.CalculateDamage` + `DataPipeline/schema/skill_schema_legend.txt` 공식 섹션.

### 3.1 최종식 (권위 — legend 기준)

```
Damage = (FinalAtk - FinalDef)
       × (1 + fullBurst + properDist + Σcrit_dmg + coreHitBase + Σcore_hit_buff)    [B2]
       × (1 + Σattack_dmg [+pierce_dmg][+parts_dmg][+dot_dmg][+sequential_dmg])     [B3]
       × (1 + Σdamage_taken + Σdistrib_dmg)                                         [B4]
       × (1 + Σstrong_elem)                                                         [B5]
       × 계수                                                                       ← SkillMultiplier (통상 1.0)
```

**FullCharge 공격일 때만 추가 2-축 (§3.3)**: `× chargeDmg_final`.

#### 최소 대미지 규칙 (구현 완료 — A1, 2026-04-23)
- `effectiveDef ≥ FinalAtk` 이면 **어떤 브래킷/계수 조합이든 최종 대미지는 1 로 즉시 낙착** (중간 곱연산 미경유).
- 여기서 `effectiveDef = IsTrueDamage ? 0 : FinalDef` — True Damage 경로에서는 사실상 이 분기를 타지 않음.
- `StatCalculator.CalculateDamage` 구현:
  ```csharp
  double effectiveDef = ctx.IsTrueDamage ? 0.0 : ctx.FinalDef;
  if (effectiveDef >= ctx.FinalAtk) return 1.0;
  ```
- 과거 `Math.Max(1.0, FinalAtk − FinalDef)` 는 "깡뎀 최소 1 보정 후 모든 배율 적용" 으로 오작동했음 — 환각. 2026-04-23 교정 완료.

#### 반올림/내림
- 최종 스칼라 후 반올림 / 내림 / 올림 중 어느 모드인지는 **사용자 실측 검증 대상** (DEVLOG §C 열린 질문).
- 현재 구현은 `Math.Floor`. 잠정일 뿐.

### 3.2 브래킷 (legend 와 C# 구현 대응)

| 브래킷 | legend 코드 | C# 구현 (`StatCalculator.CalculateDamage`) | 조건 |
|---|---|---|---|
| **B2** | `b2_crit_core` | `1 + FullBurstBonus + ProperDistanceBonus + (IsCrit ? SumCritDmg : 0) + (IsCoreHit ? CoreHitBase(1.0) + SumCoreHitBuff : 0)` | `SumCritDmg` = 기본 0.5 + OL `StatCriticalDamage` + 버프 |
| **B3** | `b3_attack_dmg` | `1 + SumAttackDmg + (IsPierceHit ? SumPierceDmg : 0) + (IsPartsHit ? SumPartsDmg : 0) + (IsDotDamage ? SumDotDmg : 0) + (IsSequentialHit ? SumSequentialDmg : 0)` | 공격 종류 플래그로 게이팅 |
| **B4** | `b4_dmg_taken` | `1 + SumDamageTaken + SumDistribDmg` | `SumDamageTaken` = 적 디버프 합, `SumDistribDmg` = 분배 대미지 증가 |
| **B5** | `b5_strong_elem` | `1 + SumStrongElem` | 기본 0.1 (우월코드) + OL `IncElementDmg` + 버프 |

### 3.3 차지 2축

`IsFullCharge == true` 일 때만 적용:
```
chargeDmg_final = (ChargeDmgBase + SumChargeDmgAdd) × (1 + SumChargeDmgMult)
                   └─ coeff_charge_add ─┘               └── coeff_charge_mult ──┘
```

- `ChargeDmgBase`: **캐릭터별 데이터 구동**. `nikke_merged_db_returned.json` 의 `roster[nc].static.basicAttack.chargeDamage` 값을 그대로 사용. `Nikke` 생성자가 `BasicAtkChargeDamage` 필드로 캐싱, `BuildAttackContext` 가 SR/RL 분기에서 `ctx.ChargeDmgBase = BasicAtkChargeDamage` 로 주입.
  - 관측 예: 대부분 `2.5` (Full Charge 250%), 일부 `3.5` (350%). 드물게 그 외 값.
  - **"SR/RL = 잠정 2.5 하드코딩" 은 환각** — 원본 JSON 에 이미 per-character 값 존재 (2026-04-23 교정).
- `SumChargeDmgAdd`: OL `StatChargeDamage` + 스킬 `charge_dmg` (legend: `"Charge Damage ▲ X%"`).
- `SumChargeDmgMult`: 콜렉션 `ChargeDamageMultiplier` + 스킬 `charge_dmg_mult` (legend: `"Charge Damage Multiplier ▲ X%"`, 원문의 Multiplier 단어 유무로 분기).
- **두 축 모두 B3 와 독립**. legend INV-2: `deal_damage` action 은 `formula_bracket = null` 강제.

### 3.4 크리 확률 축 (브래킷 없음)

- `AttackContext.BaseCritRate` (기본 0.15) + OL `StatCritical` + 버프.
- **샘플링 방식**: tick 마다 `CritSampler.RollCrit(rng, ctx.BaseCritRate)` 판정하여 `IsCrit` 플래그 세팅. 기댓값 평균화 **아님**.
  - 예: 크리 확률 40% → 각 tick 에서 독립 40% 확률로 `IsCrit = true`. 연속 miss/hit 편차는 RNG 에 의해 자연 발생.
- legend stat 이름: `crit_rate`. 독립 계산, 어느 브래킷에도 속하지 않음.
- **RNG 추상화 (A6, 2026-04-24 구현)**:
  - `Stats/IRandomSource.cs`: `IRandomSource` 인터페이스 + `SystemRandomSource.Instance` (Random.Shared 래핑, 스레드 안전) + `CritSampler.RollCrit(rng, rate)` 헬퍼.
  - **고정 시드 절대 금지** (DEVLOG 2026-04-23 결정). 회귀 테스트는 샘플 수 증가 + 기댓값 수렴 (±ε) 패턴 사용 — deterministic seed stub 주입 금지.
  - 시뮬 루프가 `ctx.IsCrit = CritSampler.RollCrit(rng, ctx.BaseCritRate)` 로 소비 예정 (로테이션 페이즈 연결).

### 3.5 True Damage (방어 무시 축)

**핵심 정의**: 트루 대미지 = **적 DEF 를 0 으로 간주한 공격**. 별도 공식이 아닌, 동일 B2~B5 공식에서 `FinalDef := 0` 치환.

```
trueDmg = (FinalAtk - 0)
        × (1 + fullBurst + properDist + Σcrit_dmg + coreHitBase + Σcore_hit_buff)
        × (1 + Σattack_dmg + ...)
        × (1 + Σdamage_taken + Σdistrib_dmg)
        × (1 + Σstrong_elem)
        × 계수
        × chargeDmg_final    ← FullCharge 시
```

- 최소 대미지 규칙 (§3.1) 은 DEF=0 이라 사실상 무의미해짐 (FinalAtk 가 1 이하가 아닌 한).
- legend stat: `true_dmg`. 일반 공격을 트루로 전환하는 것은 `trait_true_dmg_conversion` 플래그 (`required_token` 조건 충족 시).

#### `CubeEffectDto.TrueDamageBonus` 의 위치
- **트루 대미지가 발생할 때만 적용되는 조건부 B3 가산 축**. 공격 종류 플래그 (`IsPierceHit` / `IsPartsHit` 등) 와 동일 패턴.
- **구현 완료 (A2, 2026-04-23)**:
  - `AttackContext.IsTrueDamage` (bool) + `AttackContext.SumTrueDmgBuff` (double) 신설.
  - `StatCalculator.CalculateDamage`: `IsTrueDamage` 시 `effectiveDef := 0` + `b3 += SumTrueDmgBuff`.
  - `Nikke.BuildAttackContext`: `CurrentCubeEffect.TrueDamageBonus` → `ctx.SumTrueDmgBuff` 주입.
- **남은 작업**: 어떤 스킬 조건이 `ctx.IsTrueDamage = true` 를 세팅하는지는 스킬 번역기 (`trait_true_dmg_conversion` + `required_token`) 에서 결정. 시뮬 루프 연결은 갭 페이즈 2.

---

## 4. Native Stat 조립식

`Nikke.InitializeFinalStats()` 에서 **생성자 + 큐브 교체 시에만** 재계산. 시뮬 루프에서는 불변.

### 4.1 조립 순서

```
(A) Core-applied  = StatTable.GetCoreAppliedStats(class, weapon, mfr, lv, grade, core, bond, consoles)
(B) Collection    = StatTable.GetCollectionStats(favoriteItemLv)         ← consts 합산
(C) Equipment     = StatTable.GetEquipmentStats(equipments)              ← 🚧 현재 TODO (0 반환)
(D) Cube          = Nikke.EquippedCube.{HP, Atk, Def} (또는 미장착 0)
(E) CubeHpRate    = CurrentCubeEffect.MaxHpBonusRate (Vigor 류)
(F) CollAmmoRate  = (WeaponType == "Machine Gun") ? CurrentCollectionEffect.MaxAmmoIncreaseRate : 0

effectiveNativeHP  = (A_hp + B_hp + C_hp + D_hp) × (1 + E)
effectiveNativeAtk =  A_atk + B_atk + C_atk + D_atk
effectiveNativeDef =  A_def + B_def + C_def + D_def
nativeAmmo         =  StaticInfo.ammoCapacity × (1 + F)

FinalBaseHP       = CalculateFinalBaseStat(effectiveNativeHP,  OL where type=="StatMaxHP",  0, 0)
FinalBaseAtk      = CalculateFinalBaseStat(effectiveNativeAtk, OL where type=="StatAtk",    0, 0)
FinalBaseDef      = CalculateFinalBaseStat(effectiveNativeDef, OL where type=="StatDef",    0, 0)
FinalBaseMaxAmmo  = CalculateFinalBaseStat(nativeAmmo,         OL where type=="StatAmmoLoad", 0, 0)
```

### 4.2 `StatTable.GetCoreAppliedStats` 공식 (출처: `Stats/StatTable.cs:172`)

```
gradeFlat = {HP: 3000·grade, ATK: 20·grade, DEF: 100·grade}

preCore   = lv + floor(lv · grade · 0.02) + gradeFlat + bond + console
final     = preCore + round(preCore · core · 0.02, AwayFromZero)
```

- `lv` 는 `_levelStats[level]` 에서 `className` (Attacker/Defender/Supporter) 로 분기하고, DEF 는 무기별 key (`AR/SR/SMG/SG/RL/MG` — `MapWeapon` 거쳐서).
- `bond` 는 `_bondStats[bond]` 에서 className 으로 분기, DEF key = `"ALL"` (호감도는 무기별 분리 안 함).
- `console` 은 `GetConsoleStats` 반환: 공용 콘솔(1001) HP·450, 클래스 콘솔(1101-1103) HP·750+DEF·5, 기업 콘솔(1201-1205) ATK·25+DEF·5.

### 4.3 `StatTable.Initialize` CSV 파싱 layout (출처: `Stats/StatTable.cs:41`)

| 데이터 | Row 범위 | Col 범위 | 대상 딕셔너리 |
|---|---|---|---|
| 호감도 테이블 | 3–42 | 26–36 | `_bondStats` (class 별 HP/ATK/DEF["ALL"]) |
| 레벨 테이블 | 6–1005 | 0–24 | `_levelStats` (class 별 HP/ATK + 무기 6종 DEF) |
| 소장품(SR) 기본 스탯 + 특수 효과 | 49–64 | 26, 28–48 | `_srCollectionStats` + `CollectionEffectTable.RegisterEffect` |
| 하모니 큐브 레벨 테이블 | (Skip 4) … lv ≥ 20 중단 | 38–43 | `_cubeTable` (Atk/Def/HP/SuperiorCodeDmg/SkillLevel) |

콜렉션 특수효과 컬럼: AI(34) Core, AK(36) Charge, AM(38) SMG, AO(40) SG, AS(44) MaxAmmo, AU(46) Def, AV(47) DmgTaken, AW(48) CoverHP.

### 4.4 버프 합산 규칙 (니케식 — OL / 스킬 버프 공통)

**출처**: 사용자 실측 지식 (2026-04-23). OL 뿐 아니라 모든 런타임 %-버프에 동일 규칙 적용.

#### 4.4.1 공식

주어진:
- `B_applicable` : 적용 기준량 (자기 버프면 자신의 native, `scale_base=caster_*` 이면 시전자의 native)
- `buffs = [p₁, p₁, p₂, p₃, ...]` : 버프 %-값 리스트 (동일값 중복 허용)
- `decimals` : 반올림 자릿수

알고리즘:
```
1. 동일 값 그룹핑:          groups = GroupBy(buffs)              // e.g. {(p₁, 2), (p₂, 1), (p₃, 1)}
2. 그룹별 델타:             Δ_g    = Round(B_applicable × p_g × count_g, decimals, AwayFromZero)
3. 총 델타:                 Σ      = Σ_g Δ_g
4. 적용 방향 (의미별):
     capacity/stat-up  →   final = B + Σ          (ammo, ATK, DEF, HP, crit_dmg, ...)
     time-down         →   final = B - Σ          (charge_time, reload 등 시간축)
```

**핵심**: 합산을 먼저 하지 않고 **그룹 단위로 먼저 반올림 후 합산**. 동일값 중복은 `p × count` 로 먼저 묶고 반올림 1회.

#### 4.4.2 `decimals` 규칙

| 스탯 종류 | decimals | 예 |
|---|---|---|
| 정수형 (Ammo, ATK, DEF, HP) | **0** | `round(6 × 0.6071 × 2, 0) = 7` |
| 차지 시간 (초 단위) | **2** | `round(1 × 0.0463 × 2, 2) = 0.09` |

다른 소수점 단위 스탯 발견 시 이 표 갱신.

#### 4.4.3 예제 1 — 장탄 수 (capacity, decimals=0)

기본 6발, 버프: 60.71% × 2, 64.41% × 1, 73.04% × 1.

```
Δ₁ = round(6 × 0.6071 × 2, 0) = round(7.2852, 0) = 7
Δ₂ = round(6 × 0.6441,     0) = round(3.8646, 0) = 4
Δ₃ = round(6 × 0.7304,     0) = round(4.3824, 0) = 4

final = 6 + (7 + 4 + 4) = 21발
```

#### 4.4.4 예제 2 — 차지 시간 (time-down, decimals=2, cross-caster)

자신의 기본 차지 시간 1초. 버프:
- 자기 기준 차지 속도 ▲ 4.63% × 2, 4.92% × 1 → `B_applicable = 1.0` (자신 native)
- 다른 아군의 "시전자 기준 차지 속도 ▲ 12.74%" (아군의 기본 차지 시간 1.5초) → `B_applicable = 1.5` (시전자 native)

```
Δ₁ = round(1.0 × 0.0463 × 2, 2) = round(0.0926, 2) = 0.09
Δ₂ = round(1.0 × 0.0492,     2) = round(0.0492, 2) = 0.05
Δ₃ = round(1.5 × 0.1274,     2) = round(0.1911, 2) = 0.19

final = 1 - (0.09 + 0.05 + 0.19) = 0.67초
```

**Cross-caster 요점**: legend `scale_base = caster_charge_speed` 인 버프는 적용 기준량이 **시전자의** native 차지 시간. `scale_base = none` 이면 자신의 native. 버프 원문에 "of caster's Charge Speed" 수식어 유무로 분기 (legend v3).

#### 4.4.5 현재 구현 상태

- `OverloadProcessor.CalculateFinalBaseStat` → `CalculateNikkeOverloadBonus` (private): **OL 전용, decimals=0** 으로 이미 위 알고리즘 구현 중. (2026-04-23 Option D 리팩토링 후 `OverloadProcessor` 로 이전 완료 — 아래 §4.4.6 참조.)
- 런타임 버프 (스킬 번역기 출력) 측에 동일 유틸리티 재사용 필요 — 갭 페이즈 1 에서 공용 `BuffSummation` 유틸로 끌어올리거나 `OverloadProcessor` 를 범용화 (사후 리팩토링).
- 차지 시간 (decimals=2) + cross-caster (`B_applicable` 선택) 경로는 **아직 미구현** — 로테이션 시뮬 (갭 페이즈 3) 진입 시 구현.

#### 4.4.6 `OverloadProcessor` 책임 격리 (Option D, 완료 2026-04-23)

SRP (Single Responsibility) 원칙에 따라 OL 합산 로직은 `Stats/OverloadProcessor.cs` 로 일원화 완료:

- **`OverloadProcessor`** — pre-combat native stat 조립. `CalculateFinalBaseStat(nativeStat, olPercents, olFlatSum, decimals)` + 내부 helper `CalculateNikkeOverloadBonus` + `CalculateFlatBonus`.
- **`StatCalculator`** — per-tick 데미지 공식만 담당. `CalculateDamage(in AttackContext)` 단일 진입점.

`Nikke.InitializeFinalStats` 의 4개 호출부 (`FinalBaseAtk/HP/Def/MaxAmmo`) 는 `OverloadProcessor.CalculateFinalBaseStat` 직접 호출. 이전에 `StatCalculator` 에 혼재하던 중복(`CalculatePercentBonus` 포함)은 제거됨.

### 4.5 OL Integer val_type 정규화

`InitializeFinalStats` 말미에서 전투축 OL 옵션 사전집계 시 `Normalize(o)` 로컬 람다로 분기:
```csharp
double Normalize(OverloadOptionDto o)
    => (o.val_type == "Integer") ? o.value / 10000.0 : o.value;
```
- Percent 는 ETL 에서 이미 `/10000` 스케일됨 → 건드리지 않음.
- Integer 는 원시값 (e.g. `StatCriticalDamage=1644`) → 여기서 `/10000` 해서 `0.1644` 로.

---

## 5. 무기 규칙

### 5.1 기본 발사 속도 (`Stats/WeaponStatTable.cs`, ✅ 구현 완료 A3, 2026-04-24)

| WeaponType | 기본 발사 속도 | API |
|---|---|---|
| Assault Rifle | 12 발/sec | `GetBaseFireRate` |
| Machine Gun | 60 발/sec | `GetBaseFireRate` |
| Submachine Gun | 24 발/sec | `GetBaseFireRate` |
| Shotgun | 5/3 ≈ 1.667 발/sec | `GetBaseFireRate` |
| Sniper Rifle | 차지 모드 or 톡톡이 | `GetChargeTiming` (§5.1a) |
| Rocket Launcher | 차지 모드 or 톡톡이 | `GetChargeTiming` (§5.1a) |

비-해당 분기로 호출 시 (AR 에 `GetChargeTiming`, SR 에 `GetBaseFireRate`) `NotSupportedException` 발생 — API 오용 차단.

**§5.1a 차지 무기 타이밍** (`ChargeTiming` readonly struct):
- `MotionDelaySec = 0.03` — 발사 직전 모션 딜레이 (~30ms).
- `FullChargeSec = 1.0` — 풀차지 완료 시간.
- `TapIntervalSec = 0.215` — 톡톡이(no-charge) 발사 간격 (0.21~0.22 중앙값).

현재 SR/RL 공통치 반환. 캐릭터별 편차 확인 시 오버로드 분기 예정.

출처: 사용자 확인 (2026-04-23). `WeaponStatTable` 소비는 로테이션 시뮬 페이즈에서 — 현재는 API 만 준비.

### 5.2 ProperDistanceBonus (B2)

| WeaponType | 적정거리 보너스 | 상태 |
|---|---|---|
| **Rocket Launcher** | **0 (상수)** | ✅ 확정 (사용자 확인) |
| 그 외 전부 | 0.3 (range 내) / 0 (range 밖) | 🚧 실측 검증 미완 |

값은 시뮬 루프가 결정하여 `AttackContext.ProperDistanceBonus` 에 주입. RL 은 **상수 0** 이므로 루프는 RL 분기에서 세팅 자체를 생략.

### 5.3 Collection Effect 라우팅 (`Nikke.BuildAttackContext`)

| WeaponType (정확 문자열) | 주입되는 Collection 필드 | AttackContext 필드 |
|---|---|---|
| `"Assault Rifle"` | `CoreDamageBonus` | `ctx.SumCoreHitBuff` |
| `"Sniper Rifle"` / `"Rocket Launcher"` | `ChargeDamageMultiplier` | `ctx.SumChargeDmgMult` (+ `ctx.ChargeDmgBase = BasicAtkChargeDamage` — JSON per-character) |
| `"Submachine Gun"` / `"Shotgun"` | `NormalAttackMultiplier` | `ctx.SumAttackDmg` |
| `"Machine Gun"` | `MaxAmmoIncreaseRate` | native ammo 곱산 (§4.1 F) |

### 5.4 **Weapon Override 원칙** (중요)

**원본 `WeaponType` 은 캐릭터 라이프사이클 내내 불변.**

`trait_weapon_transformed` 효과 (Snow White, Laplace-treasure, Maxwell, Red Hood Step 3, Snow White: Heavy Arms 등 ≤ 10명 예상) 가 발동하더라도:
- ❌ `weapon_type` 필드 override 금지 — B2 / Collection / ChargeDmgBase 라우팅 오염.
- ✅ **granular field 만 override**: `fire_rate`, `charge_time_secs`, `full_charge_damage_override`, `max_ammo`, `basic_atk_multiplier_override`, `initial_damage_mult`, `dot_damage_mult`.

**근거**: Laplace-treasure 가 버스트 중 "60발/sec" 로 쏘지만 실제 MG 가 되는 것이 아님 — ProperDistanceBonus 는 RL 의 0 을 유지해야 함. `weapon_type` 을 MG 로 바꾸면 0.3 이 올라타서 **원본보다 +30% 인플레** 발생.

**현재 데이터 상태**: `skills_parsed.json` 의 `trait_weapon_transformed` 20건은 override 파라미터가 `EffectBlock.notes` 문자열에 원문 보존 ("Change the weapon in use: Charge Time: 5 sec, ..."). 스키마 1급 확장 (weapon_override 오브젝트) 은 파서 후속 작업 예정 — DATA_SCHEMA §7 참조.

---

## 6. 스킬 번역 경계

스킬 효과는 적용 시점에 따라 두 축으로 분리:

### 6.1 Static modifier (→ `BuildAttackContext` 주입)
상태 독립적이거나 느리게 변하는 값. `Nikke` 엔티티에 캐싱.

예시:
- OL 옵션 전체 (StatCritical, StatCriticalDamage, StatChargeDamage, IncElementDmg, …)
- 큐브 고정 효과 (PartsDamageBonus, PierceDamageBonus)
- 콜렉션 무기별 효과 (CoreDamageBonus, ChargeDamageMultiplier, …)

### 6.2 Runtime trigger (→ 시뮬 루프가 소비)
시간/조건/스택/쿨다운 있는 효과.

예시:
- 풀버스트 중 ATK +50% (`trigger.event=burst_active`)
- 크리 시 스택 쌓기 (`stack_conditions`)
- 부위파괴 시 쿨다운 감소 (`trigger.event=on_hit` + `condition_on=hitting_parts`)
- HP 80% 이하 조건부 버프 (`condition_on=hp_below_pct` + `condition_threshold_pct=80`)

**구분 기준**: legend 의 `trigger.event` 가 `passive` 가 아니거나 / `duration` 이 non-null 이거나 / `stack_conditions` 가 있으면 runtime.

→ **스킬 번역기** (향후 구현) 는 `skills_parsed.json` → 두 버킷 중 하나로 라우팅:
- static 이면 `Nikke` 의 `_olXxx` 류 사전집계 필드와 같은 위치에 추가 주입
- runtime 이면 `SkillRuntime` (예정) 이 소비할 `TriggerDef` / `BuffInstance` 로 변환

### 6.3 Trait 처리

legend INV-9a: `action=grant_trait` 의 stat 화이트리스트:
- `trait_pierce` — 관통 특성 획득
- `trait_true_dmg_conversion` — 조건부 true damage 변환 (`required_token` 에 조건 원문)
- `trait_weapon_transformed` — 무기 파라미터 덮어쓰기 (§5.4)

C# 런타임 측에서 각각 독립 플래그로 관리.

---

## 7. 변경 가이드

| 변경 종류 | 업데이트 위치 |
|---|---|
| 데미지 브래킷 재정의 | 이 파일 §3, `StatCalculator.CalculateDamage` |
| 무기 발사 속도 값 | 이 파일 §5.1, `Stats/WeaponStatTable.cs` |
| 차지 무기 타이밍 (모션/풀차지/탭) | 이 파일 §5.1a, `Stats/WeaponStatTable.cs` (`ChargeTiming` struct) |
| 크리 RNG / 확률 효과 샘플링 | 이 파일 §3.4, `Stats/IRandomSource.cs` (`CritSampler.RollCrit`) |
| Native stat 조립식 | 이 파일 §4, `Nikke.InitializeFinalStats` |
| Collection 라우팅 | 이 파일 §5.3, `Nikke.BuildAttackContext` |
| OL type 추가/변경 | `DATA_SCHEMA.md` §3, `Nikke.InitializeFinalStats` |
| 큐브 TID / 레벨 값 | `Data/Constants/CubeSkillTable.cs` (하드코딩 dict), `DATA_SCHEMA.md` §5.1 |
| CSV 레이아웃 변경 | 이 파일 §4.3, `StatTable.Initialize` row/col 범위 |
