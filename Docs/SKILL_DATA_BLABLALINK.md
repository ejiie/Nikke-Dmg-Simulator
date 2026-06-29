# 공식 스킬 데이터 — blablalink CDN (`roledata`)

> **발견 2026-06-29.** blablalink 공개 CDN 이 **게임 공식·구조화·레벨별 스킬 데이터**를 제공한다.
> 기존 prydwen 산문 → LLM 파싱 트랙([SKILL_PARSING.md](SKILL_PARSING.md))을 **대체/스킵**할 수 있는 ground-truth.
> 접근: `getFromBlaLinkStatic.py` 의 URL 난독화 알고리즘과 동일 (로그인 불필요). 상세는 메모리 `project_blabla_static_cdn`.

---

## 1. 위치

- 캐릭터 풀데이터: **`roledata/{resource_id}-v2-{locale}.json`** (1캐릭 1파일).
- enumerate: `character/en/nikke_list_en_v2.json` 의 각 record `resource_id` 로 순회.
  (name_code ↔ resource_id 는 nikke_list / `character/character_id_map.json` 에 있음.)
- 공개 CDN(`sg-tools-cdn.blablalink.com`), URL = 경로 MD5 + djb2 디렉토리 해시(크랙 완료).

## 2. roledata 구조 (스킬 관련)

캐릭터 스칼라: `name_code, resource_id, class, element_id, shot_id`(무기), `critical_ratio`(1500=15%),
`critical_damage`(15000=150%), `use_burst_skill`/`change_burst_step`(버스트 단계), `burst_duration`,
`stat_enhance_id`, `grade_core_id`, `character_level_attack/hp/defence_list`(레벨별 기초스탯).

스킬 3종: `skill1_detail`, `skill2_detail`, `ulti_skill_detail` (+ `skill1_id/skill2_id/ulti_skill_id` 코드,
`skill1_table/skill2_table` = `"StateEffect"`).

### 2.1 텍스트 ↔ 레벨별 수치 (핵심)
각 스킬 detail:
- `name_localkey` : 스킬명
- `description_localkey` : 텍스트 + `{description_value_NN}` placeholder + 태그(`<color=…>`, `<word_group=…>`)
- `description_value_list[i].description_value` : **레벨 1~10 값 배열**

**매핑 규칙**: `{description_value_NN}` = `description_value_list[NN-1].description_value[skill_level-1]`

예 (Emma skill1 "Cheerleading"):
```
desc: "{description_value_02}% chance to activate when attacked...
       Recovers {description_value_01}% of the caster's final Max HP"
description_value_list[0] = ["5.92","6.46",...,"10.77"]   → {description_value_01} (회복%/레벨)
description_value_list[1] = ["5","5",...,"5"]             → {description_value_02} (발동확률%)
```
→ **레벨별 정확 수치, 산문 파싱 불필요.**

### 2.2 효과 종류·로직 (버스트 detail 추가 필드)
`ulti_skill_detail` 은 위 + 효과 코드:
- `skill_type` : `"SetBuff"` / `"ChangeWeapon"` / … (효과 종류 코드)
- `attack_type`(Fire/Iron…), `counter_type`, `prefer_target`(LowHP…), `prefer_target_condition`
- `skill_cooltime`(4000) / `skill_cooltime_list`, `duration_type` / `duration_value`
- `skill_value_data` : `[{skill_value_type:"Integer"/"Percent", skill_value:N}, …]` (타입+값)
- `before/after_use/hurt_function_id_list` : **효과 함수 ID 참조** (예 `109030101`)

skill1/2 는 `skill_table:"StateEffect"` — 패시브 효과도 StateEffect 함수로 코드화돼 있음.

## 3. 시사점

- **값**: `description_value_list` 가 레벨별·타입별 exact → LLM 다듬기 **불필요**.
- **효과 종류**: `skill_type` + `function_id` = 코드 → 엔진이 직접 dispatch 가능.
- 즉 prydwen 스크래핑 + Gemini 파싱(55 PARSE_ERROR 병목) 트랙을 **공식 데이터로 대체** 가능 → 비용·정확도 동시 개선.

## 4. function / StateEffect 테이블 — CDN 에 **없음** (조사 완료 2026-06-29)

- JS 데이터 경로 전수 확인: function/StateEffect **정의 테이블 경로 없음**. 프론트는 description 텍스트만
  렌더하므로 게임 내부 효과 함수 정의를 노출하지 않는다.
- `equip_option_table_v2`(=디스커버리 e765, 오버로드 옵션 30개)는 `state_effect_id_list:[9310101,…]` **참조만**
  담고 정의(function_type)는 없음.
