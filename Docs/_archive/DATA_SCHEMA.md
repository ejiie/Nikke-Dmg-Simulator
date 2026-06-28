# DATA_SCHEMA

> **역할**: JSON/CSV 파일 스키마, enum 고정값, DTO 대응표, val_type 규칙, 알려진 데이터 결함.
> **업데이트**: JSON shape / enum 추가 / 파서 보강 시마다.
> **근거**: `DataPipeline/schema/skill_schema_legend.txt` (스킬), `DataPipeline/schema/skill_schema.py` (Pydantic), C# `Data/Dto/*.cs` (DTO), 실제 JSON 관측값.

---

## 1. 파일 인벤토리

### 1.1 `Database/raw/` (크롤러 출력)

| 파일 | 역할 | 생성 출처 |
|---|---|---|
| `nikke_full_scroll_result.json` | blablalink 유저/캐릭터 raw 응답 | `DataPipeline/crawler/getFromBlaLink.py` |
| `prydwen_all_details_v3.json` | prydwen.gg 캐릭터 정적 정보 raw | `DataPipeline/crawler/getFromPrydwen.py` |
| `real_en_dict_dump.txt` | 영문 스트링 사전 (번역 대조용) | (수동 덤프) |

### 1.2 `Database/processed/` (ETL 출력)

| 파일 | 역할 | 생성 출처 | 소비처 |
|---|---|---|---|
| `nikke_merged_db_returned.json` | 캐릭터 정적+유저상태 통합 DB (최종) | `DataPipeline/etl/db_merger.py` | C# `RootDto` |
| `nikke_merged_db.json` | 병합 중간 산출물 | `etl/db_merger.py` | — |
| `skills_parsed.json` | 스킬 텍스트 → 구조화 효과 | `DataPipeline/schema/skill_parser_llm.py` | (예정) C# 스킬 번역기 |
| `prydwen_clean.json` | 프리드웬 raw 정제본 (+ atk_parser 후처리) | `DataPipeline/etl/prydwen_cleaner.py` → `etl/atk_parser.py` | `db_merger` 입력 |
| `user_state_clean.json` | 유저 측 소유 상태 스냅샷 (OL `val_type==Percent` 는 이 단계에서 `/10000` 스케일) | `DataPipeline/etl/blabla_merger.py` | `db_merger` 입력 |
| `final_mapping.json` | slug ↔ name_code 매핑 | `DataPipeline/etl/auto_mapper.py` | `db_merger` 입력 |
| `stat_table.csv` | 레벨/등급/코어/클래스/제조사/호감도/콘솔별 기초 스탯 | (사용자 직접 수집) | C# `StatTable.Initialize` |
| `skills_parsed.*.backup.json` | 파서 리비전 백업 (v2-backup / slug-keyed / pre-targetfilter / pre-v3-rerun / pre-charge-trait) | 파서 단계 | — |

### 1.3 파이프라인 순서

```
crawler/getFromBlaLink.py  ──→  raw/nikke_full_scroll_result.json ──→  etl/blabla_merger.py ──→  processed/user_state_clean.json ─┐
crawler/getFromPrydwen.py  ──→  raw/prydwen_all_details_v3.json   ──→  etl/prydwen_cleaner.py                                    │
                                                                  ──→  etl/atk_parser.py (in-place)                              ├─→  etl/db_merger.py ──→  processed/nikke_merged_db_returned.json
                                                                                                     etl/auto_mapper.py ─────────┘
                                                                  ──→  schema/skill_parser_llm.py ──→  processed/skills_parsed.json
(사용자 직접 공급)                                                 ──→  processed/stat_table.csv
```

---

## 2. `nikke_merged_db_returned.json` ↔ C# DTO 대응

최상위 = `RootDto` (`SimulatorEngine/Nikke.Simulator.Core/Data/Dto/RootDto.cs`).

| JSON 경로 | C# 필드 | 타입 | 비고 |
|---|---|---|---|
| `uid` | `RootDto.uid` | `ulong` | |
| `global_state.synchro_level` | `GlobalStateDto.synchro_level` | `int` | |
| `global_state.consoles` | `GlobalStateDto.consoles` | `Dictionary<string,int>` | 콘솔 TID 문자열 → 레벨. O(1) 탐색용 |
| `roster` | `RootDto.roster` | `Dictionary<string,CharacterDto>` | ⚠️ **key = `name_code`** (numeric string, 예: `"1010"`). slug 아님 |
| `roster[nc].slug` | `CharacterDto.slug` | `string` | 실제 캐릭터 slug (예: `"snow-white"`) |
| `roster[nc].name_code` | `CharacterDto.name_code` | `string` | key 와 동일값 |
| `roster[nc].static` | `CharacterDto.StaticInfo` | `CharacterStaticDto` | C# 예약어 회피 `[JsonPropertyName("static")]` |
| `roster[nc].user` | `CharacterDto.user` | `CharacterUserDto` | |

