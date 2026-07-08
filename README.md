# Nikke Damage Simulator

NIKKE 보유 로스터로 **최적 solo raid 덱 편성**을 찾아주는 도구. 정밀 전투 시뮬레이션으로 덱별
대미지 **분포**(평균·표준편차·신뢰구간·상위 tail)를 축적하고, 그걸로 최적 조합을 탐색한다.

> 개발 중. MVP(ver.0) = solo raid. union raid·웹 UI·배포는 확장 예정.

## 구성

| 층 | 위치 | 내용 |
|---|---|---|
| 데이터 파이프라인 (Python) | `DataPipeline/` | blablalink·NIKKE StaticData 크롤 + MemoryPack 디코드 + ETL → `Database/` |
| 시뮬레이터 엔진 (C# .NET8) | `SimulatorEngine/` | 검증된 대미지 공식 + 스탯 조립 + 60fps 프레임 전투 시뮬 |
| 대조 하네스 (콘솔) | `SimulatorEngine/Nikke.Simulator.Harness` | `nikke-harness run <name_code>` — in-game 대조 |

## 정확성

- **대미지 공식**: in-game 18 측정점 bit-exact 검증 (잔차 ≤1.3e-7).
- **스탯 조립**: 다캐릭·다레벨·돌파불변 0-error 검증.
- **발사/모션/재장전**: 3.5년 플레이 실측 + [nikke-einkk](https://github.com/d34d633f/nikke-einkk) 교차검증.
- **스킬 데이터**: 게임 공식 FunctionTable (StaticData) 디코드.

증명된 불변 사실 = [`Docs/FACTS.md`](Docs/FACTS.md).

## 빌드·테스트

```
dotnet test SimulatorEngine                              # 엔진 테스트
dotnet run --project SimulatorEngine/Nikke.Simulator.Harness -- run 5001 --sec 60   # 대조
python DataPipeline/run_pipeline.py --stage all          # 데이터 재생성 (크롤+ETL)
```

## 문서

- [`Docs/ROADMAP.md`](Docs/ROADMAP.md) — 목표·기술스택·마일스톤 (줄기)
- [`Docs/FACTS.md`](Docs/FACTS.md) — 검증된 불변 사실
- [`Docs/DESIGN.md`](Docs/DESIGN.md) — 방향·공식 권위 · [`Docs/ENGINE_GUIDE.md`](Docs/ENGINE_GUIDE.md) — 엔진 계약
- [`Docs/tasks/`](Docs/tasks/) — 개별 작업 명세 (가지)

## 라이선스·데이터

게임 데이터(스킬/보스 복호물)와 개인 로스터는 재배포 금지 — 저장소에 포함되지 않는다(gitignore).
참조 구현 nikke-einkk = MIT (아키텍처/공식 효과모델 참조, 코드 직접 복사 없음).
