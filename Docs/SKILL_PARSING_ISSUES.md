# SKILL_PARSING_ISSUES — v4 재파싱 후 남은 두 문제

> 2026-05-29 v4 전체 재파싱(`--overwrite`) 직후, 코드/데이터에서 직접 확인한 미해결 문제 2건.
> 본 문서는 **원인 분석**까지만. 수정 방향은 후보로만 적고 확정·구현은 별도.
> 관련: [SKILL_PARSING.md](SKILL_PARSING.md)(v4 스키마), [SKILL_MISMAPPING_GUARD.md](SKILL_MISMAPPING_GUARD.md).

---

## 문제 1 — 무기 변환 계수가 구조화되지 않음 (`trait_weapon_transformed`)

### 증상
`name_code=5012` (Snow White) burst 등에서 **무기 자체를 교체하는 계수**가
구조화 필드가 아니라 `notes` 산문에만 들어감 → 시뮬레이터가 사용 불가.

예 (5012 burst, 원문):
```
Changes the weapon in use: Charge Time: 5 sec, Damage 499.5% of final ATK,
Full Charge Damage: 1000% damage, Max Ammunition Capacity: 1 round, Additional Effect: Pierce
```
→ 파싱 결과: `trait_weapon_transformed`(grant_trait, value=1 플래그) + `trait_pierce` 만 남고,
   `499.5% / 1000% / 5sec / 1round` 은 `notes` 텍스트로만 보존.

### 성격
이 수치는 **일회성 스킬 계수(deal_damage)가 아니다.** 버스트 지속 동안 무기의
발사 파라미터(per-shot 배율, 풀차지 배율, 차지 시간, 장탄)를 **교체**하는 값이다.
그래서 deal_damage 로 안 잡히고 notes 로 빠졌다. 본질적으로 **무기 오버라이드 파라미터**.

### 범위 (실측 13명)
`trait_weapon_transformed` 13건 / 13명:
laplace-treasure, moran-treasure, maxwell, **snow-white(5012)**, blue-ocean-neon,
zwei-treasure, red-hood, rapi-red-hood, eve, eunhwa-tactical-upgrade,
snow-white-heavy-arms, velvet, takina-inoue.
- 대부분 `Charge Time / Damage% / Full Charge Damage% / Max Ammo` 형태로 notes 에 존재.
- 일부 불완전: red-hood(Charge Time/Max Ammo 누락), eve("Exospine Mk2 transformation" 서술형),
  snow-white-heavy-arms("Max Lock-On +10" 등 비표준) → 게임 실측 보강 필요할 수 있음.

### 처리 방향 후보
| 방식 | 내용 | 평가 |
|---|---|---|
| A. C# per-character 하드코딩 | `switch(slug)` / `Dictionary<slug,override>` 에 13명 수치 | ❌ 데이터 변경 = 코드 릴리스. DEVLOG 2026-04-22 에서 "switch(slug) 안티패턴"으로 기각한 방식 |
| **B. 데이터 테이블 + C# 제네릭 (권장)** | `weapon_overrides.json`(slug 키, 13개)에 `{charge_time_sec, damage_pct, full_charge_damage_pct, max_ammo, pierce}` 손으로 작성. C# 은 "override 있으면 무기 파라미터 교체" **단일 제네릭 경로** | ✅ 데이터/코드 분리. 13개 안정 게임상수라 손작성이 LLM 재파싱보다 정확. 전체 철학(데이터=서술/엔진=실행) 일치 |
| C. skills_parsed 에 구조화 필드 주입 | grant_trait 에 `overrides{}` 추가 + notes 2차 파싱 | △ 한 파일에 모이나 스키마 확장 + 깨지기 쉬운 산문 파싱 |

- 핵심 원칙: **C# 에 캐릭터별 로직 금지.** 무기 파라미터 교체는 제네릭 코드 1개가 데이터를 읽을 뿐.
  `WeaponType` 자체는 불변(ARCHITECTURE §5.4 — B2/Collection/ChargeDmgBase 라우팅 오염 방지),
  granular 파라미터만 교체.
- 따라서 "C# 하드코딩이냐"의 답: **로직은 C# 제네릭, 수치는 JSON 데이터(B안).**

