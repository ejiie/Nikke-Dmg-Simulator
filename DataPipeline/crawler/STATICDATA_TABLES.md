# StaticData 테이블 인벤토리 — 무슨 정보가 있나 (2026-07-01)

> 게임 StaticData 복호(`getFromNikkeStaticData.py`) + il2cpp 스키마(`metadata_fields`) + `.mpk`
> 디코드로 확보한 데이터의 **목록·필드**. 1047 고유 테이블 / 580 `*Record`(행 스키마).
> 디코드 = **해결**(스키마+마커+int64, `STATICDATA_PREP.md` §7). 값(게임데이터)은 gitignore.
>
> **관계**: 스탯 = base × ratio × enhance[level]. 스킬 = roledata `function_id_list` → `FunctionRecord`.
> localkey 필드는 localization 표로 텍스트 해소(별도).

## 1. 캐릭터 스탯·성장
| Record | 필드 수 | 핵심 필드 | 용도 |
|---|---|---|---|
| `CharacterRecord` | 40 | Element_id, Class, Corporation, Shot_id, **Bonusrange_min/max**, Critical_ratio/damage, Use_burst_skill, Burst_apply_delay/duration, Ulti/Skill1/Skill2_id, Stat_enhance_id, Squad, Piece_id | 캐릭 메타(roledata 와 중복+α) |
| `CharacterStatRecord` | 9 | Group, Level, **Level_hp(int64), Level_attack, Level_defence**, 저항×3 | **레벨별 base 스탯**(64800행). ⭐ 수기 stat_table.csv 대체 |
| `CharacterStatEnhanceRecord` | 14 | **Grade_ratio, Grade_hp/attack/defence, Core_hp/attack/defence** | ⭐ **돌파/코어 공식 상수**(DESIGN §3.5 하드코딩 확증) |
| `AttractiveLevelRecord` | 21 | Attractive_point, {attacker/defender/supporter}_{hp/attack/defence/저항}_rate | 호감도 40레벨 (검증 완료) |
| `RecycleResearchStatRecord` | 14 | Attack, Defence, Hp, Recycle_type, Unlock_* | 함선연구 스탯 |
| `CoverStatEnhanceRecord` | 4 | Lv, Level_hp, Level_defence | 엄폐물 HP/DEF |

## 2. 무기·사격 (⭐ 모션·딜레이 포함)
`CharacterShotRecord` (58필드) — 프론트 모션의 **백엔드 타이밍/딜레이** 전부 여기.
- **사격 사이클**: `Rate_of_fire`(발사속도), `Rate_of_fire_reset_time`, `Rate_of_fire_change_pershot`(연사 가속), `End_rate_of_fire`, `Shot_timing`, `Shot_count`, `Muzzle_count`.
- **커버↔사격 전환(네 질문)**: `Uptype_fire_timing`(엄폐서 올라와 사격하는 타이밍=전환 딜레이), `Maintain_fire_stance`(사격자세 유지시간). ← 프론트 모션 연속성의 백엔드 값.
- **탄약/재장전**: `Max_ammo`, `Reload_time`, `Reload_bullet`, `Reload_start_ammo`.
- **딜레이**: `Spot_first_delay`(첫탄 지연), `Spot_last_delay`.
- **차지**: `Charge_time`, `Full_charge_damage`, `Full_charge_burst_energy`.
- **조준/명중**: `Start/End_accuracy_circle_scale`, `Accuracy_change_pershot`, `Accuracy_change_speed`(조준원 수렴속도), Auto_* (오토 조준), `Zoom_rate`, `Multi_aim_range`.
- **대미지/판정**: `Damage`, `Core_damage_rate`, `Penetration`, `Spot_radius`(펠릿), `Spot_explosion_range`(폭발), `Spot_projectile_speed`.
- **버스트**: `Burst_energy_pershot`, `Target_burst_energy_pershot`.
- **함수 연결**: `Use_function_id_list`, `Hurt_function_id_list`.
> = roledata `shot_detail` 의 **완전판**(더 많은 타이밍 필드). 로테이션 sim 의 발사 모델 정본.

