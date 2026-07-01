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

## 에뮬레이터 경로 (LDPlayer/MuMu + frida — Magisk 불필요, 권장)
루팅 토글 + `frida-il2cpp-bridge`의 `Il2Cpp.dump()`가 dump.cs 를 바로 생성. 벽돌·계정 무관.

1. **LDPlayer 9** or **MuMu 12** 설치 → 설정에서 **Root ON** + ADB ON → 재시작.
2. PC: `pip install frida-tools`, Node.js. `adb connect 127.0.0.1:5555`(LDPlayer 기본) → `adb devices` 확인.
3. abi 확인: `adb shell getprop ro.product.cpu.abi` (보통 `x86_64`).
4. **frida-server**(= frida-tools 와 **같은 버전**, 위 abi) 다운 → push+실행:
   `adb push frida-server /data/local/tmp/` → `adb shell su -c 'chmod 755 /data/local/tmp/frida-server; /data/local/tmp/frida-server &'` → `frida-ps -U` 로 확인.
5. NIKKE 설치(에뮬 플스토어 or APK+OBB). 패키지: `adb shell pm list packages | grep -i nikke`.
6. agent 준비: `npm i frida-il2cpp-bridge && npm i -g frida-compile`. `agent.ts`:
   ```ts
   import "frida-il2cpp-bridge";
   Il2Cpp.perform(() => { Il2Cpp.dump("/sdcard/nikke_dump.cs"); console.log("DUMPED"); });
   ```
   `frida-compile agent.ts -o agent.js`
7. 실행: `frida -U -f <pkg> -l agent.js` → NIKKE 스폰 → 스플래시서 il2cpp init → `DUMPED` 로그 + `/sdcard/nikke_dump.cs`. (로그인 불필요.)
8. 추출: `adb pull /sdcard/nikke_dump.cs`.

> **번역 이슈**: x86 에뮬이 NIKKE arm64 를 번역 실행 → frida(x86) 가 libil2cpp 를 못 찾을 수 있음.
> 그럴 때: MuMu 로 바꿔보거나, 안 되면 **arm64 시스템 이미지**(AVD arm64 / 물리 arm64 기기 = 네이티브).
> **버전 정합 필수**: `frida-server` == `frida-tools`(=agent 의 frida) 버전. 안 맞으면 attach 실패.

## arm64 AVD 경로 (안드스튜디오 — 확실, 보호·번역 면역)
LDPlayer(x86)는 arm 번역이 frida·dd 다 막음(실증됨). **arm64 네이티브 AVD**면 frida-il2cpp-bridge가
런타임 타입을 그대로 뽑음(정답). x86 PC선 QEMU 전체에뮬=느리지만, il2cpp init은 앱 시작 초반이라 덤프는 됨.

1. **안드스튜디오** 설치 → SDK Manager → 시스템이미지 **`arm64-v8a` + `Google APIs`**(Play 아님! Google APIs여야 `adb root` 됨) 설치. API 31~34.
2. Device Manager → Create Device → Pixel류 → 위 **arm64-v8a Google APIs** 이미지 선택 → 실행.
3. **root**: `adb root` → "restarting adbd as root" 뜨면 OK (Google APIs 이미지라 됨).
4. **NIKKE 설치**(Play 없으니 sideload): APKPure 등서 arm64 APK+OBB.
   - split APK면 `adb install-multiple base.apk config.arm64_v8a.apk config.xxhdpi.apk`
   - OBB: `adb push <obb> /sdcard/Android/obb/com.proximabeta.nikke/`
5. **frida-server ARM64**: `frida-server-<ver>-android-**arm64**`(x86아님!) push+chmod+실행(위 §에뮬 4번과 동일, arm64 빌드만).
6. **덤프**(§에뮬 6번 agent 그대로): `frida -U -f com.proximabeta.nikke -l agent.js` → 스플래시서 `DUMPED`(느려도 기다림) → `/sdcard/nikke_dump.cs`.
   - LDPlayer와 달리 여기선 `Il2Cpp.perform` 이 libil2cpp 찾음(네이티브 arm64).
7. `adb pull /sdcard/nikke_dump.cs` → 나에게. **dump.cs = 모든 클래스 필드의 정답 타입**(int/long/float/List<T>/string) → 복잡표(FunctionTable 등) 100% 디코드 완성.

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