> `RootDto.cs` 의 현재 주석 (`key=slug`) 은 정확하지 않음 — 실제 데이터는 `name_code` 키. 동작에는 영향 없음 (컨슈머가 Value 의 `.slug` 를 참조).

### 2.1 `CharacterStaticDto` 필드

| JSON | C# | 타입 | 예 |
|---|---|---|---|
| `name` | `name` | `string` | "Snow White" |
| `iconUrl` | `iconUrl` | `string` | |
| `element` | `element` | `string` | "Iron" / "Fire" / "Water" / "Wind" / "Electric" |
| `weapon` | `weapon` | `string` | WeaponType enum 문자열 (§4) |
| `class` | `character_class` | `string` | `[JsonPropertyName("class")]`. "Attacker"/"Defender"/"Supporter" |
| `burstType` | `burstType` | `string` | "I" / "II" / "III" / "A" |
| `manufacturer` | `manufacturer` | `string` | "Missilis"/"Elysion"/"Tetra"/"Pilgrim"/"Abnormal" |
| `ammoCapacity` | `ammoCapacity` | `int` | native ammo |
| `reloadTime` | `reloadTime` | `double` | sec |
| `basicAttack` | `basicAttack` | `BasicAttackDto` | multiplier / coreHitBonus / chargeTime / **chargeDamage (→ `ctx.ChargeDmgBase` per-character; 대부분 2.5, 일부 3.5)** / rawText |
| `skills` | `skills` | `List<SkillDto>` | skillId / name / slot / type / cooldown (nullable) / descriptionLevel10 |

### 2.2 `CharacterUserDto` 필드

| JSON | C# | 타입 | 비고 |
|---|---|---|---|
| `level` | `level` | `int` | |
| `grade` | `grade` | `int` | |
| `core` | `core` | `int` | |
| `combat` | `combat` | `int` | 게임 내부 표기상 전투력 |
| `bond_level` | `bond_level` | `int` | 호감도 |
| `favorite_item_lv` | `favorite_item_lv` | `int` | `slug.Contains("treasure")` 시 C# 에서 15 고정 (`Nikke` 생성자) |
| `skills` | `skills` | `SkillLevelsDto` | skill1 / skill2 / burst |
| `equipments` | `equipments` | `EquipmentPartsDto` | head / torso / arm / leg (각 `EquipmentInfoDto`: tier, level). 현재 stat 주입 경로는 미구현 (B2 대기) |
| `overload_stats` | `overload_stats` | `List<OverloadOptionDto>` | §3 |

---

## 3. OverloadOptionDto — `val_type` 규칙 ⚠️

```json
{ "type": "StatAtk",            "value": 0.1181, "val_type": "Percent" }
{ "type": "StatCriticalDamage", "value": 1644,   "val_type": "Integer" }
```

**스케일 책임 분담**:
- **ETL 측** (`etl/blabla_merger.py`): `val_type == "Percent"` 인 경우에만 원시값을 `/10000` 으로 미리 스케일해서 저장.
- **C# 측** (`Nikke.InitializeFinalStats` 의 `Normalize`): `val_type == "Integer"` 인 경우 `value / 10000.0` 으로 정규화. (`Percent` 는 이미 스케일되어 있으므로 건드리지 않음.)

```csharp
double Normalize(OverloadOptionDto o)
    => (o.val_type == "Integer") ? o.value / 10000.0 : o.value;
```

### 3.1 관측된 `type` 목록 (현재 178명 기준)