- 즉 `function_id`(109030101) / `state_effect_id` 의 **기계적 정의는 blablalink 에 없다**. 완전 정의가 필요하면
  게임 자체 datamine(StateEffect StaticDataTable) — 별도 소스, 난이도 높음.

> **그러나 불필요 판단**: 공식 `description_localkey`(게임 작성·일관) + `description_value_list`(레벨별 exact 값)
> + `skill_type`(효과 종류 코드) 조합이면 스킬을 충분히 모델링 가능. prydwen 산문보다 훨씬 깨끗해 규칙기반
> 파싱이 현실적이고, LLM 다듬기는 스킵. (function 정의는 후순위 nice-to-have.)

## 4.1 특수효과 → 엔진 버킷 / 의미 규칙 (큐브·소장품·스킬 공통)

효과 종류는 description 키워드로 식별(StateEffect 함수정의 미노출). 각 효과의 **적용 위치·방향**:

| effect | 적용 | 비고 |
|---|---|---|
| ElementAdvantageDamage | B5 `SumStrongElem` | 우월코드 |
| CoreDamage | B2 `SumCoreHitBuff` | |
| PartsDamage / PierceDamage / TrueDamage | B3 (플래그 조건) | |
| **NormalAttackMultiplier** | **W × (1 + 배율)** | ⚠ B3 아님! 무기 계수에 곱. (기존 코드 오류였음) |
| ChargeDamage / ChargeDamageMultiplier | charge add / mult | |
| **MaxHp / Def** | **stat × (1 + Σrate)** | ⚠ 전투 유지 rate 버프. 큐브0.1 + 버프0.2 → ×1.3 (합산 후 곱) |
| **DamageTaken(받피감)** | **생존(비대미지)** | ⚠ "캐릭이 적에게서 받는 뎀 감소". B4 `damage_taken`(적 취약=내 출력↑)과 **방향 반대·별개** |
| ReloadSpeed/MaxAmmo/ChargeSpeed/BurstGauge/ReloadRounds | 무기타이밍(sim루프) | 파싱만 |
| HealPotency / CoverHp / 조건부 | 생존 | 파싱만 |
| HitRate | 제외 | DESIGN: 명중률만 제외 |

## 4.2 ⏸ 미소비 효과 — 추후 구현 (잊지 말 것)

아래 효과들은 effect 표에 **파싱돼 저장**돼 있으나 엔진이 **아직 소비 안 함**. EffectType enum
에는 존재. `Nikke.RouteEffects` 의 switch 에 case 추가 + 소비처 구현하면 됨.

**무기 타이밍 (로테이션 sim 루프 생기면 소비)** — 발사/재장전/버스트 사이클:
- `ReloadSpeed` (Resilience 큐브): 재장전 시간 단축 → 재장전 틱 계산
- `ReloadRounds` (Bastion 큐브, **조건부**: N발 발사마다 M발 재장전)
- `ChargeSpeed` (Adjutant 큐브): 차지 완료 시간 단축
- `BurstGauge` (Quantum 큐브): 버스트 게이지 충전속도 → 풀버스트 주기
- (`MaxAmmo` 는 base stat 으로 이미 소비)

**조건부 효과 (sim 런타임의 트리거/조건 시스템 필요)**:
- Bastion: "N발 발사 → M발 재장전" (발사 카운트 트리거)
- Assist: "HP < X% → MaxHP +Y% Z초" (HP 임계 트리거 + 지속시간)
- effect 표의 `conditional: true` + `desc` 로 식별. placeholder 다중값(임계/효과/지속) 별도 해석 필요.

**생존 (DPS 스코프 밖, 우선순위 낮음)**:
- `DamageTaken` (Tempering 큐브 / 소장품): **캐릭이 적에게서 받는 뎀 감소** (B4 아님!)
- `HealPotency` (Healing 큐브): 받는 회복량 증가
- `CoverHp` (Stealth 큐브 / 소장품): 엄폐물 HP 증가

**제외**: `HitRate` (Assault 큐브) — DESIGN: 명중률(StatAccuracyCircle)만 제외.

## 5. 열린 항목

- [x] roledata 크롤러 — `getFromBlaLinkRoledata.py` (메타+무기+스킬, 공유 `_bbl_cdn.py`, 로그인 불필요).
      192/192 → `Database/raw/blabla_roledata.json`(name_code 키). `etl/roledata_cleaner.py` 가 정제(prydwen 대체).
- [ ] 엔진/ETL 연동: 스킬(`skills.skill1/2/burst`) → C# 스킬 런타임 (`skill_type` → dispatch, placeholder↔레벨값 주입).
- [ ] (후순위) 게임 datamine 에서 StateEffect 정의 확보 — 완전 기계화 시.
