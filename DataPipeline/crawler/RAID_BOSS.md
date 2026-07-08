# 레이드 보스 데이터 (server StaticData) — 진척 (2026-07-07)

> 목표: 시뮬 타깃으로 쓸 **레이드 보스** 스탯. DummyTarget 다음. **사용자 방침(7/7): union 무시, solo raid 집중.**
> 파이프라인: `getFromNikkeStaticData.py`(fetch) → `staticdata_raid_decode.py`(bool+NF 휴리스틱: SoloRaidPreset/
> Manager/MonsterModel) + `memorypack_decode.py`(**MemoryPack 정밀**: MonsterParts/MonsterTable/MonsterStatEnhance)
> → `staticdata_solo_raid.py`(조립 → `raid/solo_raid_boss.{json,md}`). 복호값=gitignore, 스크립트만 커밋.

## 디코드 돌파구 (필드셋 drift 해결)
2개 규칙으로 flat 표 clean 디코드:
1. **bool = 1바이트** (int32 4B 아님). `Spot_autocontrol`/`Is_*`/`Use_*`/`Nonetarget` 등.
2. **nFields = 표당 상수**(=`raw[4]`) → 레코드마다 다음 바이트가 NF 인지로 **경계 자기검증**.
+ string = `[-(len+1)][len][utf8]` 마커 자기검증, list(`_list`/`_data`) = `[count]+중첩레코드`.

## ✅ 신뢰 가능 (clean 디코드, off==len + 경계검증 통과)
| 표 | 행 | 핵심 |
|---|---|---|
| `UnionRaidPresetTable` | 2353 | Preset_group_id·Difficulty·**Monster_stage_lv**·Wave·Wave_name·**Monster_image**(보스코드) |
| `UnionRaidManagerTable` | 41 | Id→Monster_preset(=Preset_group_id) |
| `SoloRaidPresetTable` | 304 | (+Character_lv·First_clear_reward) |
| `SoloRaidManagerTable` | 39 | (+Ranking_group_id) |
| `MonsterStatEnhanceTable` | 30671 | **Group_id·Lv → Level_hp(int64)/attack/defence/broken_hp/projectile_hp** |
| `MonsterModelTable` | 209 | Id→**Mon_prefab**(코드)·Grade·Attribute·Class·Size |

→ **레이드 보스 로스터**(코드·이름·난이도·레벨)와 **레벨별 스탯 스케일**(HP/ATK/DEF/파츠HP)은 확보.
보스코드(`full_eca001`→`eca001`) → `MonsterModelTable.Mon_prefab` 정확매칭 → model_id·Grade·Class·Size.
검증: bba001 group 230000 = Lv55 HP 16.9M ~ Lv390 HP 5.87B (레이드 스케일 일치).

## ⚠️ 미해결 = 보스 → statenhance group + element 링크
각 보스의 **정확한 stat group·element** 를 잇는 다리 = `MonsterTable`
(monster_id → Element_id, Statenhance group). 그러나:
- `MonsterTable`(2035행)은 레코드마다 **가변길이 `Skill_data` 중첩리스트**(평균 ~964B/rec) +
  **metadata 필드셋/순서 drift**(예 model_id 가 스키마 index2 아닌 실제 index4) → 이름추론/heuristic
  풀 디코드 **불가**.
- 위치기반 우회(`Locale_Monster:{id}_name` 앵커 → 헤더 6 int32 + 다음앵커 직전 int) 시도했으나:
  앵커가 959/2035(실수-헤더 몬스터만; 이벤트몹 string-element 는 헤더길이 달라 누락) → "다음 앵커
  직전 int" 가 건너뛴 레코드의 엉뚱한 값을 Statenhance 로 오인 → **다수 보스가 group 230000 에
  몰려 동일 HP** = **신뢰불가**. ("valid group 959/959" 는 39개 중 우연일치 false validation.)
- 확정 헤더 필드: **h0=Id, h3=Element_id**(5속성 100001/200001/300001/400001/500001), **h4=Model_id**.
  Statenhance(마지막 필드)만 가변 trailer 때문에 위치추출 실패.