## 3. 스킬·함수 (⭐ THE GAP = 스킬 런타임)
| Record | 필드 | 핵심 |
|---|---|---|
| `FunctionRecord` (55) | **19111 함수** | **Function_type, Function_standard, Function_value_type, Function_value**(효과 타입·수치), **Timing_trigger_{type,standard,value}**·**Status_trigger_{,2_}{type,standard,value}**(발동조건), **Duration_type/value, Delay_type/value, Full_count, Limit_value, Keeping_type, Is_cancel, Function_target**, Buff/Buff_remove, Connected_function | roledata `function_id_list` → 이 표. **스킬 효과 의미 공식 데이터** |
| `CharacterSkillRecord` (17) | | Skill_type, Skill_cooltime, Duration_*, Skill_value_data, **Before/After_use/hurt_function_id_list** | 캐릭 스킬 → function 연결 |
| `SkillInfoRecord` (10) | | Group_id, Skill_level, Description_localkey, **Description_value_list** | 스킬 설명+레벨별 수치(roledata 와 유사) |
| `StateEffectRecord`(장비) (4) | | StateEffectGroupId, EquipmentOptionTid, OptionRatio, StateEffect | OL 옵션 → state effect 값 (equip_option_table 해소) |

## 4. 몬스터·보스 (⭐ BossTarget K11)
| Record | 필드 | 핵심 |
|---|---|---|
| `MonsterRecord` (32) | 2035행 | Element_id, Monster_model_id, **Hp_ratio, Attack_ratio, Defence_ratio, {energy/metal/bio}_resist_ratio**, Statenhance_id, Passive_skill_id, Skill_data, Spot_ai*, Detector_* | 몬스터 base 비율 |
| `MonsterStatEnhanceRecord` (12) | 30671행 | Group_id, Lv, **Level_hp(int64), Level_attack, Level_defence**, Level_statdamageratio, 저항, Level_projectile_hp, **Level_broken_hp(int64)** | 레벨별 스탯 스케일 (예: Lv250 HP 58억) |
| `MonsterPartsRecord` (23) | 668행 | Monster_model_id, **Hp_ratio, Defence_ratio, Attack_ratio, 저항_ratio**, Damage_hp_ratio, Passive_skill_id, Is_main_part, Is_parts_damage_able | 파츠(부위) 스탯 |
| `MonsterSkillRecord` (46) | | Attack_type, Shot_count, Projectile_*, Casting_time, Delay_time, Skill_value_*, Target_cover_ratio | 몬스터 스킬 |
| `MonsterModelRecord` (13) | | Attribute, Class, Size, Move_type, Category_type_* | 모델/분류 |
> 보스 실제스탯 = base_ratio × StatEnhance[Lv] (스테이지가 Lv 지정: `CampaignStageRecord` 등).

## 5. 속성 (상성)
`ElementRecord` (9) — Element, **Weak_element_id**(약점=상성 우위), Group_id, localkey. → B5 강속성 판정 정본.

## 6. 장비·큐브·소장품
| Record | 필드 |
|---|---|
| `ItemEquipRecord` (15) | Item_type/sub_type, Class, Item_rare, Grade_core_id, Grow_grade, Stat, Option_slot/cost |
| `ItemEquipCorpSettingRecord` (10) | Corp_type, **Ratio_{elysion/missilis/tetra/pilgrim/abnormal}** (제조사 보너스) |
| `ItemHarmonyCubeRecord`(15)·`ItemHarmonyCubeLevelRecord`(9) | 큐브 정의·레벨 |
| `FavoriteItemRecord`(17)·`FavoriteItemLevelRecord`(6) | 소장품 정의·레벨 (Collection_skill_group_data) |
> blablalink CDN 으로 이미 확보한 것과 중복(교차검증용).

## 7. 글로벌 설정
`ConfigBattleRecord` (Id, Value) — 배틀 글로벌 상수 key-value (적정거리 보너스 크기 등 상수 후보 — 값 디코드 필요).

## 디코드 상태
- 스칼라 표(스탯/enhance/attractive/element) = **완전 디코드 검증**(int64 자동).
- 문자열/리스트 포함 표(Function/Shot/Monster) = 마커로 문자열 OK, `*_list` 배열 인코딩만 확정하면 완성.
- 툴: `metadata_fields.py`(스키마 추출), 디코더(스키마 구동). 방법=`STATICDATA_DECODE_GUIDE.md`, 포맷=`STATICDATA_PREP.md` §7.
