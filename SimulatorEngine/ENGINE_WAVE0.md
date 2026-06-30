# TASK — 엔진 Wave 0 (K0 계약 스켈레톤 + K1 foundation 검증)

> **도메인**: SimulatorEngine (C#). **WBS 연계**: `Docs/WORK_BREAKDOWN.md` Wave 0 = K0 + K1. 이게 **Wave 1 전체(K2~K6)를 푼다.**
> **상위 권위**: `Docs/DESIGN.md`(방향·공식), `Docs/ENGINE_GUIDE.md`(컴포넌트 계약·MUST). 충돌 시 그쪽 우선.
> **병렬**: DataPipeline 의 roledata audit(`DataPipeline/ROLEDATA_SKILL_AUDIT.md`) 와 독립 동시 가능. (K0/K1 은 스킬 소스와 무관.)

---

## K0 — `Nikke.Simulator.Engine` 프로젝트 + 계약 스텁  ★blocks Wave1

### 목표
새 클래스 라이브러리 프로젝트를 만들고, **모든 공유 인터페이스/DTO 를 컴파일되는 스텁**(`throw new NotImplementedException()`)으로 박아 **동결**. 임플은 Wave 1 에서 병렬.

### 작업
1. `SimulatorEngine/Nikke.Simulator.Engine/Nikke.Simulator.Engine.csproj` (net8.0) 생성 → `Nikke.Simulator.Core` **ProjectReference**. `NikkeSimulator.sln` 에 추가.
2. 계약 스텁 (ENGINE_GUIDE §5 기준):
   - `ISimClock` (`Schedule(double atSec, Action)`, `Run(double untilSec)`)
   - `IRotationController` (`Decide(simState)→actions`)
   - `ITarget` (FinalDef/HasParts/Element/InProperRange/IsBoss → AttackContext 채움)
   - `Combatant` (Core `Nikke` 래핑 + 런타임 버프 상태 보유 — **Nikke(Core)는 static 유지**)
   - `SkillParsedDto` 패밀리 (스킬 소스 audit 결과 반영; 미정이면 최소 placeholder)
   - `BuffInstance` (stat/value/bracket/expirySec/stacks)
   - `IMetricsSink` / `RunResult { double TotalDamage; … }`
   - 엔트리 `SimulationRunner.RunOnce(teams, ITarget, IRandomSource) → RunResult` (스텁)

### MUST
- 엔진 = **UI/compute/직렬화 무지 순수 라이브러리.** UI·서버·JSON-API 타입 의존 0 (DESIGN §1, ENGINE_GUIDE §1). Tier 3/4/5 재사용 전제.
- `Nikke.Simulator.Core` 에 Engine 타입 역참조 **금지** (단방향 Engine→Core).

### 수용 기준
- [x] `dotnet build NikkeSimulator.sln` 0 에러 (스텁 throw 허용). — 2026-06-30, Engine.dll 산출, 4 프로젝트 전부 빌드.
- [~] 계약 시그니처 리뷰·동결. — 스텁 작성 완료(`SimulatorEngine/Nikke.Simulator.Engine/`); **사용자 리뷰 후** read-only 동결.

> **구현 메모**: enum 슬롯(event/stat/action/…)은 `SkillParsedDto` 패밀리에서 **string** 으로 둠 (roledata audit + KP1 흡수 전 enum 값 선잠금 회피; ENGINE_GUIDE §5 "string + 검증"). K4 Loader 가 검증/매핑.

---

## K1 — W 단위 픽스 + foundation 검증 (M0)  ★정확성 게이트

### 목표
`Initialize → new Nikke → BuildAttackContext → CalculateDamage` 를 1발 굴려, **알려진 in-game 캐릭 1명**의 FinalAtk + 무버프 평타 1발 대미지가 **게임 실측과 일치**하는지 확인.

### 핵심 버그 (확인됨, 반드시 픽스)
- 데이터 `basicAttack.multiplier` = **percent**(예 8.73 = "8.73% ATK", SG 214.3), 그런데 공식 W 는 **fraction**(golden 4.995=499.5%/100). `chargeDamage` 는 fraction(2.5)로 저장 → **단위 불일치.**
- 현 `Entities/Nikke.cs:~239` `ctx.SkillMultiplier = BasicAtkMultiplier` 는 **raw percent 주입 = 100× 버그.**
- **정규화 1곳 확정**: ✅ **`Nikke` 생성자(주입측) `/100`** (2026-06-30 확정). 엔진 로컬 — ETL 재실행/merged DB 재생성 불필요, 데이터 DTO 는 raw(percent-number) 유지. 문서화: DESIGN §3·§6, ENGINE_GUIDE §6 D2.
  - ※ 구 `atk_parser.py` 는 폐기됨 — 현재 `multiplier` 생산처 = `roledata_cleaner`(이미 `damage/100`=percent-number 저장; 추가 변환 없음).

### 작업
1. ✅ multiplier 단위 정규화 1곳 적용 — `Nikke.cs` [4] `/100`.
2. ✅ 검증 유닛테스트 배선 — `WUnitFoundationTests`(W 불변식 3 + 파서 셀 락 1 + foundation smoke 1, 엔드투엔드 동작).
3. ✅ `StatTable.Initialize` 견고 파서 교체 — cp949/UTF-8 + 따옴표 + **셀 내부 줄바꿈** + 천단위 콤마 내성, 행위치 내용기반 탐지. WPF `App.OnStartup` 경로도 이제 정상 로드. (사용자가 정본 csv 도 master 업로드: `d4899ff`.)

### 수용 기준 — ✅ 게이트 통과 (2026-06-30)
- [x] W 정규화 위치 확정·문서화. — `Nikke` 생성자 `/100`; CI 가드 `…BasicAtkMultiplier_IsNormalizedToFraction`.
- [x] FinalAtk 가 알려진 빌드 in-game 수치와 일치. — **stat 조립 0-error**(사용자: 다캐릭·다레벨·돌파불변 in-game, VERIFICATION_LOG §5) + 견고 파서로 정본 csv 로드 + 셀 락 테스트(`StatTable_Parses_KnownCells`: lv1/lv1000/bond40 일치).
- [x] 무버프 평타 1발 대미지 in-game 일치. — 비차지 무기 W·C 접힘 **in-game 실측 완료**(gap#4, 사용자) + 공식 golden 18(≤1.3e-7) + 엔드투엔드 wiring 테스트(`FinalAtk_And_UnbuffedBasicShot_AreReported`: bareShot==floor(FinalAtk×W), 실 로드값으로 통과). 검증 근거 = (stat 0-error) ∘ (formula golden) ∘ (gap#4) ∘ (wiring).
- [x] ❗ 정확성 게이트 **통과** → **Wave 1(K2~K6) 착수 가능.**

---

## Coordination
- 청크 = master 분기 → 커밋 → PR. uncommitted 방치 금지. bin/obj/.vs·개인데이터 커밋 금지(gitignore 됨).
- K0 계약 동결 후 변경 = 이슈로 올리고 의존 청크 통지.
- 시작 전: 최신 master 분기 확인, DESIGN/ENGINE_GUIDE/WORK_BREAKDOWN 숙지.