**정확한 링크엔 `MonsterTable` 풀 디코드 필요 = il2cpp 런타임 타입**(중첩 `SkillData` 레코드 스키마 +
필드 타입/순서) = **FunctionTable 와 동일한 벽**. → Apple Silicon 맥 frida-il2cpp-bridge 로 해소 예정.
그 타입 확보 시 `MonsterTable` clean 디코드 → boss→group→stat 완결.

## 대안 링크 후보 (미확인, 맥 전 시도 가능)
- `RaidPreset.Wave`(6304006/6700101) → spawn/spot → monster_id: 그러나 raid 용 `WaveDataTable.*` 파일
  부재. `MonsterCallingListTable`(72KB)·`MonsterFieldTable` 미조사.
- 보스코드 → monster_id 직접 패턴(model 151001 → monster 15100101?) 미검증.

## Season 39 Solo Raid 보스 (2026-07-07, `qa-260702-07b`)
**⚠️ 미래 시즌 = StaticData 재fetch 필수.** `qa-260611`(6/11)엔 season 38까지뿐 → `getFromNikkeStaticData.py`
재실행 → `qa-260702`(7/2) = **season 39** 포함. SoloRaidManager `Ranking_group_id`=시즌번호,
`Monster_preset`=preset_group. season39 → preset_group **10039** → 보스:

| 항목 | 값 |
|---|---|
| code | `ebg001_island_zeus` |
| model | 252021 (Grade5, Size4, Class3, Attribute4) |
| element | **400001 = ELECTRIC** ⚡ (monster 2520210141, 앵커 신뢰) |
| stat group | 230000 (solo raid 공유) — Lv200 HP329M/DEF9107, Lv390 HP5.87B/DEF30925 |
| Lv 사다리 | diff1: 45/85/120/145/175/185/200, diff2: 390 |

**ElementTable(clean)**: 100001 Fire · 200001 Water · 300001 Wind · **400001 Electric** · 500001 Iron.
weak cycle(각 Weak_element_id): Fire→Water, Water→Electric, Wind→Fire, Electric→Iron, Iron→Wind.

### 코어 판정 (ground truth 검증, 2026-07-07 정정)
사용자 ground truth: **s38 xba003_dmtr=몸통 / s37 bbg006_hsta=파츠(코어HP 무한)**. `MonsterPartsTable`
= **파츠당 1레코드**(Id=model×100+idx, ...01=메인바디). core 문자열=byte-scan 신뢰. **3분류**:
- **바디판정** (22 solo): MonsterParts에 **코어파츠 없음**. 코어=바디 약점존(Parts_type로 지정, 미디코드).
  예 s38. ⚠️ **무코어 vs 바디코어 확정구분 불가** — 구분자=`Parts_type` 필드(미디코드 영역).
- **파츠판정** (16 solo): 코어=**별도 파츠 엔티티**(is_main=false), 자체 `Hp_ratio`. **Hp_ratio=0=무한HP**.
  예 s37(Hp=0=무한). 무한 3종=s26 xbg002_zeus·s33 xbg003_hsta·s37 bbg006_hsta. 나머지 유한.
- **메인파츠부착** (1 solo = **s39 ebg001_island_zeus**): 코어 소켓/본이 **메인바디 파츠**에(is_main=true),
  Hp_ratio=10000(바디HP). **이례**(is_main인데 코어문자열). ebg001 계열 특유(core_bone001[+R+L]).

