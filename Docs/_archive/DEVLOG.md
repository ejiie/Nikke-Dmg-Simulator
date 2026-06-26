# DEVLOG

> **역할**: 페이즈 현황, 결정 로그(경량 ADR), 열린 질문, 차기 백로그.
> **업데이트**: 페이즈 종료 시 + 설계 결정 발생 시. append-only (수정 시 취소선 유지).

---

## A. 페이즈 현황

### 완료
- [x] **B1** — `StatTable.Initialize` 미호출 (WPF `App.OnStartup` 에서 호출 추가, CSV 경로 `Database/processed/stat_table.csv`)
- [x] **B3** — `Nikke` 생성자 NRE 내성 (null guard + `_overloadStats`/`_equipments` 정규화 필드)
- [x] **B4** — `JsonProvider` nullable/예외 체인 정리 (`where T : class`, 타입별 구체 예외, InnerException 보존)
- [x] **M1** — 15개 .cs 파일 cp949 → UTF-8 일괄 변환 (U+FFFD 오염 복구 포함)
- [x] **H1** — 큐브 `MaxHpBonusRate` 를 `effectiveNativeHP` 곱산에 반영
- [x] **H2** — MG `MaxAmmoIncreaseRate` native ammo 곱산 + `BuildAttackContext` 팩토리 신설 (무기별 Collection 라우팅)
- [x] **H3** — OL 전투축 주입: `StatCritical`/`StatCriticalDamage`/`StatChargeDamage`/`IncElementDmg` → `ctx.BaseCritRate`/`SumCritDmg`/`SumChargeDmgAdd`/`SumStrongElem`. Integer `/10000` 정규화, `StatMaxAmmo` → `StatAmmoLoad` dead code 버그 수정, `AttackContext.BaseCritRate` 필드 신설 (기본 0.15)
- [x] **A1** — 최소 대미지 규칙 교정: `Math.Max(1.0, ...)` (환각) 제거. "`effectiveDef ≥ FinalAtk` → 즉시 `1.0` 반환 (중간 곱연산 미경유)" 분기로 재작성
- [x] **A2** — True Damage 축 신설: `AttackContext.IsTrueDamage` + `AttackContext.SumTrueDmgBuff` 필드. `StatCalculator` 에 `effectiveDef := 0` + `B3 += SumTrueDmgBuff` 분기. `Nikke.BuildAttackContext` 에서 `CurrentCubeEffect.TrueDamageBonus` → `ctx.SumTrueDmgBuff` 주입
- [x] **A4** — `OverloadProcessor` 중복 정리 (Option D): `CalculateFinalBaseStat` / `CalculateNikkeOverloadBonus` 를 `StatCalculator` 에서 `OverloadProcessor` 로 이전. `StatCalculator` 는 `CalculateDamage` 전용으로 격리. `Nikke.InitializeFinalStats` 호출부 4곳 전환
- [x] **A5** — `RootDto.cs` roster 주석 `key = name_code` 로 교정
- [x] **A3** — `WeaponStatTable` 정적 클래스 신설 (`Stats/WeaponStatTable.cs`): WeaponType 상수 + `GetBaseFireRate` (AR=12 / MG=60 / SMG=24 / SG=5/3) + `GetChargeTiming` (SR/RL, `ChargeTiming` struct: 모션 0.03s / 풀차지 1.0s / 탭 0.215s) + `IsChargeWeapon`. 비-해당 무기 호출 시 `NotSupportedException` 로 미스매치 차단
- [x] **A6** — Crit RNG 추상화 (`Stats/IRandomSource.cs`): `IRandomSource` 인터페이스 + `SystemRandomSource.Instance` (Random.Shared wrap, 스레드 안전) + `CritSampler.RollCrit(rng, baseCritRate)` 헬퍼 (clamp [0,1] 방어). **고정 시드 주입 경로 원천 차단** — 시뮬 루프가 `ctx.IsCrit = CritSampler.RollCrit(...)` 로 소비 예정 (로테이션 시뮬 페이즈에서 연결). ※ 이전 턴 요약에서 "A5 = 크리 RNG" 로 오기재되어 번호 A6 로 재할당 (DEVLOG 역사 보존 원칙)

### 진행 중
- [x] **문서화 초판** (ARCHITECTURE / DATA_SCHEMA / DEVLOG) — 2026-04-22
- [x] **문서화 2차 교정** (환각 제거, 실제 코드/데이터 재조사 후 재작성) — 2026-04-23

### 병렬 로드맵 (파서 보강과 독립 실행 가능 — 2026-04-23 확정)

