#!/usr/bin/env python3
"""Resolve Solo Raid Challenge spot_ai assets and extract behavior flow data.

Authoritative chain:

    Challenge monster -> spot_ai -> Addressables exact key -> bundle FK
    -> NAPS content hash -> UnityFS -> ExternalBehaviorTree JSON

The generated artifact lives below ``Database/raw/staticdata`` and is ignored by
git.  A 39/39 result is written to the authoritative filename.  Any missing
client asset is instead written to ``*.partial.json`` and returns exit code 2;
it must not promote the snapshot manifest's behavior tier.

``--season N`` writes an isolated ``season_N.partial.json`` diagnostic.  It
resolves only that season, remains non-promotable, and preserves exit code 2.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
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
    from .addressables_nkdb import (
        AddressableResolution,
        NKDBCatalog,
        NKDBError,
        cached_bundle_path,
        open_nkdb,
        resolve_addressable,
    )
    from .memorypack_decode import SCHEMAS, decode_table
    from .unityfs_minimal import UnityFSBundle, UnityFSError, read_unityfs
    from .unity_serialized_timeline import (
        SerializedTimelineError,
        parse_serialized_file,
    )
except ImportError:  # direct script execution
    from addressables_nkdb import (
        AddressableResolution,
        NKDBCatalog,
        NKDBError,
        cached_bundle_path,
        open_nkdb,
        resolve_addressable,
    )
    from memorypack_decode import SCHEMAS, decode_table
    from unityfs_minimal import UnityFSBundle, UnityFSError, read_unityfs
    from unity_serialized_timeline import (
        SerializedTimelineError,
        parse_serialized_file,
    )

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SCHEMA_VERSION = 1
CATALOG_KIND = "solo_raid_challenge_behavior"
EXPECTED_CHALLENGES = 39
EXPECTED_BEHAVIOR_CLASS = "BehaviorDesigner.Runtime.ExternalBehaviorTree"
ADDRESS_PREFIX = "ExternalBehavior/spot/"
SHOT_RE = re.compile(r"^Shot_(0[1-9]|[1-9][0-9])$")
NAME_BYTES_RE = re.compile(rb"bt_[A-Za-z0-9_]+")
JSON_MARKER = b'{"EntryTask"'

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_STATIC_ROOT = REPO_ROOT / "Database" / "raw" / "staticdata"
DEFAULT_CHALLENGE_CATALOG = (
    DEFAULT_STATIC_ROOT / "assembled" / "solo_raid_challenge_catalog.json"
)
DEFAULT_OUTPUT = (
    DEFAULT_STATIC_ROOT / "assembled" / "solo_raid_challenge_behavior.json"
)
DEFAULT_PARTIAL_OUTPUT = (
    DEFAULT_STATIC_ROOT / "assembled" / "solo_raid_challenge_behavior.partial.json"
)
DEFAULT_CATALOG_DIR = (
    Path.home()
    / "AppData"
    / "LocalLow"
    / "com_proximabeta"
    / "NIKKE"
    / "com.shiftup.addressables"
)
DEFAULT_NAPS_ROOT = Path(r"C:\NIKKE\Unity\com_proximabeta_NIKKE\naps")


class BehaviorCatalogError(RuntimeError):
    """A source is missing, ambiguous, corrupt, or has schema drift."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _id(value: Any, label: str) -> str:
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        number = int(value)
    else:
        raise BehaviorCatalogError(f"{label}: invalid exact integer ID")
    if number <= 0:
        raise BehaviorCatalogError(f"{label}: ID must be positive")
    return str(number)


def _frames_from_centiseconds(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BehaviorCatalogError(f"{label}: invalid nonnegative centiseconds")
    # FACTS.md canonical conversion at 60 fps.  Inputs are nonnegative, so this
    # is explicit half-up quantization and does not depend on Python's bankers'
    # rounding.
    return (value * 60 + 50) // 100


def _find_catalog_files(catalog_dir: Path) -> list[Path]:
    selected: list[Path] = []
    for partition in ("core", "dp", "fd"):
        matches = sorted(catalog_dir.glob(f"{partition}_*_catalog.db"))
        if len(matches) > 1:
            raise BehaviorCatalogError(
                f"{catalog_dir}: multiple current {partition} catalogs; pass --catalog"
            )
        selected.extend(matches)
    if not any(path.name.startswith("core_") for path in selected):
        raise BehaviorCatalogError(f"{catalog_dir}: current core catalog not found")
    return selected


def _load_challenge_catalog(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {token}")
            ),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise BehaviorCatalogError(f"cannot read Challenge catalog: {path}") from exc
    if not isinstance(value, dict):
        raise BehaviorCatalogError("Challenge catalog root is not an object")
    if value.get("catalog_kind") != "solo_raid_challenge_static":
        raise BehaviorCatalogError("unexpected Challenge catalog kind")
    stored_digest = value.get("catalog_digest_sha256")
    digest_payload = dict(value)
    digest_payload.pop("catalog_digest_sha256", None)
    if not isinstance(stored_digest, str) or stored_digest != _sha256(
        _canonical_bytes(digest_payload)
    ):
        raise BehaviorCatalogError("Challenge catalog digest mismatch")
    if value.get("difficulty_type") != 2:
        raise BehaviorCatalogError("Challenge catalog difficulty is not Challenge(2)")
    if value.get("validation", {}).get("status") != "complete":
        raise BehaviorCatalogError("Challenge catalog is not complete")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) != EXPECTED_CHALLENGES:
        raise BehaviorCatalogError("Challenge catalog is not exact 39-row scope")
    seasons = [_id(entry.get("season"), "season") for entry in entries]
    if seasons != [str(index) for index in range(1, EXPECTED_CHALLENGES + 1)]:
        raise BehaviorCatalogError("Challenge seasons are not ordered 1..39")
    mapping_lines: list[str] = []
    for entry in entries:
        season = _id(entry.get("season"), "season")
        if entry.get("difficulty_type") != 2:
            raise BehaviorCatalogError(f"season {season}: difficulty drift")
        monster = entry.get("monster")
        spot = entry.get("spot_ai")
        if not isinstance(monster, dict) or not isinstance(spot, dict):
            raise BehaviorCatalogError(f"season {season}: missing monster/spot_ai")
        monster_id = _id(monster.get("monster_id"), f"season {season}.monster_id")
        exact_id = _id(
            entry.get("exact_boss_monster_id"),
            f"season {season}.exact_boss_monster_id",
        )
        if monster_id != exact_id:
            raise BehaviorCatalogError(f"season {season}: exact boss ID mismatch")
        wave_id = _id(entry.get("wave_id"), f"season {season}.wave_id")
        normal = spot.get("normal")
        if not isinstance(normal, str) or not normal:
            raise BehaviorCatalogError(f"season {season}: invalid spot_ai")
        mapping_lines.append(f"{season}|{wave_id}|{exact_id}|{normal}\n")
    mapping_digest = _sha256("".join(mapping_lines).encode("utf-8"))
    if value.get("mapping_digest_sha256") != mapping_digest:
        raise BehaviorCatalogError("Challenge mapping digest mismatch")
    return value