| type | val_type | 건수 | C# 소비 위치 | 상태 |
|---|---|---|---|---|
| `IncElementDmg` | Percent | 113 | `ctx.SumStrongElem` | ✅ B5 축 |
| `StatAtk` | Percent | 105 | `FinalBaseAtk` (native × (1+Σ%)) | ✅ |
| `StatAmmoLoad` | Percent | 72 | `FinalBaseMaxAmmo` (native × (1+Σ%)) | ✅ (과거 `"StatMaxAmmo"` 오타로 dead code 였음, H3 수정) |
| `StatChargeTime` | Percent | 56 | 🚧 미구현 (차지 시간 감소 축, 시간축 → runtime) | ⏳ 스킬 런타임 페이즈 |
| `StatCriticalDamage` | Integer | 48 | `ctx.SumCritDmg` | ✅ `/10000` 정규화 |
| `StatCritical` | Integer | 46 | `ctx.BaseCritRate` | ✅ `/10000` 정규화 (기본 0.15 에 가산) |
| `StatAccuracyCircle` | Percent | 44 | 🚧 미구현 (에임 보정, DPS 모델 밖) | ⏳ 스코프 외 (당분간 무시) |
| `StatChargeDamage` | Integer | 40 | `ctx.SumChargeDmgAdd` | ✅ `/10000` 정규화 (SR/RL 만 의미) |
| `StatDef` | Percent | 38 | `FinalBaseDef` (native × (1+Σ%)) | ✅ |
| `StatMaxHP` | Percent | 0 | `FinalBaseHP` | ⚠️ 현재 0건 — LINQ 유지 (비용 0, 미래 대비) |

**요약**: 현재 JSON 에 등장하는 OL `type` 은 위 10종. 새 type 추가 시 `Nikke.InitializeFinalStats` 에 LINQ 분기 추가 + 이 표 업데이트 + DEVLOG 결정 로그.

---

## 4. WeaponType enum (정확 문자열)

JSON `roster[nc].static.weapon` 에 들어오는 정확한 문자열. `Nikke.BuildAttackContext` 의 `switch` 와 Collection 라우팅 양쪽에서 키로 사용되므로 반드시 일치해야 함.

| 문자열 | 약칭 |
|---|---|
| `"Assault Rifle"` | AR |
| `"Machine Gun"` | MG |
| `"Submachine Gun"` | SMG |
| `"Shotgun"` | SG |
| `"Sniper Rifle"` | SR |
| `"Rocket Launcher"` | RL |

**주의**: 공백/대소문자 정확히. 변경 시 C# `switch` + `DataPipeline` 매핑 양쪽 확인.

---

## 5. Cube / Collection Effect 스키마

### 5.1 `CubeEffectDto` (readonly struct, `Data/Constants/EffectModels.cs`)

6종 필드, 하모니 큐브 스킬 효과 고정:

| 필드 | 의미 | 소비 축 |
|---|---|---|
| `ReloadTimeReduction` | 재장전 속도 감소 | 시간축 (runtime) |
| `AmmoChargeRate` | 탄환 충전 비율 | 시간축 (runtime) |
| `PartsDamageBonus` | 파츠 대미지 증가 | `ctx.SumPartsDmg` |
| `PierceDamageBonus` | 관통 대미지 증가 | `ctx.SumPierceDmg` |
| `TrueDamageBonus` | 트루 대미지 증가 | 🚧 미구현 (AttackContext 필드 없음) |
| `MaxHpBonusRate` | 체력 증가율 | native HP 곱산 (H1) |

### 5.2 `CubeSkillTable` — **하드코딩 딕셔너리** (CSV 아님)

`SimulatorEngine/Nikke.Simulator.Core/Data/Constants/CubeSkillTable.cs`. TID → `{ skillLevel → CubeEffectDto }` 이중 딕셔너리.

| TID | 상수명 | 큐브명 | 스킬 레벨 범위 |
|---|---|---|---|
| 1000313 | `CubeResilience` | Resilience (재장전 ▲) | 1-7 |
| 1000314 | `CubeBastion` | Bastion (탄환 충전 ▲) | 1-7 |
| 1000318 | `CubePartsDamage` | Parts Damage ▲ | {1, 4, 7} (예시치) |
| 1000319 | `CubePierceDamage` | Pierce Damage ▲ | {1, 4, 7} (예시치) |
| 1000320 | `CubeTrueDamage` | True Damage ▲ | {1, 4, 7} (예시치) |
| 1000321 | `CubeVigor` | Vigor (Max HP ▲) | {1, 4, 7} (예시치) |

**주의**: 1000318-1000321 의 수치는 **코드 주석상 "예시 TID / 예시 수치"**. 실측 데이터 확보 후 교체 필요 (DEVLOG 열린 질문 참조).

### 5.3 `CollectionEffectDto` (readonly struct)

무기별 4종 + 공통 3종:

