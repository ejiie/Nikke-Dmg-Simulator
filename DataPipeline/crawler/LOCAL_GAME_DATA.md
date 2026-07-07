# 로컬 게임설치 (`C:\NIKKE`) 데이터 전수조사 (2026-07-07)

> 목적: 업데이트마다 갱신되는 **로컬 디스크** 데이터 파일 식별 — 서버 StaticData
> (`getFromNikkeStaticData.py`)로 안 잡히는 보스 목록/전투상수 등을 로컬에서 확보 가능한지.
> 결론: **평문 게임데이터 표는 `sd.bin`의 5개 JSON뿐.** 나머지는 전부 암호화(NKDB catalog + NKAB 번들).

## 1. 디렉토리 지도 (`C:\NIKKE`)

| 경로 | 정체 | per-patch 갱신? | 우리에게 |
|---|---|---|---|
| `NIKKE\game\` | Unity 빌드(GameAssembly.dll 259MB, il2cpp) | 클라 업데이트 | metadata.dat=스키마(기확보) |
| `NIKKE\game\nikke_Data\StreamingAssets\`**`sd.bin`** | **ZIP → 5표 평문 JSON** | 클라 업데이트 | ⭐ 아래 §2 |
| `…\StreamingAssets\aa\catalog.db` (+`.nds`) | `NKDB` 암호화 Addressables catalog | 클라 업데이트 | 암호화, 에셋 인덱스 |
| `…\StreamingAssets\aa\settings.json` | 호스트/버전/**AES KeySets v33–37** | 런타임 갱신 | 번들 복호키(§4) |
| `Unity\com_proximabeta_NIKKE\naps\` | Unity 번들 캐시 20GB (`UnityFS`/`NKAB` 암호화) | 다운로드마다 | 아트/프리팹/오디오·lua |
| `LocalLow\com_proximabeta\NIKKE\com.shiftup.addressables\`**`{core,dp,fd}_<ver>_catalog.db`** | 프로젝트별 `NKDB` 암호화 catalog (**버전이 파일명에**) | **패치마다** | dp=data pack(§4) |
| `LocalLow\com_proximabeta\NIKKE\*.nkcache` | **SQLite** = 클라 UI/세이브 상태(방문·팝업·SaveStrings) | 플레이마다 | 게임데이터 표 아님 |
| `LocalLow\com_proximabeta\NIKKE\NKSD_TRIGGER_*` | ZIP→`trigger.txt` = **플레이어 이벤트 로그**(계정별) | 플레이마다 | StaticData 아님 |
| `LocalLow\com_proximabeta\NIKKE\NKPERSISTSD_*` | JSON prefs(리뷰·공지 무시일) | 플레이마다 | 무시 |

**함정 정정**: `NKSD_TRIGGER`/`NKPERSISTSD`/`.nkcache` 는 이름이 StaticData(SD) 같지만
전부 **클라 로컬 상태/텔레메트리**다. 게임 데이터 표 아님.

## 2. ⭐ `sd.bin` — StaticData 부트스트랩 5표 (평문 JSON)

포맷 = `{ "version": …, "records": [ {필드:값}, … ] }`. **필드명·타입 self-describing**
(JSON int/float/str/bool/array) → **il2cpp 타입 불필요.** 서버 .mpk 는 같은 데이터의 packed 판.
추출: `python getFromLocalSdBin.py` → `Database/raw/staticdata/sd_bin_json/` (gitignore).

| 표 | 행 | 내용 |
|---|---|---|
| `CampaignChapterTable` | 43 | world/chapter, field_id |
| `CampaignStageTable` | 3825 | id·chapter·**stage_category**(Normal 2477/Hard 1059/Extra 160/**Boss 129**)·**field_monster_id**·**monster_stage_lv**·standard_battle_power |
| `CharacterReactionTable` | 2671 | 로비 리액션(전투 무관) |
| `ConfigBattleTable` | 139 | ⭐ **전역 전투상수** KV (아래) |
| `ConfigGameTable` | 257 | 전역 게임설정 KV(인벤토리/UI 등) |

### 2a. 캠페인 보스 = 배선 대상 아님 (사용자 지시 2026-07-07)
`CampaignStageTable` 의 `stage_category=="Boss"`(129 스테이지, field_monster_id 8종)는
**캠페인 몬스터** — 시뮬 attend 대상 **아님**. **attend 대상 = 레이드 보스 몬스터**
(Union/Solo Raid). 레이드 보스 로스터/스탯은 sd.bin 밖 → **서버 .mpk**(`MonsterTable` +
레이드 stage 표, 실패 327셋)에 있고, 필드셋 교정(§3)이 필요 → 별도 작업.
CampaignStage 는 참고 자료로만 추출(배선 X).

### 2b. ⭐ ConfigBattleTable — 전역 전투상수 (값 = ×10000 스케일 다수)
`getFromLocalSdBin.py` 가 `ConfigBattleTable_kv.json`(flat {id:value}, gitignore)도 뽑음.

**채택 정책 (사용자 지시 2026-07-07):**
- ✅ **버스트 게이지 상수만 프로젝트에 반영** → `Database/processed/burst_gauge_table.json`(커밋).
- ⏸ **코어·적정거리 = 현행 유지** (엔진 기존값 `core_damge_rate=25000`=2.5× · `BonusRangeRate=13000`=1.3×
  와 일치 — **검증만, 엔진 변경 없음**).
- ⏸ ElementBonusDamage(+10%) = 미채택(ElementAdvantage 보류 유지). cover_hp/groupshot/fire_speed = 참고만.

**채택된 버스트 게이지 상수:**
```
burst_energy_max            = 1000000  # 게이지 cap (도달 시 버스트 준비)
ally  per_sec=100  kill{minion,elite,centurion,boss}=960/1440/1920/2880
      use_skill=200 skill_hit=100 shot_hit=4 hurt=480 cover_hurt=0 empty_ammo=13