def _select_challenge_entries(
    challenge: dict[str, Any], season: int | None
) -> tuple[list[dict[str, Any]], bool]:
    """Return the canonical full scope or one explicitly targeted season.

    A targeted run is always a partial artifact.  It exists for local
    forensics and must never satisfy the 39/39 authoritative promotion rule.
    """

    entries = challenge["entries"]
    if season is None:
        return entries, False
    if type(season) is not int or not 1 <= season <= EXPECTED_CHALLENGES:
        raise BehaviorCatalogError(
            f"season must be an integer in 1..{EXPECTED_CHALLENGES}"
        )
    selected = [entry for entry in entries if str(entry.get("season")) == str(season)]
    if len(selected) != 1:
        raise BehaviorCatalogError(f"season {season}: not uniquely present in Challenge catalog")
    return selected, True


def _decode_monster_skills(staticdata_zip: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entry_name = "MonsterSkillTable.mpk"
    try:
        with zipfile.ZipFile(staticdata_zip) as archive:
            info = archive.getinfo(entry_name)
            raw = archive.read(info)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise BehaviorCatalogError(f"cannot read {entry_name} from StaticData.zip") from exc
    schema = SCHEMAS["MonsterSkillData"]
    if len(raw) < 5 or raw[4] != len(schema):
        actual = raw[4] if len(raw) >= 5 else None
        raise BehaviorCatalogError(
            f"{entry_name}: memberCount drift expected={len(schema)} actual={actual}"
        )
    try:
        rows, clean, wire_count = decode_table(
            raw,
            "MonsterSkillData",
            SCHEMAS,
            strict_strings=True,
        )
    except (IndexError, KeyError, UnicodeError, ValueError, struct.error) as exc:
        raise BehaviorCatalogError(f"{entry_name}: exact MemoryPack decode failed") from exc
    if not clean or len(rows) != wire_count:
        raise BehaviorCatalogError(f"{entry_name}: decode did not consume the full payload")
    expected_fields = [name for name, _ in schema]
    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or list(row) != expected_fields:
            raise BehaviorCatalogError(f"{entry_name}[{index}]: object schema drift")
        skill_id = _id(row.get("id"), f"{entry_name}[{index}].id")
        if skill_id in by_id:
            raise BehaviorCatalogError(f"{entry_name}: duplicate skill id {skill_id}")
        by_id[skill_id] = row
    return rows, {
        "archive_entry": entry_name,
        "record_count": wire_count,
        "size": len(raw),
        "sha256": _sha256(raw),
        "staticdata_zip_sha256": _sha256_file(staticdata_zip),
        "by_id": by_id,
    }


def _decode_monster_models(staticdata_zip: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entry_name = "MonsterModelTable.mpk"
    try:
        with zipfile.ZipFile(staticdata_zip) as archive:
            raw = archive.read(entry_name)
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise BehaviorCatalogError(f"cannot read {entry_name} from StaticData.zip") from exc
    schema = SCHEMAS["MonsterModelData"]
    if len(raw) < 5 or raw[4] != len(schema):
        actual = raw[4] if len(raw) >= 5 else None
        raise BehaviorCatalogError(
            f"{entry_name}: memberCount drift expected={len(schema)} actual={actual}"
        )
    try:
        rows, clean, wire_count = decode_table(
            raw,
            "MonsterModelData",
            SCHEMAS,
            strict_strings=True,
        )
    except (IndexError, KeyError, UnicodeError, ValueError, struct.error) as exc:
        raise BehaviorCatalogError(f"{entry_name}: exact MemoryPack decode failed") from exc
    if not clean or len(rows) != wire_count:
        raise BehaviorCatalogError(f"{entry_name}: decode did not consume the full payload")
    expected_fields = [name for name, _ in schema]
    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or list(row) != expected_fields:
            raise BehaviorCatalogError(f"{entry_name}[{index}]: object schema drift")
        model_id = _id(row.get("id"), f"{entry_name}[{index}].id")
        prefab = row.get("mon_prefab")
        if not isinstance(prefab, str) or not prefab:
            raise BehaviorCatalogError(f"{entry_name}[{index}]: missing mon_prefab")
        if model_id in by_id:
            raise BehaviorCatalogError(f"{entry_name}: duplicate model id {model_id}")
        by_id[model_id] = row
    return rows, {
        "archive_entry": entry_name,
        "record_count": wire_count,
        "size": len(raw),
        "sha256": _sha256(raw),
        "by_id": by_id,
    }


def _normalize_skill(row: dict[str, Any]) -> dict[str, Any]:
    animation_number = row["skill_ani_number"]
    if not isinstance(animation_number, int) or not 1 <= animation_number <= 99:
        raise BehaviorCatalogError(
            f"MonsterSkill {row.get('id')}: unsupported Shot enum {animation_number!r}"
        )
    casting_cs = row["casting_time"]
    delay_cs = row["delay_time"]
    return {
        "skill_id": _id(row["id"], "MonsterSkill.id"),
        "animation": {
            "enum_value": animation_number,
            "shot_key": f"Shot_{animation_number:02d}",
        },
        "timing": {
            "casting_centiseconds": casting_cs,
            "casting_frames_60fps": _frames_from_centiseconds(
                casting_cs, f"MonsterSkill {row['id']}.casting_time"
            ),
            "delay_centiseconds": delay_cs,
            "delay_frames_60fps": _frames_from_centiseconds(
                delay_cs, f"MonsterSkill {row['id']}.delay_time"
            ),
            "shot_count": row["shot_count"],
            "shot_timing_enum": row["shot_timing"],
            "relate_anim": row["relate_anim"],
            "is_using_timeline": row["is_using_timeline"],
            "event_frame_status": "requires_animation_or_timeline_marker",
        },
        "attack": {
            "weapon_type_enum": row["weapon_type"],
            "attack_type_enum": row["attack_type"],
            "fire_type_enum": row["fire_type"],
            "penetration": row["penetration"],
            "projectile_speed": row["projectile_speed"],
            "projectile_hp_ratio": row["projectile_hp_ratio"],
            "projectile_def_ratio": row["projectile_def_ratio"],
            "projectile_radius_object": row["projectile_radius_object"],
            "projectile_radius": row["projectile_radius"],
            "spot_explosion_range": row["spot_explosion_range"],
            "is_destroyable_projectile": row["is_destroyable_projectile"],
        },
        "targeting": {
            "prefer_target_enum": row["prefer_target"],
            "target_count": row["target_count"],
            "target_character_ratio": row["target_character_ratio"],
            "target_cover_ratio": row["target_cover_ratio"],
            "target_nothing_ratio": row["target_nothing_ratio"],
        },
        "control": {
            "control_gauge": row["control_gauge"],
            "show_breakable_time": row["show_breakable_time"],
            "control_parts": row["control_parts"],
            "cancel_type_enum": row["cancel_type"],
            "linked_parts_enum": row["linked_parts"],
        },
        "resources": {
            "object_resource": row["object_resource"],
            "break_object": row["break_object"],
            "move_object": row["move_object"],
        },
        "skill_values": [
            {
                "type_enum": row["skill_value_type_01"],
                "value": str(row["skill_value_01"]),
            },
            {
                "type_enum": row["skill_value_type_02"],
                "value": str(row["skill_value_02"]),
            },
        ],
    }


@dataclasses.dataclass(frozen=True)
class BehaviorDocument:
    asset_internal_id: str
    name: str
    path_id: int
    source_offset: int
    raw_json_size: int
    raw_json_sha256: str
    tree: dict[str, Any]


def _serialized_node(bundle: UnityFSBundle) -> Any:
    candidates = [
        node
        for node in bundle.nodes
        if not node.path.lower().endswith(".ress")
        and len(node.data) >= 48
        and struct.unpack_from(">I", node.data, 8)[0] == 22
    ]
    if len(candidates) != 1:
        raise BehaviorCatalogError(
            f"expected one SerializedFile v22 node, found {len(candidates)}"
        )
    return candidates[0]


def _asset_bundle_container(serialized: Any) -> dict[str, int]:
    objects = [
        obj
        for obj in serialized.objects
        if serialized.types[obj.type_id].class_id == 142
    ]
    if len(objects) != 1:
        raise BehaviorCatalogError(f"expected one AssetBundle object, found {len(objects)}")
    reader = serialized.object_reader(objects[0], "AssetBundle")
    reader.aligned_string()  # m_Name
    preload_count = reader.count("m_PreloadTable")
    preload = [reader.pptr() for _ in range(preload_count)]
    container_count = reader.count("m_Container")
    result: dict[str, int] = {}
    for _ in range(container_count):
        internal_id = reader.aligned_string()
        preload_index = reader.i32()
        preload_size = reader.i32()
        asset = reader.pptr()
        if not re.fullmatch(r"[0-9a-f]{32}", internal_id):
            raise BehaviorCatalogError("AssetBundle container has invalid internal ID")
        if internal_id in result:
            raise BehaviorCatalogError(f"duplicate AssetBundle internal ID {internal_id}")
        if preload_index < 0 or preload_size < 0:
            raise BehaviorCatalogError(f"{internal_id}: invalid preload range")
        if preload_index + preload_size > len(preload):
            raise BehaviorCatalogError(f"{internal_id}: preload range exceeds table")
        if asset.file_id != 0 or asset.path_id not in serialized.objects_by_path:
            raise BehaviorCatalogError(f"{internal_id}: invalid local asset PPtr")
        result[internal_id] = asset.path_id
    # m_MainAsset AssetInfo
    reader.i32()
    reader.i32()
    main_asset = reader.pptr()
    if main_asset.file_id != 0:
        raise BehaviorCatalogError("AssetBundle main asset is external")
    reader.i32()  # m_RuntimeCompatibility
    reader.aligned_string()  # m_AssetBundleName
    for _ in range(reader.count("m_Dependencies")):
        reader.aligned_string()
    streamed = reader.u8()
    if streamed not in (0, 1):
        raise BehaviorCatalogError("AssetBundle streamed flag is not bool")
    reader.align(4)
    explicit_layout = reader.i32()
    if explicit_layout not in (0, 1):
        raise BehaviorCatalogError("AssetBundle explicit-layout flag is not bool")
    reader.i32()  # m_PathFlags
    for _ in range(reader.count("m_SceneHashes")):
        reader.aligned_string()
        reader.aligned_string()
    reader.finish()
    return result


def _external_behavior_script_path(serialized: Any) -> int:
    matches: list[int] = []
    for obj in serialized.objects:
        if serialized.types[obj.type_id].class_id != 115:
            continue
        reader = serialized.object_reader(obj, f"MonoScript {obj.path_id}")
        reader.aligned_string()  # m_Name
        reader.i32()
        reader.bytes(16)
        class_name = reader.aligned_string()
        namespace = reader.aligned_string()
        assembly = reader.aligned_string()
        reader.finish()
        if (
            class_name == "ExternalBehaviorTree"
            and namespace == "BehaviorDesigner.Runtime"
            and assembly.startswith("BehaviorDesigner.Unity.Runtime")
        ):
            matches.append(obj.path_id)
    if len(matches) != 1:
        raise BehaviorCatalogError(
            f"expected one ExternalBehaviorTree MonoScript, found {len(matches)}"
        )
    return matches[0]


def extract_behavior_documents(bundle: UnityFSBundle) -> dict[str, BehaviorDocument]:
    """Map AssetBundle internal IDs to the exact referenced behavior objects."""

    node = _serialized_node(bundle)
    serialized = parse_serialized_file(node.data)
    container = _asset_bundle_container(serialized)
    script_path = _external_behavior_script_path(serialized)
    documents: dict[str, BehaviorDocument] = {}
    names: set[str] = set()
    for internal_id, path_id in container.items():
        obj = serialized.objects_by_path[path_id]
        if serialized.types[obj.type_id].class_id != 114:
            raise BehaviorCatalogError(f"{internal_id}: container target is not MonoBehaviour")
        reader = serialized.object_reader(obj, f"ExternalBehaviorTree {path_id}")
        game_object = reader.pptr()
        enabled = reader.u8()
        if enabled not in (0, 1):
            raise BehaviorCatalogError(f"{internal_id}: m_Enabled is not bool")
        reader.align(4)
        script = reader.pptr()
        name = reader.aligned_string()
        if game_object.file_id != 0 or game_object.path_id != 0:
            raise BehaviorCatalogError(f"{internal_id}: unexpected GameObject owner")
        if script.file_id != 0 or script.path_id != script_path:
            raise BehaviorCatalogError(f"{internal_id}: wrong MonoScript reference")
        if not isinstance(name, str) or not name.startswith("bt_"):
            raise BehaviorCatalogError(f"{internal_id}: invalid behavior name")

        object_start = serialized.data_offset + obj.byte_start
        object_end = object_start + obj.byte_size
        search_from = reader.offset
        found: list[tuple[int, int, bytes, dict[str, Any]]] = []
        while True:
            start = serialized.data.find(JSON_MARKER, search_from, object_end)
            if start < 0:
                break
            if start >= object_start + 4:
                raw_size = struct.unpack_from("<I", serialized.data, start - 4)[0]
                end = start + raw_size
                if raw_size > len(JSON_MARKER) and end <= object_end:
                    raw_json = serialized.data[start:end]
                    try:
                        tree = json.loads(
                            raw_json.decode("utf-8", "strict"),
                            parse_constant=lambda token: (_ for _ in ()).throw(
                                ValueError(f"non-finite JSON constant {token}")
                            ),
                        )
                    except (UnicodeError, ValueError, json.JSONDecodeError):
                        tree = None
                    if (
                        isinstance(tree, dict)
                        and "EntryTask" in tree
                        and "RootTask" in tree
                    ):
                        found.append((start, raw_size, raw_json, tree))
                        search_from = end
                        continue
            search_from = start + 1
        # Some editor/container entries legitimately have no serialized task
        # graph.  They remain unselectable; every catalog-selected Challenge
        # asset below is required to have exactly one.
        if not found:
            continue
        if len(found) != 1:
            raise BehaviorCatalogError(f"{internal_id}: multiple behavior JSON payloads")
        start, raw_size, raw_json, tree = found[0]
        if name in names:
            raise BehaviorCatalogError(f"duplicate behavior asset name {name}")
        names.add(name)
        documents[internal_id] = BehaviorDocument(
            asset_internal_id=internal_id,
            name=name,
            path_id=path_id,
            source_offset=start,
            raw_json_size=raw_size,
            raw_json_sha256=_sha256(raw_json),
            tree=tree,
        )
    if not documents:
        raise BehaviorCatalogError("UnityFS bundle contains no behavior documents")
    return documents


_DECORATOR_NAMES = {
    "Inverter",
    "Repeater",
    "ReturnFailure",
    "ReturnSuccess",
    "StartAttack",
    "EndAttack",
}


def _node_kind(task: dict[str, Any], children: list[Any]) -> str:
    type_name = task.get("Type", "")
    short_name = type_name.rsplit(".", 1)[-1]
    if children:
        return "decorator" if short_name in _DECORATOR_NAMES else "composite"
    if ".Conditionals." in type_name:
        return "condition"
    if short_name == "TimeCount":
        return "timer"
    if (
        "SkillAniNumberTypemSkillAniNumber" in task
        or "List`1_aniNumberTypes" in task
    ):
        return "skill_action"
    if ".Actions." in type_name or type_name.endswith(".Actions"):
        return "action"
    return "unknown"


def _shot_keys(task: dict[str, Any], label: str) -> list[str]:
    values: list[Any] = []
    if "SkillAniNumberTypemSkillAniNumber" in task:
        values.append(task["SkillAniNumberTypemSkillAniNumber"])
    if "List`1_aniNumberTypes" in task:
        listed = task["List`1_aniNumberTypes"]
        if not isinstance(listed, list):
            raise BehaviorCatalogError(f"{label}: Shot list is not an array")
        values.extend(listed)
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not SHOT_RE.fullmatch(value):
            raise BehaviorCatalogError(f"{label}: invalid Shot key {value!r}")
        result.append(value)
    return result


def _normalize_task_graph(
    document: BehaviorDocument,
    skills_by_shot: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    tree = document.tree
    entry = tree.get("EntryTask")
    root = tree.get("RootTask")
    detached = tree.get("DetachedTasks")
    if not isinstance(entry, dict) or not isinstance(root, dict):
        raise BehaviorCatalogError(f"{document.name}: missing entry/root task")
    if detached is None:
        detached = []
    if not isinstance(detached, list) or not all(isinstance(item, dict) for item in detached):
        raise BehaviorCatalogError(f"{document.name}: DetachedTasks is not a task list")
    if entry.get("ID") != 0 or root.get("ID") != 1:
        raise BehaviorCatalogError(f"{document.name}: expected Entry=0 and Root=1")
    if root.get("Type") != "NK.Spot.BehaviorTree.Monster.Composites.InitVariables":
        raise BehaviorCatalogError(f"{document.name}: unexpected root task type")

    nodes: list[dict[str, Any]] = []
    skill_sites: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    stats = defaultdict(int)

    def visit(
        task: dict[str, Any],
        *,
        role: str,
        parent_id: int | None,
        child_index: int | None,
        source_path: str,
        parent_effective_enabled: bool,
        ancestors: list[dict[str, Any]],
    ) -> None:
        task_id = task.get("ID")
        type_name = task.get("Type")
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 0:
            raise BehaviorCatalogError(f"{document.name}:{source_path}: invalid task ID")
        if not isinstance(type_name, str) or not type_name:
            raise BehaviorCatalogError(f"{document.name}:{source_path}: missing task type")
        if task_id in seen_ids:
            raise BehaviorCatalogError(f"{document.name}: duplicate task ID {task_id}")
        seen_ids.add(task_id)
        children = task.get("Children", [])
        if children is None:
            children = []
        if not isinstance(children, list) or not all(isinstance(item, dict) for item in children):
            raise BehaviorCatalogError(f"{document.name}:{task_id}: invalid Children")
        disabled = task.get("Disabled", False)
        instant = task.get("Instant")
        if type(disabled) is not bool:
            raise BehaviorCatalogError(f"{document.name}:{task_id}: Disabled is not bool")
        if type(instant) is not bool:
            raise BehaviorCatalogError(f"{document.name}:{task_id}: Instant is not bool")
        locally_enabled = not disabled
        effective_enabled = parent_effective_enabled and locally_enabled
        active_graph = role == "root"
        kind = _node_kind(task, children)
        shots = _shot_keys(task, f"{document.name}:{task_id}")
        node_data = task.get("NodeData")
        comment = node_data.get("Comment") if isinstance(node_data, dict) else None
        reserved = {
            "Type",
            "NodeData",
            "ID",
            "Name",
            "Instant",
            "Disabled",
            "Children",
            "AbortTypeabortType",
            "SkillAniNumberTypemSkillAniNumber",
            "List`1_aniNumberTypes",
        }
        params = {key: value for key, value in task.items() if key not in reserved}
        normalized: dict[str, Any] = {
            "id": task_id,
            "type": type_name,
            "kind": kind,
            "graph_role": role,
            "active_graph": active_graph,
            "locally_enabled": locally_enabled,
            "effective_enabled": effective_enabled,
            "instant": instant,
            "name": task.get("Name"),
            "comment": comment,
            "parent_id": parent_id,
            "child_index": child_index,
            "child_ids": [child.get("ID") for child in children],
            "abort_type": task.get("AbortTypeabortType"),
            "params": params,
            "shot_keys": shots,
            "source_path": source_path,
        }
        if kind == "timer":
            mode = task.get("ETimeCountTypemType")
            seconds = task.get("SinglemCustomTime")
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds)
            ):
                raise BehaviorCatalogError(f"{document.name}:{task_id}: invalid TimeCount")
            normalized["timer"] = {
                "mode": mode,
                "seconds_decimal": str(seconds),
                "frame_expression": {
                    "fps": 60,
                    "expression": f"quantize({seconds} * 60)",
                    "rounding": "runtime_tick_semantics_required",
                },
            }
        if not normalized["instant"]:
            normalized["completion_to_next_dispatch"] = {
                "status": "runtime_behavior_designer_semantics_required",
                "update_ticks": None,
                "frame_count": None,
            }
        nodes.append(normalized)
        stats["node_count"] += 1
        stats[f"kind:{kind}"] += 1
        if not locally_enabled:
            stats["locally_disabled_count"] += 1

        if shots:
            candidates = [
                {
                    "shot_key": shot,
                    "status": (
                        "unresolved"
                        if not skills_by_shot.get(shot)
                        else "exact"
                        if len(skills_by_shot[shot]) == 1
                        else "ambiguous"
                    ),
                    "candidate_skill_ids": [
                        skill["skill_id"] for skill in skills_by_shot.get(shot, [])
                    ],
                }
                for shot in shots
            ]
            skill_sites.append(
                {
                    "node_id": task_id,
                    "action_type": type_name,
                    "shot_keys": shots,
                    "active_graph": active_graph,
                    "effective_enabled": effective_enabled,
                    "source_path": source_path,
                    "control_path_node_ids": [item["node_id"] for item in ancestors],
                    "monster_skill_join": candidates,
                    "dispatch_frame": {
                        "status": (
                            "conditional_symbolic"
                            if active_graph and effective_enabled
                            else "excluded_inactive_or_disabled"
                        ),
                        "origin": "battle_start",
                        "expression": {
                            "op": "behavior_flow_dispatch",
                            "node_id": task_id,
                        },
                        "requires": [
                            "branch_results",
                            "condition_state",
                            "movement_completion",
                            "repeater_iteration",
                            "parallel_preemption",
                            "runtime_tick_semantics",
                        ],
                    },
                }
            )
            stats["shot_reference_count"] += len(shots)
            if active_graph and effective_enabled:
                stats["active_shot_reference_count"] += len(shots)

        next_ancestors = ancestors + [
            {
                "node_id": task_id,
                "type": type_name,
                "child_index": child_index,
                "abort_type": task.get("AbortTypeabortType"),
            }
        ]
        for index, child in enumerate(children):
            visit(
                child,
                role=role,
                parent_id=task_id,
                child_index=index,
                source_path=f"{source_path}/{index}",
                parent_effective_enabled=effective_enabled,
                ancestors=next_ancestors,
            )

    visit(
        entry,
        role="entry",
        parent_id=None,
        child_index=None,
        source_path="entry",
        parent_effective_enabled=True,
        ancestors=[],
    )
    visit(
        root,
        role="root",
        parent_id=None,
        child_index=None,
        source_path="root",
        parent_effective_enabled=True,
        ancestors=[],
    )
    detached_root_ids: list[int] = []
    for index, task in enumerate(detached):
        detached_root_ids.append(task.get("ID"))
        visit(
            task,
            role="detached",
            parent_id=None,
            child_index=None,
            source_path=f"detached/{index}",
            parent_effective_enabled=True,
            ancestors=[],
        )
    nodes.sort(key=lambda item: item["id"])
    skill_sites.sort(key=lambda item: item["node_id"])
    graph = {
        "entry_id": 0,
        "root_id": 1,
        "detached_root_ids": detached_root_ids,
        "execution_scope": "root_only",
        "nodes": nodes,
    }
    return graph, skill_sites, dict(sorted(stats.items()))


def _resolve_all(
    catalogs: list[NKDBCatalog],
    key: str,
) -> tuple[NKDBCatalog, AddressableResolution] | None:
    matches: list[tuple[NKDBCatalog, AddressableResolution]] = []
    for catalog in catalogs:
        resolution = resolve_addressable(
            catalog,
            key,
            expected_class=EXPECTED_BEHAVIOR_CLASS,
        )
        if resolution is not None:
            matches.append((catalog, resolution))
    if not matches:
        return None
    if len(matches) != 1:
        raise BehaviorCatalogError(f"{key}: present in multiple catalog partitions")
    return matches[0]


def build_behavior_catalog(
    *,
    challenge_catalog_path: Path = DEFAULT_CHALLENGE_CATALOG,
    staticdata_zip: Path | None = None,
    catalog_paths: list[Path] | None = None,
    catalog_dir: Path = DEFAULT_CATALOG_DIR,
    naps_root: Path = DEFAULT_NAPS_ROOT,
    season: int | None = None,
) -> dict[str, Any]:
    challenge = _load_challenge_catalog(challenge_catalog_path)
    challenge_entries, targeted = _select_challenge_entries(challenge, season)
    target_count = len(challenge_entries)
    if staticdata_zip is None:
        staticdata_zip = DEFAULT_STATIC_ROOT / "StaticData.zip"
    if catalog_paths is None:
        catalog_paths = _find_catalog_files(catalog_dir)

    catalogs: list[NKDBCatalog] = []
    try:
        for path in sorted(catalog_paths, key=lambda item: item.name):
            catalogs.append(open_nkdb(path))
        if not catalogs:
            raise BehaviorCatalogError("no Addressables catalogs selected")

        _all_skill_rows, skill_source = _decode_monster_skills(staticdata_zip)
        skill_by_id: dict[str, dict[str, Any]] = skill_source.pop("by_id")
        _all_model_rows, model_source = _decode_monster_models(staticdata_zip)
        model_by_id: dict[str, dict[str, Any]] = model_source.pop("by_id")

        resolved: dict[str, tuple[NKDBCatalog, AddressableResolution]] = {}
        missing: list[dict[str, Any]] = []
        for challenge_entry in challenge_entries:
            season = _id(challenge_entry.get("season"), "season")
            spot = challenge_entry.get("spot_ai")
            if not isinstance(spot, dict):
                raise BehaviorCatalogError(f"season {season}: missing spot_ai object")
            normal = spot.get("normal")
            if not isinstance(normal, str) or not normal:
                raise BehaviorCatalogError(f"season {season}: invalid normal spot_ai")
            if spot.get("defense") != normal or spot.get("base_defense") != normal:
                raise BehaviorCatalogError(
                    f"season {season}: Challenge spot_ai variants are not identical"
                )
            key = ADDRESS_PREFIX + normal
            match = _resolve_all(catalogs, key)
            if match is None:
                missing.append(
                    {
                        "season": season,
                        "spot_ai": normal,
                        "addressable_key": key,
                        "reason": "missing_in_client_snapshot",
                    }
                )
            else:
                resolved[season] = match

        bundle_records: dict[str, dict[str, Any]] = {}
        behavior_by_bundle: dict[str, dict[str, BehaviorDocument]] = {}
        for _season, (_catalog, resolution) in resolved.items():
            existing = bundle_records.get(resolution.bundle_hash)
            if existing is not None:
                if existing["catalog_bundle_size"] != resolution.bundle_size:
                    raise BehaviorCatalogError("same bundle hash has conflicting sizes")
                continue
            bundle_path = cached_bundle_path(naps_root, resolution)
            bundle = read_unityfs(bundle_path)
            documents = extract_behavior_documents(bundle)
            behavior_by_bundle[resolution.bundle_hash] = documents
            bundle_records[resolution.bundle_hash] = {
                "catalog_content_hash": resolution.bundle_hash,
                "catalog_bundle_size": resolution.bundle_size,
                "file_sha256": bundle.sha256,
                "format_version": bundle.format_version,
                "unity_version": bundle.unity_version,
                "unity_revision": bundle.unity_revision,
                "node_count": len(bundle.nodes),
                "nodes": [
                    {"logical_path": node.path, "size": node.size, "flags": node.flags}
                    for node in bundle.nodes
                ],
                "behavior_document_count": len(documents),
            }

        entries: list[dict[str, Any]] = []
        total_stats = defaultdict(int)
        for challenge_entry in challenge_entries:
            season = _id(challenge_entry["season"], "season")
            monster = challenge_entry.get("monster")
            if not isinstance(monster, dict):
                raise BehaviorCatalogError(f"season {season}: missing monster object")
            monster_id = _id(monster.get("monster_id"), f"season {season}.monster_id")
            model_id = _id(
                monster.get("monster_model_id"), f"season {season}.monster_model_id"
            )
            model = model_by_id.get(model_id)
            if model is None:
                raise BehaviorCatalogError(
                    f"season {season}: MonsterModel row {model_id} is missing"
                )
            raw_skill_ids = monster.get("skill_ids")
            if not isinstance(raw_skill_ids, list):
                raise BehaviorCatalogError(f"season {season}: missing skill_ids")
            skill_ids = [_id(value, f"season {season}.skill_id") for value in raw_skill_ids]
            if len(skill_ids) != len(set(skill_ids)):
                raise BehaviorCatalogError(f"season {season}: duplicate boss skill ID")
            missing_skill_ids = [skill_id for skill_id in skill_ids if skill_id not in skill_by_id]
            if missing_skill_ids:
                raise BehaviorCatalogError(
                    f"season {season}: MonsterSkill rows missing {missing_skill_ids}"
                )
            skills = [_normalize_skill(skill_by_id[skill_id]) for skill_id in skill_ids]
            skills_by_shot: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for skill in skills:
                skills_by_shot[skill["animation"]["shot_key"]].append(skill)

            normal = challenge_entry["spot_ai"]["normal"]
            key = ADDRESS_PREFIX + normal
            base_entry: dict[str, Any] = {
                "season": season,
                "monster_id": monster_id,
                "monster_model": {
                    "model_id": model_id,
                    "mon_prefab": model["mon_prefab"],
                    "spotmonster_addressable_key": f"SpotMonster/{model['mon_prefab']}",
                    "resource_id": model["resource_id"],
                    "grade_enum": model["grade"],
                    "size_enum": model["size"],
                    "attribute_enum": model["attribute"],
                    "move_type_enum": model["move_type"],
                    "class_enum": model["monster_class"],
                },
                "spot_ai": normal,
                "addressable_key": key,
                "monster_skills": skills,
            }
            if season not in resolved:
                base_entry.update(
                    {
                        "resolution_status": "missing_in_client_snapshot",
                        "behavior_asset": None,
                        "task_graph": None,
                        "skill_cast_sites": [],
                    }
                )
                entries.append(base_entry)
                continue

            catalog, resolution = resolved[season]
            documents = behavior_by_bundle[resolution.bundle_hash]
            document = documents.get(resolution.asset_internal_id)
            if document is None:
                raise BehaviorCatalogError(
                    f"season {season}: catalog internal ID absent from resolved bundle container"
                )
            if document.name != normal:
                raise BehaviorCatalogError(
                    f"season {season}: catalog internal ID points to {document.name!r}, "
                    f"expected {normal!r}"
                )
            task_graph, skill_sites, stats = _normalize_task_graph(
                document, skills_by_shot
            )
            for key_name, value in stats.items():
                total_stats[key_name] += value
            base_entry.update(
                {
                    "resolution_status": "resolved_exact",
                    "behavior_asset": {
                        "catalog_logical_name": catalog.identity.logical_name,
                        "asset_internal_id": resolution.asset_internal_id,
                        "serialized_path_id": str(document.path_id),
                        "asset_type": resolution.asset_class,
                        "bundle_content_hash": resolution.bundle_hash,
                        "serialized_json_size": document.raw_json_size,
                        "serialized_json_sha256": document.raw_json_sha256,
                        "behavior_name": document.name,
                    },
                    "task_graph": task_graph,
                    "skill_cast_sites": skill_sites,
                    "statistics": stats,
                }
            )
            entries.append(base_entry)

        unresolved_joins = []
        ambiguous_joins = []
        for entry in entries:
            for site in entry["skill_cast_sites"]:
                if not site["active_graph"] or not site["effective_enabled"]:
                    continue
                for join in site["monster_skill_join"]:
                    item = {
                        "season": entry["season"],
                        "node_id": site["node_id"],
                        "shot_key": join["shot_key"],
                    }
                    if join["status"] == "unresolved":
                        unresolved_joins.append(item)
                    elif join["status"] == "ambiguous":
                        item["candidate_skill_ids"] = join["candidate_skill_ids"]
                        ambiguous_joins.append(item)

        selected_asset_complete = len(resolved) == target_count
        active_shot_refs = total_stats.get("active_shot_reference_count", 0)
        exact_active_shot_refs = (
            active_shot_refs - len(unresolved_joins) - len(ambiguous_joins)
        )
        skill_join_complete = (
            exact_active_shot_refs == active_shot_refs
            and not unresolved_joins
            and not ambiguous_joins
        )
        selected_complete = selected_asset_complete and skill_join_complete
        behavior_complete = not targeted and selected_complete
        artifact: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "catalog_kind": CATALOG_KIND,
            "status": (
                "behavior_graph_complete"
                if behavior_complete
                else "behavior_graph_partial"
            ),
            "tiers": {
                "static_monster_skill": "complete",
                "behavior_asset_resolution": (
                    "complete" if selected_asset_complete else "partial"
                ),
                "active_shot_skill_join": (
                    "complete" if skill_join_complete else "blocked"
                ),
                "conditional_dispatch_timeline": "symbolic",
                "animation_or_timeline_event_frames": "pending",
            },
            "scope": {
                "mode": "solo_raid_challenge_only",
                "difficulty_type": 2,
                "expected_seasons": EXPECTED_CHALLENGES,
                **(
                    {
                        "selection_mode": "focused_diagnostic",
                        "selected_seasons": [str(season)],
                        "promotion_eligible": False,
                    }
                    if targeted
                    else {}
                ),
            },
            "coverage": {
                "challenge_rows": len(entries),
                "behavior_resolved": len(resolved),
                "behavior_missing": len(missing),
                "challenge_monster_skill_sets_exact": len(entries),
                "active_shot_references": active_shot_refs,
                "active_shot_skill_joins_exact": exact_active_shot_refs,
                "active_shot_skill_joins_unresolved": len(unresolved_joins),
                "active_shot_skill_joins_ambiguous": len(ambiguous_joins),
                "skill_shots_with_animation_or_timeline_marker": 0,
            },
            "missing": missing,
            "source": {
                "challenge_catalog": {
                    "logical_path": "repo/Database/raw/staticdata/assembled/solo_raid_challenge_catalog.json",
                    "sha256": _sha256_file(challenge_catalog_path),
                    "mapping_digest_sha256": challenge.get("mapping_digest_sha256"),
                },
                "addressables_catalogs": [
                    dataclasses.asdict(catalog.identity)
                    for catalog in sorted(
                        catalogs,
                        key=lambda item: (
                            item.identity.logical_name,
                            item.identity.sha256,
                        ),
                    )
                ],
                "monster_skill_table": skill_source,
                "monster_model_table": model_source,
                "bundles": [bundle_records[key] for key in sorted(bundle_records)],
            },
            "frame_model": {
                "fps": 60,
                "monster_skill_centiseconds": {
                    "conversion": "round_half_up(value * 60 / 100)",
                    "status": "integer_frames_exact",
                },
                "behavior_time_count": {
                    "conversion": "quantize(seconds * 60)",
                    "status": "symbolic_until_runtime_tick_semantics_verified",
                },
                "action_dispatch": "conditional_behavior_flow_symbolic",
                "projectile_or_damage_event": "unresolved_until_animation_or_timeline_marker",
            },
            "flow_semantics": {
                "Sequence": "serial; continue and accumulate only after child success",
                "Selector": "ordered alternatives after prior child failure",
                "RandomSelector": "nondeterministic alternative; no fixed seed injected",
                "Parallel": "children share a start; completion/preemption policy preserved",
                "Repeater": "count/forever/endOnFailure parameters preserved",
                "Inverter": "duration preserved; task status inverted",
                "conditional_abort": "abort type preserved as a preemption edge",
                "DetachedTasks": "editor/detached graph; excluded from execution",
                "Disabled": "disabled node and descendants excluded from execution",
            },
            "join_diagnostics": {
                "active_unresolved_shot_joins": unresolved_joins,
                "active_ambiguous_shot_joins": ambiguous_joins,
            },
            "statistics": dict(sorted(total_stats.items())),
            "entries": entries,
            "validation": {
                "status": (
                    "behavior_graph_complete"
                    if behavior_complete
                    else "partial"
                    if targeted
                    else "behavior_graph_blocked"
                ),
                "checks": [
                    {
                        "name": (
                            "targeted_challenge_scope"
                            if targeted
                            else "challenge_catalog_scope"
                        ),
                        "expected": target_count,
                        "actual": len(entries),
                        "status": "passed" if len(entries) == target_count else "failed",
                    },
                    {
                        "name": "behavior_asset_exact_resolution",
                        "expected": target_count,
                        "actual": len(resolved),
                        "status": "passed" if selected_asset_complete else "blocked",
                    },
                    {
                        "name": "challenge_monster_skill_sets_exact",
                        "expected": target_count,
                        "actual": len(entries),
                        "status": "passed",
                    },
                    {
                        "name": "active_shot_join_cardinality",
                        "expected": active_shot_refs,
                        "actual_exact": exact_active_shot_refs,
                        "unresolved": len(unresolved_joins),
                        "ambiguous": len(ambiguous_joins),
                        "status": (
                            "passed"
                            if not unresolved_joins and not ambiguous_joins
                            else "requires_runtime_choice_or_additional_mapping"
                        ),
                    },
                    {
                        "name": "animation_timeline_event_frames",
                        "expected": "all active skill sites",
                        "actual": 0,
                        "status": "pending",
                    },
                ],
            },
        }
        digest_payload = dict(artifact)
        artifact["catalog_digest_sha256"] = _sha256(_canonical_bytes(digest_payload))
        return artifact
    except (NKDBError, UnityFSError, SerializedTimelineError) as exc:
        raise BehaviorCatalogError(str(exc)) from exc
    finally:
        for catalog in catalogs:
            catalog.close()