### ✅ 데이터 테이블 작성 완료 (2026-05-29) — `Database/processed/weapon_overrides.json`

- B안 채택. slug 키 16명: **표준 무기-파라미터 교체 12** + **특수 변환 4**(별도 처리 플래그).
  - 표준(12): snow-white, maxwell, zwei-treasure, eunhwa-tactical-upgrade, nayuta, red-hood, k,
    takina-inoue, blue-ocean-neon, velvet, moran-treasure, laplace-treasure.
  - 특수(4, `"special": true`): snow-white-heavy-arms(파라미터 수정형), modernia(타겟팅 모드),
    rapi-red-hood(투사체), eve(서브스킬 강화). 무기 배율 교체가 아니라 별도 메커니즘 — kind+note 보존.
- 필드: `duration_sec / charge_time_sec / damage_pct / full_charge_damage_pct / max_ammo /
  pellet_count / attack_speed_pct / pierce / true_damage`(+ laplace 전용 `initial_damage_pct / dot_damage_pct`).
- 수치는 전부 `skills_parsed.json` raw_text 에서 추출(날조 없음). `raw` 필드에 원문 보존.
- `needs_verification: true` (7명) — 원문에 일부 누락: nayuta(Max Ammo), red-hood(Charge Time/Max Ammo),
  laplace(DoT tick 주기), + 특수 4명. 게임 실측으로 보강.

### C# 제네릭 적용 설계 (소비처 — 갭 페이즈에서 구현)

무기 변환은 ARCHITECTURE §5.4 의 **granular override 원칙**으로 처리. 제안 형태:
```
1. 로드: WeaponOverrideTable.Load("weapon_overrides.json") → Dictionary<slug, WeaponOverride>
         (StatTable 처럼 프로세스당 1회. special=true 는 별도 핸들러 레지스트리로 분기.)
2. 활성: 시뮬 루프가 trait_weapon_transformed 플래그 on 을 감지하면
         (skills_parsed 의 grant_trait trait_weapon_transformed effect + duration)
         Nikke 에 ActiveWeaponOverride 를 세팅 (duration 동안).
3. 적용: 발사/대미지 계산 시 — override 가 활성이면 그 필드로 교체:
         · damage_pct           → BasicAtkMultiplier 대체
         · full_charge_damage_pct → ctx.ChargeDmgBase 대체 (÷100)
         · charge_time_sec       → WeaponStatTable 차지 타이밍 대체 (null=비차지=평타형)
         · max_ammo              → FinalBaseMaxAmmo 대체
         · pellet_count / attack_speed_pct → 발사 타이밍/히트수(로테이션 페이즈)
         · true_damage=true      → ctx.IsTrueDamage 강제
         · pierce=true           → ctx.IsPierceHit 경로 (trait_pierce 와 동일)
   ※ WeaponType 은 절대 안 바꾼다. ProperDistance/Collection 라우팅은 원본 유지.
4. 단일 제네릭 경로. per-character switch 없음. 신규 변환 캐릭 = JSON 한 줄 추가(코드 불변).
   special=true(modernia/eve/rapi/snow-white-heavy-arms)만 named 핸들러 (long-tail).
```

- 미해결: `needs_verification` 7명 수치 보강, special 4명 핸들러 설계, laplace DoT tick 주기.

---

## 문제 2 — v4 재파싱 PARSE_ERROR 42건 (36 캐릭) 원인 분석

### 집계 (skills_parsed.failed.json 기준)
- 총 42건. **Pydantic 검증 실패 40 + JSON 잘림 2.**
- 검증 실패 INV 분포: **INV-9a ×24** · INV-3b ×8 · INV-12 ×8 · INV-2 ×3 · INV-1 ×2 · INV-5 ×1.

### 원인별 분류

#### (1) 🔴 INV-9a × `unsupported` 충돌 — 24건 (최다, 자초한 구멍)
`action=grant_trait` 인데 `stat=unsupported`. 실패 메시지:
```
[INV-9a] action=grant_trait 은 stat ∈ {trait_weapon_transformed, trait_true_dmg_conversion,
trait_pierce} 필수. got stat=unsupported.
```
- **근본 원인**: v4 최소변경 때 ① `unsupported` 탈출구(stat)를 추가했지만 ② "Gains X status"
  류 **커스텀 상태 부여를 담을 `grant_status` action 이 없다.** LLM 은 상태 부여를
  grant_trait 로 시도 → stat 이 trait_* 3종에 없으니 unsupported → INV-9a 위반.
