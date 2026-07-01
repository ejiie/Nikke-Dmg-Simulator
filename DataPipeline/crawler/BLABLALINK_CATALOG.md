# BLABLALINK 데이터 카탈로그 — 전수 조사 (2026-07-01)

> blablalink(공식 NIKKE 게임툴, Shift Up)에서 **얻을 수 있는 모든 데이터**의 확정 목록.
> 방법: 프론트 번들 `index-*.js` 의 `getGameJsonResource()` 호출 전수 추출 +
> 크롬확장 `IsolateOB/ExiaInvasion` 소스의 유저 API 엔드포인트.

## 1. CDN 접근 방식
- 공개 CDN `sg-tools-cdn.blablalink.com`, **로그인 불필요**, curl_cffi(Cloudflare 우회).
- URL = **난독화**: 파일명 `md5(논리경로)`, 디렉토리 `djb2(경로, prime)`. → 재현 = `_bbl_cdn.py`.
- **md5 주소라 디렉토리 나열 불가** — 논리경로 문자열을 알아야 fetch 가능. 그래서 프론트 JS 마이닝이 유일한 체계적 발견법.
- 프론트 번들: `https://www.blablalink.com/assets/nikke/version/default/assets/index-*.js` (2.2MB) + 195 lazy 청크.

## 2. CDN 정적 데이터 카탈로그 (메인 번들 `getGameJsonResource` 16종 전수)

| 논리경로 | 내용 | 수집 | 시뮬 가치 |
|---|---|---|---|
| `character/{lang}/nikke_list_{lang}_v2.json` | 캐릭 인덱스(resource_id) | ✅ roledata 크롤러 | 진입점 |
| `roledata/{rid}-v2-{locale}.json` | **캐릭 풀 데이터**(메타/무기 shot_detail/스킬 desc+값+function_id_list) | ✅ subset + **풀 raw**(`blabla_roledata_full.json`) | ★ 최고 |
| `character/AttractiveLevelTable.json` | 호감도 40lv, 클래스별 hp/atk/def **rate** | ❌ (stat_table.csv 에 이미 있음) | 중(rate-vs-flat 정합 필요) |
| `character/CharacterLevelTable.json` | 레벨업 **비용/exp**(level/gold/character_exp) — **스탯 아님** | ❌ | 낮음(비용표) |
| `character/RecycleResearchStatTable.json` | 함선연구 9노드 flat atk/def/hp | ❌ (csv 에 있음) | 낮음 |
| `character/character_skill_map.json` | resource_id → 스킬 아이콘 | ❌ | 낮음(아이콘) |
| `character/character_id_map.json` · `character_avatar_map.json` · `character_face_list.json` · `scene_characeter_list_v2.json` | id/아바타/얼굴/씬 매핑 | ❌ | 낮음 |
| `equip/ItemEquipTable-{locale}.json` | 장비 base(class×tier×module) | ✅ static 크롤러 | ✅ |
| `equip/cube_rare_map.json` · `equip/{locale}/cube_{id}.json` | 큐브 레벨별 base+효과 | ✅ | ✅ |
| `equip/favorite_rare_map.json` · `equip/{locale}/favorite_{id}.json` | 소장품 base+효과 | ✅ | ✅ |
| `equip/equip_option_table_v2-{locale}.json` | **OL 옵션 9종**(ATK/DEF/MaxAmmo/ChargeDmg/ChargeSpeed/CritRate/CritDmg/ElementDmg/HitRate)×3티어. **HP 없음** | ❌ | 중(카탈로그; 롤 **값**은 state_effect 표 필요, 유저데이터가 이미 resolve) |
| `attractscene/{id}-{locale}.json` | 호감도 스토리 씬 | ❌ | 시뮬 무관 |

### 2.1 roledata 풀 raw 채굴 결과 (2026-07-01)
`blabla_roledata_full.json`(캐릭당 ~6500줄) 검사 — 큐레이트 subset 이 버리던 고가치 필드:

| 필드 | 내용 | 처리 |
|---|---|---|
| `character_level_{attack,hp,defence}_list[1200]` | **캐릭별 레벨별 base HP/ATK/DEF** (ATK/HP=class×rare, **DEF=per-char 변동**) | ⭐ 공식 stat 소스 = 수기 `stat_table.csv` 대체 후보(사용자 Y). 미배선(후속) |
| `stat_enhance_detail` | grade/core 상수(`grade_attack=20 grade_hp=3000 grade_defence=100 ratio=0.02`, core) — **전캐릭 동일** | DESIGN §3.5 하드코딩 **공식 확증**. 하드코딩 유지(글로벌 무예외) |
| `bonusrange_min/max` | 적정거리 보너스 **범위**(무기별 결정) | ✅ 추출 → `proper_distance_table.json`(무기별) + per-char `properRange`(merged DB) |
| `squad` | 스쿼드(62종) — 동일 스쿼드 아군 조건 버프 스킬용 | ✅ 추출 → merged DB `static.squad` |
| `skill*_table='StateEffect'`·`category_type`·`teammate_list` | 스킬 효과 테이블 타입·태그·팀메이트 | 미사용(후속 후보) |
| `piece/costume/dialog/cv/attractive_scenario` | 가챠·코스튬·대사·성우·호감도씬 | 시뮬 무관 |

## 3. 유저 데이터 API (`api.blablalink.com`, 로그인 필요)
`GetUserCharacters` · `GetUserCharacterDetails` · `GetUserProfileBasicInfo` · `GetUserProfileOutpostInfo` · `GetUserGamePlayerInfo`. → `getFromBlaLink.py` (API replay). ✅ 수집 중.

## 4. ⚠️ blablalink 에 **없는** 것 (게임 StaticData 전용)
blablalink 는 게임 데이터의 **큐레이트 부분집합**(캐릭/장비/스탯). 다음은 **노출 안 함**:
- **스킬 FunctionTable** (function_id → 효과 타입/트리거 의미). roledata 는 `description` 텍스트 + `description_value_list`(레벨별 수치) + 불투명 `function_id_list` 만 줌. 구조화 의미는 게임 StaticData 의 **Lua 스크립트 + FunctionTable**.
- **보스/레이드/적 전투 스탯** (HP/파츠/DEF/속성/거리) — BossTarget(K11)용.
- 청크명 전수 스캔 확인: boss/monster/function/skill-logic 데이터 청크 **부재**(`union-raid`=소셜기능, 데이터X).

### StaticData 루트 (DMCA 회색)
- `Hiro420/NikkeTools` = 라이브서버 StaticData.zip 복호화(protobuf) + UnLuac(스킬 Lua 디컴파일) + il2cpp metadata.
- `hibikidesu/nikke-data`(복호 미러) = **DMCA 차단**(2022-12, 퍼블리셔 신고). 직접 미러는 법적 취약·휘발.
- 완전하지만 게임클라이언트 RE + 라이브서버 접근 = 법적 회색. **결정 보류**(blabla 먼저 → 그 다음 StaticData 복호 시도 — 사용자 방침 2026-07-01).

## 5. Sources
- 프론트 번들 마이닝(self) · [IsolateOB/ExiaInvasion](https://github.com/IsolateOB/ExiaInvasion)(유저API) · [Hiro420/NikkeTools](https://github.com/Hiro420/NikkeTools)(StaticData 복호)