| 필드 | 적용 무기 | 소비 축 |
|---|---|---|
| `CoreDamageBonus` | AR | `ctx.SumCoreHitBuff` |
| `ChargeDamageMultiplier` | SR, RL | `ctx.SumChargeDmgMult` |
| `NormalAttackMultiplier` | SMG, SG | `ctx.SumAttackDmg` |
| `MaxAmmoIncreaseRate` | MG | native ammo 곱산 (H2) |
| `DefIncreaseRate` | 공통 | 🚧 자기생존 (DPS 스코프 외) |
| `DamageTakenReduction` | 공통 | 🚧 자기생존 |
| `CoverHpIncreaseRate` | 공통 | 🚧 자기생존 |

### 5.4 `CollectionEffectTable` 등록 흐름

- CSV rows 49-64 의 SR 컬렉션 스탯과 별도로, `CollectionEffectTable.RegisterEffect(...)` 가 `StatTable.Initialize` 단계에서 호출되며 효과 맵을 채운다.
- 런타임 조회: `CollectionEffectTable.Get(characterId, level)` → `CollectionEffectDto`.
- 무기별 라우팅은 `Nikke.BuildAttackContext` 가 `WeaponType` switch 로 분기.

---

## 6. `skills_parsed.json` 스펙 (v3)

**권위 레퍼런스**: `DataPipeline/schema/skill_schema_legend.txt` + `DataPipeline/schema/skill_schema.py` (Pydantic). 본 섹션은 요약.

### 6.1 최상위 구조

```jsonc
{
  "<name_code>": {                    // 키는 numeric string (예: "1010"). slug 아님.
    "name_code": "1010",
    "slug": "snow-white",
    "name": "Snow White",
    "status": "completed" | "pending",
    "skills": [ SkillParsed, SkillParsed, SkillParsed ]   // s1 / s2 / burst
  },
  ...
}
```

- 현재 178명
- `status`: `"completed"` (정상) / `"pending"` (파서 미처리). 관측상 대부분 `completed`.

### 6.2 `SkillParsed`

```jsonc
{
  "skill_name": "Dark Purger",
  "skill_slot": "s1" | "s2" | "burst",
  "raw_text": "...",                       // 원본 descriptionLevel10
  "groups": [ TriggeredEffectGroup, ... ], // 비어있으면 파서 bailout 또는 stack 분기로 이관
  "stack_conditions": null | [ StackCondition, ... ],
  "stack_mode": null | "cumulative" | "replace",
  "stack_trigger": null | "<trigger event>",
  "stack_trigger_count": null | N,
  "parsing_notes": null | "..."
}
```

**3-layer 구조 (v3 핵심)**: `SkillParsed → groups[] → (trigger, target, effects[])`.
동일 `trigger+target` 게이트를 공유하는 효과는 하나의 group 안에 묶인다.

### 6.3 `TriggeredEffectGroup`

```jsonc
{
  "trigger":  TriggerBlock,
  "target":   TargetBlock,
  "effects":  [ EffectBlock, ... ]
}
```

### 6.4 `TriggerBlock`

| 필드 | 의미 | 값 |
|---|---|---|
| `event` | 트리거 이벤트 | §6.8 `[trigger event]` enum |
| `trigger_count` | 카운팅형 event 의 N | `every_n_shots`/`every_n_normal_attacks`/`when_attacked_n_times` 일 때만 |
| `condition_on` | 추가 조건 | §6.9 `[condition_on]` enum |
| `condition_threshold_pct` | HP 임계치 % | `hp_below_pct`/`hp_above_pct` 와만 |
| `required_token` | free-form 전제 상태/토큰 | 예: `"Nano Coating status"`, `"Hero Vision fully stacked"` |
| `internal_cooldown` | ICD 초 | |

### 6.5 `TargetBlock`

| 필드 | 의미 | 값 |
|---|---|---|
| `target` | 효과 대상 | §6.10 `[TargetType]` enum |
| `target_count` | 지정 N | `all_*` 이면 null |
| `target_filter` | 추가 필터 | §6.11 `[TargetFilter]` enum |
| `filter_token` | free-form 추가 필터 | 예: `"with a Shotgun"`, `"of caster's element"` |

### 6.6 `EffectBlock`