def write_catalog(
    value: dict[str, Any],
    output: Path,
    *,
    static_root: Path = DEFAULT_STATIC_ROOT,
) -> Path:
    allowed = static_root.resolve() / "assembled"
    resolved = output.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise BehaviorCatalogError("output must stay below static-root/assembled") from exc
    resolved.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        prefix=resolved.name + ".",
        suffix=".tmp",
        dir=resolved.parent,
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, resolved)
    finally:
        if temporary.exists():
            temporary.unlink()
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract Challenge spot_ai behavior graphs and symbolic frame flow"
    )
    parser.add_argument("--static-root", type=Path, default=DEFAULT_STATIC_ROOT)
    parser.add_argument("--challenge-catalog", type=Path, default=None)
    parser.add_argument("--staticdata-zip", type=Path, default=None)
    parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    parser.add_argument(
        "--catalog",
        type=Path,
        action="append",
        default=None,
        help="explicit NKDB catalog path; repeat for core/dp/fd",
    )
    parser.add_argument("--naps-root", type=Path, default=DEFAULT_NAPS_ROOT)
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="extract one Challenge season as a non-promotable partial artifact",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--partial-output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.season is not None and (
        args.output is not None or args.partial_output is not None
    ):
        parser.error("--season uses an isolated diagnostic output; do not pass output paths")
    challenge_catalog = args.challenge_catalog or (
        args.static_root / "assembled" / "solo_raid_challenge_catalog.json"
    )
    staticdata_zip = args.staticdata_zip or (args.static_root / "StaticData.zip")
    output = args.output or (
        args.static_root / "assembled" / "solo_raid_challenge_behavior.json"
    )
    partial_name = (
        f"solo_raid_challenge_behavior.season_{args.season}.partial.json"
        if args.season is not None
        else "solo_raid_challenge_behavior.partial.json"
    )
    partial_output = args.partial_output or (
        args.static_root / "assembled" / partial_name
    )
    try:
        artifact = build_behavior_catalog(
            challenge_catalog_path=challenge_catalog,
            staticdata_zip=staticdata_zip,
            catalog_paths=args.catalog,
            catalog_dir=args.catalog_dir,
            naps_root=args.naps_root,
            season=args.season,
        )
        complete = artifact["status"] == "behavior_graph_complete"
        destination = output if complete else partial_output
        destination = write_catalog(
            artifact, destination, static_root=args.static_root
        )
        if complete:
            allowed = args.static_root.resolve() / "assembled"
            stale_partial = partial_output.resolve()
            try:
                stale_partial.relative_to(allowed)
            except ValueError as exc:
                raise BehaviorCatalogError(
                    "partial-output must stay below static-root/assembled"
                ) from exc
            if stale_partial.is_file():
                stale_partial.unlink()
    except BehaviorCatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"wrote {destination} "
        f"({artifact['coverage']['behavior_resolved']}/"
        f"{artifact['coverage']['challenge_rows']} behavior, "
        f"status={artifact['status']})"
    )
    if not complete:
        reason = (
            "focused behavior diagnostic is non-promotable by design"
            if args.season is not None
            else "client Addressables snapshot is incomplete"
        )
        print(f"behavior tier not promoted: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