**추천 순서**:
1. [x] **A1 최소 대미지 규칙 교정** — `StatCalculator.CalculateDamage` 에 "DEF ≥ ATK → 즉시 1 반환" 분기 (중간 곱연산 미경유). ✅ 완료 (2026-04-23)
2. [x] **A2 `IsTrueDamage` + `SumTrueDmgBuff` 신설** — `AttackContext` 필드 2개 + `StatCalculator` 분기 + `Nikke.BuildAttackContext` 에서 `CurrentCubeEffect.TrueDamageBonus` 주입. ✅ 완료 (2026-04-23)
3. [x] **A3 `WeaponStatTable` 정적 클래스** — AR=12 / MG=60 / SMG=24 / SG=5/3 / SR·RL 차징 타이밍 헬퍼. ✅ 완료 (2026-04-24)
4. [x] **A4 `OverloadProcessor` 중복 제거 (Option D)** — OL 로직을 `OverloadProcessor` 로 이전, `StatCalculator` 는 대미지 공식 전용화. ✅ 완료 (2026-04-23)
5. [x] **A5 `RootDto.cs` 주석 드리프트 수정** — `roster` 주석 `key=slug` → `key=name_code`. ✅ 완료 (2026-04-23)
5b. [x] **A6 Crit RNG 추상화** — `IRandomSource` + `SystemRandomSource` + `CritSampler.RollCrit`. 시뮬 루프가 `ctx.IsCrit` 세팅 전 호출. **고정 시드 금지** 정책 코드화. ✅ 완료 (2026-04-24)
6. **B1 M10 Snow White 골든 회귀 테스트** — xUnit/NUnit 프로젝트 골격 + 고정 RootDto 주입기 + Assert 하니스 (사용자 실측 병렬 대기). ※ `IRandomSource` 의 기댓값-수렴 검증 패턴도 여기에 합류 예정.
7. **B2 장비 테이블 주입** — 사용자가 tier × level → HP/ATK/DEF 표 제공 시 `StatTable.GetEquipmentStats` 스텁 교체.
8. **B3 반올림 모드 확정** — 사용자 실측 후 `Math.Floor` 1줄 교체.
9. **B4 `CubeSkillTable` placeholder 수치 교정** — TID 1000318-1000321 실측 교체.
10. **C1 `StatChargeTime` 시간축 합산 규칙 설계** — 로테이션 tick 계산기 선구현.
11. **C2 `StatAccuracyCircle` 스코프 결정** — 무시 정당화 문서화.
12. **C3 WPF 디버그 덤프 패널** — `FinalBase*` / `BuildAttackContext()` 가시화.

### 대기 (우선순위순)
- [ ] **파서 보강** (사용자 진행 예정)
  - [ ] `trait_weapon_transformed` notes → `weapon_override` granular 스키마 파싱 (20건)
  - [ ] 70 bailout slot 재파싱 (57명)
  - [ ] `filter_token` (62종) / `required_token` (184종) 상위 enum화 + 잔여 dispatch table 설계
  - [ ] `distrib_dmg`(21) / `sequential_dmg`(7) formula_bracket 지정
  - [ ] 재분류: `julia-treasure` s2, `ein` s1 (trait_weapon_transformed 오용)
- [ ] **M10** — Snow White 기준 골든 데이터셋 회귀 테스트
- [ ] **B2** — 장비 테이블 확보 + 주입 (사용자 직접 data 추가 예정)
- [ ] **갭 페이즈 1**: 스킬 번역기 (`SkillParsed` → static modifier / runtime trigger 분리)
- [ ] **갭 페이즈 2**: 스킬 런타임 (triggers / conditions / stacks / cooldowns / timeline)
- [ ] **갭 페이즈 3**: 로테이션 시뮬 (무기별 발사 타이밍, 풀버스트 사이클)

---

## B. 결정 로그 (경량 ADR)

형식: **날짜 · 컨텍스트 · 결정 · 근거**. 번복 시 새 엔트리 추가 + 원본은 취소선.

---

### 2026-04-22 · `weapon_type` override 금지
- **컨텍스트**: `trait_weapon_transformed` 20건(Snow White, Laplace-treasure 등)의 JSON 스키마 확장 설계. 초안은 `"weapon_type": "Machine Gun"` 같은 무기 타입 교체 필드 포함.
- **결정**: `weapon_type` 필드 **전면 제거**. granular field 만 (fire_rate / charge_time_secs / full_charge_damage_override / max_ammo / basic_atk_multiplier_override / initial_damage_mult / dot_damage_mult).
- **근거**:
  - B2 `ProperDistanceBonus` 오염 (RL 원본 0 → MG override 0.3 → **+30% 인플레**)
  - Collection effect 라우팅 오염 (RL `ChargeDamageMultiplier` ↔ MG `MaxAmmoIncreaseRate` 교체)
  - Laplace-treasure 의 "60발/sec" 는 실제 MG 가 되는 것이 아니라 발사 속도만 MG-like. B2/Collection/ChargeDmgBase 는 원본 RL 기준 유지가 정답.