| 필드 | 의미 | 값 |
|---|---|---|
| `stat` | 버프/디버프 스탯 | §6.7 `[StatType]` enum |
| `action` | 행동 종류 | §6.12 `[ActionType]` enum |
| `value` | 수치 (음수 금지; INV-7) | |
| `scale` | 값 단위 | `pct` / `flat` / `seconds` |
| `scale_base` | 값 기준량 | `none` / `caster_atk` / `caster_max_hp` / `caster_charge_speed` / `target_max_hp` / `target_current_hp` / `damage_dealt` |
| `formula_bracket` | 대미지 공식 브래킷 | §6.13 enum (비대미지 스탯은 null) |
| `duration` | 지속 초 (null = 영구) | |
| `max_stacks` | 버프 최대 스택 | |
| `stack_increment` | 트리거당 획득 스택 | |
| `notes` | 런타임 참고 메모 | |

### 6.7 `[StatType]` — 34종 (관측 상위순)

- **B2 crit/core**: `crit_rate` / `crit_dmg` / `core_hit_buff`
- **B3 attack damage 계열**: `attack_dmg` / `pierce_dmg` / `parts_dmg` / `dot_dmg` / `sequential_dmg`
- **B4 받뎀 / 분배**: `damage_taken` / `distrib_dmg`
- **B5 우월 코드**: `strong_elem`
- **Final ATK modifiers**: `atk_pct` / `atk_flat` (cross-stat caster 스케일링도 `atk_flat` 로 표현)
- **Defense / HP**: `def_pct` / `def_flat` / `max_hp_pct` / `max_hp_flat`
- **차지 2축** (Full Charge 한정): `charge_dmg` (가산, `coeff_charge_add`) / `charge_dmg_mult` (곱셈, `coeff_charge_mult`) / `charge_speed` (시간축)
- **Trait (플래그; `action=grant_trait` 전용)**: `trait_pierce` / `trait_true_dmg_conversion` / `trait_weapon_transformed` — **INV-9a 화이트리스트**
- **브래킷 외**: `ammo_capacity` / `reload_speed` / `true_dmg` / `hp_potency` / `burst_gauge` / `burst_cooldown` / `heal` / `lifesteal` / `shield` / `move_speed` / `immunity`

관측 상위 건수: `attack_dmg`(200) / `atk_pct`(96) / `crit_rate`(65) / `heal`(60) / `atk_flat`(49) / `def_pct`(44) / `shield`(42) / `damage_taken`(41) / `ammo_capacity`(41) / `immunity`(29) / ...

### 6.8 `[trigger event]` — 고정 enum

- **Passive / lifecycle**: `passive` / `enter_battle`
- **Self skill slot**: `skill_cast` (같은 슬롯 한정) / `skill1_use` / `skill2_use` / `burst_use`
- **Full Burst 생명주기**: `burst_start` / `burst_end` / `burst_active`
- **Combat events**: `on_hit` / `on_kill` / `last_bullet_hit` / `on_reload` / `full_magazine` / `low_ammo`
- **Ally events**: `ally_hit` / `ally_kill`
- **HP gates**: `hp_drops_below` / `hp_above`
- **Stack internal**: `stack_threshold` (stack_conditions 내부 group 전용)
- **Expiry**: `effect_expiry`
- **카운팅형 (반드시 `trigger_count` 동반; INV-3)**: `every_n_shots` / `every_n_normal_attacks` / `when_attacked_n_times` / `full_charge_hit`

### 6.9 `[condition_on]` — 고정 enum (TriggerBlock 차원)

- `none`
- **B3 sub-type**: `piercing_attack` / `hitting_parts` / `dot_instance` / `sequential_hit`
- **B4 sub-type**: `distribution_attack`
- **Situational**: `full_burst` / `hp_below_pct` / `hp_above_pct` / `in_cover` / `out_of_cover` / `enemy_debuffed`

### 6.10 `[TargetType]` — 고정 enum

`self` / `single_ally` / `all_allies` / `attacker` / `most_injured_ally` / `random_ally` / `single_enemy` / `all_enemies` / `random_enemy` / `hit_target`

### 6.11 `[TargetFilter]` — 고정 enum

`none` / `highest_max_hp` / `lowest_hp_pct` / `highest_atk` / `highest_def` / `nearest_to_crosshair` / `nearest_to_caster` / `within_attack_range` / `same_squad` / `same_element_code`

> 이외의 캐릭터 고유 필터는 `filter_token` (free-text) 에 원문 보존. C# 번역기는 **dict/switch dispatch 필수** (enum cast 금지).

### 6.12 `[ActionType]` — 11종 고정 enum

`buff` / `debuff` / `deal_damage` / `heal` / `grant_shield` / `grant_trait` / `fill_burst_gauge` / `reduce_cooldown` / `restore_ammo` / `grant_immunity` / `dispel`

