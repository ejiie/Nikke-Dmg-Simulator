# CURRENT_STATE — 사실 스냅샷 (2026-06-30 갱신)

> 코드/데이터를 직접 읽어 검증한 현재 상태. "잘 됨/안 됨"을 추측 없이 기록한다.
> 수치는 이 날짜 기준 실측이며, 데이터 재생성 시 달라진다.
> 방향/공식 권위 = `DESIGN.md`. 엔진 빌드 분담 = `WORK_BREAKDOWN.md`.

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
- **정적 캐릭터 데이터 = blablalink roledata(공식)** 로 이전 완료 (구 Prydwen 크롤러/`prydwen_cleaner`/`atk_parser`/`auto_mapper` 폐기). roledata 는 name_code 네이티브라 slug 퍼지매핑 불필요.
- 파이프라인 오케스트레이터 `run_pipeline.py`: 크롤 3종(roledata·static = 로그인불필요 / blabla = 유저데이터) → ETL 7단(정적표 4: equip/static_base/cube_effect/collection_effect + 유저병합 3: blabla_merger → roledata_cleaner → db_merger).
- `nikke_merged_db_returned.json`: **roster 178명** (name_code 키, static+user 결합).
- 오버로드 `Percent` 값은 `blabla_merger.py` 에서 `/10000` 스케일됨. `Integer`(예: `StatCriticalDamage=1644`)는 원시값 유지 → 해석은 C# 책임.

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
- ~~**장비 스탯**~~ → **연동 완료**: `StatTable.GetEquipmentStats(class, manufacturer, equips)` 가 `equip_stat_table.json`(ETL) 로드 + 공식 `round(base×(1+0.3·corp일치+0.1·level))` 적용. 부위별 corp(제조사) 는 `blabla_merger` 가 추출. xUnit 4 케이스 검증.
- ~~**큐브/소장품 효과**~~ → **연동 완료**: `EffectType` enum + `EffectTable`(공식 `cube_effect_table`/`collection_effect_table.json`). `Nikke.RouteEffects` 가 기초스탯(MaxHp/Def/MaxAmmo rate)+대미지브래킷 라우팅(교정의미: NormalAtk=W곱, 받피감=생존, MaxHp/Def=rate버프). base atk/hp/def 는 `cube_base_table`/`collection_base_table.json`. 큐브 tid 는 merged DB→자동 `EquipCube`. 타이밍/조건부/생존 효과는 **파싱만**(sim 루프 대기, [SKILL_DATA_BLABLALINK](SKILL_DATA_BLABLALINK.md) §4.2).
- ~~**최종 반올림 모드**~~ → **해결**: 단일 final `floor` 확정 (실측 역산 18-golden, DESIGN §3). B2 = 가산 per-term-floor.
- **WPF**: `MainWindow` 가 DB 로드 + 오버로드 계산 스모크 테스트만 수행. 실제 UI 없음.
- **Tests**: 골든(대미지공식)·장비·EffectTable·Nikke빌드 통합 = **34 케이스 통과**. (`UnitTest1.cs` 만 빈 스텁.)

### 3.3 미구현 — 단계 1↔2 사이의 공백
C# 엔진은 `skills_parsed.json` 을 **읽지 않는다** (`.cs` 전수 검색 결과 주석 1줄만 언급). 따라서 다음이 통째로 없다:
1. **스킬 번역기**: `skills_parsed.json` → C#가 쓸 수 있는 형태(정적 modifier / 런타임 트리거)로 변환.
2. **스킬 런타임**: 트리거/조건/스택/쿨다운/지속시간 타임라인 관리.
3. **로테이션 시뮬레이션 루프**: 무기별 발사 타이밍, 풀버스트 사이클 → 실제 DPS 산출.

즉 **현재는 "한 발(tick)의 대미지"는 계산 가능하지만, "시간에 걸친 전투 DPS"는 계산할 수 없다.**

## 4. 코드베이스 정리 필요 항목 (관측된 것)
- `SimulatorEngine/Core/` (레거시 `NikkeDmgSimulator.Core` 콘솔 앱)은 `Nikke.Simulator.Core` 로 대체된 구버전. 하드코딩 절대경로(`Program.cs:133`) 사용. 정리 여부 결정 필요.
- ~~빌드 산출물 git 추적~~ → **해결**: `bin/obj/.vs` untrack + `.gitignore` 등록 (2026-06-27).
- ~~이전 설계 문서 main 삭제 / magical-benz 워크트리~~ → **해결**: ARCHITECTURE/DATA_SCHEMA/DEVLOG 는 `Docs/_archive/` 로 이동(historical, 공식 섹션 SUPERSEDED 배너). magical-benz 워크트리 제거됨. 현행 권위 = `Docs/DESIGN.md`.

## 5. 열린 질문 / 미확정 (실측·결정 대기)
- ~~최종 대미지 반올림/내림/올림~~ → **해결**: 단일 `floor` (18-golden, DESIGN §3).
- ~~장비 tier×level 스탯 표~~ → **해결**: base 표(blabla_static_tables) + 공식 `round(base×(1+0.3·corp+0.1·level))`. C# 연동만 남음.
- ~~큐브 TID 실측 수치~~ → **해결**: blabla_static_tables cubes(레벨별). C# 연동만 남음.
- ProperDistance 보너스 0.3의 무기별 정확한 적용 조건 (RL은 0 확정).
- `skills_parsed.json` 의 free-form 토큰 195+64종을 런타임에서 어떻게 처리할지 (→ [SKILL_PARSING.md](SKILL_PARSING.md)).