- **결과**: 원본 `WeaponType` 은 캐릭터 라이프사이클 내내 불변 보증. 관련 규칙 `ARCHITECTURE.md §5.4`.

---

### 2026-04-22 · 무기 발사 속도 C# 하드코딩
- **컨텍스트**: AR 12 / MG 60 / SMG 24 / SG (5/3) / SR·RL 차징모드 — 어디 둘지.
- **결정**: C# 측 `WeaponStatTable` 정적 클래스 (예정). JSON 에 넣지 않음.
- **근거**:
  - 게임 물리 상수 성격. 178명 전부 동일값 중복 저장 무의미.
  - 차징 무기의 "full vs tap" 모드 분기는 JSON 구조체화보다 C# 메서드 하나가 읽기 쉬움.
  - 튜닝 주기 길다. ETL 재돌 대상이 아님.

---

### 2026-04-22 · OL Integer `val_type` 정규화는 C# 책임
- **컨텍스트**: ETL (`blabla_merger.py`) 이 `val_type == "Percent"` 인 경우만 `/10000` 스케일. `Integer` (StatCriticalDamage=1644 등) 는 원시값 그대로.
- **결정**: C# `Nikke.InitializeFinalStats` 의 `Normalize(o)` 로컬 람다가 `Integer` 에 한해 `/10000` 나눔.
- **근거**:
  - ETL 이 모든 타입을 동일 스케일로 정규화하면 `val_type` 필드 존재 의미 소멸. 값 해석은 소비자 책임.
  - C# 측 단일 진입점 (`Normalize`) 에서 규칙 일원화 → 드리프트 방지.

---

### 2026-04-22 · `StatMaxAmmo` → `StatAmmoLoad` 버그 수정
- **컨텍스트**: `Nikke.InitializeFinalStats` 의 OL ammo 합산이 `type == "StatMaxAmmo"` 로 필터. 실제 JSON type 은 `"StatAmmoLoad"`.
- **결정**: `"StatAmmoLoad"` 로 교체. 모든 OL 장탄수 옵션이 그동안 무시되고 있었음 (72건 dead code).
- **근거**: 데이터-코드 불일치. 실측 검증으로 확정.

---

### 2026-04-22 · `StatMaxHP` OL LINQ 유지
- **컨텍스트**: 현재 JSON 에 `StatMaxHP` 타입 0건. LINQ 체인 제거할지.
- **결정**: 유지.
- **근거**: 실행 비용 0 (LINQ deferred + Empty), 미래 데이터 추가 시 자동 편입. 제거하면 추가 시점에 복구 필요.

---

### 2026-04-22 · `trait_weapon_transformed` 스키마 확장 (C# 하드코딩 X)
- **컨텍스트**: 20건 전부 override 파라미터가 `notes` 문자열로 박힘. C# `switch(slug)` vs JSON 스키마 확장.
- **결정**: JSON 스키마 확장 + 파서 notes 2차 파싱. C# 는 일반 메커니즘만 (`ActiveWeaponOverride` 필드 + "override 있으면 override 우선" 단일 규칙).
- **근거**:
  - 20건뿐이지만 `switch(slug)` 는 데이터 추가마다 코드 릴리스. 안티패턴.
  - notes 문자열이 규칙적 패턴 ("Charge Time: X sec, Damage Y% ...") → 정규식으로 전수 추출 가능.
  - 예외 2건 (`julia-treasure` s2, `ein` s1) 은 애초 오분류 → stat 재분류가 정답.

---

### 2026-04-22 · Taunt 는 런타임 target enum 레벨 처리
- **컨텍스트**: Taunt 효과 대부분 보스에 적용, 일반 몹은 확률 적용.
- **결정**: 스킬 번역기 단계에서 특별 처리 X. 시뮬 루프의 target 선정 로직에서 "보스 우선 + 확률 apply" 규칙으로 흡수.
- **근거**: Taunt 는 효과 본체가 아닌 target 선정 메커니즘. 데이터 스키마 확장 불필요.

---

### 2026-04-22 · `AttackContext.BaseCritRate` 필드 신설
- **컨텍스트**: 크리 확률 = 기본 15% + OL `StatCritical` + 버프 합산. 현재까지 `IsCrit` 플래그만 있고 확률값 자리 없음.
- **결정**: `AttackContext` 에 `double BaseCritRate` 필드 추가. 생성자 기본값 0.15.
- **근거**: 시뮬 루프의 RNG 가 이 값과 비교해서 `IsCrit` 를 세팅하는 구조. 값이 struct 에 있어야 runtime / static modifier 양쪽에서 합산 가능.