관측 건수: `buff`(545) / `deal_damage`(167) / `heal`(81) / `debuff`(74) / `grant_trait`(40) / `grant_shield`(38) / `dispel`(22) / `grant_immunity`(20) / `reduce_cooldown`(19) / `restore_ammo`(10) / `fill_burst_gauge`(5).

### 6.13 `[formula_bracket]` — 고정 enum

> ⚠️ **`b2_crit_core` 행의 `(1 + ...)` 곱셈 표기는 SUPERSEDED.** B2 는 가산 per-term FLOOR (`floor(P)+Σfloor(P×bracket)`). enum 값/이름은 유효(파서가 씀), 계산식만 폐기. 현행 = `Docs/DESIGN.md` §3.

| 값 | 의미 |
|---|---|
| `b2_crit_core` | `(1 + FullBurst + ProperDist + ΣcritDmg + coreHitBase + ΣcoreHitBuff)` |
| `b3_attack_dmg` | `(1 + Σattack_dmg [+pierce] [+parts] [+dot] [+sequential])` |
| `b4_dmg_taken` | `(1 + Σdamage_taken + Σdistrib_dmg)` |
| `b5_strong_elem` | `(1 + Σstrong_elem)` |
| `coeff_charge_add` | `(ChargeDmgBase + Σcharge_dmg)` — Full Charge 가산 축 |
| `coeff_charge_mult` | `× (1 + Σcharge_dmg_mult)` — Full Charge 곱셈 축 |
| `null` | 브래킷 외 (ATK/DEF/HP 배율, heal, true_dmg, trait 등) |

**차지 2축 최종 수식**: `chargeDmg_final = (ChargeDmgBase + ΣADD) × (1 + ΣMULT)`.
두 축 합쳐 B3 와 독립 — 절대 혼용 금지 (INV-2 관련).

### 6.14 Stack 분기 (`stack_conditions` + `stack_mode`)

"Once / Twice / Three times" 패턴 스킬은 `groups[]` 를 비우고 `stack_conditions[]` 에만 기재:

```jsonc
{
  "skill_name": "Survival",
  "groups": [],
  "stack_conditions": [
    { "threshold": 1, "groups": [ TriggeredEffectGroup, ... ] },
    { "threshold": 2, "groups": [ ... ] },
    { "threshold": 3, "groups": [ ... ] }
  ],
  "stack_mode": "cumulative" | "replace",
  "stack_trigger": "skill_cast",        // 스택 카운터를 +1 시키는 이벤트
  "stack_trigger_count": null           // 카운팅형 stack_trigger 시 N
}
```

- `stack_mode = "cumulative"`: threshold=N 시 branch[1..N] 전부 활성 (원문 "Previous effects trigger repeatedly")
- `stack_mode = "replace"`: threshold=N 시 branch[N] 만 활성 (최상위 교체)
- 각 branch 의 `group.trigger.event` 는 `stack_threshold` 고정 (INV-4b)

---

## 7. `trait_weapon_transformed` — 현재 blob / 확장 스펙 (파서 보강 예정)

### 7.1 현재 상태

`stat == "trait_weapon_transformed"` 인 `deal_damage` 아닌 `grant_trait` effect 총 **20건**. override 파라미터는 `EffectBlock.notes` 에 원문 문자열로 박혀 있음:

```jsonc
{
  "stat": "trait_weapon_transformed",
  "action": "grant_trait",
  "value": 1.0,
  "scale": "flat",
  "scale_base": "none",
  "formula_bracket": null,
  "duration": 10.0,
  "notes": "Changes the weapon in use: Charge Time: 5 sec, Damage 499.5% of final ATK, Full Charge Damage: 1000% damage, Max Ammunition Capacity: 1 round."
}
```

### 7.2 확장 후 (granular; 파서 보강 TODO)

```jsonc
{
  "stat": "trait_weapon_transformed",
  "action": "grant_trait",
  "value": 1.0,
  "duration": 10.0,
  "weapon_override": {
    "fire_rate":                      null,   // 발/sec. null = 원본 유지
    "charge_time_secs":               5.0,    // SR/RL 차징 시간 덮어쓰기
    "full_charge_damage_override":    10.0,   // ChargeDmgBase 전체 대체 (1000% = 10.0)
    "max_ammo":                       1,
    "basic_atk_multiplier_override":  4.995,  // BasicAttackDto.multiplier 대체 (499.5%)
    "initial_damage_mult":            null,   // laplace-treasure 용 1회성 initial hit
    "dot_damage_mult":                null    // laplace-treasure 용 DoT tick
  }
}
```

