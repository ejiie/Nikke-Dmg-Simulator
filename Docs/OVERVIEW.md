# OVERVIEW — Nikke Damage Simulator

> 이 문서는 2026-05-26 기준 **실제 코드/데이터를 읽고 검증한** 프로젝트 개요다.
> 추측이나 미래 계획은 담지 않는다. 현황은 [CURRENT_STATE.md](CURRENT_STATE.md),
> 스킬 파싱 재설계는 [SKILL_PARSING.md](SKILL_PARSING.md) 참조.

## 1. 목적

NIKKE(가챠 게임) 캐릭터의 대미지를 계산/시뮬레이션하는 도구.

큰 흐름은 두 단계다:

1. **DataPipeline (Python)** — 웹/게임 API에서 데이터를 긁어와 가공해 JSON DB로 만든다.
2. **SimulatorEngine (C# / .NET 8)** — 그 JSON DB를 읽어 스탯을 조립하고 대미지 공식을 계산한다.

두 단계는 **파일(JSON) 경계로만** 연결된다. 코드 의존성은 없다.

## 2. 디렉터리 맵

```
DataPipeline/            Python: 크롤러 + ETL + LLM 스킬 파서
  run_pipeline.py        전체 파이프라인 오케스트레이터 (crawl 2종 → etl 5단계)
  crawler/               웹/게임 API 수집 → Database/raw/
  etl/                   raw 가공/병합 → Database/processed/
  schema/                LLM 스킬 파싱 (Pydantic 스키마 + Gemini 호출기)
Database/
  raw/                   크롤러 원본 응답 (가공 전)
  processed/             ETL 산출물 (시뮬레이터가 읽는 최종물 포함)
SimulatorEngine/
  Nikke.Simulator.Core/  ★ 실제 엔진 라이브러리 (.NET 8)
  Nikke.Simulator.Wpf/   WPF UI (현재는 로드 스모크 테스트 수준)
  Nikke.Simulator.Tests/ xUnit (현재 빈 스텁)
  Core/                  레거시 콘솔 시제품 (NikkeDmgSimulator.Core) — 구버전
Docs/                    이 문서들
```

## 3. 데이터 흐름 (검증된 실제 경로)

### 3.1 크롤 → `Database/raw/`
| 산출물 | 내용 |
|---|---|
| `nikke_full_scroll_result.json` | 유저 계정 데이터 (레벨/등급/코어/장비/오버로드/콘솔). blabla 계열 크롤러 |
| `prydwen_all_details_v3.json` | 정적 캐릭터 데이터 (스탯/스킬 텍스트/평타). Prydwen 크롤러 |
| `real_en_dict_dump.json` | name_code → 영문 이름 사전 (매핑용). blabla 크롤러가 응답 스니핑 후 검증된 JSON 으로 저장 |
| `blabla_static_tables.json` | 장비(class×tier×slot base) + 하모니 큐브(레벨별) + 소장품(레벨별). `getFromBlaLinkStatic.py` 가 공개 CDN 에서 수집(로그인 불필요). 가끔만 갱신 |

> 수집은 `getFromBlaLink.py`(유저 데이터 + 영문 사전), `getFromPrydwen.py`(정적 캐릭터 데이터),
> `getFromBlaLinkStatic.py`(장비/큐브/소장품 정적표, 공개 CDN·로그인 불필요·가끔만) 세 크롤러가 담당.

### 3.2 ETL → `Database/processed/`
실행 순서대로:

| 스크립트 | 입력 → 출력 | 핵심 동작 |
|---|---|---|
| `etl/blabla_merger.py` | raw 유저데이터 → `user_state_clean.json` | 유저 동적 데이터 추출. **`val_type == "Percent"` 인 오버로드 값만 `/10000` 스케일링** (의미 해석은 안 함) |
| `etl/prydwen_cleaner.py` | `prydwen_all_details_v3.json` → `prydwen_clean.json` | Prydwen의 Rich-Text JSON에서 순수 텍스트만 추출, 아이콘 URL 정리 |
| `etl/atk_parser.py` | `prydwen_clean.json` (in-place) | 평타 텍스트를 정규식으로 파싱 → `multiplier / coreHitBonus / chargeTime / chargeDamage` |
| `etl/auto_mapper.py` | 사전 + clean 2종 → `final_mapping.json` | name_code → slug 매핑. 기존 매핑 보존(stateful), `-treasure` 우선 승격 |
| `etl/db_merger.py` | user_clean + prydwen_clean + mapping → **`nikke_merged_db_returned.json`** | 최종 마스터 DB. roster를 **name_code 키**로 조립 (static + user 결합) |

> `Database/processed/stat_table.csv` 는 **스크립트 산출물이 아니라 사용자가 직접 수집한 표**다.
> C# `StatTable` 이 직접 읽는다.

### 3.3 LLM 스킬 파싱 (별도 트랙) → `skills_parsed.json`
- `schema/skill_schema.py` — Pydantic v3 스키마 + few-shot 예시 (대미지 공식 B2~B5 브래킷 구조).
- `schema/skill_parser_llm.py` — Gemini 호출기. `nikke_merged_db_returned.json` 의 roster를 읽어 스킬 텍스트를 구조화 JSON으로 파싱.
- `schema/skill_schema_legend.txt` — 출력 JSON의 코드값/약어 해석 레퍼런스 + 대미지 공식 원본.
- 출력 `skills_parsed.json` 은 name_code 키, 캐릭별 status(`completed`/`pending`).

> **중요**: 이 산출물은 현재 C# 엔진이 읽지 않는다. 단계 1~2 사이의 연결이 비어 있다.
> 자세한 내용과 재설계 제안은 [SKILL_PARSING.md](SKILL_PARSING.md).

## 4. SimulatorEngine 구조 (Nikke.Simulator.Core)

| 영역 | 타입 | 역할 |
|---|---|---|
| `Data/` | `JsonProvider` | JSON I/O 단일 진입점. `GetSmartDatabasePath`(루트 자동 탐색) + `LoadJson<T>` |
| `Data/Dto/` | `RootDto` 외 | `nikke_merged_db_returned.json` 1:1 매핑 POCO. roster 키 = name_code |
| `Data/Constants/` | `CubeSkillTable`, `CollectionEffectTable`, 효과 struct | 하모니 큐브/소장품 효과 (불변 readonly struct) |
| `Stats/` | `StatTable` | `stat_table.csv` 로더. 레벨/호감도/콘솔/코어 적용 기초 스탯 |
| `Stats/` | `OverloadProcessor` | 전투 전(pre-combat) 오버로드 합산 → 최종 기초 스탯 |
| `Stats/` | `StatCalculator` + `AttackContext` | per-tick 대미지 공식 (B2~B5 + 차지 2축 + True Damage) |
| `Stats/` | `WeaponStatTable`, `IRandomSource`/`CritSampler` | 무기 발사 타이밍, 크리 RNG 추상화 |
| `Entities/` | `Nikke` | 캐릭터 1인스턴스. 최종 기초 스탯 보유 + `BuildAttackContext()` 팩토리 |

대미지 공식 (권위: **`Docs/DESIGN.md` §3** + `StatCalculator.CalculateDamage` + 18 golden test):

```
Damage = floor( B2 × (1 + ΣB3) × (1 + ΣB4) × (1 + ΣB5) )
  P  = (FinalAtk - FinalDef) × 계수(W) × chargeDmg_final(C)
  B2 = floor(P) + Σ_active floor(P × bracket)   ← 가산 per-term FLOOR (곱셈 아님!)
       bracket: properDist, fullBurst, (크리)Σcrit_dmg, (코어)coreHitBase+Σcore_hit_buff
  B3 = 1 + Σattack_dmg [+pierce][+parts][+dot][+sequential]   (곱셈)
  B4 = 1 + Σdamage_taken + Σdistrib_dmg                        (곱셈)
  B5 = 1 + Σstrong_elem                                        (곱셈)
  (Full Charge) C = (ChargeDmgBase + Σcharge_dmg) × (1 + Σcharge_dmg_mult)
```
- `effectiveDef ≥ FinalAtk` 이면 즉시 1 반환. True Damage는 `FinalDef := 0`.
- 반올림: **단일 final floor 확정** (18-golden 실측 역산). 과거 'B2 도 곱셈' / '반올림 미확정' 표기는 폐기.

## 5. 실행 방법

### DataPipeline
```bash
cd DataPipeline
pip install -r requirements.txt
playwright install chromium            # blabla 크롤러용 (1회)
cp .env.example .env                   # 자격증명 채우기 (NIKKE_BLABLA_ID/PW/UID)

# ── 권장: 오케스트레이터 한 방 (crawl 2종 → etl 5단계 순서대로) ──
python run_pipeline.py                 # 전체
python run_pipeline.py --stage etl     # 가공만 (수집 생략)
python run_pipeline.py --dry-run       # 실행 계획만 확인

# ── 또는 수동 단계별 실행 ──
python crawler/getFromPrydwen.py       # 정적 캐릭터 데이터 → raw/
python crawler/getFromBlaLink.py       # 유저 데이터 + 영문 사전 → raw/ (.env 로그인 자동)
python etl/blabla_merger.py            # 이하 ETL 은 이 순서 의존
python etl/prydwen_cleaner.py
python etl/atk_parser.py
python etl/auto_mapper.py
python etl/db_merger.py

# LLM 스킬 파싱 (별도 트랙, GEMINI_API_KEY 필요)
python schema/skill_parser_llm.py
```

> `run_pipeline.py` 는 각 단계를 subprocess 로 돌려 종료 코드를 존중한다(실패 시 중단).
> `getFromBlaLink.py` 는 로그인·수집 완전 자동(쿠키/region/id-pw + API replay) — `DataPipeline/crawler/AUTOMATION_DESIGN.md` 참조.

### SimulatorEngine
```bash
cd SimulatorEngine
dotnet build NikkeSimulator.sln
# WPF 실행 (Windows). 현재는 DB 로드 확인용 스모크 테스트.
dotnet run --project Nikke.Simulator.Wpf
```

## 6. 기술 스택
- Python 3 (Pydantic, google-genai). LLM: Gemini (`gemini-3-flash-preview`).
- C# / .NET 8 (Core 라이브러리 + WPF UI + xUnit 테스트).
- 데이터 교환: JSON (UTF-8). 모든 `.cs` 파일 UTF-8 고정.
