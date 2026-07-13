#!/usr/bin/env python3
"""StaticData.zip에서 Solo Raid Challenge boss catalog를 직접 조립한다.

권위 규칙은 추정이 아니라 다음 exact join이다.

``manager -> Difficulty_type=2 preset -> GroupDict -> WaveData.StageId``
``boss = nonzero(TargetList) ∩ nonzero(all WaveMonster.MonsterId)``
``boss -> MonsterTable.Id -> spot_ai``

교집합, wave record, MonsterTable row가 각각 정확히 하나가 아니면 기존 catalog를
교체하지 않고 실패한다. 출력은 gitignore 된 ``Database/raw/staticdata`` 아래에만 쓴다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import struct
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from .memorypack_decode import SCHEMAS, decode_table
except ImportError:  # 직접 스크립트 실행
    from memorypack_decode import SCHEMAS, decode_table

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SCHEMA_VERSION = 1
CATALOG_KIND = "solo_raid_challenge_static"
DIFFICULTY_TYPE = 2
EXPECTED_CHALLENGE_ROWS = 39
EXPECTED_SCOPE_DIGEST = "85ce4059d7905371b1075979d094aa29a501ffd978f6550a248ab5030da30278"
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_STATIC_ROOT = REPO_ROOT / "Database" / "raw" / "staticdata"
DEFAULT_OUTPUT = DEFAULT_STATIC_ROOT / "assembled" / "solo_raid_challenge_catalog.json"

FIXED_ENTRIES = (
    "SoloRaidManagerTable.mpk",
    "SoloRaidPresetTable.mpk",
    "WaveData.GroupDict.csv",
    "MonsterTable.mpk",
)


class CatalogError(RuntimeError):
    """입력 drift, 결손, 모호성 등 authoritative mapping 실패."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _id(value: Any, label: str) -> str:
    if isinstance(value, bool):
        raise CatalogError(f"{label}: bool은 ID가 아님")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CatalogError(f"{label}: 정수 ID 결손") from exc
    if number <= 0:
        raise CatalogError(f"{label}: 양의 ID가 아님 ({number})")
    return str(number)


def _nonnegative_id(value: Any, label: str) -> str:
    if isinstance(value, bool):
        raise CatalogError(f"{label}: bool은 정수 ID가 아님")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CatalogError(f"{label}: 정수 ID 결손") from exc
    if number < 0:
        raise CatalogError(f"{label}: 음수 ID ({number})")
    return str(number)


def _numeric_sort(values: set[str] | list[str]) -> list[str]:
    return sorted(set(values), key=lambda value: int(value))


