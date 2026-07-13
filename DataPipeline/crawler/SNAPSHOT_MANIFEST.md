# Solo Raid Challenge snapshot manifest

> 범위: `SoloRaidPresetTable.Difficulty_type == 2`만 attend한다. 일반 solo raid와 union raid는 제외한다.

behavior → Timeline → battle-frame IR → scenario 평가까지의 재현 절차는
[`SOLO_RAID_CHALLENGE_TIMELINE.md`](SOLO_RAID_CHALLENGE_TIMELINE.md)를 따른다.

## 실행

```powershell
python DataPipeline/run_pipeline.py --stage challenge
python DataPipeline/run_pipeline.py --stage behavior
python DataPipeline/run_pipeline.py --stage timeline
python DataPipeline/run_pipeline.py --stage snapshot
```

`challenge`는 `StaticData.zip`을 직접 디코드해 exact catalog만 만든다. `snapshot`은 catalog를 먼저
재생성한 다음 manifest에 반영한다. `behavior`는 로컬 current Addressables NKDB와 NAPS를 읽어
`spot_ai`의 behavior graph와 MonsterSkill frame model을 만든다. `timeline`은 그 behavior artifact와
동일한 catalog snapshot에서 SpotMonster SD bundle을 exact resolve한 뒤 상대 marker frame을 만든다.
라이브 fetch는 수행하지 않는다.

## 출력

```text
Database/raw/staticdata/assembled/solo_raid_challenge_catalog.json
Database/raw/staticdata/assembled/solo_raid_challenge_behavior.partial.json
Database/raw/staticdata/assembled/solo_raid_challenge_timeline.partial.json
Database/raw/staticdata/snapshots/solo_raid_challenge/
  <data_version>/manifest.json
  latest.json
```

전체 출력은 복호 게임데이터와 같은 `.gitignore` 경계에 둔다. 저장소에는 생성기와 JSON Schema만
커밋한다.

`data_version`은 다음 canonical identity의 SHA-256이다.

- StaticData.zip, 공개 roledata, sd.bin, boot catalog, GameAssembly/ScriptingAssemblies 해시
- settings.json에서 allowlist로 투영한 Addressables 버전·project 이름·KeySet 버전/개수
- challenge `(season, preset_id, preset_group_id, wave_id)` scope digest
- 관련 extractor/schema 파일과 현재 파생 artifact 해시

생성 시각과 아직 선택되지 않은 NAPS 전체 캐시 지문은 `data_version`에서 제외한다. 관련 boss bundle을
catalog로 정확히 선택한 뒤에는 선택 bundle의 해시만 identity에 승격한다.

## staged coverage

현재 manifest는 FK 단계를 분리한다.

1. `SoloRaidManager → challenge preset`
2. `challenge preset → WaveData group`
3. `WaveData record → exact boss monster_id`
4. `monster_id → spot_ai`
5. `spot_ai → catalog key → bundle → decoded behavior`

3~4단계는 `nonzero(Target_list) ∩ nonzero(all WaveMonster.MonsterId)`가 정확히 하나일 때만
확정하며, 그 ID를 `MonsterTable`에 exact join한다. 현재 Challenge 39개는 모두 이 검증을 통과해
`static_only` tier다. `Monster_image`, model 이름, 배열 첫 슬롯은 선택 근거가 아니다. 교집합이 0개
또는 여러 개면 기존 catalog를 교체하지 않고 실패한다.

5단계의 exact FK는 다음과 같다.

```text
ExternalBehavior/spot/<spot_ai>
  → keys → key_entries → entries(ExternalBehaviorTree)
  → dependency_key_rowid → bundle entry → entry_data.hash/size
  → NAPS/<hash 앞 2자>/<hash> → UnityFS → behavior JSON
```

2026-07-13 focused 재검증에서는 업데이트된 `core_148.10.b24`와 같은 snapshot의 dp/fd catalog,
NAPS를 사용해 s39 `bt_ebg001_island_zeus_singleRaid`를 exact resolve했다. 이 결과는 season 39만
담은 non-promotable diagnostic이므로 canonical 39/39 behavior artifact의 재생성이나 승격을 주장하지
않는다. focused 결과는 `*.season_39.partial.json`에만 기록하며 다른 `ebg001` variant를 alias로
선택하지 않는다.

behavior output은 `EntryTask`, `RootTask`, `DetachedTasks`, disabled subtree를 구분한 flat graph와
각 Shot action의 boss-local `MonsterSkillTable` multimap join을 담는다. `casting_time`과 `delay_time`은
centisecond에서 60fps integer frame으로 변환한다. 반면 branch/condition/repeater/parallel을 지난
action dispatch frame과 AnimationClip/Timeline marker 기반 실제 hit frame은 근거가 완성될 때까지
symbolic/unresolved로 유지한다.

Timeline의 Shot FK는 asset 이름의 `shot_N` 문자열이 아니다. 다음 serialized object 관계만
authoritative하게 사용한다.

```text
Shot_N
  → MonsterTimeLineData.aniNumberLists
  → owner GameObject.PlayableDirector.m_PlayableAsset
  → top TimelineAsset
  → NKSpotMonsterAttackMarker.m_Time
```

marker frame은 Timeline action 시작 기준 상대 frame이다. 전투 절대 frame은
`조건부 behavior dispatch frame + 상대 marker frame`이며, 분기·HP·반복·이동·preemption이 남으면
symbolic이다. 비-Timeline 공격은 AnimationClip event 또는 runtime callback 근거가 추가되기 전까지
`casting_time`을 곧바로 hit frame으로 간주하지 않는다.

현재 승인 scope는 39행과 그 `(season, preset, group, wave)` digest로 고정한다. 새 시즌 StaticData를
받아 행 수가 바뀌면 자동으로 `40/40 complete` 처리하지 않고 실패하므로, 새 scope를 검토한 뒤
`EXPECTED_CHALLENGE_ROWS`와 `EXPECTED_SCOPE_DIGEST`를 명시적으로 갱신해야 한다. manifest는 저장된
catalog의 digest만 믿지 않고 같은 ZIP에서 catalog를 메모리상 다시 조립해 exact 동등성도 확인한다.

## privacy boundary

생성기는 settings.json 전체를 dump하거나 hash하지 않는다. 다음은 manifest에 들어가지 않는다.

- AES key, `.nds` 내용/해시, host/URL/relative path, pack URL·salt·password
- 절대경로, 사용자명, hostname, 원천 파일 mtime (`generated_at_utc`만 정보용으로 기록)
- `.env`, cookie, auth header, UID, 개인 roster·장비·OL·콘솔
- 로그, telemetry, LocalLow player state, 복호 table/behavior/timeline 원문(검증된 최소 FK 파생값 제외)

NAPS는 파일 내용 대신 정렬된 `상대경로 + 크기`의 내부용 aggregate 지문과 prefix별 1파일 헤더 표본만
기록한다.
