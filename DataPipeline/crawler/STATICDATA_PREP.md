# StaticData 복호 — 준비 (read-only 분석, 2026-07-01)

> 목적: blablalink 에 **없는** 게임 데이터(스킬 **FunctionTable** = 런타임 효과 의미, **monster/boss** 전투스탯 = BossTarget K11)를 게임 공식 StaticData 에서 확보.
> 상태: **메커니즘 분석 완료 / 미실행.** 실행("시도")은 사용자 명시 go-ahead 후 (방침: blabla 먼저 → 그 다음 StaticData).

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

## 6. 다음 (디코드 단계 — 더 깊은 RE)
테이블 레코드 정밀 파싱 = 스키마 확보 필요. 옵션:
1. `NikkeTools/Protobuf`(il2cpp 덤프 → `Nikke.proto`) — **게임 클라 설치 + Il2CppDumper 필요**(무거움).
2. 커뮤니티 proto/스키마 덤프 탐색.
3. 표별 바이너리 역공학(고정표=수치 정렬 추정 가능, String 표는 난해).
우선 = FunctionTable/StateEffect 스키마(스킬 런타임 직결). 산출도 원본 대량복제면 커밋 신중(§3).

## Sources
[Hiro420/NikkeTools](https://github.com/Hiro420/NikkeTools) — `StaticData/NikkeStaticData/Program.cs` · `ResStaticDataPackInfo.cs` 정독.
