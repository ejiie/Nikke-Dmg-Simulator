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
- [ ] `dotnet build NikkeSimulator.sln` 0 에러 (스텁 throw 허용).
- [ ] 계약 시그니처 리뷰·동결. 이후 계약 파일 read-only (변경 시 §coordination).

---

## K1 — W 단위 픽스 + foundation 검증 (M0)  ★정확성 게이트

### 목표
`Initialize → new Nikke → BuildAttackContext → CalculateDamage` 를 1발 굴려, **알려진 in-game 캐릭 1명**의 FinalAtk + 무버프 평타 1발 대미지가 **게임 실측과 일치**하는지 확인.

### 핵심 버그 (확인됨, 반드시 픽스)
- 데이터 `basicAttack.multiplier` = **percent**(예 8.73 = "8.73% ATK", SG 214.3), 그런데 공식 W 는 **fraction**(golden 4.995=499.5%/100). `chargeDamage` 는 fraction(2.5)로 저장 → **단위 불일치.**
- 현 `Entities/Nikke.cs:~239` `ctx.SkillMultiplier = BasicAtkMultiplier` 는 **raw percent 주입 = 100× 버그.**
- **정규화 1곳 확정**: `etl/roledata_cleaner.py`(저장 시 `/100`, chargeDamage 와 통일) **vs** `Nikke`(주입 시 `/100`). 결정 후 문서화(DESIGN §3 ⚠️ 갱신).
  - ※ 구 `atk_parser.py` 는 폐기됨 — 현재 `multiplier` 생산처 = `roledata_cleaner`.

### 작업
1. multiplier 단위 정규화 1곳 적용.
2. 검증 콘솔/유닛테스트: 1캐릭 로드 → FinalAtk 출력 → 게임 스탯창 대조. 무버프 평타 1발 대미지 → in-game 대조.
3. WPF `App.OnStartup` 의 `StatTable.Initialize` 경로 정상 확인(이미 호출됨).

### 수용 기준
- [ ] FinalAtk 가 알려진 빌드 in-game 수치와 일치(±표시반올림).
- [ ] 무버프 평타 1발 대미지 in-game 일치.
- [ ] W 정규화 위치 확정·문서화.
- [ ] ❗ **불일치 시 Wave 1+ 착수 금지** (전 damage 가 이 위에 얹힘).

---

## Coordination
- 청크 = master 분기 → 커밋 → PR. uncommitted 방치 금지. bin/obj/.vs·개인데이터 커밋 금지(gitignore 됨).
- K0 계약 동결 후 변경 = 이슈로 올리고 의존 청크 통지.
- 시작 전: 최신 master 분기 확인, DESIGN/ENGINE_GUIDE/WORK_BREAKDOWN 숙지.