def _require_exact_object(value: Any, schema_name: str, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{label}: null/object drift")
    expected = [name for name, _ in SCHEMAS[schema_name]]
    if list(value) != expected:
        raise CatalogError(
            f"{label}: {schema_name} member drift "
            f"expected={expected!r} actual={list(value)!r}"
        )
    return value


def _decode_exact(raw: bytes, entry: str, schema_name: str) -> tuple[list[dict[str, Any]], int]:
    if len(raw) < 5:
        raise CatalogError(f"{entry}: root/header가 너무 짧음")
    root_count = struct.unpack_from("<i", raw, 0)[0]
    if root_count <= 0:
        raise CatalogError(f"{entry}: 비어 있거나 잘못된 root count={root_count}")
    expected_members = len(SCHEMAS[schema_name])
    if raw[4] != expected_members:
        raise CatalogError(
            f"{entry}: memberCount drift expected={expected_members} actual={raw[4]}"
        )
    try:
        rows, clean, wire_count = decode_table(
            raw,
            schema_name,
            SCHEMAS,
            strict_strings=True,
        )
    except (IndexError, KeyError, UnicodeError, ValueError, struct.error) as exc:
        raise CatalogError(f"{entry}: MemoryPack decode 실패") from exc
    if not clean:
        raise CatalogError(f"{entry}: MemoryPack off != len")
    if wire_count != root_count or len(rows) != root_count:
        raise CatalogError(f"{entry}: root count 불일치")
    for index, row in enumerate(rows):
        _require_exact_object(row, schema_name, f"{entry}[{index}]")
    return rows, root_count


def _validate_wave_nested(rows: list[dict[str, Any]], entry: str) -> None:
    for row_index, row in enumerate(rows):
        paths = row.get("wave_data")
        if not isinstance(paths, list):
            raise CatalogError(f"{entry}[{row_index}].wave_data: list 결손")
        for path_index, path in enumerate(paths):
            path = _require_exact_object(
                path,
                "WavePathData",
                f"{entry}[{row_index}].wave_data[{path_index}]",
            )
            monsters = path.get("wave_monster_list")
            if not isinstance(monsters, list):
                raise CatalogError(
                    f"{entry}[{row_index}].wave_data[{path_index}].wave_monster_list: list 결손"
                )
            for slot_index, monster in enumerate(monsters):
                _require_exact_object(
                    monster,
                    "WaveMonster",
                    f"{entry}[{row_index}].wave_data[{path_index}].wave_monster_list[{slot_index}]",
                )


def _validate_monster_nested(rows: list[dict[str, Any]], entry: str) -> None:
    for row_index, row in enumerate(rows):
        skills = row.get("skill_data")
        if skills is None:
            continue
        if not isinstance(skills, list):
            raise CatalogError(f"{entry}[{row_index}].skill_data: list/null이 아님")
        for skill_index, skill in enumerate(skills):
            _require_exact_object(
                skill,
                "MonsterSkillInfoData",
                f"{entry}[{row_index}].skill_data[{skill_index}]",
            )


def _entry_fingerprint(name: str, raw: bytes, *, record_count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "archive_entry": name,
        "size": len(raw),
        "sha256": _sha256_bytes(raw),
    }
    if record_count is not None:
        result["record_count"] = record_count
    return result


def _read_group_dict(raw: bytes) -> tuple[dict[str, set[str]], dict[str, int], int]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CatalogError("WaveData.GroupDict.csv: UTF-8 decode 실패") from exc
    rows = csv.reader(io.StringIO(text))
    header = next(rows, None)
    if not header or len(header) != 2:
        raise CatalogError("WaveData.GroupDict.csv: header 불량")
    normalized_header = [value.strip().lower() for value in header[:2]]
    if normalized_header != ["stage_id", "group_id"]:
        raise CatalogError(
            f"WaveData.GroupDict.csv: header drift actual={normalized_header!r}"
        )
    groups_by_stage: defaultdict[str, set[str]] = defaultdict(set)
    group_counts: defaultdict[str, int] = defaultdict(int)
    total = 0
    for index, row in enumerate(rows, 2):
        if len(row) != 2:
            raise CatalogError(f"WaveData.GroupDict.csv:{index}: column count={len(row)}")
        stage, group = row[0].strip(), row[1].strip()
        if not re.fullmatch(r"[0-9]+", stage):
            raise CatalogError(f"WaveData.GroupDict.csv:{index}: stage_id 불량")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", group):
            raise CatalogError(f"WaveData.GroupDict.csv:{index}: group_id 불량")
        total += 1
        group_counts[group] += 1
        groups_by_stage[stage].add(group)
    if not total:
        raise CatalogError("WaveData.GroupDict.csv: data row 없음")
    return dict(groups_by_stage), dict(group_counts), total


def _index_many(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, list[dict[str, Any]]]:
    result: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        result[_id(row.get(key), f"{label}[{index}].{key}")].append(row)
    return dict(result)


def _atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def build_catalog(
    static_root: Path = DEFAULT_STATIC_ROOT,
    *,
    expected_challenge_rows: int | None = EXPECTED_CHALLENGE_ROWS,
    expected_scope_digest: str | None = EXPECTED_SCOPE_DIGEST,
) -> dict[str, Any]:
    static_root = static_root.resolve()
    zip_path = static_root / "StaticData.zip"
    if not zip_path.is_file():
        raise CatalogError("StaticData.zip 없음")

    source_entries: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        missing = [name for name in FIXED_ENTRIES if name not in names]
        if missing:
            raise CatalogError(f"StaticData.zip 필수 entry 결손: {', '.join(missing)}")

        manager_raw = archive.read("SoloRaidManagerTable.mpk")
        preset_raw = archive.read("SoloRaidPresetTable.mpk")
        group_raw = archive.read("WaveData.GroupDict.csv")
        monster_raw = archive.read("MonsterTable.mpk")

        managers, manager_count = _decode_exact(
            manager_raw, "SoloRaidManagerTable.mpk", "SoloRaidManagerData"
        )
        presets, preset_count = _decode_exact(
            preset_raw, "SoloRaidPresetTable.mpk", "SoloRaidPresetData"
        )
        monsters, monster_count = _decode_exact(monster_raw, "MonsterTable.mpk", "MonsterData")
        _validate_monster_nested(monsters, "MonsterTable.mpk")
        groups_by_stage, group_counts, group_row_count = _read_group_dict(group_raw)

        source_entries["SoloRaidManagerTable.mpk"] = _entry_fingerprint(
            "SoloRaidManagerTable.mpk", manager_raw, record_count=manager_count
        )
        source_entries["SoloRaidPresetTable.mpk"] = _entry_fingerprint(
            "SoloRaidPresetTable.mpk", preset_raw, record_count=preset_count
        )
        source_entries["WaveData.GroupDict.csv"] = _entry_fingerprint(
            "WaveData.GroupDict.csv", group_raw, record_count=group_row_count
        )
        source_entries["MonsterTable.mpk"] = _entry_fingerprint(
            "MonsterTable.mpk", monster_raw, record_count=monster_count
        )

        relation_ids: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
        relations_by_preset: defaultdict[str, set[str]] = defaultdict(set)
        for index, manager in enumerate(managers):
            manager_id = _id(manager.get("Id"), f"manager[{index}].Id")
            preset_group = _id(manager.get("Monster_preset"), f"manager[{index}].Monster_preset")
            season = _id(manager.get("Ranking_group_id"), f"manager[{index}].Ranking_group_id")
            relation_ids[(season, preset_group)].add(manager_id)
            relations_by_preset[preset_group].add(season)

        challenge_presets = [row for row in presets if row.get("Difficulty_type") == DIFFICULTY_TYPE]
        if not challenge_presets:
            raise CatalogError("Difficulty_type=2 challenge preset 없음")
        challenge_by_group: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for index, preset in enumerate(challenge_presets):
            preset_group = _id(
                preset.get("Preset_group_id"), f"challenge_preset[{index}].Preset_group_id"
            )
            challenge_by_group[preset_group].append(preset)
        duplicate_presets = [group for group, rows in challenge_by_group.items() if len(rows) != 1]
        if duplicate_presets:
            raise CatalogError(
                "preset_group별 challenge preset이 정확히 하나가 아님: "
                + ", ".join(_numeric_sort(duplicate_presets))
            )

        selected_groups: set[str] = set()
        selected_stages: list[tuple[dict[str, Any], str, list[str], str]] = []
        for preset_group, preset_rows in challenge_by_group.items():
            seasons = relations_by_preset.get(preset_group, set())
            if len(seasons) != 1:
                raise CatalogError(
                    f"preset_group {preset_group}: manager season relation count={len(seasons)}"
                )
            season = next(iter(seasons))
            preset = preset_rows[0]
            wave_id = _id(preset.get("Wave"), f"preset_group {preset_group}.Wave")
            groups = groups_by_stage.get(wave_id, set())
            if len(groups) != 1:
                raise CatalogError(f"wave {wave_id}: GroupDict group count={len(groups)}")
            wave_group = next(iter(groups))
            selected_groups.add(wave_group)
            selected_stages.append(
                (preset, season, _numeric_sort(relation_ids[(season, preset_group)]), wave_group)
            )

        if len(selected_stages) != len(relation_ids):
            raise CatalogError(
                "manager relation과 challenge preset 범위 불일치: "
                f"relations={len(relation_ids)} challenge={len(selected_stages)}"
            )

        wave_rows_by_group: dict[str, list[dict[str, Any]]] = {}
        wave_index_by_group: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for group in sorted(selected_groups):
            entry = f"WaveDataTable.{group}.mpk"
            if entry not in names:
                raise CatalogError(f"StaticData.zip wave entry 결손: {entry}")
            raw = archive.read(entry)
            rows, count = _decode_exact(raw, entry, "WaveData")
            _validate_wave_nested(rows, entry)
            if group_counts.get(group) != count:
                raise CatalogError(
                    f"{entry}: GroupDict/root count 불일치 "
                    f"groupdict={group_counts.get(group)} root={count}"
                )
            wave_rows_by_group[group] = rows
            wave_index_by_group[group] = _index_many(rows, "stage_id", entry)
            source_entries[entry] = _entry_fingerprint(entry, raw, record_count=count)

    monster_index = _index_many(monsters, "id", "MonsterTable.mpk")
    entries: list[dict[str, Any]] = []
    for preset, season, manager_ids, wave_group in selected_stages:
        preset_id = _id(preset.get("Id"), f"season {season}.preset_id")
        preset_group = _id(preset.get("Preset_group_id"), f"season {season}.preset_group")
        wave_id = _id(preset.get("Wave"), f"season {season}.wave_id")
        wave_matches = wave_index_by_group[wave_group].get(wave_id, [])
        if len(wave_matches) != 1:
            raise CatalogError(
                f"season {season} wave {wave_id}: WaveData StageId count={len(wave_matches)}"
            )
        wave = wave_matches[0]
        if str(wave.get("group_id") or "") != wave_group:
            raise CatalogError(
                f"season {season} wave {wave_id}: record group_id={wave.get('group_id')!r} "
                f"archive group={wave_group!r}"
            )

        target_ids = {
            _id(value, f"season {season}.target_list")
            for value in (wave.get("target_list") or [])
            if value
        }
        spawned: list[dict[str, Any]] = []
        for path_index, path in enumerate(wave["wave_data"]):
            for slot_index, slot in enumerate(path["wave_monster_list"]):
                monster_id = slot.get("wave_monster_id")
                if not monster_id:
                    continue
                spawned.append(
                    {
                        "monster_id": _id(monster_id, f"season {season}.spawned_monster"),
                        "path_index": path_index,
                        "slot_index": slot_index,
                        "wave_path": path.get("wave_path"),
                        "private_monster_count": path.get("private_monster_count"),
                        "spawn_type": slot.get("spawn_type"),
                    }
                )
        spawned_ids = {row["monster_id"] for row in spawned}
        candidates = _numeric_sort(target_ids & spawned_ids)
        if len(candidates) != 1:
            raise CatalogError(
                f"season {season} wave {wave_id}: target∩spawn cardinality={len(candidates)} "
                f"targets={_numeric_sort(target_ids)} spawned={_numeric_sort(spawned_ids)}"
            )
        boss_id = candidates[0]
        monster_matches = monster_index.get(boss_id, [])
        if len(monster_matches) != 1:
            raise CatalogError(
                f"season {season} boss {boss_id}: MonsterTable row count={len(monster_matches)}"
            )
        monster = monster_matches[0]
        spot_ai = {
            "normal": monster.get("spot_ai"),
            "defense": monster.get("spot_ai_defense"),
            "base_defense": monster.get("spot_ai_basedefense"),
        }
        blank_variants = [
            name
            for name, value in spot_ai.items()
            if not isinstance(value, str) or not value.strip() or "\ufffd" in value
        ]
        if blank_variants:
            raise CatalogError(
                f"season {season} boss {boss_id}: blank spot_ai variants={blank_variants}"
            )
        skill_ids = _numeric_sort(
            [
                _id(skill["skill_id"], f"season {season}.skill_id")
                for skill in (monster.get("skill_data") or [])
                if skill and skill.get("skill_id")
            ]
        )
        entries.append(
            {
                "season": season,
                "manager_ids": manager_ids,
                "preset_id": preset_id,
                "preset_group_id": preset_group,
                "difficulty_type": DIFFICULTY_TYPE,
                "wave_order": _id(preset.get("Wave_order"), f"season {season}.wave_order"),
                "wave_id": wave_id,
                "wave_group_id": wave_group,
                "wave_archive_entry": f"WaveDataTable.{wave_group}.mpk",
                "wave_record": {
                    "stage_id": wave_id,
                    "spot_mod": wave.get("spot_mod"),
                    "battle_time": wave.get("battle_time"),
                    "target_monster_ids": _numeric_sort(target_ids),
                    "spawned_monster_ids": _numeric_sort(spawned_ids),
                    "spawned_monsters": spawned,
                    "boss_candidates": candidates,
                },
                "exact_boss_monster_id": boss_id,
                "monster": {
                    "monster_id": boss_id,
                    "monster_model_id": _nonnegative_id(
                        monster.get("monster_model_id"), f"season {season}.monster_model_id"
                    ),
                    "statenhance_id": _nonnegative_id(
                        monster.get("statenhance_id"), f"season {season}.statenhance_id"
                    ),
                    "passive_skill_id": _nonnegative_id(
                        monster.get("passive_skill_id"), f"season {season}.passive_skill_id"
                    ),
                    "skill_ids": skill_ids,
                },
                "spot_ai": spot_ai,
                "verification": {
                    "manager_to_challenge_preset": "verified_exact",
                    "preset_to_wave_group": "verified_exact",
                    "wave_record_lookup": "verified_exact",
                    "target_spawn_intersection": "verified_exact_unique",
                    "monster_to_spot_ai": "verified_exact",
                },
            }
        )

    entries.sort(key=lambda row: int(row["season"]))
    scope_tuples = [
        [row["season"], row["preset_id"], row["preset_group_id"], row["wave_id"]]
        for row in entries
    ]
    scope_digest = _sha256_bytes(_canonical_bytes(scope_tuples))
    if expected_challenge_rows is not None and len(entries) != expected_challenge_rows:
        raise CatalogError(
            f"approved Challenge scope row count drift: expected={expected_challenge_rows} "
            f"actual={len(entries)}"
        )
    if expected_scope_digest is not None and scope_digest != expected_scope_digest:
        raise CatalogError(
            "approved Challenge scope digest drift: "
            f"expected={expected_scope_digest} actual={scope_digest}"
        )
    mapping_text = "".join(
        f"{row['season']}|{row['wave_id']}|{row['exact_boss_monster_id']}|{row['spot_ai']['normal']}\n"
        for row in entries
    ).encode("utf-8")
    duplicate_relations = [
        {
            "season": season,
            "preset_group_id": preset_group,
            "manager_ids": _numeric_sort(ids),
        }
        for (season, preset_group), ids in sorted(
            relation_ids.items(), key=lambda item: (int(item[0][0]), int(item[0][1]))
        )
        if len(ids) > 1
    ]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "catalog_kind": CATALOG_KIND,
        "difficulty_type": DIFFICULTY_TYPE,
        "selection_rule": "nonzero(WaveData.TargetList) intersect nonzero(all WaveMonster.MonsterId)",
        "source": {
            "staticdata_zip": {
                "path": "repo/Database/raw/staticdata/StaticData.zip",
                "size": zip_path.stat().st_size,
                "sha256": _sha256_file(zip_path),
            },
            "entries": dict(sorted(source_entries.items())),
            "schema_source": {
                "repository": "SharpnelXu/nikke-mpk-json-converter",
                "commit": "c02571f68766840054b0f640a21fd9941ba35a95",
                "models": ["NikkeMpkConverter/model/Stages.cs", "NikkeMpkConverter/model/Monster.cs"],
            },
        },
        "scope": {
            "mode": "solo_raid",
            "difficulty_type": DIFFICULTY_TYPE,
            "label": "challenge",
            "scope_digest_sha256": scope_digest,
            "preset_rows": len(entries),
            "season_min": min(int(row["season"]) for row in entries),
            "season_max": max(int(row["season"]) for row in entries),
        },
        "coverage": {
            "denominator": len(entries),
            "wave_records_exact": len(entries),
            "boss_monsters_exact": len(entries),
            "monster_spot_ai_exact": len(entries),
            "duplicate_manager_relations": duplicate_relations,
        },
        "mapping_digest_sha256": _sha256_bytes(mapping_text),
        "entries": entries,
        "validation": {
            "status": "complete",
            "checks": [
                {
                    "name": "challenge_scope_fully_joined",
                    "status": "passed",
                    "expected": len(relation_ids),
                    "actual": len(entries),
                },
                {
                    "name": "boss_candidate_unique",
                    "status": "passed",
                    "expected": len(entries),
                    "actual": len(entries),
                },
                {
                    "name": "monster_spot_ai_exact",
                    "status": "passed",
                    "expected": len(entries),
                    "actual": len(entries),
                },
            ],
        },
    }
    result["catalog_digest_sha256"] = _sha256_bytes(_canonical_bytes(result))
    return result


def write_catalog(
    catalog: dict[str, Any],
    output: Path = DEFAULT_OUTPUT,
    *,
    static_root: Path = DEFAULT_STATIC_ROOT,
) -> Path:
    allowed = (static_root.resolve() / "assembled")
    resolved = output.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise CatalogError("output은 static-root/assembled 하위여야 함") from exc
    _atomic_json_write(resolved, catalog)
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solo Raid Challenge monster_id -> spot_ai catalog 생성")
    parser.add_argument("--static-root", type=Path, default=DEFAULT_STATIC_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    output = args.output or (args.static_root / "assembled" / "solo_raid_challenge_catalog.json")
    try:
        catalog = build_catalog(args.static_root)
        written = write_catalog(catalog, output, static_root=args.static_root)
    except (
        CatalogError,
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
        csv.Error,
        UnicodeError,
        struct.error,
        IndexError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"❌ challenge catalog 실패: {exc}", file=sys.stderr)
        return 1
    coverage = catalog["coverage"]
    print(
        "✅ Solo Raid Challenge exact mapping: "
        f"{coverage['monster_spot_ai_exact']}/{coverage['denominator']}"
    )
    print(f"   mapping digest: {catalog['mapping_digest_sha256']}")
    print(f"   catalog: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
