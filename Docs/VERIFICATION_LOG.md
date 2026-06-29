# VERIFICATION LOG — 빌드/테스트/데이터 정합 증거

> **역할**: 주요 작업 묶음마다 빌드·테스트·파이프라인·데이터 불변식을 실측 캡처해 **정합함을 증거로** 남긴다.
> 날짜 내림차순. 각 항목은 그 시점의 commit 과 재현 명령을 포함한다.

---

## 2026-06-30 — 장비/큐브/소장품 데이터 연동 + 문서 정합

**범위**: 장비 스탯 + 하모니 큐브·소장품 (base ATK/HP/DEF + 특수효과) 를 공식 blablalink JSON
으로 C# 엔진에 배선. 옛 CSV "예시 수치" / `stub=0` 경로 제거. 병행 로컬 문서(deck-optimizer)와의
모순·중복 정정.

**관련 commit**: `69210f2`(장비 배선) · `f1256f2`/`8d63e68`(큐브·소장품 effect ETL) ·
`273f777`(EffectType enum/dict 배선) · `1358e0c`(base→JSON + 큐브 자동장착 + 데드코드 제거 + 파이프라인) · 본 문서/문서정정 commit.

### 1. 빌드 — 0 errors
```
dotnet build SimulatorEngine/NikkeSimulator.sln
→ 오류 0개
```

### 2. 단위/통합 테스트 — 34/34 통과
```
dotnet test SimulatorEngine/Nikke.Simulator.Tests/Nikke.Simulator.Tests.csproj
→ 실패: 0, 통과: 34, 건너뜀: 0, 전체: 34
```

| 파일 | 검증 대상 | 케이스 |
|---|---|---|
| `DamageFormulaGoldenTests.cs` | 대미지 공식 §3 (in-game 18 golden + 브래킷 구조/최소뎀/TrueDamage) | 골든 Theory + 구조 단위 |
| `EquipmentStatsTests.cs` | `GetEquipmentStats` 공식 `round(base×(1+0.3·corp+0.1·lv))`, 제조사 일치 +30%, 빈 장비=0, merged DB 신 shape 역직렬화 | 4 |
| `EffectTableTests.cs` | 큐브/소장품 특수효과 표 로드 (Vigor MaxHp 9.69%·ElemAdv 19.09%, AR Core·Def, SR chargeMult, 미지 큐브=빈 dict) | 4 |
| `NikkeBuildIntegrationTests.cs` | merged DB 의 큐브 장착 캐릭 → `Nikke` 생성 시 자동 `EquipCube` + base 스탯이 `FinalBaseHP` 에 반영 | 1 |

> 골든 회귀: 대미지 공식 결과는 모든 배선 변경 후에도 불변(bit-exact). 라우팅/스탯 변경이 공식을 건드리지 않음을 보장.

### 3. ETL 파이프라인 — 7단계 전부 exit 0
```
python DataPipeline/run_pipeline.py --stage etl
→ etl:equip_table · static_base · cube_effect · collection_effect
  · blabla_merger · roledata_cleaner · db_merger   (전부 exit 0)
→ 전체 7단계 성공.
```

### 4. 데이터 불변식 (마이그레이션 전제 검증)
```
cube base signatures        = 1   (전 큐브 공통 → base 표 = {level:{ATK,HP,DEF}} 로 단순화 정당)
collection(R) base signatures = 1 (전 무기 공통 → 동일)
cube_base_table levels      = 15
collection_base_table levels = 16
merged roster = 185 | cube-equipped chars = 61  (큐브 tid 가 merged DB→자동장착 경로로 흐름 확인)
```

### 5. 문서 정합성 정정 (병행 로컬 작업과의 모순 해소)
deck-optimizer 방향 확장 문서(`67bc8ed`/`737966b`)가 장비·큐브 작업 **이전 스냅샷** 기준이라,
merge 후 아래 stale 주장·중복이 남아 정정함:
- `DESIGN.md` §6: 중복 블록(코드구조/DamageCalculator/파서/출력 각 2회) 제거 + `장비표=0 stub, 큐브=예시 수치, 실측 필요` (stale) 삭제 → `확보+C# 연동 완료` 단일화.
- `ENGINE_GUIDE.md`: `GetEquipmentStats(equips) (stub=0)` → 실 시그니처 `(class,mfr,equips)` + JSON 연동 완료. §7 데이터 의존 항목도 해소 반영.
- `WORK_BREAKDOWN.md` KP2: `Core stub 교체 필요` → 연동 완료(잔여 = ProperDistance, 타이밍/조건부 효과).

> 코드/데이터는 merge 로 훼손되지 않았음(우리 브랜치 = master 조상 → fast-forward, 0 코드 diff). 정정은 **문서 텍스트 한정**.

### 6. 잔여 (의도적 미구현 — sim 루프 대기)
타이밍(Reload/Charge/Burst/Bastion)·조건부(Assist)·생존(받피감/Heal/Cover) 큐브·소장품 효과는
표에 **파싱만** 되고 엔진 미소비. 사유·소비처: [`SKILL_DATA_BLABLALINK.md`](SKILL_DATA_BLABLALINK.md) §4.2.
