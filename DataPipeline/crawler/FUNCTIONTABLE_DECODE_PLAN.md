# FunctionTable.mpk 디코드 — 계획 (실행 전, 2026-07-07)

> 목표: `FunctionTable.mpk`(MemoryPack, 19459 함수) → 함수별 `FunctionData`. **스킬 런타임(THE GAP)의
> 데이터원**. 참조 = `Docs/SKILL_RUNTIME_REFERENCE.md`. **이 문서는 계획만 — 아직 실행 안 함.**

## 1. 확정 사실
- `.mpk` = MemoryPack. 디코더 = `memorypack_decode.py`(스칼라/리스트/문자열 OK, MonsterParts 등 clean).
- `FunctionTable` rec0: `memberCount=55`, 282바이트, 문자열 2개(Name@16, Buff_icon@156), 나머지 int/빈문자열.
- 필드 **이름 55개** = metadata `FunctionRecord`(확보). **타입** = nikke-einkk `FunctionData`(확보): 대부분 int,
  `Is_cancel`=bool, `Connected_function`=List<int>, 진짜 문자열=localkey/icon/prefab/socket/target(총 ~26).
  enum(Function_type/Buff/*_type/*_standard/target)은 .mpk 에선 **int**(JSON 변환기가 이름화한 것).
- **막힌 점**: metadata **선언순 ≠ MemoryPackOrder**(rec0서 Buff_icon 위치 +9~12 어긋남; 3-long 가설·타입tweak
  실패 → 단순 타입 아닌 **필드 재배치(순열)** or metadata 필드셋 drift 가능성). 55! 순열이라 무작정 탐색 불가.

## 2. 결정적 단순화 (탐색공간 축소)
- **효과에 필요한 필드 = ~13개뿐**: `id·group_id·function_type·function_value·function_value_type·
  function_standard·function_target·timing_trigger_type/standard/value·status_trigger_type/standard/value·
  duration_type/value·limit_value·full_count·connected_function`. **Fx_* 26개 문자열(prefab/target/socket)=
  시각효과=시뮬 무관** → 디코드 정확도 신경 안 써도 됨(끝부분 몰림).
- **레코드 경계 = memberCount(55) 상수** → `decode_table_resync` 로 각 레코드 **앞쪽 효과필드만 읽고
  다음 경계로 점프** 가능(끝의 Fx junk 무시). 단 앞필드 순서/타입은 정확해야 함.
- **문자열 = 자기검증 마커** → 앵커. Fx 채워진 레코드로 문자열 member-index 를 핀.

## 3. 접근법 (우선순위)

### A. SharpnelXu 비공개 repo 컨택 — **최선/최속**
`github.com/SharpnelXu/nikke-mpk-json-converter` README: "decryption 성격상 추가개발은 private repo,
contribute 원하면 연락". Monster/UnionRaidPreset 등 C# 모델은 이미 [MemoryPackOrder] 포함. **FunctionData
모델(순서+타입)만 받으면 즉시 해결** → `memorypack_decode.py` 에 스키마 추가로 끝. 컨택 시도 권장.

### B. 경험적 RE — 제약 솔버 (DIY, A 실패 시)
순서를 데이터로 역산. 단계:
1. **문자열 member-index 확정**: Fx 가 채워진 레코드 다수 수집 → 각 레코드를 "string marker면 string,
   아니면 4B" 로 greedy 파싱하며 **어느 순번(0-54)이 문자열인지** 통계. 26개 문자열 위치 확정.
2. **비문자열 순번의 타입 확정**: 문자열 위치 고정 후, 나머지 29순번을 int(4)/bool(1)/list([i32 n]+n) 중
   무엇인지 **`off==len`(전 19459 레코드)** 제약으로 탐색. bool=1개(Is_cancel)·list=1개(Connected)라 조합 소수.
   (홀수 drift = bool 존재 확정; list 는 count 큰 레코드로 식별.)
3. **효과필드만 필요**하면 전체 55 대신 **앞 ~30순번**만 확정 + `resync` (Fx junk 무시)로 축소 가능.
4. **값→이름 매핑**: 확정된 순번별 값을, 내용으로 필드명 배정 — id(첫·큰수)·Name(`Locale_Skill:`)·
   Connected(list)·trigger/value(범위·0많음) 등. metadata 이름은 참고만(순서 못 믿음).

### C. Ground-truth 교차검증 (A/B 보조)
nikke-einkk 는 **디코드된 `FunctionTable.json`을 외부서 받아** 씀(자체 mpk→json 변환 없음). 그 소스
(SharpnelXu 변환물 or 데이터 repo) 한 부 확보하면 **정답지** → 우리 디코더 검증/순서 역산에 활용.

## 4. 검증 (디코드 후 정합 확인)
- **보스/니케 스킬 function_id → FunctionData → 알려진 효과와 대조.** 예: season39 보스 코어 passive 7252022
  의 use function → heal/regen 계열이면 "재생 코어"(사용자 관측) 확증. 유명 니케 버스트 스킬로도 검증.
- FunctionType 분포가 nikke-einkk enum 범위(0~77+) 안인지, function_value 가 %스케일(10000=100%)인지 sanity.

## 4b. B 실행 결과 (2026-07-07 — 시도, 미완)
경험적 RE 착수했으나 벽 확인:
- metadata 선언순 + 타입tweak → 실패. **1bool+3long 전조합(42504) 탐색 → 500레코드 통과 0** = **순서가
  metadata서 재배치됨(permutation) 확정**.
- rec0 구조는 규명: `0-3 int · 4=Name(str) · 5-32=27 int + 1 bool · 33=Buff_icon(str) · 34-54=Fx tail+Connected`.
  Buff_icon 이 member **33**(metadata 30 아님) = 순서 어긋남 증거. long 없음(사이 109B=27·4+1).
- bool 위치+resync → 57/19459 (resync 가 `byte==55` 흔해 오탐). `id=group×100+lv` 경계휴리스틱 → 1541만
  (대부분 함수 id 규칙 불균일).
- **핵심 난점**: 순서·경계 chicken-egg — 전체 55필드 순서 없이 레코드 경계 신뢰검출 불가, 경계 없이 순서 역산 불가.
  → 본격 **구조 솔버**(다중레코드 통계로 member별 타입+순서 동시추정, list/bool 위치 포함) 필요 = 고비용·불확실.
**판정: B 는 가능하나 비효율. A(SharpnelXu 컨택)가 실질 최선.** 효과 의미는 nikke-einkk 에 이미 있어 엔진 K7 설계는 B 없이 진행 가능.

## 5. 권장 순서
1. **A 컨택 시도** (즉시성). 응답 없으면 →
2. **B 단계1~3** (문자열 위치 → 타입 → resync 로 효과필드만). Fx junk 무시로 난이도 대폭↓.
3. C 로 교차검증.
데이터 신선도는 문제 아님 — 우리 `StaticData.zip`=qa-260702 최신(season39 함수 존재 확인). 순서(스키마)만 남음.

## 교차링크
런타임 사용처 = `Docs/SKILL_RUNTIME_REFERENCE.md`. MemoryPack 포맷·디코더 = `STATICDATA_PREP.md`·`memorypack_decode.py`.
보스 스킬 function_id 원천 = `RAID_BOSS.md`(MonsterTable.skill_data).