---

### 2026-04-22 · 문서화 우선순위 (정적 + 동적 3파일)
- **컨텍스트**: 앞만 보고 달려온 상태 — M10 / 파서 보강 / 갭 페이즈 진입 전에 현재까지의 결정을 박제할 필요.
- **결정**: `docs/ARCHITECTURE.md` (정적 공식/경계) + `docs/DATA_SCHEMA.md` (정적 스키마) + `docs/DEVLOG.md` (동적 로그) 3파일.
- **근거**: 파일 수 늘리면 드리프트 위험 ↑, 너무 적으면 업데이트 주기 충돌. 정적/동적 분리 + 스키마 독립이 최소 분할.

---

### 2026-04-23 · `OverloadProcessor` 중복 정리 — Option D 실행 완료 ✅
- **컨텍스트**: `Stats/OverloadProcessor.cs::CalculatePercentBonus` 와 `Stats/StatCalculator.cs::CalculateNikkeOverloadBonus` 가 동일 로직을 중복 구현 중. `Nikke.cs` 는 후자만 사용, 전자는 dead code.
- **옵션**:
  - **A: `OverloadProcessor` 삭제** — 가장 단순. 모든 OL 로직을 `StatCalculator` 에 존속.
  - **B: `OverloadProcessor` 가 `StatCalculator` 호출하게 위임** — 인터페이스는 이원화, 구현은 일원화. indirection 추가.
  - **C: 현상 유지** — 중복, 드리프트 리스크. 비추천.
  - **D (권고): OL 로직을 `OverloadProcessor` 로 이동, `StatCalculator` 는 대미지 공식 (`CalculateDamage`) 전용화** — `Nikke.InitializeFinalStats` 가 `OverloadProcessor.CalculateFinalBaseStat` 를 직접 호출하게 변경.
- **분석**:
  - **성능**: 네 옵션 모두 `static`, inline 가능. 차이 0.
  - **SRP (단일 책임 원칙)**: `StatCalculator` 는 현재 (1) OL 기초 스탯 합산 (pre-combat) + (2) 대미지 공식 (per-tick combat) 두 가지를 혼재. 개념적으로 이질적.
    - OL 합산은 **전투 시작 전 native 스탯 조립** 단계. `InitializeFinalStats` 에서만 호출.
    - 대미지 공식은 **tick 마다 호출** 되는 hot path.
  - **확장성**: 갭 페이즈 1 (스킬 번역기) 에서 **런타임 버프 합산** 에도 동일 니케식 합산 규칙 재사용 필요 (§4.4). 이때 재사용 대상이 `OverloadProcessor` 인지 `StatCalculator` 인지 명확해야.
    - OL 전용 클래스로 격상 (D) 하면 네이밍 혼동 없이 범용 `BuffSummation` 유틸로 진화시키기 쉬움 (class rename 가능).
  - **비용**: Nikke.cs 의 `CalculateFinalBaseStat` 호출 4곳을 `OverloadProcessor.CalculateFinalBaseStat` 로 find-replace. `StatCalculator` 의 OL 메서드 2개 (`CalculateFinalBaseStat`, `CalculateNikkeOverloadBonus`) 를 `OverloadProcessor` 로 이동. 총 20줄 수준 리팩토링.
- **권고**: **Option D**. SRP + 미래 범용화 경로 + 저비용. 부수 효과로 §4.4 의 `StatCalculator` vs `OverloadProcessor` 주의 문구 자체가 사라짐.
- **결정**: 사용자 "D로 진행" 확정 (2026-04-23).
- **실행 결과** (2026-04-23):
  1. `OverloadProcessor.cs` 전면 재작성 — `CalculateFinalBaseStat` (public) + `CalculateNikkeOverloadBonus` (private helper) + 기존 `CalculateFlatBonus` 유지. Dead code `CalculatePercentBonus` 제거. SRP docstring 추가.
  2. `StatCalculator.cs` 에서 OL 메서드 2개 제거. `using System.Collections.Generic` / `using System.Linq` 제거. class docstring 에 Option D 책임 분리 명시.
  3. `Nikke.cs::InitializeFinalStats` 호출부 4곳 (`FinalBaseAtk/HP/Def/MaxAmmo`) 을 `OverloadProcessor.CalculateFinalBaseStat` 로 전환.
  4. `MainWindow.xaml.cs` 스모크 테스트 callsite 를 새 API (`CalculateFinalBaseStat` → `finalAtk - testNativeAtk`) 로 마이그레이션. `using System.Linq` 추가.
  5. `ARCHITECTURE.md` §2 네임스페이스 맵 + ASCII 다이어그램 + §4.4.5 / §4.4.6 갱신 (중복 주의 문구 삭제, Option D 완료 명시).