### 7.3 적용 대상 사례 (예상)

| slug | fire_rate | charge_time | full_charge_override | max_ammo | basic_atk_override | initial | dot |
|---|---|---|---|---|---|---|---|
| `snow-white` | null | 5.0 | 10.0 | 1 | 4.995 | null | null |
| `laplace-treasure` | 60.0 | null | null | null | null | 14.5572 | 0.222 |
| `maxwell` | null | 2.0 | 3.0 | 1 | 8.1342 | null | null |

**원칙**: `weapon_type` 필드 **없음**. 원본 `CharacterStaticDto.weapon` 불변 (근거: DEVLOG 2026-04-22 · ARCHITECTURE.md §5.4).

### 7.4 재분류 필요한 오용 2건

- `julia-treasure` s2: "강제 스킬 1 발동" → `trait_weapon_transformed` 가 아님. 스킬 체인 트리거로 재분류.
- `ein` s1: "4 Near Feathers 소환" → 소환물 메커니즘. 별도 stat enum 필요.

### 7.5 연관 trait 스탯

- `trait_pierce`: "Gains continuous Pierce" / "Additional Effect: Pierce". value=1.0 flat.
- `trait_true_dmg_conversion`: "Normal damage is applied as true damage when <조건>". 조건은 `trigger.required_token` 원문 보존.

---

## 8. 알려진 데이터 결함

### 8.1 파서 bailout (`groups = []`)
- **완전 실패 (3/3 슬롯)**: 2명 — `alice-wonderland-bunny`, `maiden-ice-rose`
- **부분 실패**: 57명, 70개 슬롯 (s1: 26 / s2: 29 / burst: 15)
- 패턴: 분기형 효과, 피해 공유, 미지원 stat enum
- **C# 런타임 규칙**: `groups: []` 는 no-op 처리, throw 금지.

### 8.2 Free-text 잔존
- `filter_token` 62종 (상위: `"with a Shotgun"`(9) / `"except self"`(7) / `"Defender ally"`(4) / `"Electric Code"`(4) / ...)
- `required_token` 184종 (상위: `"when recovery takes effect"` / `"destroys an enemy's part"` / `"Drunken status"` / `"decoy exists"` / `"critical hit"`)
- → 파서 보강 시 top-N 을 enum 화, 나머지는 dispatch table.

### 8.3 `formula_bracket` 미설정
- `distrib_dmg` 21건 — 브래킷 위치 미정 (B3 vs B4 조사 필요)
- `sequential_dmg` 7건 — 브래킷 위치 미정
- → 수동 조사 후 파서 재돌 or 번역기 측 lookup table.

### 8.4 `StatMaxHP` OL 0건
- 현재 관측 0 건. `Nikke.InitializeFinalStats` 의 LINQ 는 유지 (실행 비용 0, 미래 대비).

### 8.5 `trait_weapon_transformed` blob
- 20건 전부 `notes` 문자열에 override 파라미터 박힘 → §7 스키마 확장으로 해소 예정.

### 8.6 `TrueDamageBonus` 미구현
- `CubeEffectDto.TrueDamageBonus` 존재하지만 `AttackContext` 에 대응 필드 없음.
- 트루 대미지는 "방어 무시" 축 — `max(1, FinalAtk − FinalDef)` 가 아닌 `FinalAtk` 직접 사용하는 별도 경로 필요.

### 8.7 CubeSkillTable 수치 placeholder
- TID 1000318-1000321 의 `partsDamage` / `pierceDamage` / `trueDamage` / `maxHp` 값은 코드 주석상 **"예시 수치"**. 실측 대조 필요.

### 8.8 `StatChargeTime` / `StatAccuracyCircle` 미주입
- `StatChargeTime` (56건): 차지 시간 감소 — 시간축 (RPS 모델). 현재 AttackContext 에 대응 필드 없음.
- `StatAccuracyCircle` (44건): 에임 원 축소 — DPS 모델 밖 (당분간 무시 정당화 필요).

---

## 9. `stat_table.csv` (C# `StatTable` 파싱 레이아웃)

컬럼/행 범위는 `StatTable.Initialize` (`SimulatorEngine/Nikke.Simulator.Core/Stats/StatTable.cs`) 가 하드코딩으로 읽음. CSV 의 시트 구조 자체가 고정.

