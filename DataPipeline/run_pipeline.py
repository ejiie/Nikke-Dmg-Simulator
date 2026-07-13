#!/usr/bin/env python3
"""DataPipeline 오케스트레이터.

crawler 3종(roledata·static=로그인불필요, blabla=유저데이터)으로 원본을 수집(Database/raw/)
하고, etl 7단계(정적표 4 + 유저병합 3)로 가공(Database/processed/)하는 전체 파이프라인을 실행한다.

각 단계는 별도 프로세스(subprocess)로 돌려 해당 스크립트의 종료 코드를 그대로 존중한다.
어떤 단계가 실패(exit != 0)하면 기본적으로 파이프라인을 중단한다(--keep-going 으로 무시).

사용 예:
  python DataPipeline/run_pipeline.py                 # 전체 (crawl + etl)
  python DataPipeline/run_pipeline.py --stage etl     # ETL 만 (수집 생략)
  python DataPipeline/run_pipeline.py --stage crawl   # 수집만
  python DataPipeline/run_pipeline.py --stage challenge # Challenge monster_id→spot_ai catalog
  python DataPipeline/run_pipeline.py --stage behavior  # spot_ai→behavior graph/frame model
  python DataPipeline/run_pipeline.py --stage timeline  # SpotMonster Timeline marker
  python DataPipeline/run_pipeline.py --stage snapshot # Challenge catalog + snapshot manifest
  python DataPipeline/run_pipeline.py --skip-blabla   # blabla 크롤 제외(로그인 불필요)
  python DataPipeline/run_pipeline.py --dry-run       # 실행 계획만 출력

종료 코드: 모든 단계 성공 0, 하나라도 실패 1.
"""
import argparse
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 이모지 대응
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(CURRENT_DIR, "..")

# (label, 스크립트 상대경로, 기대 산출물 상대경로[정보용])
# 정적 캐릭터 데이터는 prydwen → blablalink roledata(공식)로 이전됨.
# roledata/static 은 공개 CDN(로그인 불필요), blabla(유저데이터)만 로그인 필요.
CRAWL_STAGES = [
    ("crawl:roledata", "crawler/getFromBlaLinkRoledata.py", "Database/raw/blabla_roledata.json"),
    ("crawl:static",   "crawler/getFromBlaLinkStatic.py",   "Database/raw/blabla_static_tables.json"),
    ("crawl:blabla",   "crawler/getFromBlaLink.py",         "Database/raw/nikke_full_scroll_result.json"),
]
# ETL — 정적표 가공(유저데이터 무관, 순서 자유) + 유저 병합 체인(순서 의존). 순서 바꾸지 말 것.
ETL_STAGES = [
    # 정적표(blabla_static_tables) → C# base/effect 표
    ("etl:equip_table",       "etl/equip_table_cleaner.py",       "Database/processed/equip_stat_table.json"),
    ("etl:static_base",       "etl/static_base_cleaner.py",       "Database/processed/cube_base_table.json"),
    ("etl:cube_effect",       "etl/cube_effect_cleaner.py",       "Database/processed/cube_effect_table.json"),
    ("etl:collection_effect", "etl/collection_effect_cleaner.py", "Database/processed/collection_effect_table.json"),
    # 유저데이터 병합 체인 (순서 의존)
    ("etl:blabla_merger",     "etl/blabla_merger.py",    "Database/processed/user_state_clean.json"),
    ("etl:roledata_cleaner",  "etl/roledata_cleaner.py", "Database/processed/roledata_clean.json"),
    ("etl:db_merger",         "etl/db_merger.py",        "Database/processed/nikke_merged_db_returned.json"),
]
# StaticData 체인 (2026-07-08 신설) — 공식 스킬/보스 데이터. ⚖️ 복호물 = gitignore(재배포 금지).
# 전제: Database/raw/staticdata/StaticData.zip (getFromNikkeStaticData.py — 라이브 fetch 는 사용자
# 명시 시에만 별도 실행). 기본 `all` 에 포함하지 않음 — `--stage staticdata` 로 명시 실행. 순서 의존.
STATICDATA_STAGES = [
    ("sd:memorypack",   "crawler/memorypack_decode.py",       "Database/raw/staticdata/mpk/FunctionTable.json"),
    ("sd:raid_decode",  "crawler/staticdata_raid_decode.py",  "Database/raw/staticdata/raid/SoloRaidPresetTable.json"),
    ("sd:solo_raid",    "crawler/staticdata_solo_raid.py",    "Database/raw/staticdata/raid/solo_raid_boss.json"),
    ("sd:skill_chains", "crawler/staticdata_skill_chains.py", "Database/raw/staticdata/assembled/skill_chains.json"),
]

CHALLENGE_CATALOG_STAGE = (
    "sd:challenge_catalog",
    "crawler/staticdata_challenge_catalog.py",
    "Database/raw/staticdata/assembled/solo_raid_challenge_catalog.json",
)

SNAPSHOT_STAGE = (
    "sd:snapshot",
    "crawler/staticdata_snapshot_manifest.py",
    "Database/raw/staticdata/snapshots/solo_raid_challenge/latest.json",
)

CHALLENGE_BEHAVIOR_STAGE = (
    "sd:challenge_behavior",
    "crawler/staticdata_challenge_behavior.py",
    "Database/raw/staticdata/assembled/solo_raid_challenge_behavior.json",
)

