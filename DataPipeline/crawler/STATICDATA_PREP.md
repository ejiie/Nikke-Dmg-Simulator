# StaticData 복호 — 준비 (read-only 분석, 2026-07-01)

> 목적: blablalink 에 **없는** 게임 데이터(스킬 **FunctionTable** = 런타임 효과 의미, **monster/boss** 전투스탯 = BossTarget K11)를 게임 공식 StaticData 에서 확보.
> 상태: **실행 완료** — fetch(`getFromNikkeStaticData.py`) + MemoryPack 디코드(`memorypack_decode.py`)로 해소 (2026-07-07~08). 이 문서 = 메커니즘/포맷 기록.

## 1. 메커니즘 (출처: `Hiro420/NikkeTools` StaticData, 정독)
게임 설치 불요 — 라이브 로비 서버에서 데이터팩을 받아 2단 복호. 게임 클라이언트가 받는 그 데이터.

1. **팩 정보**: `POST https://global-lobby.nikke-kr.com/v1/get-static-data-pack-info-mpk`
   - 헤더 `Accept/Content-Type: application/octet-stream+protobuf`, 빈 바디, TLS1.1.
   - 응답 protobuf `ResStaticDataPackInfo` (wire 수동 파싱 가능):
     `1:string Url · 2:int64 Size · 3:bytes Sha256Sum · 4:bytes Salt1 · 5:bytes Salt2 · 6:string Version`
2. **다운로드**: `GET {Url}` → 암호화된 StaticData.pack 바이트.
3. **복호 (2단)**, `password` = RE 로 추출된 하드코딩 base64 키(NikkeTools 에 공개):
   - `key1 = PBKDF2(password, Salt1, 10000, SHA256, 32B)`, `key2 = PBKDF2(password, Salt2, …)`.
   - `part1 = AES-CBC(no-pad) decrypt(pack, key2)` (AES key=key[:16], IV=key[-16:]).
   - part1 = zip → entry `data` 추출 = `innerEncrypted`.
   - `finalZip = AES-CTR decrypt(innerEncrypted, key1)` → **StaticData.zip** (게임 테이블 아카이브).
4. 내부 포맷: 엔드포인트 `-mpk` 접미사 → **MessagePack** 테이블 추정(확정은 1회 fetch 후 검사).

## 2. Python 이식성 — trivial
순수 표준 crypto. C# 도구 빌드/실행 불필요, 파이프라인 통합 가능:
`hashlib.pbkdf2_hmac` + `cryptography`/`pycryptodome`(AES-CBC/CTR) + `zipfile` + 수동 varint protobuf 파서(6필드). ~60줄. → `getFromNikkeStaticData.py`(미작성, 시도 단계에서).

## 3. ⚖️ 법적 posture (중요)
- StaticData 는 게임 클라가 받는 데이터팩과 동일(읽기 전용, **모딩 아님**). NikkeTools 면책=모딩 밴 관련.
- **DMCA 위험 = 재배포**: 차단된 `hibikidesu/nikke-data` 는 복호 데이터를 **호스팅**해서 신고됨. **fetch ≠ redistribute.**
- 회색 요소: RE 추출 하드코딩 복호키 사용 + 사설 엔드포인트 접근.
- **규칙**:
  1. 복호 StaticData(원본/zip/추출 테이블)는 **절대 커밋·재배포 금지** → `.gitignore`(portraits·full-raw 처럼 로컬).
  2. 우리가 **필요한 표만**(FunctionTable·monster) 우리 포맷으로 **derive**, 파생 산출도 원본 수치 대량 복제면 커밋 신중.
  3. 라이브 서버 fetch = 이 환경에서 **사용자 명시 go-ahead 없이는 실행 안 함**(crawler 정책 + 법적 민감도 가중).

## 4. 얻을 것 (우선순위)
1. **FunctionTable / StateEffect 류** — roledata `function_id_list` 의 효과 의미(타입/트리거) → 스킬 런타임을 LLM 없이 공식 구동. 프로젝트 최대 갭(THE GAP) 직격.
2. **monster / stage / boss 테이블** — HP/파츠/DEF/속성/거리 → `BossTarget`(K11).
3. (보조) CharacterStatTable 등으로 stat 조립 교차검증.