- **검증**: `dotnet build` → 0 오류 (잔여 nullability 경고는 Option D 와 무관).

---

### 2026-04-23 · 버프 합산 규칙 (니케식) — OL / 스킬 공통
- **컨텍스트**: `StatChargeTime` (56건) 시간축 주입 규칙 질의. 사용자가 일반 버프 + 차지 시간 전용 규칙을 설명.
- **결정**: 모든 %-버프 (OL / 스킬) 에 공통 적용되는 합산 공식을 ARCHITECTURE.md §4.4 에 박제.
  1. 동일값 버프 그룹핑 (`GroupBy(value)`)
  2. 그룹별 델타 `Δ_g = Round(B_applicable × p_g × count_g, decimals, AwayFromZero)`
  3. 총 Σ = Σ_g Δ_g
  4. 의미별 적용: capacity/stat-up → `final = B + Σ`, time-down → `final = B - Σ`
- **decimals 규칙**: 정수형 스탯 (Ammo/ATK/DEF/HP) = 0, 차지 시간 = 2.
- **Cross-caster**: legend `scale_base = caster_*` 인 버프는 `B_applicable = 시전자 native`. `scale_base = none` 이면 자신 native.
- **근거**: 사용자 실측 지식. 동일값 중복 버프를 합산 전에 `p × count` 로 묶어 반올림 1회만 적용하는 것이 핵심 (합산 후 반올림과 결과가 다름).
- **현재 구현**: `StatCalculator.CalculateNikkeOverloadBonus` 가 decimals=0 경로만 이미 구현. decimals=2 / cross-caster / time-down 방향은 로테이션 시뮬 페이즈 (갭 페이즈 3) 에서 신규 구현.
- **참조**: ARCHITECTURE.md §4.4.1~§4.4.5 (예제 2건 포함).

---

### 2026-04-23 · 크리 RNG 정책 — 고정 시드 절대 금지
- **컨텍스트**: M10 설계 시 결정성 vs 분포 검증 사이 절충 질의.
- **결정**: **고정 시드 사용 금지**. `Random()` 기본 생성자 (시스템 시각 기반) 또는 별도 randomness 함수 주입 구조.
- **근거**: 크리 확률은 **tick 별 독립 베르누이 시행** (§3.4). 고정 시드 도입 시:
  - 동일 시뮬레이션이 동일 결과 → 확률 분포 편향 덮어버림
  - 실제 게임 내 랜덤성을 왜곡
  - 버그 reproducibility 를 위해 쓰기엔 시뮬 본질 목적과 상충
- **테스트 전략**: M10 에서 대수의 법칙 기반 회귀 — N tick 시뮬 평균 DPS 가 기대값 ±ε 내에 수렴하는지 검증 (고정 시드 대신 반복 횟수 + 허용 오차).
- **구현 힌트**: `IRandomSource` 인터페이스 혹은 `Func<double>` 주입. production 은 `Random.Shared.NextDouble`, 테스트는 stub 으로 대체 — 단 **stub 도 시드 기반이면 안 됨**.
- **후속 실행 (2026-04-24, A6)**: `Stats/IRandomSource.cs` 신설. `IRandomSource` 인터페이스 + `SystemRandomSource.Instance` (Random.Shared wrap) + `CritSampler.RollCrit(rng, baseCritRate)` 헬퍼. `baseCritRate` clamp 방어. docstring 에 "고정 시드 금지" 정책 박제. 사용처 (시뮬 루프) 는 로테이션 페이즈에서 연결 — 현재는 API 만 준비.

---

### 2026-04-24 · A3 `WeaponStatTable` 신설
- **컨텍스트**: 병렬 로드맵 3번. 로테이션 시뮬 (갭 페이즈 3) 진입 전 무기별 발사 속도 / 차지 타이밍을 정적 테이블화할 필요.
- **결정**: `Stats/WeaponStatTable.cs` 신설.
  - `public const string AssaultRifle/MachineGun/SubmachineGun/Shotgun/SniperRifle/RocketLauncher` — JSON staticInfo.weapon 정확 문자열을 코드 상수로 고정 (오타 방지).
  - `GetBaseFireRate(weaponType) : double` — AR=12.0 / MG=60.0 / SMG=24.0 / SG=5/3. SR/RL 호출 시 `NotSupportedException` 으로 API 오용 차단.
  - `GetChargeTiming(weaponType) : ChargeTiming` — SR/RL 전용. `ChargeTiming` readonly struct (`MotionDelaySec=0.03`, `FullChargeSec=1.0`, `TapIntervalSec=0.215`). 현재는 전 차지 무기 공통값; 캐릭터별 편차 확인 시 오버로드 분기 예정.
  - `IsChargeWeapon(weaponType) : bool` — SR/RL 판별 헬퍼.
