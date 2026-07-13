# Solo Raid Challenge timeline 추출 사용법

> 범위는 `SoloRaidPresetTable.Difficulty_type == 2`, 즉 **Solo Raid Challenge**뿐이다.
> 일반 Solo Raid와 Union Raid는 이 파이프라인의 대상이 아니다.

## 무엇을 생성하는가

이 파이프라인은 로컬 게임 설치와 StaticData를 다음 순서로 결합한다.

```text
SoloRaidManager / SoloRaidPreset / WaveData
  → season → boss monster_id → MonsterTable.spot_ai
  → ExternalBehavior/spot/<spot_ai> → behavior asset
  → MonsterTimeLineData.aniNumberLists → TimelineAsset attack marker
  → GameAssembly native scheduler contract
  → branch-aware battle-frame IR
  → scenario의 실제 runtime 입력 → 절대 battle frame 평가
```

커밋되는 것은 생성기, 스키마, 테스트와 최소 검증 증거뿐이다. StaticData.zip, 복호 표,
Unity bundle 내용, IL2CPP metadata, 생성 JSON은 모두 `Database/raw/staticdata/` 아래에 있으며
`.gitignore` 대상이다.

## 전제 조건

- Windows의 기본 설치 위치 `C:\NIKKE`
- 현재 클라이언트의 Addressables catalog와 NAPS cache
- `Database/raw/staticdata/StaticData.zip`
- Python 3.11과 `DataPipeline/requirements.txt`의 의존성

다른 설치 위치는 각 명령의 `--nikke-root`, `--naps-root`, `--game-assembly` 옵션으로 지정한다.

업데이트 직후에는 이전 catalog가 LocalLow에 남을 수 있다. 자동 탐색이 여러 core catalog를
발견하면 임의로 고르지 않고 실패한다. 이 경우 snapshot과 기존 artifact의 해시를 확인한 다음
동일 snapshot의 core/dp/fd 세 파일을 `--catalog`로 각각 지정한다.

## 1. 원천 snapshot과 Challenge catalog

라이브 fetch는 자동으로 수행하지 않는다. 먼저 현재 로컬 원천의 manifest와 39개 Challenge
`monster_id → spot_ai` catalog를 만든다.

```powershell
python DataPipeline/crawler/staticdata_challenge_catalog.py
python DataPipeline/crawler/staticdata_snapshot_manifest.py
```

간단한 오케스트레이터 명령도 사용할 수 있다.

```powershell
python DataPipeline/run_pipeline.py --stage snapshot
python DataPipeline/run_pipeline.py --stage challenge
```

처음 실행할 때는 catalog를 먼저 만든 뒤 manifest를 생성해야 manifest에 Challenge identity가
포함된다. `--stage snapshot`은 내부에서 이 순서를 보장한다. 반면 `--stage timeline`은 기존 behavior
artifact를 소비할 뿐 behavior를 자동 생성하지 않는다.

주요 출력:

```text
Database/raw/staticdata/assembled/solo_raid_challenge_catalog.json
Database/raw/staticdata/snapshots/solo_raid_challenge/<data_version>/manifest.json
Database/raw/staticdata/snapshots/solo_raid_challenge/latest.json
```

## 2. 한 시즌의 behavior와 Timeline 자산 추출

시즌 39처럼 한 시즌만 조사할 때는 focused diagnostic을 사용한다. 아래 catalog 이름은
2026-07-13에 분석한 `qa-260702-07b` snapshot의 예다. 게임 업데이트 후에는 현재 snapshot의
이름으로 바꾼다.

```powershell
$catalogRoot = Join-Path $HOME "AppData\LocalLow\com_proximabeta\NIKKE\com.shiftup.addressables"

python DataPipeline/crawler/staticdata_challenge_behavior.py --season 39 `
  --catalog "$catalogRoot\core_148.10.b24_catalog.db" `
  --catalog "$catalogRoot\dp_e7e2988_catalog.db" `
  --catalog "$catalogRoot\fd_3b26558_catalog.db"

python DataPipeline/crawler/staticdata_challenge_timeline.py --season 39 `
  --catalog "$catalogRoot\core_148.10.b24_catalog.db" `
  --catalog "$catalogRoot\dp_e7e2988_catalog.db" `
  --catalog "$catalogRoot\fd_3b26558_catalog.db"
```

출력:

```text
Database/raw/staticdata/assembled/solo_raid_challenge_behavior.season_39.partial.json
Database/raw/staticdata/assembled/solo_raid_challenge_timeline.season_39.partial.json
```

focused artifact는 한 시즌만 담으므로 canonical 39/39 artifact로 승격되지 않는다. 따라서 파일이
정상 생성되어도 CLI 종료 코드는 `2`다. `0`은 canonical complete, `1`은 오류, `2`는 의도적인
non-promotable partial을 뜻한다.

## 3. native scheduler를 결합한 battle-frame IR

```powershell
python DataPipeline/crawler/staticdata_challenge_battle_timeline.py --season 39
```

이 단계는 `C:\NIKKE\NIKKE\game\GameAssembly.dll`의 크기와 SHA-256이 분석한 빌드와 정확히
일치할 때만 native contract를 적용한다. 다른 빌드에는 RVA나 frame 규칙을 재사용하지 않는다.

출력:

```text
Database/raw/staticdata/assembled/solo_raid_challenge_battle_timeline.season_39.partial.json
```