## 5. 시도 결과 (2026-07-01 — 사용자 go-ahead, 실행 완료)
`getFromNikkeStaticData.py` 작성 → **fetch+복호 1회 성공**(Python 이식 §2 그대로, 1트). StaticData.zip
16.3MB, 버전 `qa-260611-06b/536334`. **`Database/raw/staticdata/` (gitignore, 재배포 금지).**

**인벤토리**: 9084 엔트리(9072 `.mpk` + 12 csv), 1047 고유 테이블. **프로젝트 갭 전부 존재**:
- 스킬 런타임(THE GAP): `FunctionTable`(19111 함수, 6.5MB) · `StateEffectTable`(5113) · `SkillInfoTable`(2.1MB) · `CharacterSkillTable` · `SkillLevelPointTable`.
- BossTarget(K11): `MonsterTable`(2035) · `MonsterStatEnhanceTable` · `MonsterSkillTable` · `MonsterPartsTable`(668, 파츠) · `CampaignStageTable`/`LostSectorStageTable`.
- stat 교차검증: `CharacterStatTable`(64800) · `CharacterStatEnhanceTable` · `CharacterLevelTable` · `CharacterShotTable` · `CoverStatEnhanceTable`.

**⚠️ 포맷 = 커스텀 바이너리, msgpack 아님**: 확장자만 `.mpk`. head `28 00 00 00`(=root offset/count) 후 레코드.
naive int32 디코드 불일치(staticdata 277 ≠ blablalink id 1) → **FlatBuffers 또는 커스텀 packed, 테이블별
스키마 의존.** 정밀 디코드엔 **proto/.fbs 스키마** 필요(필드명·타입·순서).

## 6. 디코드 단계 — 진행 결과 (2026-07-01)

**옵션 A (커뮤니티 스키마/디코더) = 실패**: 공개 repo 에 전투표(FunctionTable/SkillInfo/StateEffect)
디코더·`.proto`·디코드 JSON 없음. NikkeTools 가 유일 디코더지만 il2cpp 필요(=B). nikke-db 는
combat 표를 비공개 API 로 서빙(번들=프로필/UI JSON 뿐).

**포맷 부분 역공학 (C)**: 레코드 = `[u32 count]` + 레코드마다 `[u8 nFields][필드…]`.
- **수치 전용 표 = 해독됨**: `AttractiveLevelTable` 완벽 일치(rec0 nf=21 → id1/lv1/point150, blablalink 동일).
  `CharacterStatTable` rec0 = (…, lv1, **HP 13500, ATK 600, DEF 90**) = class base 일치.
- **String 포함 표(FunctionTable 등) = 스키마 의존**: 필드가 혼합타입(int32 + 인라인 문자열
  `[u32 len][utf8]`, 예 `"Locale_Skill:20111_name"`), **per-field 타입태그 없음** → 필드 타입/순서를
  알아야 세그먼트 가능. 표별 정렬도 미묘차(CharacterStat stride). → 스키마(proto) 필수.

**옵션 B (il2cpp proto 덤프)**: `Nikke.proto` = 정밀 디코드 키. 단 `NikkeTools/{MetadataDumper,Protobuf}`
는 **NIKKE 게임 클라 설치 머신**에서 Il2CppDumper 로 실행해야 함 — **이 자동화 환경엔 게임 미설치라 불가.**
→ 사용자 PC(게임 설치)에서 1회 덤프 → `Nikke.proto` 확보 → Python 디코더 포팅 + 스킬 ETL.

**✅ SOLVED (2026-07-01)**: B(il2cpp)를 사용자 에뮬(LDPlayer)서 시도 → frida/dd 둘 다 arm 번역에 막힘.
**우회 성공** = frida-il2cpp-bridge 대신 **디스크 파일 직접 추출**: `libil2cpp.so`(보호됨, Il2CppDumper 실패)
+ **복호된 `global-metadata.dat`(v31) pull** → **메타데이터만 파싱**(`metadata_fields.py`)해 표 Record 클래스의
**필드명·순서** 확보(바이너리 registration 불필요!). 580 Record 스키마 → `all_records.json`.
+ **int64 자동감지**(고정 stride: `(stride-1-4·nf)/4`=int64 개수, hp계열 배정) → **CharacterStat/MonsterStatEnhance
완전 디코드**(예: monster Lv250 HP 58억 int64). **THE GAP(FunctionTable) 포함 전 표 디코드 가능.**
표 인벤토리 = `STATICDATA_TABLES.md`.