- diesel scratch(`_test_diesel.json`)는 `grant_status` 를 썼지만, **코드 스키마엔 미반영**(미니멀 결정).
- 즉 scratch 설계와 코드 스키마의 간극이 그대로 드러난 것.
- **수정 후보**: (a) `grant_status` action + 임의 `@status` 토큰 허용(가장 정공법, ~24건 해소),
  또는 (b) INV-9a 완화(grant_trait 에 unsupported 허용), 또는 (c) 프롬프트에서 "상태부여는
  buff/grant_status 로, grant_trait 는 3종 전용" 명시.

#### (2) 🟡 카운팅 변형 trigger 갭 — 8건 (INV-3b)
비카운팅 trigger 에 trigger_count 설정. 실패 메시지:
```
[INV-3b] event=on_hit 은 카운팅형이 아니므로 trigger_count 설정 금지. got 5.
[INV-3b] event=burst_use ... got 5.   ('when using Burst skill for 5 time(s)')
```
- **근본 원인**: `every_n_full_charge` 처럼, `'when using Burst Skill for N time(s)'` /
  `'on hit ... N times'` 같은 **다른 카운팅 변형**에 enum 슬롯이 없다. LLM 이 비카운팅
  event 에 trigger_count 를 억지로 붙임.
- **수정 후보**: 카운팅 변형 trigger 추가(예: `every_n_burst_use`, `every_n_hits`) + trigger_count.
  (every_n_full_charge 와 동일 패턴. 단 무한 추가는 overfitting 주의 — 빈도 보고 상위만.)

#### (3) 🟡 INV-12 self-collapse 미준수 — 8건
`target=self` + `(max_hp_flat, caster_max_hp)` / `(atk_flat, caster_atk)`. 실패 메시지:
```
[INV-12] target=self + stat=max_hp_flat + scale_base=caster_max_hp 은 중복 표현.
본인 기준이 곧 시전자 기준 → scale_base=none 으로 쓰라.
```
- **근본 원인**: "Max HP ▲ X% of caster's Max HP" 를 self 에 걸 때 같은 stat×같은 base 라
  collapse 대상인데 LLM 이 caster_* 를 그대로 씀. **프롬프트 준수 문제**(스키마 갭 아님).
- **수정 후보**: (a) 프롬프트 강조, 또는 (b) 검증자를 **거부 대신 자동정규화**(self+같은base →
  none 으로 silently 교정)로 완화. 후자가 LLM 부담 감소.

#### (4) 🟢 deal_damage 규칙 위반 — 5건 (INV-1 ×2, INV-2 ×3)
deal_damage 에 formula_bracket 채움(INV-1) 또는 scale_base≠caster_atk(INV-2). 프롬프트 준수 문제.

#### (5) 🟢 JSON 잘림 — 2건 (belorta burst 등)
거대 스킬에서 출력이 MAX_TOKENS 초과로 잘려 malformed JSON. 실패 메시지: `Expecting ',' delimiter`.
- **수정 후보**: 해당 스킬만 MAX_TOKENS 상향 재시도, 또는 thinking_budget 조정.

### 요약 — 고치면 효과 큰 순서
1. **grant_status action 신설** (+ @status 허용) → INV-9a 24건 해소. 가장 큰 효과, 자초한 구멍.
2. **카운팅 변형 trigger 보강** → INV-3b 8건. (빈도 상위만, overfitting 주의)
3. **INV-12 자동정규화** → 8건. 검증자 완화로 LLM 부담↓.
4. deal_damage 프롬프트 강화(5건), 거대스킬 MAX_TOKENS 재시도(2건).

> 재시도 방법: `--overwrite` **없이** 재실행하면 per-skill preservation 으로 **실패분만** 재파싱
> (깨끗한 스킬 보존, 토큰 절약). 단 위 (1)~(3) 스키마/프롬프트 수정을 먼저 해야 같은 실패 반복 안 함.