- **원칙**: 이 테이블은 **원본 무기 기준** 값만 반환. `trait_weapon_transformed` 의 granular override (fire_rate / charge_time_secs 등) 는 `Nikke.cs` 측 일시 플래그로 처리 — ARCHITECTURE.md §5.4 Weapon Override 원칙 준수.
- **참조**: ARCHITECTURE.md §5.1 / §5.1a.

---

### 2026-04-23 · A1 + A2 구현 (최소 대미지 규칙 + True Damage 축)
- **컨텍스트**: 병렬 로드맵 1, 2번. 파서 보강과 독립.
- **A1 결정**: `StatCalculator.CalculateDamage` 초입에서 `effectiveDef >= FinalAtk` 체크 → `return 1.0`. `Math.Max` 형태 폐기.
- **A2 결정**:
  - `AttackContext` 에 `bool IsTrueDamage` + `double SumTrueDmgBuff` 필드 추가. 기본값 `false` / `0` (struct auto-init 으로 충족).
  - `StatCalculator` 에서 `effectiveDef = ctx.IsTrueDamage ? 0.0 : ctx.FinalDef`, B3 누적부에 `if (ctx.IsTrueDamage) b3 += ctx.SumTrueDmgBuff`.
  - `Nikke.BuildAttackContext` 에서 `ctx.SumTrueDmgBuff += cube.TrueDamageBonus` 로 큐브 축 소비처 해소.
- **근거**:
  - A1: 환각 제거 (2026-04-23 공식 교정 로그 참조). DEF ≥ ATK 상황에서 버프 누적해도 1 로 고정되는 실제 게임 거동 정합.
  - A2: `CubeEffectDto.TrueDamageBonus` 가 데이터 구조에만 있고 소비처 없던 dead field 해소. 공격 종류 플래그 패턴 (`IsPierceHit → SumPierceDmg`) 과 동형.
- **한계**: `ctx.IsTrueDamage` 를 시뮬 루프/스킬 번역기가 언제 세팅하는지는 아직 결정 안 됨. 해당 브리지는 갭 페이즈 2.
- **검증**: `dotnet build` 통과 (0 오류, 기존 34 nullability 경고 유지).

---

### 2026-04-23 · 대미지 공식 환각 교정 (§3 전면 재작성)
- **컨텍스트**: ARCHITECTURE.md §3 재검토 시 사용자가 4건 환각 지적:
  1. §3.1 최종식 `finalDmg = floor( max(1, FinalAtk − FinalDef) × B2 × B3 × B4 × B5 × SkillMultiplier × ChargeMultiplier )` → legend 원식과 형식이 다름. 과거 파싱 작업 맡긴 LLM 의 hallucination.
  2. "깡뎀 최소 1 보정" 해석 틀림 — 실제 게임: `FinalDef ≥ FinalAtk` 면 최종 대미지가 어떤 조합이든 **1 로 고정** (중간 곱연산 경유 X).
  3. `ChargeDmgBase = 잠정 2.5` 는 환각. `nikke_merged_db_returned.json` 의 `roster[nc].static.basicAttack.chargeDamage` 에 per-character 값 이미 존재 (대부분 2.5, 일부 3.5 등).
  4. `CubeEffectDto.TrueDamageBonus` 를 "미구현 별도 공식" 으로 서술 → 실제로는 **트루 대미지 판정 시만 적용되는 조건부 B3-유사 증가 버프**.
- **결정**:
  - §3.1: legend 공식을 권위 형식으로 명시. `max(1, ...)` 해석 삭제, "DEF≥ATK → 1 고정" 규칙 박제. 반올림/내림 모드는 사용자 실측 검증 대기.
  - §3.3: `ChargeDmgBase` 는 JSON `basicAttack.chargeDamage` per-character 로 명시. `Nikke.BuildAttackContext` 의 SR/RL 분기 하드코딩 `2.5` 도 `BasicAtkChargeDamage` 로 코드 수정.
  - §3.4: 크리 확률은 tick 별 RNG 샘플링 (기댓값 평균화 아님) 명시.
  - §3.5: 트루 대미지 = "적 DEF=0 인 공격". 공식 자체는 B2~B5 동일. `TrueDamageBonus` 는 `IsTrueDamage` 플래그 시 적용되는 조건부 합산 축으로 재정의.
