# T04 — BossTarget + ElementAdvantage 통합 (구 K11)

> 필독: `CLAUDE.md` → `ROADMAP.md` → `FACTS.md` → 이 문서 → `DataPipeline/crawler/RAID_BOSS.md`.
> 의존: 없음 (T01 과 병렬 가능). MVP 핵심 — solo raid 덱 평가의 타겟 축.

## 목표
solo raid 보스 데이터 기반 `ITarget` 구현 — 시즌/난이도 보스를 골라 run.

## 입력 (준비됨 — gitignore, 재생성 `run_pipeline.py --stage staticdata`)
- `Database/raw/staticdata/raid/solo_raid_boss.json` — 39 solo 변종: element_id·모델·레벨 사다리·
  스탯(group 230000: Lv별 HP/ATK/DEF/파츠HP)·전 파츠[type·is_main·damageable·hp_ratio·passive]·코어 판정 3분류.
- `skill_chains.json` `bosses` 섹션 — passive StateEffect 체인 + 스킬별 use/hurt function 체인 (monster_id 키).
- `ElementTable`(clean): 100001 Fire · 200001 Water · 300001 Wind · 400001 Electric · 500001 Iron.
  weak cycle: Fire→Water, Water→Electric, Wind→Fire, Electric→Iron, Iron→Wind (Weak_element_id 관점 — 주의: 공격자 우월 방향으로 화살표 해석 재확인).

## 구현
1. `BossTarget : ITarget` — 생성 파라미터 (monster_id, level): 스탯 로드(DEF→FinalDef), element_id → Element,
   파츠/코어 → CoreRadius/BodyRadius(설정 상수 — FACTS §8)·HasParts. Distance = 시나리오 파라미터.
2. **ElementAdvantage 통합** (보류 해제 — 이 태스크에서):
   유실분 원본 = `_archive` 아님, 세션 scratchpad 소실 가능 → 5속성 순환 재작성 (FACTS §8 명세로 충분).
   `DummyTarget`/`BossTarget.PopulateContext` 에 상성 판정 배선.
   **⚠ FACTS §7-5: B5 기본 +0.1 단일 소스** — `ElementAdvantage.StrongElementBonus` 만. OL IncElementDmg(별축 가산)·
   스킬 상성버프(AddIncElementDmgType 179 등)와 역할 구분. 골든 리그의 SumStrongElem=1.4293 은 이미 0.1 포함 형태였음.
3. 보스 passive(Immune 계열 — s39 = ImmuneDamage_MainHP 등) → T01 런타임에 등록 (DPS 무관 다수 = no-op).
4. 파츠 히트: `IsPartsHit` 게이트 (B3 parts_dmg) — 파츠 타겟팅 정책은 단순화(메인 바디 기본, 옵션으로 파츠 지정).
5. 하네스 확장: `--boss <monster_id> --boss-level N`.

## 수용 기준
- s39(ebg001_island_zeus, Electric) Lv200: DEF 9107 주입, Iron 공격자 상성 +10%, HP/파츠 수치 로드 정합.
- 상성 순환 5케이스 + 역상성/무상성 0 단위테스트. 중복 가산 없음 검증 (골든 리그 재실행 무변).

## 함정
- solo_raid_boss.json 부재 시 graceful skip (fresh clone). monster_id ↔ skill_chains.bosses 키 = 문자열.
- 보스 스킬 자체 수치(MonsterSkillTable) 미디코드 — 보스 가해 대미지는 스코프 밖(DPS 타겟 역할만). 생존 시뮬 확장 시 재론.
- HP 스케일 = int64 (5.87B까지) — double 정밀도 주의 (2^53 이내라 OK).