CHALLENGE_TIMELINE_STAGE = (
    "sd:challenge_timeline",
    "crawler/staticdata_challenge_timeline.py",
    "Database/raw/staticdata/assembled/solo_raid_challenge_timeline.json",
)


def run_stage(label, rel_path):
    """단계 1개를 subprocess 로 실행. (ok, returncode, elapsed) 반환."""
    script = os.path.join(CURRENT_DIR, rel_path)
    print(f"\n{'=' * 64}\n▶ {label}   ({rel_path})\n{'=' * 64}", flush=True)
    if not os.path.exists(script):
        print(f"❌ 스크립트 없음: {script}", flush=True)
        return False, 127, 0.0
    t0 = time.time()
    # 출력/입력을 그대로 콘솔에 연결 (blabla 의 브라우저 진행 로그가 실시간으로 보이도록)
    proc = subprocess.run([sys.executable, script])
    dt = time.time() - t0
    ok = proc.returncode == 0
    print(f"{'✅' if ok else '❌'} {label} → exit {proc.returncode}  ({dt:.1f}s)", flush=True)
    return ok, proc.returncode, dt


def build_plan(args):
    """선택된 옵션에 따라 실행할 (label, path, expected) 리스트를 만든다."""
    plan = []
    if args.stage in ("all", "crawl"):
        for label, path, expected in CRAWL_STAGES:
            if args.skip_blabla and "blabla" in label:
                continue
            if args.skip_roledata and "roledata" in label:
                continue
            plan.append((label, path, expected))
    if args.stage in ("all", "etl"):
        plan.extend(ETL_STAGES)
    if args.stage == "staticdata":
        plan.extend(STATICDATA_STAGES)
        plan.append(CHALLENGE_CATALOG_STAGE)
    if args.stage == "challenge":
        plan.append(CHALLENGE_CATALOG_STAGE)
    if args.stage == "behavior":
        plan.append(CHALLENGE_CATALOG_STAGE)
        plan.append(CHALLENGE_BEHAVIOR_STAGE)
    if args.stage == "timeline":
        plan.append(CHALLENGE_TIMELINE_STAGE)
    if args.stage == "snapshot":
        plan.append(CHALLENGE_CATALOG_STAGE)
        plan.append(SNAPSHOT_STAGE)
    return plan


def main():
    parser = argparse.ArgumentParser(
        description="DataPipeline 오케스트레이터 (crawl 3종 → etl 7단계)"
    )
    parser.add_argument(
        "--stage",
        choices=["all", "crawl", "etl", "staticdata", "challenge", "behavior", "timeline", "snapshot"],
        default="all",
        help="실행 범위. all=수집+가공(기본), crawl=수집만, etl=가공만, "
             "staticdata=공식 스킬/보스 체인(게임 설치 불필요), "
             "challenge=Challenge monster_id→spot_ai catalog만, "
             "behavior=Challenge spot_ai→behavior graph/frame model, "
             "timeline=SpotMonster authoritative timeline marker, "
             "snapshot=Challenge catalog 생성 후 현재 로컬 원천 manifest",
    )
    parser.add_argument("--skip-blabla", action="store_true",
                        help="유저 데이터 크롤(getFromBlaLink) 제외 (로그인/브라우저 불필요할 때)")
    parser.add_argument("--skip-roledata", action="store_true",
                        help="roledata 정적 크롤 제외 (공식 캐릭터 데이터 재수집 안 할 때)")
    parser.add_argument("--keep-going", action="store_true",
                        help="단계가 실패해도 중단하지 않고 계속")
    parser.add_argument("--dry-run", action="store_true",
                        help="실행하지 않고 계획만 출력")
    args = parser.parse_args()

    plan = build_plan(args)
    if not plan:
        print("⚠️ 실행할 단계가 없음 (옵션 확인).")
        return 0

    print("📋 실행 계획:")
    for i, (label, path, _) in enumerate(plan, 1):
        print(f"  {i}. {label:22} {path}")
    if args.dry_run:
        print("\n(dry-run — 실제 실행 안 함)")
        return 0

    results = []
    aborted = False
    for label, path, expected in plan:
        ok, code, dt = run_stage(label, path)
        # 정보용 산출물 점검 (exit 0 인데 산출물이 없으면 경고만)
        if ok and expected and not os.path.exists(os.path.join(ROOT_DIR, expected)):
            print(f"⚠️ {label}: exit 0 이지만 기대 산출물이 없음 → {expected}", flush=True)
        results.append((label, ok, code, dt))
        if not ok and not args.keep_going:
            print(f"\n⛔ {label} 실패(exit {code}) → 파이프라인 중단. (--keep-going 으로 무시 가능)")
            aborted = True
            break

    print("\n" + "=" * 64 + "\n📊 파이프라인 요약\n" + "=" * 64)
    for label, ok, code, dt in results:
        print(f"  {'✅' if ok else '❌'} {label:22} exit {code:<3} ({dt:.1f}s)")
    failed = [r for r in results if not r[1]]
    skipped = len(plan) - len(results)
    if skipped:
        print(f"  … 미실행 {skipped}단계 (중단됨)")

    if failed or aborted:
        print(f"\n❌ 실패 {len(failed)}개 / 실행 {len(results)}개.")
        return 1
    print(f"\n✅ 전체 {len(results)}단계 성공.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
