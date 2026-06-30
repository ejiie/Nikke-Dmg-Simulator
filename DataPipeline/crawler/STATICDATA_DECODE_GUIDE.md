# StaticData 디코드 가이드 — il2cpp 스키마 덤프 (사용자 PC)

> 목적: StaticData 표(특히 `FunctionTable`)의 **레코드 스키마(필드명·타입·순서)** 를 게임 바이너리에서
> 뽑아, 이미 깬 표 바이너리 포맷에 입혀 디코드한다.
> 산출 = `Nikke.proto` + `dump.cs` → 나에게 전달 → Python 디코더 포팅 + 스킬 ETL.

## ⚠️ 경고 (먼저 읽기)
**MetadataDumper 단계는 게임 프로세스에 DLL 을 주입한다 → 안티치트/계정 밴 위험.** 본인 판단·책임.
밴 우려 시: (a) 부계정/에뮬에서, (b) 메인계정 미접속 중 실행, (c) 이 경로 포기하고 수치표만 활용.
StaticData **fetch/복호 자체**(`getFromNikkeStaticData.py`)는 주입 없음 — 위험은 **이 메타데이터 덤프 단계만**.

## 준비물
- NIKKE 설치된 **Windows PC** (글로벌 `nikke.exe` + `GameAssembly.dll` 존재).
- Visual Studio 2022 (.NET 빌드), Python 3, git.
- [Hiro420/NikkeTools](https://github.com/Hiro420/NikkeTools), [Perfare/Il2CppDumper](https://github.com/Perfare/Il2CppDumper) (release exe).

## 단계

### 1. 게임 디렉터리 확인
`nikke.exe`·`GameAssembly.dll`·`nikke_Data/il2cpp_data/Metadata/global-metadata.dat`(암호화) 위치 확인.
(런처 설치 경로, 보통 `...\NIKKE\game\` 류.)

### 2. metadata 복호 (NikkeTools/MetadataDumper) — ⚠️주입 단계
1. `MetadataDumper/NikkeMetadataDumper.sln` VS2022 빌드(Win64) → `NikkeMetadataDumper.dll`.
2. 그 dll + `Gadget/` 폴더 파일들(`winhttp.dll` 등)을 **`nikke.exe` 옆에** 복사.
3. 게임 실행 → 게임 디렉터리에 **복호된 `global-metadata.dat`** 생성됨. 게임 끄고 그 파일 빼냄.
   (Gadget 의 `winhttp.dll` 은 DLL 프록시 로더 — 그래서 안티치트 위험.)

### 3. il2cpp 덤프 (Il2CppDumper)
`Il2CppDumper.exe GameAssembly.dll global-metadata.dat`(복호본) 실행 →
출력: **`DummyDll/`**, **`dump.cs`**, `script.json` 등. ← `dump.cs` 가 핵심(모든 클래스 필드 정의).

### 4. (선택) proto 덤프 (NikkeTools/Protobuf)
`Protobuf/NikkeProtoDumper.sln` 빌드 → `DummyDll/` 폴더를 exe 에 드래그 → **`Nikke.proto`**(proto3) 생성.

### 5. 나에게 전달
다음을 주면 디코더 포팅함 (큰 파일이면 표 클래스 부분만 발췌해도 됨):
- **`Nikke.proto`** (있으면) — 표가 proto 메시지로 정의됐으면 이게 필드명/타입/순서 키.
- **`dump.cs`** 에서 표 레코드 클래스들 — 클래스명 검색:
  `FunctionTable`·`FunctionTableRecord`·`StateEffectTable`·`SkillInfoTable`·`CharacterSkillTable`·
  `MonsterTable`·`MonsterStatEnhanceTable`·`MonsterPartsTable`·`CharacterStatTable`.
  각 레코드 클래스의 **필드 선언(이름+타입+순서)** 가 필요.

## 내가 이미 깬 바이너리 포맷 (스키마 입히면 끝)
표 `.mpk` = `[u32 count]` + 레코드마다 `[u8 nFields][필드…]`. 필드는 **선언순**, per-field 타입태그 없음:
- 정수 = `int32`(LE 4B). 검증: AttractiveLevel(nf21 → id/lv/point), CharacterStat(lv1 HP13500/ATK600/DEF90).
- 문자열 = `[u32 len][utf8 len바이트]`. 예: FunctionTable rec0 에 `"Locale_Skill:20111_name"`.
- (스키마에서 float/int64/bool/enum 타입 나오면 그에 맞춰 리더 분기 추가 — dump.cs 타입으로 결정.)
→ 스키마(필드 타입/순서)만 오면 `getFromNikkeStaticData.py` 에 표별 디코더 + 스킬 ETL 붙임.

## 우선순위
1. `FunctionTable` + `StateEffectTable` + `SkillInfoTable` — 스킬 런타임(THE GAP) 직결.
2. `MonsterTable`/`MonsterPartsTable`/`MonsterStatEnhanceTable` — BossTarget(K11).
3. 나머지 — 필요시.

## Sources
[Hiro420/NikkeTools](https://github.com/Hiro420/NikkeTools) · [Perfare/Il2CppDumper](https://github.com/Perfare/Il2CppDumper). 디코드 분석 = `STATICDATA_PREP.md` §6.