- **코드 수정**:
  - `Nikke.cs` line 262: `ctx.ChargeDmgBase = 2.5;` → `ctx.ChargeDmgBase = BasicAtkChargeDamage;`
  - `StatCalculator.cs` `ChargeDmgBase` 필드 주석에서 "예: 스나 2.5" 제거, "JSON per-character" 로 교체.
  - `StatCalculator.CalculateDamage` 의 `Math.Max(1.0, FinalAtk − FinalDef)` 는 아직 손대지 않음 — 실측 검증 후 "DEF≥ATK → 즉 1" 분기로 재작성 예정 (DEVLOG §C 열린 질문).
- **근거**:
  - legend (`DataPipeline/schema/skill_schema_legend.txt` §대미지 공식) 이 ground truth.
  - `basicAttack.chargeDamage` 는 이미 `Nikke.cs:108` 에서 `BasicAtkChargeDamage` 로 캐싱되고 있었음에도 switch 에서 2.5 로 덮어씀 — 데이터 무시 버그.
  - "깡뎀 min 1" vs "최종 min 1" 해석차는 버프 누적 상황에서 수백배 대미지 차이 발생 가능 (DEF≥ATK 상태로 B2/B3 버프 쌓이면 min 1 × 모든배율 vs 그냥 1).

---

### 2026-04-23 · 문서 2차 교정 (환각 제거)
- **컨텍스트**: 초판 문서에 환각 발견. 사용자 지적:
  - `stat_table.csv` 출처 = 사용자 직접 수집 (스크립트 없음)
  - `prydwen_clean.json` 생성자 = `prydwen_cleaner.py` (초판은 `prydwen_scraper.py` 로 오기)
  - `final_mapping.json` 생성자 = `auto_mapper.py` (초판은 "매핑 스크립트" 로 얼버무림)
  - "이 외에도 환각 현상 종종 발견됨. 전체 코드를 자세히 읽고 다시 작성 바랄게."
- **결정**: 실제 `DataPipeline/{crawler,etl,schema}/*.py` + `Database/{raw,processed}/*` + C# `Data/Dto/*.cs` + `Data/Constants/CubeSkillTable.cs` + `Stats/StatTable.cs` + `schema/skill_schema_legend.txt` 전수 재조사 후 ARCHITECTURE / DATA_SCHEMA 재작성.
- **근거**: 문서가 ground truth 역할을 하려면 일단 참이어야 함. 드리프트보다 환각이 더 치명적.
- **재조사로 확인된 추가 오류**:
  1. `nikke_merged_db_returned.json` 의 `roster` 키는 **`name_code` (numeric string)** — 초판은 `slug` 로 오기 (`RootDto.cs` 주석도 동일 오류)
  2. OL type 목록 누락: `StatChargeTime` (56건, Percent, 시간축) / `StatAccuracyCircle` (44건, Percent, DPS 스코프 외) — 총 10종이 존재
  3. `StatDef` 건수 = 38 (초판 "—" 표기)
  4. `CubeSkillTable` 은 CSV 아닌 **하드코딩 딕셔너리** (TID 1000313-1000321)
  5. `CubeSkillTable` 의 파츠/관통/트루/Vigor 수치는 코드 주석상 **"예시 수치"** 상태 (실측 미확보)
  6. `CollectionEffectTable` 은 별도 파이프라인이 아닌 `StatTable.Initialize` 내부에서 `RegisterEffect` 호출로 채워짐
  7. `formula_bracket` enum 정확 값 = `b2_crit_core` / `b3_attack_dmg` / `b4_dmg_taken` / `b5_strong_elem` / `coeff_charge_add` / `coeff_charge_mult` / `null` (초판은 `B2`/`B3` 등 오기)
  8. `TargetType` 에 `most_injured_ally` 누락, `TargetFilter` 에 `highest_max_hp` / `same_element_code` 등 누락
  9. `stack_conditions` + `stack_mode` (cumulative/replace) + `stack_trigger` 섹션 누락
  10. `OverloadProcessor` 클래스가 존재하나 현재 `Nikke.cs` 에서 미사용 (중복 로직) — 정리 대상 후보
  11. `StatTable` CSV 레이아웃은 행/열 범위가 특정 (Bond 3-42/26-36, Level 6-1005/0-24, Collection 49-64, Cube break at lv ≥ 20)
  12. `GetCoreAppliedStats` 의 gradeFlat: HP=3000·grade / ATK=20·grade / DEF=100·grade
  13. 콘솔 보너스: common(1001)=HP·450, class(1101-1103)=HP·750+DEF·5, mfr(1201-1205)=ATK·25+DEF·5
  14. INV-11 v3 에서 폐지됨 (초판 미반영)