monster per_sec=250 use_skill=100 skill_hit=10 shot_hit=4 hurt=4
```
(kill 등급 m/e/c/b = minion/elite/centurion/boss — `spot_mod_defense_*_count` 명명과 일치.)

## 3. 왜 .mpk 서버팩 327표 디코드가 실패했나 (root cause 확정)
`sd.bin` JSON 과 metadata 스키마를 대조하니: `CampaignStageRecord` metadata=**27필드**
(`Parents_id`,`Character_lv` 포함) vs JSON 실제 직렬화=**25필드**(그 둘 없음).
→ **il2cpp Record 클래스 필드목록 ≠ 실제 .mpk 직렬화 필드셋.** 타입 문제 이전에
**필드셋 drift** 가 있어 정렬이 어긋나며 cascade. **JSON = 실제 직렬화 ground truth**,
metadata+.mpk 조합보다 우월. sd.bin 밖 표는 이 JSON 을 못 구해 여전히 어려움.

## 4. 미개척: dp(data pack) catalog 복호 (보류)
`dp_<ver>_catalog.db` = `NKDB` 완전 암호화(고엔트로피, 평문 표이름 0). `.nds`(96B)=키material.
`settings.json` 의 AES KeySets(v33–37, 5키/셋)로 복호 이론상 가능하나 (a) NKAddressable
복호 스킴 RE 필요, (b) dp 는 십중팔구 **에셋 번들**(테이블 아님 — 테이블=서버 .mpk).
→ 투자 대비 불확실, **보류.** 전 표 JSON 이 목표면 이쪽보다 서버팩 필드셋 교정이 유효.

## 5. 산출물
- `getFromLocalSdBin.py` — sd.bin → 5 JSON + Config*_kv.json 추출(로컬경로 의존, 게임설치 필요).
- 추출물 `Database/raw/staticdata/sd_bin_json/` = **gitignore**(게임데이터, 재배포금지).
- 교차링크: 서버 StaticData=`STATICDATA_PREP.md`, 표 인벤토리=`STATICDATA_TABLES.md`,
  디코드 워크리스트=`STATICDATA_WORKLIST.md`.