### ✅ MemoryPack 완전 디코드 (2026-07-07 — il2cpp 벽 우회, 맥 불필요)
**`.mpk` = MemoryPack**(Cysharp C# 직렬화, 커스텀 아님). 스키마(필드 순서/타입) 출처 =
[`github.com/SharpnelXu/nikke-mpk-json-converter`](https://github.com/SharpnelXu/nikke-mpk-json-converter)
C# 모델(`[MemoryPackable]`/`[MemoryPackOrder]`). → **metadata drift/타입추론 불필요, 전 표 clean 디코드.**
도구 = `memorypack_decode.py`(MonsterParts/MonsterTable/MonsterStatEnhance clean, off==len). 와이어포맷:
Array=`[i32 len]`+elem · Object=`[u8 memberCount]`+members(Order순) · string=`~byteCount`+utf16len+utf8 ·
int=4B long=8B bool=1B enum=4B.

**MonsterPartData 확정 스키마**(23필드): id·model·parts_name·damage_hp_ratio·**hp_ratio**·defence·
destroy_after_anim/movable(bool)·**passive_skill_id**·visible_hp(bool)·linked_parts·weapon_object(str[])·
weapon_object_enum·**parts_type**(enum Body=6/Chest=7/Head=3/Weapon=13-22…, **Core 없음**)·parts_object(str[])·
resist×3·attack·parts_skin·destroy_anim_trigger·**is_main_part**(bool)·**is_parts_damage_able**(bool).
**MonsterData**: id(long)·**element_id(int[]배열!)**·model·ui_grade·…·detector_center/radius(**균일 500=코어아님**)·
…·**skill_data(MonsterSkillInfoData[]: skill_id+use/hurt_function_id)**·**statenhance_id**. 모델당 monster 변종
다수 → **solo raid 변종 = statenhance_id=230000**.

### 코어 판정 = SOLVED (ground truth 전부 검증: s37/s38/s9/s22/s18/s39)
코어 = `weapon_object`/`parts_object` 에 core collider(core_col/core_bone/socket_core) 가진 파츠.
- **파츠판정**: is_main=false **별도 파츠**. `hp_ratio=0`=**무한**(s26/s33/s37) · `hp_ratio>0 & passive_skill_id≠0`=**재생**(s9/s22 Head hp10000 passive7252002; s7 bbg006 hp1억) · 그 외 유한.
- **몸통판정(메인바디 부착)**: is_main=true 메인바디 파츠에 코어 collider(바디HP). **s39 유일**(Body, passive7252022).
- **몸통판정(암묵)**: 코어 collider 파츠 **없음** → 코어=바디 기본약점(prefab). s38 등 25종.

종합 = `staticdata_solo_raid.py` → **`raid/solo_raid_boss.{json,md}`** (39 solo × 정체/element/model/lv/
스탯230000/**전 파츠[type·is_main·damageable·hp_ratio·passive]**/코어판정). union 드롭(사용자).
잔여였던 보스 스킬값: **FunctionTable/StateEffectTable 디코드 완료(2026-07-08, `FUNCTIONTABLE_DECODE_PLAN.md` §0)**
— MonsterTable.skill_data 의 function_id → FunctionData 해석 가능. 파츠 passive 실해석 예: 7252002 =
Immune{Stun/ForcedStop/GravityBomb} + **ImmuneDamage_MainHP** (구 "재생" 관측의 데이터 실체 — K11 에서 의미 확정).
잔여 = `MonsterSkillTable`(캐스팅 스킬 자체 수치) 필요 시 추가 + D3 조립.

## 산출물
- `staticdata_raid_decode.py` — SoloRaid Preset/Manager·MonsterModel 등 flat 표 clean 디코드(bool+NF) → `raid/*.json`(gitignore).
- `memorypack_decode.py` — **MemoryPack 정밀 디코더**(스키마=SharpnelXu C# 모델): MonsterParts/MonsterTable/MonsterStatEnhance → `mpk/*.json`(gitignore).
- `staticdata_solo_raid.py` — 조립 → **`raid/solo_raid_boss.{json,md}`**(39 solo, 검증완료). (이전 positional 조립본 raid_assemble/raid_full 은 MemoryPack 정밀본으로 대체·삭제.)
- 교차링크: MemoryPack 포맷 = `STATICDATA_PREP.md`, 로컬 sd.bin = `LOCAL_GAME_DATA.md`, FunctionTable/nikke-einkk = 메모리 `project_blabla_catalog`.
