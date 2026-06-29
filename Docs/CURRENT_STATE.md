# CURRENT_STATE — 사실 스냅샷 (2026-05-26)

> 코드/데이터를 직접 읽어 검증한 현재 상태. "잘 됨/안 됨"을 추측 없이 기록한다.
> 수치는 이 날짜 기준 실측이며, 데이터 재생성 시 달라진다.

## 1. 한눈에 보기

| 영역 | 상태 |
|---|---|
| DataPipeline ETL (크롤→merged DB) | ✅ 동작. 178명 roster 생성 |
| LLM 스킬 파싱 산출물 | ⚠️ 부분 완료 (135/178명 completed, 55/534 스킬 파싱 실패) |
| C# 기초 스탯 조립 (스탯/OL/큐브/콜렉션) | ✅ 구현됨 |
| C# per-tick 대미지 공식 (B2~B5/차지/트루) | ✅ 구현됨 |
| **스킬 효과 → 시뮬레이터 연결** | ❌ 없음 (가장 큰 공백) |
| 시뮬레이션 루프 / 로테이션 / DPS 산출 | ❌ 없음 |
| 테스트 | ❌ 빈 스텁 (`UnitTest1.Test1()` 비어 있음) |

## 2. DataPipeline 현황

### 2.1 ETL — 동작 확인됨
- `nikke_merged_db_returned.json`: **roster 178명** (name_code 키, static+user 결합).
- 오버로드 `Percent` 값은 `blabla_merger.py:138` 에서 `/10000` 스케일됨. `Integer`(예: `StatCriticalDamage=1644`)는 원시값 유지 → 해석은 C# 책임.
- `db_merger.py` 는 Prydwen에 없는 신캐는 건너뜀(skip).

### 2.2 LLM 스킬 파싱 — 부분 완료 (`skills_parsed.json`)
실측 (2026-05-26):
- 총 캐릭터 178명: **completed 135 / pending 43**.
- 총 스킬 534개 중 **PARSE_ERROR 55개** (≈10%). 이 55개는 groups/stack_conditions가 비어 있음.
- `grant_trait` 분포: `trait_weapon_transformed` 21, `trait_pierce` 17, `trait_true_dmg_conversion` 3.
- **free-form 토큰 long-tail**: 고유 `required_token` 195종, 고유 `filter_token` 64종. (enum으로 못 잡은 캐릭터 고유 상태/필터를 원문 문자열로 보존한 것.)

> 이 부분이 "꼬임"의 핵심. 분석 + **v4 스키마 확정 형태**는 [SKILL_PARSING.md](SKILL_PARSING.md) §3.
> (단, 스키마 *형태*만 확정. 위 수치는 **기존 v3 산출물** 기준 — v4로 재파싱은 아직 안 함.)
> 오매핑(Hit Rate→crit_rate 등) 방지 규칙은 [SKILL_MISMAPPING_GUARD.md](SKILL_MISMAPPING_GUARD.md).

## 3. SimulatorEngine 현황

### 3.1 구현·검증됨
- **JSON 로드**: `JsonProvider` (스마트 경로 탐색 + 타입별 예외 체인).
- **기초 스탯 조립** (`Nikke.InitializeFinalStats`): 레벨/등급/코어/호감도/콘솔 → 코어 적용 스탯, + 소장품 + 장비 + 큐브, + 오버로드 합산(니케식 그룹-반올림). HP는 큐브 Vigor 곱산, MG는 장탄 증가 곱산.
- **per-tick 대미지 공식** (`StatCalculator.CalculateDamage`): B2~B5 브래킷, 차지 2축, True Damage(DEF=0), 최소 대미지 규칙(DEF≥ATK→1).
- **오버로드 전투축** 사전집계: `StatCritical/StatCriticalDamage/StatChargeDamage/IncElementDmg` → AttackContext 주입. `Integer` 값 `/10000` 정규화.
- **무기 타이밍 테이블** (`WeaponStatTable`): AR=12 / MG=60 / SMG=24 / SG=5/3 발/sec, SR·RL 차지 타이밍. (값 존재, 아직 소비처 없음.)
- **크리 RNG 추상화** (`IRandomSource`/`CritSampler`): 고정 시드 금지 정책. (API만 준비, 소비처 없음.)

### 3.2 스텁/플레이스홀더 (값이 임시이거나 0 반환)
- **장비 스탯**: `StatTable.GetEquipmentStats` 가 사실상 0 반환. **데이터는 확보됨**(`blabla_static_tables.json` 장비 base = class×tier×slot, +공식 레벨 공식 `round(base×(1+0.3·corp일치+0.1·level))`, blablalink JS 추출). **C# 연동만 미완.**
- **큐브 효과 수치**: `CubeSkillTable` 값이 코드 주석상 "예시 수치". **실측 확보됨**(`blabla_static_tables.json` cubes = 레벨별 atk/hp/def). C# 연동만 미완.
- **최종 반올림 모드**: `Math.Floor` 잠정. 게임 실측으로 확정 필요.
- **WPF**: `MainWindow` 가 DB 로드 + 오버로드 계산 스모크 테스트만 수행. 실제 UI 없음.
- **Tests**: `Nikke.Simulator.Tests/UnitTest1.cs` 가 빈 `Test1()`. 회귀 테스트 없음.

### 3.3 미구현 — 단계 1↔2 사이의 공백
C# 엔진은 `skills_parsed.json` 을 **읽지 않는다** (`.cs` 전수 검색 결과 주석 1줄만 언급). 따라서 다음이 통째로 없다:
1. **스킬 번역기**: `skills_parsed.json` → C#가 쓸 수 있는 형태(정적 modifier / 런타임 트리거)로 변환.
2. **스킬 런타임**: 트리거/조건/스택/쿨다운/지속시간 타임라인 관리.
3. **로테이션 시뮬레이션 루프**: 무기별 발사 타이밍, 풀버스트 사이클 → 실제 DPS 산출.

즉 **현재는 "한 발(tick)의 대미지"는 계산 가능하지만, "시간에 걸친 전투 DPS"는 계산할 수 없다.**

## 4. 코드베이스 정리 필요 항목 (관측된 것)
- `SimulatorEngine/Core/` (레거시 `NikkeDmgSimulator.Core` 콘솔 앱)은 `Nikke.Simulator.Core` 로 대체된 구버전으로 보임. 하드코딩 절대경로(`Program.cs:133`) 사용. 정리 여부 결정 필요.
- 빌드 산출물(`obj/`, `bin/`, `.vs/`)이 git에 추적되고 있음 (git status에 다수 노출).
- 이전 설계 문서(ARCHITECTURE/DATA_SCHEMA/DEVLOG)는 main에서 삭제됨. `claude/magical-benz` 워크트리에 옛 버전이 남아 있으나 **일부 환각 포함**으로 신뢰하지 말 것 — 검증 참고용으로만.

## 5. 열린 질문 / 미확정 (실측·결정 대기)
- 최종 대미지 반올림/내림/올림 모드.
- ~~장비 tier×level 스탯 표~~ → **해결**: base 표(blabla_static_tables) + 공식 `round(base×(1+0.3·corp+0.1·level))`. C# 연동만 남음.
- ~~큐브 TID 실측 수치~~ → **해결**: blabla_static_tables cubes(레벨별). C# 연동만 남음.
- ProperDistance 보너스 0.3의 무기별 정확한 적용 조건 (RL은 0 확정).
- `skills_parsed.json` 의 free-form 토큰 195+64종을 런타임에서 어떻게 처리할지 (→ [SKILL_PARSING.md](SKILL_PARSING.md)).
