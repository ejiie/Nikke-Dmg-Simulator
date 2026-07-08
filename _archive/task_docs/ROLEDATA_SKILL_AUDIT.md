# TASK — roledata 스킬 구조 audit → K4 스킬 소스 결정

> **도메인**: DataPipeline (데이터). **WBS 연계**: `Docs/WORK_BREAKDOWN.md` K4(SkillDTO/Translator)·KP1(파서 backlog) 의 **선행 결정**.
> **상위 권위**: `Docs/DESIGN.md`. **병렬**: 엔진 Wave 0(`SimulatorEngine/ENGINE_WAVE0.md`) 와 독립 동시 가능.
> **이 task = 조사+결정 1건.** 코드 변경 아님(결정 후 후속).

---

## 1. 목적

정적 캐릭터 데이터가 prydwen → **blablalink roledata(공식)** 로 이전됨. roledata 는 공식 구조화 데이터라 **스킬 효과도 구조화(수치/타입/트리거)로 줄 가능성**이 있다.
→ 그렇다면 기존 **LLM 스킬 파서**(`skills_parsed.json`; 55 PARSE_ERROR, 고유 `required_token` 195종·`filter_token` 64종 long-tail)를 **대체/축소** 가능 = 엔진 K4 의 갈아엎기 비용 회피.
**결정할 것: 엔진의 스킬 소스를 roledata-structured / skills_parsed(LLM) / hybrid 중 무엇으로 할지.**

---

## 2. 입력 (실측 대상)

- `Database/raw/blabla_roledata.json` (~2MB). `roster[name_code]` 에 `name_code/resource_id/name/class/corporation/element/critical_ratio/…` + **스킬 상세(깊은 구조)**. ← 이 스킬 상세의 구조화 깊이가 핵심.
- `DataPipeline/etl/roledata_cleaner.py` + 산출 `Database/processed/roledata_clean.json`: 현재 `{basicAttack, skills{skill1,skill2,burst}}` 로 정규화 (구 prydwen contract 호환). **현재 cleaner 가 스킬을 텍스트로 떨구는지 / 구조화 필드를 살리는지 확인.**
- 비교 기준: `DataPipeline/schema/skill_schema.py` (v3 Pydantic) + `skill_schema_legend.txt` — 엔진이 필요로 하는 필드 집합.

---

## 3. 작업 (steps)

1. **raw roledata 스킬 상세 구조 덤프** — `blabla_roledata.json` 의 한 캐릭 스킬을 깊이 전수. OL `state_effects` 처럼 `function_type`/`function_value`/`duration`/`stack` 류 **구조화 함수 테이블**이 있는지, 아니면 `description` 텍스트뿐인지.
2. **커버리지 매트릭스 작성** — v3 스키마 각 필드를 roledata 가 네이티브로 주는지 표로:
   | v3 필드 | roledata 제공? | 비고 |
   |---|---|---|
   | stat (StatType) | ? | |
   | action (ActionType) | ? | |
   | value / scale / scale_base | ? | |
   | formula_bracket | ? (추론 가능?) | |
   | trigger.event / condition_on / required_token | ? | long-tail 195종이 여기서 해소되나 |
   | target / target_filter / filter_token | ? | |
   | duration / max_stacks / stack | ? | |
   | charge 2축 / true_dmg / trait_* | ? | |
3. **갭 식별** — roledata 가 못 주는 필드(있으면) = LLM/추론 필요분.
4. **권장 산출** — K4 소스 결정 + 근거 + KP1 영향(파서 backlog 축소/폐기 여부).

---

## 4. 산출 (Deliverable)

- 이 파일 §5 에 **결정 기록**(커버리지 매트릭스 + K4 소스 권장 + KP1 영향). 또는 별 finding 문서.
- 결정 반영: `Docs/WORK_BREAKDOWN.md` K4/KP1, `Docs/DESIGN.md` (소스 확정 시).

## 5. 수용 기준

- [ ] raw roledata 스킬 1캐릭 구조 전수 덤프 첨부.
- [ ] v3 필드 커버리지 매트릭스 채움(추측 아닌 실측).
- [ ] K4 소스 = {roledata / skills_parsed / hybrid} 중 1개 + 근거.
- [ ] KP1(파서 backlog) 운명 명시 (유지/축소/폐기).

## 6. 결정 (작업자가 채움)

_(미정 — audit 후 기록)_