| 블록 | 행 범위 | 열 범위 | 의미 |
|---|---|---|---|
| Bond | 3-42 | 26-36 | 호감도 레벨별 보너스 |
| Level | 6-1005 | 0-24 | 레벨별 기초 스탯 (class × weapon × manufacturer × HP/ATK/DEF) |
| Collection (SR) | 49-64 | 26, 28-48 | SR 컬렉션 스탯 |
| Cube (스킬 레벨별) | (전용 섹션) | 38-43 | `break at lv ≥ 20` |

### 9.1 `GetCoreAppliedStats` 공식

```
preCore  = lv + floor(lv · grade · 0.02) + gradeFlat + bond + console
final    = preCore + round(preCore · core · 0.02, AwayFromZero)
```

- `gradeFlat`: HP = 3000 · grade, ATK = 20 · grade, DEF = 100 · grade
- `bond`: Bond 테이블 조회 (행 3-42)
- `console`: `GlobalState.consoles` 딕셔너리에서 TID 문자열로 조회
  - **Common** (TID 1001): HP · 450
  - **Class** (TID 1101 Attacker / 1102 Defender / 1103 Supporter): HP · 750 + DEF · 5
  - **Manufacturer** (TID 1201-1205): ATK · 25 + DEF · 5

### 9.2 조회 시그니처

```csharp
StatTable.GetCoreAppliedStats(
    CharacterClass, WeaponType, Manufacturer,
    Level, Grade, Core, BondLevel, consoles)
→ (HP, ATK, DEF)
```

O(1) 조회. Initialize 1회만 CSV 파싱, 이후는 dict 룩업.

---

## 10. 도메인 불변식 (Invariants) 요약

`skill_schema_legend.txt` 권위본. 파서/번역기/테스트가 모두 지켜야 함.

| ID | 내용 |
|---|---|
| INV-1 | `stat` ↔ `formula_bracket` 정합성 (예: `atk_pct` 는 B2/B4/B5 금지) |
| INV-2 | `deal_damage` 의 `formula_bracket` 은 **항상 null** (스킬 계수는 브래킷에 들어가지 않음) |
| INV-3 | 카운팅형 event 는 `trigger_count` 필수 (역도 성립) |
| INV-3b | `stack_threshold` event 는 카운팅형 아님 (`trigger_count` 금지) |
| INV-4a | `stack_conditions` 와 `groups` 동시 사용 금지 |
| INV-4b | `stack_conditions` 내부 `group.trigger.event` 는 `stack_threshold` 고정 |
| INV-4c | `stack_conditions[].threshold` 는 1부터 1씩 증가 |
| INV-4d | `stack_conditions` 있으면 `stack_mode` / `stack_trigger` 필수 |
| INV-5 | `stack_trigger` 자체가 카운팅형이면 `stack_trigger_count` 필요 |
| INV-6 | `target_count` 는 단일/지정 target 에서만 (`all_*` 에서는 null) |
| INV-7 | `value < 0` 금지. 감소는 `action=debuff` 로 표현 |
| INV-8 | `condition_threshold_pct` 는 `hp_below_pct` / `hp_above_pct` 와만 |
| INV-9a | `grant_trait` 의 stat 은 `{trait_pierce, trait_true_dmg_conversion, trait_weapon_transformed}` 화이트리스트 |
| INV-9b | `grant_trait` 은 `value=1.0` + `scale=flat` + `scale_base=none` 강제 |
| INV-9c | `trait_*` stat 은 `action=grant_trait` 전용 |
| INV-10 | `lifesteal` ↔ `heal` + `scale_base=damage_dealt` 쌍대성 |
| INV-12 | `target=self` 에서 같은 stat × 같은 `caster_*` base 는 collapse 금지 (`scale_base=none` 으로 단순화). cross-stat 은 허용 |

> INV-11 (v2 의 `pct_of_caster_stat` 화이트리스트) 는 v3 에서 폐지.

---

## 11. 스키마 드리프트 체크리스트

JSON shape 변경 시 확인:
1. [ ] C# DTO (`Data/Dto/*.cs`) 필드 대응 업데이트
2. [ ] 이 문서 §2 ~ §7 업데이트
3. [ ] `Nikke.InitializeFinalStats` 의 LINQ `type` 필터 (OL) 또는 `BuildAttackContext` (scale 라우팅) 확인
4. [ ] `skill_schema_legend.txt` 에 enum 추가 시 파서 prompt 재정렬
5. [ ] `DEVLOG.md` 결정 로그에 변경 이유 추가