- **결과**: ARCHITECTURE.md / DATA_SCHEMA.md 는 실제 코드를 루트로 한 권위 참조. 이 로그 이후 수정은 본 DEVLOG 신규 엔트리로 추적.

---

## C. 열린 질문 (우선순위순)

- [x] ~~**`ChargeDmgBase` 실측**: SR/RL 기본 차지 배율 잠정 2.5.~~ → 2026-04-23 해소: JSON `basicAttack.chargeDamage` per-character 로 확정.
- [x] ~~**`distrib_dmg` / `sequential_dmg` 브래킷 위치**~~ → 2026-04-23 해소: 의미에 따라 이분법 — **버프(`action=buff/debuff`)** 면 legend 공식 그대로 (distrib_dmg → B4, sequential_dmg → B3 sub-type). **대미지 부여(`action=deal_damage`)** 면 스킬 계수 위치 (× 계수), `formula_bracket = null` (INV-2). 파서 측 lookup 은 action 필드로 자동 분기 가능.
- [x] ~~**크리 RNG 시드 정책**~~ → 2026-04-23 결정: **고정 시드 절대 금지**. 시드 없는 `Random` 또는 별도 randomness source 함수 주입 (아래 결정 로그 참조).
- [ ] **최종 대미지 반올림/내림/올림 모드**: 현재 `Math.Floor`. 게임 실측으로 확정 필요 (사용자 실험 예정).
- [x] ~~**최소 대미지 규칙 구현 교정**~~ → A1 완료 (2026-04-23)
- [x] ~~**`IsTrueDamage` 플래그 + `SumTrueDmgBuff` 필드 신설**~~ → A2 완료 (2026-04-23). 스킬 측에서 `IsTrueDamage` 를 세팅하는 트리거 (`trait_true_dmg_conversion` + `required_token`) 연결은 갭 페이즈 2 에서.
- [x] ~~**OL `StatDef` 건수**~~ → 이미 DATA_SCHEMA.md §3.1 에서 **38건** 으로 확정 기록됨. 이 DEVLOG 엔트리 자체가 stale — 2026-04-23 해소.
- [x] ~~**`favorite_item_lv` 15 고정 조건**~~ → 2026-04-23 해소: `-treasure` slug = 애장품 니케. 애장품은 소장품 15레벨 필요. 따라서 `slug.Contains("treasure") ⇒ favorite_item_lv = 15` 규칙은 정당. 현 구현 유지.
- [ ] **`CubeSkillTable` placeholder 수치**: TID 1000318-1000321 (Parts/Pierce/True/Vigor) 의 skillLevel 1/4/7 값이 코드 주석상 "예시 수치". 실측값 확보되는 대로 하드코딩 dict 교체 (점진적 업데이트 방식).
- [x] ~~**`OverloadProcessor` 중복 정리**~~ → A4 완료 (2026-04-23). Option D 실행: OL 로직을 `OverloadProcessor` 로 일원화, `StatCalculator` 는 `CalculateDamage` 전용. 상세는 상단 결정 로그 + `ARCHITECTURE.md` §4.4.6 참조.
- [ ] **`StatChargeTime` (56건) 시간축 주입 시점**: 규칙은 2026-04-23 결정 로그 "버프 합산 규칙" 로 확정 (decimals=2, time-down, cross-caster 지원). 코드 구현은 로테이션 시뮬 페이즈.
- [x] ~~**`StatAccuracyCircle` (44건) 처리**~~ → 2026-04-23 해소: 대미지 축 영향 **없음**. 명중률 관련은 보류, 추후 특수 기믹 등장 시 재검토.
- [x] ~~**`RootDto.cs` roster 주석 수정**~~ → 2026-04-23 해소: `RootDto.roster` 주석 `key = name_code (numeric string)` 로 교정.

---

## D. 작업 규칙 (지속)

- **파일 인코딩**: 모든 .cs UTF-8 고정. Edit 도구로 cp949 파일 건드리면 U+FFFD 오염 재발 위험 (M1 사건 참조).
- **커밋 전**: 관련 DEVLOG 엔트리 추가 권장.
- **`ARCHITECTURE.md` / `DATA_SCHEMA.md` 변경**: 반드시 DEVLOG 에 결정 로그 남기기.
- **결정 번복**: 원 엔트리를 삭제하지 말고 취소선 + 새 엔트리 + 교차 참조.

---

## E. 번복된 결정 (참고용)

_(없음 — 첫 엔트리)_
