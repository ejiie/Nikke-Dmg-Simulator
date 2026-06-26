# SKILL_PARSING — 문제 분석 + v4 스키마

> 스킬 파싱이 "꼬인" 이유(§1~2)와, 그 위에서 **확정한 v4 스키마 형태(§3)**,
> 그리고 아직 안 한 일(§4~6)을 적는다.
> §3는 2026-05-26 task 루프(diesel/soda/2b/cinderella/rouge 실데이터 검증)로 합의된 **확정 형태**다.
> 단, "스키마 형태"가 확정됐다는 뜻이지 **소비자(C# 런타임)는 아직 없다** — §4~5 참조.
> 오매핑 방지 규칙은 별도 문서 [SKILL_MISMAPPING_GUARD.md](SKILL_MISMAPPING_GUARD.md).

## 1. 지금 무엇을 하고 있나 (사실)

`schema/skill_parser_llm.py` 가 Gemini로 각 스킬의 영문 텍스트(`descriptionLevel10`)를
`schema/skill_schema.py` 의 Pydantic 스키마(v3)로 구조화한다. 출력은 `skills_parsed.json`.

스키마는 매우 정교하다:
- 3계층: `SkillParsed → groups[] → (trigger, target, effects[])`
- 대미지 공식 B2~B5 브래킷 + 차지 2축을 `formula_bracket` 으로 태깅
- `scale` / `scale_base` 직교 분해 (단위 vs 기준량)
- 12개 도메인 불변식(INV-1~12)을 Pydantic validator로 강제
- stack_conditions(Once/Twice/Three times) 분기, trait 플래그(무기변환/관통/트루변환)

## 2. 왜 꼬였나 (관측된 증거)

### 2.1 Long-tail 토큰 폭발
- 고유 `required_token` **195종**, `filter_token` **64종** (2026-05-26 실측).
- 이들은 enum으로 못 잡은 캐릭터 고유 상태를 **원문 문자열 그대로** 보존한 것이다.
  예: `"Hero Vision is fully stacked"`, `"Drunken status"`, `"with a Shotgun"`,
  `"Water Code allies"`, `"not in Nano Coating status"`.
- 문제: 이 문자열들은 **시뮬레이터가 해석해야 비로소 의미**가 생긴다. 즉
  스키마는 "보존"만 했고, 실제 처리 부담을 전부 C# 런타임으로 미뤘다.
  런타임이 없는 지금, 195+64종을 어떻게 처리할지는 미해결로 남아 누적된다.

### 2.2 소비자(런타임)가 없어 검증 루프가 없다
- `skills_parsed.json` 을 읽는 코드가 **존재하지 않는다**.
- 스키마가 "실제로 시뮬레이션에 쓸 수 있는 형태인가"를 확인할 방법이 없다.
- 결과적으로 스키마는 "그럴듯하지만 미검증"인 채로 계속 정교해졌다. (옛 문서에
  환각이 섞인 것도 같은 뿌리 — ground truth로 되먹임할 소비자가 없었다.)

### 2.3 파싱 실패가 묻힌다
- 534개 스킬 중 **55개(≈10%)가 PARSE_ERROR** 로 빈 껍데기 상태. 43명이 `pending`.
- LLM이 어려운 스킬을 만나면 bailout → 빈 groups로 저장. 커버리지가
  일급 지표로 추적되지 않아 "얼마나 실제로 쓸 수 있는지"가 흐려진다.

### 2.4 long-tail을 스키마 1급으로 끌어들이려는 압력
- `trait_weapon_transformed` 21건은 덮어쓸 수치를 `notes` 자유 문자열에 보존하고,
  실제 처리는 "C# per-character override table"로 미뤄둔 상태(legend 규약).
  ≤10명짜리 롱테일을 스키마/파서로 완벽히 잡으려다 복잡도가 커졌다.

### 2.5 요약
근본 원인은 **"소비자(시뮬레이터 런타임)를 만들기 전에, LLM으로 모든 스킬을
(롱테일 캐릭터 고유 기믹까지) 완벽 구조화하려 한 것"**이다.
검증 루프 없이 스키마만 비대해지고, 처리 부담은 빈 런타임으로 계속 이월됐다.

## 3. v4 스키마 (확정 형태)

v3를 버리지 않고 **소비자 관점에서 정리**한 형태. 핵심 전환: JSON의 역할을
"실행 가능한 완전 명세"에서 **"충실한 구조적 전사 + 분류"**로 격하 — 실행 의미는
엔진/핸들러가 가진다. (JSON에 모든 것을 담는 것은 포기.)

### 3.1 구조

```text
skill → groups[] → { when: trigger+conditions, who: target+filter, effects[] }
```

- **group** = 같은 `(trigger, conditions, target, filter)`를 공유하는 효과 묶음.
  (실측: 멀티 effect 그룹 ~20% — 묶기 정당.)
- **판별자**: effect 안 `action` 하나가 **필드 집합**을 결정 (discriminated union).
  `stat`은 평범한 enum 필드 — 엔진이 stat 값으로 동작을 분기하되 스키마 모양은 안 바뀜.
  → "판별자는 필드 집합이 바뀌는 축(action)에만. stat은 값/동작만 바꾸는 enum."

### 3.2 토큰 이분 (가장 중요한 경계)

- **맨낱말** (`self`, `all_enemies`, `burst_start`, `hp_below_pct`): 엔진이 아는 **닫힌 enum**.
  로더가 enum 대조 → 미등록이면 에러.
- **`@`접두사** (`@Intro`, `@Mute`, `@GoldenChip`): C# **named 핸들러**가 필요한 캐릭터 고유
  토큰/상태. 핸들러 레지스트리 조회 → 없으면 `unsupported`로 **카운트(커버리지)**.
- 경계 판정 한 줄: *"닫힌 어휘로 표현되면 generic(JSON+엔진), 새 free-form 토큰이 필요하면
  핸들러(@)."* — 핸들러는 토큰의 on/off·지속·스택만 소유하고, **그 토큰에 게이트된
  숫자 효과(crit_dmg 등)는 전부 엔진이 처리**한다.

### 3.3 group 필드

`trigger`, `trigger_count`, `condition_on`, `condition_threshold_pct`,
`required_token`, `target`, `target_count`, `target_filter`, `stack_threshold`.

### 3.4 action별 payload (요약)

| action | 주요 필드 |
|---|---|
| `buff`/`debuff` | stat, value, scale, scale_base, formula_bracket?, duration, max_stacks?, stack_increment? |
| `deal_damage` | stat, value(계수%), scale_base=caster_atk, **damage_kind**(instant/dot/sequential) + 타이밍 파라미터 |
| `heal` | stat(heal/lifesteal), value, scale_base(target_*/caster_max_hp/damage_dealt). lifesteal→damage_dealt 강제 |
| `grant_shield` | value, scale_base, duration |
| `grant_status` | status(@토큰), duration, max_stacks?, stack_increment?, flags? |
| `grant_trait` | trait(pierce/true_dmg_conversion/weapon_override) + trait별 파라미터 |
| `grant_immunity` | immunity_target(@토큰), duration |
| `reduce_cooldown` | target_kind(burst/skill1/skill2), value(초, ▼면 음수) |
| `restore_ammo` / `fill_burst_gauge` / `dispel` | value 등 (legend 참조) |

### 3.5 확정 규칙 (task 루프에서 합의)

| # | 규칙 |
|---|---|
| **B1** | `duration`: `null`=영구(INFINITE), 숫자=초. `"infinite"` 문자열 안 씀. |
| **B2** | condition은 분리 필드: `condition_on`(enum) + `condition_threshold_pct` + `required_token`(@토큰). |
| **B3** | value 부호 = **원문 화살표 그대로**(▲ 양수 / ▼ 음수). `action`(buff/debuff)은 사이드(아군/적)만 표시, 부호를 결정 안 함. (예: `damage_taken ▲25.09%`→+25.09/debuff) |
| **B5b** | 스택 분기는 별도 구조 없이 `groups[]` 안 `trigger=stack_threshold` + `stack_threshold`(숫자). 상시효과는 일반 trigger group. 스택 메커니즘(`stack_mode`/`stack_trigger`)은 skill 레벨. |
| **B6** | `target_filter`도 맨낱말 enum vs `@`토큰 이분 (적/아군 양쪽 동일). |
| **B7** | 대미지축 칸에 우겨넣기 **금지**. 대미지 무관 stat → 이름 유지 + `formula_bracket=null` + **`dps_scope=false`**. 스키마에 stat 자체가 없으면 **`@stat`**(핸들러행). 상세 [SKILL_MISMAPPING_GUARD.md](SKILL_MISMAPPING_GUARD.md). |
| 카운팅 trigger | `every_n_shots` / `every_n_normal_attacks` / `when_attacked_n_times` / `every_n_full_charge` + `trigger_count`(N). |
| cross-caster | `atk_flat`/`max_hp_flat` + `scale_base=caster_atk`/`caster_max_hp`. 시전자 stat×value%를 대상에 평탄 가산. 합산 기준량(B_applicable)=**시전자** native. |
| deal_damage 타이밍 | `instant`(즉시) / `dot`(interval+duration) / `sequential`(initial_delay+interval+hit_count). **시간 전개는 JSON이 아니라 C# 메커니즘이 구현.** |
| `value_scales_with_token` | "Mirrors the stack count of X" → 실효값 = value × 토큰 스택. buff/deal_damage 공통. |
| 수식자 | `without_restoring_hp`(Max HP 상한만), `removed_on`(@조건부 해제), `flags`(no_dispel/persist_after_revival). |

### 3.6 마스터 레퍼런스 + 검증 예시 (scratch)

- **마스터 legend**: [`DataPipeline/schema/_test_diesel.json`](../DataPipeline/schema/_test_diesel.json) 의 `_legend`.
- 검증 예시 3종 (실데이터 기반, 파이프라인 산출물 아님):
  - `_test_diesel.json` (5159) — 일반/토큰 게이트/dot buff·deal, grant_status.
  - `_test_soda_stack.json` (5113) — B5b 스택 분기(cumulative).
  - `_test_caster_counting.json` — 카운팅 trigger(every_n_shots/full_charge), cross-caster(caster_atk+caster_max_hp), sequential, without_restoring_hp.
- feature 분포 집계기: `_test_inspect_features.py`.

> ⚠️ overfitting 경계: §3은 **형태와 규칙**이지 모든 엣지 케이스 카탈로그가 아니다.
> 새 캐릭터 기믹은 `@`토큰으로 흘려보내고 핸들러에서 처리 — 스키마를 늘리지 않는다.

## 4. 재설계 원칙

1. **소비자 우선(Consumer-first)**: 스키마를 더 다듬기 전에 `skills_parsed`를 실제로
   소비하는 최소 런타임을 먼저. 스키마는 런타임이 필요로 하는 만큼만.
2. **수직 슬라이스로 검증**: 캐릭터 1~3명을 끝까지(파싱→번역→런타임→DPS) 관통시켜
   스키마를 현실에 되먹인다.
3. **파레토 + 우아한 degrade**: 흔한 효과는 generic 자동 처리, 롱테일 기믹은
   "미지원 → 스킵 + 로그". 침묵 실패 금지.
4. **커버리지를 일급 지표로**: 반영률을 상시 측정. PARSE_ERROR·미지원 토큰(@)을 명시 카운트.
5. **정적 먼저, 런타임 나중**: 상태 독립 정적 modifier(쉬움)부터 end-to-end 완성.

## 5. 로드맵 (스키마 형태 확정 이후)

- [x] **스키마 형태 확정** — task 루프(2026-05-26). §3.
- [ ] **0단계 — 효과 이분 분류기**: 각 group을 `passive && duration==null && 토큰/스택 없음`
  → 정적, 그 외 → 런타임으로 분류. 정적/런타임 건수 = 커버리지 베이스라인.
- [ ] **1단계 — 정적 modifier 주입**: 토큰/조건 없는 정적 버프를 C# `Nikke`의 OL 사전집계
  자리에 합산. 니케식 그룹-반올림 합산을 OL 전용→범용 유틸로 승격.
- [ ] **2단계 — 수직 슬라이스 런타임**: 캐릭 1명으로 풀버스트/발동 타임라인 최소 루프 + DPS.
- [ ] **3단계 — 토큰 레지스트리**: `required_token`(195) / `filter_token`(64)을 빈도순 상위 N개만
  핸들러 큐레이션, 나머지 미지원 등록.
- [ ] **4단계 — 롱테일 무기변환**: `weapon_override` 등은 캐릭터별 override 테이블(데이터)로.

## 6. 미해결 / 남은 일

- **소비자(C# 런타임)는 아직 없음** — `skills_parsed.json`을 읽는 코드 0. §5가 그 작업.
- **재파싱 필요**: 기존 `skills_parsed.json`은 오매핑(Hit Rate→crit_rate 등 72건 의심)과
  PARSE_ERROR 55건이 박혀 있음. v4 스키마 + [SKILL_MISMAPPING_GUARD.md](SKILL_MISMAPPING_GUARD.md)를
  프롬프트에 넣어 재파싱해야 교정됨.
- **B7 notes 정형화(#1~#7) 미완**: once_per_battle / dispel 대상 / immunity 종류 등 일부 패턴은
  아직 notes에 남아 있음 — 필드 승격 여부 추후.
- **B4 grant_trait 상세**: pierce/true_dmg_conversion/weapon_override의 런타임 소비는 갭 페이즈에서.
- 커버리지 목표 숫자 합의 (예: 정적 효과 N% 자동 처리, 런타임 토큰 상위 N종).
