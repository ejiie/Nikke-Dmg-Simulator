# StaticData 디코드 가이드 — il2cpp 스키마 덤프 (사용자 PC)

> 목적: StaticData 표(특히 `FunctionTable`)의 **레코드 스키마(필드명·타입·순서)** 를 게임 바이너리에서
> 뽑아, 이미 깬 표 바이너리 포맷에 입혀 디코드한다.
> 산출 = `Nikke.proto` + `dump.cs` → 나에게 전달 → Python 디코더 포팅 + 스킬 ETL.

## ⚠️ 경고 (먼저 읽기)
**MetadataDumper 단계는 게임 프로세스에 DLL 을 주입한다 → 안티치트/계정 밴 위험.** 본인 판단·책임.
밴 우려 시: (a) 부계정/에뮬에서, (b) 메인계정 미접속 중 실행, (c) 이 경로 포기하고 수치표만 활용.
StaticData **fetch/복호 자체**(`getFromNikkeStaticData.py`)는 주입 없음 — 위험은 **이 메타데이터 덤프 단계만**.

---

# 📱 모바일 경로 (Android — 권장, 계정/밴 우회)

**핵심**: il2cpp metadata 는 앱 **스플래시(프로세스 시작)** 때 메모리에 복호됨 — 로그인/계정 바인딩 전.
→ **타이틀 화면까지만** 켜고 덤프 → **계정 불필요(실명인증 무관) + 인게임 행동 0.** 에뮬은 일회용이라 격리.

## 준비 (모바일)
- rooted Android: 물리 기기(arm64) 또는 ARM 지원 에뮬. **Magisk + Zygisk 활성**.
- NIKKE 글로벌 APK+OBB (APKPure 등). 패키지명 = 설치 후 `adb shell pm list packages | grep -i nikke` 로 확인(`com.proximabeta.nikke` 류).
- PC 에 `adb`.

## 단계 (Zygisk-Il2CppDumper — 런타임 자동 덤프, 암호화 metadata 자동 처리)
1. Magisk 에 [Perfare/Zygisk-Il2CppDumper](https://github.com/Perfare/Zygisk-Il2CppDumper) 모듈 flash → 재부팅.
2. 모듈 `game.config.json` 에 NIKKE 패키지명 지정 (모듈 README 참조).
3. NIKKE 실행 → **타이틀 화면 도달** 하면 모듈이 자동 덤프:
   `/data/data/<pkg>/files/` 에 `dump.cs` · `il2cpp.h` · `script.json` · dump 바이너리. **로그인 말고** 앱 종료.
4. 추출: `adb shell su -c 'cp -r /data/data/<pkg>/files /sdcard/nikkedump'` → `adb pull /sdcard/nikkedump`.
5. (선택) dump 바이너리 + `script.json` → PC `Il2CppDumper` → DummyDll → `NikkeProtoDumper` → `Nikke.proto`.

> Magisk 싫으면: `frida-il2cpp-bridge` + `frida-server`(root) 스크립트로 런타임 덤프도 가능.
> x86 에뮬은 arm64 라이브러리 번역 이슈 가능 → **물리 arm64 기기가 안정적**.

## 나에게 전달 (모바일·PC 공통)
`dump.cs`(핵심) + `Nikke.proto`(있으면). 큰 파일이면 표 레코드 클래스만 발췌해도 됨.
표 클래스 검색: `FunctionTable`·`StateEffectTable`·`SkillInfoTable`·`CharacterSkillTable`·`MonsterTable`·
`MonsterPartsTable`·`MonsterStatEnhanceTable`·`CharacterStatTable`. → 각 레코드 클래스 **필드(이름+타입+순서)**.
→ §7(=`STATICDATA_PREP.md`) 포맷에 타입 입혀 표별 디코더 + ETL 즉시 완성.

---

# 🖥 PC 경로 (대안 — VS2022 필요, 주입 방식)

## 준비물 (PC)
- NIKKE 설치된 **Windows PC** (글로벌 `nikke.exe` + `GameAssembly.dll` 존재).
- Visual Studio 2022 (.NET 빌드), Python 3, git.
- [Hiro420/NikkeTools](https://github.com/Hiro420/NikkeTools), [Perfare/Il2CppDumper](https://github.com/Perfare/Il2CppDumper) (release exe).

## 단계 (PC)

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

## 내가 이미 깬 바이너리 포맷 (스키마 입히면 끝)
표 `.mpk` 레코드 포맷 = **역공학 완료.** 권위 스펙 = [`STATICDATA_PREP.md`](STATICDATA_PREP.md) §7:
`[u32 count]` + 레코드 `[u8 nFields][필드…]`(선언순, per-field 타입태그 없음), 문자열 =
`[i32 -(len+1)][u32 len][utf8]`(marker 가 `-(len+1)` 로 자기검증). 순수 수치표는 이미 clean 디코드
(AttractiveLevel 검증). **혼합표(Function/Monster/Skill)는 float↔int·int64 구분이 안 돼** 미완 —
그래서 `dump.cs` 의 표 레코드 클래스 필드 타입/순서만 받으면 §7 에 입혀 표별 디코더 + ETL 즉시 완성.

## 우선순위
1. `FunctionTable` + `StateEffectTable` + `SkillInfoTable` — 스킬 런타임(THE GAP) 직결.
2. `MonsterTable`/`MonsterPartsTable`/`MonsterStatEnhanceTable` — BossTarget(K11).
3. 나머지 — 필요시.

## Sources
모바일: [Perfare/Zygisk-Il2CppDumper](https://github.com/Perfare/Zygisk-Il2CppDumper). PC: [Hiro420/NikkeTools](https://github.com/Hiro420/NikkeTools) · [Perfare/Il2CppDumper](https://github.com/Perfare/Il2CppDumper). 포맷/디코드 분석 = [`STATICDATA_PREP.md`](STATICDATA_PREP.md) §6·§7.