여기에는 전체 behavior graph, branch/parallel/repeater/random recurrence, skill dispatch/effect
template, task terminal contract가 들어간다. 한 시즌 focused artifact이므로 이 명령도 정상 결과에서
종료 코드 `2`를 반환한다.

## 4. 180초 절대 frame 평가

현재 빌드용 예제 scenario를 ignored 작업 디렉터리로 복사한다.

```powershell
New-Item -ItemType Directory -Force Database/raw/staticdata/scenarios | Out-Null
Copy-Item `
  DataPipeline/examples/solo_raid_challenge_battle_scenario.season_39.180s_frontier.json `
  Database/raw/staticdata/scenarios/

python DataPipeline/crawler/staticdata_challenge_scenario_evaluator.py `
  --timeline Database/raw/staticdata/assembled/solo_raid_challenge_battle_timeline.season_39.partial.json `
  --scenario Database/raw/staticdata/scenarios/solo_raid_challenge_battle_scenario.season_39.180s_frontier.json `
  --output Database/raw/staticdata/assembled/solo_raid_challenge_scenario_evaluation.season_39.180s_frontier.partial.json
```

scenario는 source artifact의 파일 SHA-256, catalog digest, GameAssembly SHA-256을 모두 고정한다.
소스가 바뀌면 예전 scenario를 조용히 재사용하지 않고 실패한다.

### runtime 입력 형식

정적으로 알 수 없는 값은 추정하지 않고 `bindings`에 명시한다.

```json
{
  "bindings": {
    "task_terminals": [
      {
        "node_id": 13,
        "context": {},
        "frame": 2088,
        "status": "failure",
        "source": "captured_runtime_trace"
      }
    ],
    "random_permutations": [
      {
        "node_id": 27,
        "activation_index": 0,
        "children": [28, 46, 64, 82],
        "source": "captured_runtime_trace"
      }
    ],
    "skill_effects": [
      {
        "event_id": "node_9_shot_02_impact_unresolved",
        "context": {"repeat_5": 0, "repeat_8": 0},
        "frame": 100,
        "source": "captured_projectile_hit_trace"
      }
    ]
  }
}
```

- `task_terminals`: phase, QTE, 이동, 공격 상태처럼 실제 runtime state에 좌우되는 task 종료
- `random_permutations`: activation별 실제 child 순열. 고정 seed를 주입하지 않는다.
- `skill_effects`: 표적 위치와 투사체 이동에 좌우되는 비-Timeline hit frame

예시 숫자는 형식 설명용이다. 실제 trace와 일치하는 값만 입력한다. native contract가 허용하는
status나 deterministic terminal과 모순되면 evaluator가 거부한다.

scenario를 수정한 뒤 self-digest를 다시 계산한다.

```powershell
python -c "import json; from pathlib import Path; from DataPipeline.crawler.staticdata_challenge_scenario_evaluator import finalize_scenario; p=Path(r'Database/raw/staticdata/scenarios/solo_raid_challenge_battle_scenario.season_39.180s_frontier.json'); v=finalize_scenario(json.loads(p.read_text(encoding='utf-8'))); p.write_text(json.dumps(v, ensure_ascii=False, indent=2, sort_keys=True)+'\n', encoding='utf-8')"
```

구조의 정식 정의는 `DataPipeline/schema/solo_raid_challenge_battle_scenario.schema.json`에 있다.

## 시즌 39 확정 결과

현재 build-pinned 분석에서 일반 BT timer와 Manual PlayableGraph는 rounded float32 `0.017` tick을
사용한다. Timeline 자산의 nominal 60fps frame을 실제 battle-frame offset으로 그대로 사용하면
안 된다.

```text
node 9 Shot_02 dispatch: f58, f230, f754, f926, f1450, f1622

node 11 Shot_07
  activation 0: dispatch f460  → attack marker f645  → terminal f696
  activation 1: dispatch f1156 → attack marker f1341 → terminal f1392
  activation 2: dispatch f1852 → attack marker f2037 → terminal f2088

Pattern node 3 terminal: f2088
최초 genuine runtime frontier: node 13 isPhaseAction @ f2088
```

node 11의 top TimelineAsset은 nominal marker `189f`, duration `240f`지만 Manual graph는 같은 시작
frame부터 `0.017`씩 전진한다. 실제 marker crossing은 186번째 update(`start+185`), playback 종료는
236번째 update(`start+235`), BT terminal 관측은 다음 frame(`start+236`)이다.

`partial`은 정적 분석 실패를 뜻하지 않는다. 실제 phase/QTE/이동/target/random trace를 만들지
않았다는 표시다. 입력을 추가하면 evaluator는 같은 IR에서 다음 genuine frontier 또는 180초 horizon까지
계속 전개한다.

## 검증

```powershell
python -m unittest discover -s DataPipeline/tests -p "test_*.py"
dotnet test SimulatorEngine
```

2026-07-13 기준 결과는 Python `66/66`, SimulatorEngine `169/169`다.

## 업데이트 시 주의사항

1. snapshot manifest를 먼저 다시 만든다.
2. 새 catalog/core build를 이전 artifact와 섞지 않는다.
3. GameAssembly SHA-256이 달라지면 native RVA와 same-frame 순서를 다시 검증한다.
4. 새 Challenge 행이 추가되면 39/39 상수를 자동 확대하지 않고 scope digest를 검토한다.
5. generated/raw/decrypted 파일은 절대 commit하지 않는다.
6. 미지 runtime 값은 graceful unresolved로 남긴다. fixed RNG seed나 추정 frame을 넣지 않는다.