## 7. 표 바이너리 포맷 스펙 (역공학 완료분, 2026-07-01)
```
Table = [u32 count] + count × Record
Record = [u8 nFields] + nFields × Field   (선언순, per-field 타입태그 없음)
Field:
  int32  = 4B LE            (스키마상 int/enum/bool; float 도 4B 라 정렬엔 무해)
  string = [i32 -(len+1)] [u32 len] [utf8 len바이트]   ← marker 가 -(len+1) 로 자기검증
```
**검증**: `AttractiveLevelTable` 100% clean(순수 int, rec0=id1/lv1/point150). `MonsterTable` rec0 =
`[11200101, 0,1,100001,112001,1, "…_name","…_appearance_name","…_description", 2560000,2560000,2560000,
0,0, 2560000, 32000, 35840, …]` (HP/ATK/DEF 수치 보임).

**부분 해결 (스키마+포맷)**: `metadata_fields.py`(필드명·순서) + 디코더(`staticdata_decode.py`):
- **✅ 완전 디코드**(스칼라+단순): CharacterStat(64800)·MonsterStatEnhance(30671, Lv1200 HP 1105억 int64)·
  AttractiveLevel·Element·RecycleResearch·SkillInfo(9130). **monster 수치·캐릭 레벨스탯·속성상성 확보.**
- **list 인코딩 확정** = `[i32 count] + count×중첩레코드`(재귀 `[u8 nf][fields]`). 문자열=마커+printable 검증.
- **⚠️ 미해결 = 필드 타입 + 필드셋 drift**: `int32 vs int64 vs float vs List<int> vs List<struct> vs struct`
  구분이 게임 바이너리의 il2cpp **type array** 에만 있음(보호됨). **추가 root cause(2026-07-07 확정)**:
  metadata Record 클래스 필드목록 ≠ 실제 .mpk 직렬화 필드셋 (예 `CampaignStageRecord` metadata 27필드
  vs 실제 25필드, `Parents_id`/`Character_lv` 미직렬화) → 타입 이전에 정렬부터 어긋나 cascade. 이름추론이
  혼합 복잡표(**FunctionTable**/MonsterTable-base/CharacterShot/CharacterSkill)에서 한계 → 그 표들은 미완.
- **완전 디코드 = arm64 네이티브 frida-il2cpp-bridge**(런타임 전체 타입, 보호·번역 면역). 그 환경 생기면 끝.

## 8. 로컬 디스크 우회 — `sd.bin` (2026-07-07, `C:\NIKKE` 전수조사)
서버 .mpk 를 안 거치고, 게임설치 `nikke_Data/StreamingAssets/sd.bin`(ZIP) 안에 **5개 표가 평문 JSON**
(`{version, records:[{필드:값}]}`, self-describing → 타입/스키마 불필요)으로 동봉됨:
`CampaignStageTable`(보스 129 스테이지, field_monster_id·monster_stage_lv)·`CampaignChapterTable`·
`ConfigBattleTable`(⭐ 전역 전투상수 core_damge_rate/BonusRangeRate/ElementBonusDamage/ulti_gauge)·
`ConfigGameTable`·`CharacterReactionTable`. 추출=`getFromLocalSdBin.py`. **이게 위 필드셋 drift 의
ground truth 증거이자, 5표에 한해 완전 디코드.** 전체 지도·전역상수·미개척(dp catalog 복호)
= `LOCAL_GAME_DATA.md`. 나머지 표는 여전히 서버 .mpk(필드셋 교정 필요).

## Sources
[Hiro420/NikkeTools](https://github.com/Hiro420/NikkeTools) — `StaticData/NikkeStaticData/Program.cs` · `ResStaticDataPackInfo.cs` 정독.
