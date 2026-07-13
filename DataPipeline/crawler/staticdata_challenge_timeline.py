#!/usr/bin/env python3
"""Extract Challenge SpotMonster timeline routes and relative event frames.

The authoritative animation-number route is the serialized
``MonsterTimeLineData.aniNumberLists`` relation.  Timeline asset names are
presentation hints only and are never used as a Shot_N foreign key.

``--season N`` accepts only a matching focused behavior diagnostic and writes
an isolated, non-promotable ``season_N.partial.json`` artifact.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from .addressables_nkdb import NKDBCatalog, NKDBError, open_nkdb
    from .staticdata_challenge_behavior import (
        DEFAULT_CATALOG_DIR,
        DEFAULT_NAPS_ROOT,
        DEFAULT_STATIC_ROOT,
        _find_catalog_files,
    )
    from .unity_serialized_timeline import (
        SerializedTimelineError,
        extract_timeline_manifest,
    )
    from .unityfs_minimal import UnityFSError
except ImportError:
    from addressables_nkdb import NKDBCatalog, NKDBError, open_nkdb
    from staticdata_challenge_behavior import (
        DEFAULT_CATALOG_DIR,
        DEFAULT_NAPS_ROOT,
        DEFAULT_STATIC_ROOT,
        _find_catalog_files,
    )
    from unity_serialized_timeline import (
        SerializedTimelineError,
        extract_timeline_manifest,
    )
    from unityfs_minimal import UnityFSError

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SCHEMA_VERSION = 1
CATALOG_KIND = "solo_raid_challenge_timeline"
EXPECTED_CHALLENGES = 39
HASH_RE = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_BEHAVIOR_PARTIAL = (
    DEFAULT_STATIC_ROOT / "assembled" / "solo_raid_challenge_behavior.partial.json"
)
DEFAULT_BEHAVIOR_FULL = (
    DEFAULT_STATIC_ROOT / "assembled" / "solo_raid_challenge_behavior.json"
)
DEFAULT_OUTPUT = (
    DEFAULT_STATIC_ROOT / "assembled" / "solo_raid_challenge_timeline.json"
)
DEFAULT_PARTIAL_OUTPUT = (
    DEFAULT_STATIC_ROOT / "assembled" / "solo_raid_challenge_timeline.partial.json"
)


class ChallengeTimelineError(RuntimeError):
    """A timeline source is missing, ambiguous, stale, or schema-drifted."""


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


def _load_behavior(
    path: Path, *, focus_season: int | None = None
) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {token}")
            ),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ChallengeTimelineError(f"cannot read behavior artifact {path}") from exc
    if not isinstance(value, dict):
        raise ChallengeTimelineError("behavior artifact root is not an object")
    if value.get("catalog_kind") != "solo_raid_challenge_behavior":
        raise ChallengeTimelineError("unexpected behavior artifact kind")
    if value.get("status") not in {
        "behavior_graph_complete",
        "behavior_graph_partial",
    }:
        raise ChallengeTimelineError("behavior artifact has unknown status")
    stored = value.get("catalog_digest_sha256")
    payload = dict(value)
    payload.pop("catalog_digest_sha256", None)
    if not isinstance(stored, str) or stored != _sha256(_canonical_bytes(payload)):
        raise ChallengeTimelineError("behavior artifact digest mismatch")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise ChallengeTimelineError("behavior artifact entries are not an array")
    scope = value.get("scope")
    if not isinstance(scope, dict) or scope.get("expected_seasons") != EXPECTED_CHALLENGES:
        raise ChallengeTimelineError("behavior artifact has invalid Challenge scope")
    if focus_season is None:
        if len(entries) != EXPECTED_CHALLENGES:
            raise ChallengeTimelineError("behavior artifact is not exact 39-row scope")
        if scope.get("selection_mode") == "focused_diagnostic":
            raise ChallengeTimelineError(
                "focused behavior artifact requires an explicit --season"
            )
    else:
        if type(focus_season) is not int or not 1 <= focus_season <= EXPECTED_CHALLENGES:
            raise ChallengeTimelineError(
                f"season must be an integer in 1..{EXPECTED_CHALLENGES}"
            )
        expected = [str(focus_season)]
        entry = entries[0] if len(entries) == 1 else {}
        if (
            scope.get("selection_mode") != "focused_diagnostic"
            or scope.get("selected_seasons") != expected
            or scope.get("promotion_eligible") is not False
            or value.get("status") != "behavior_graph_partial"
            or len(entries) != 1
            or str(entry.get("season")) != str(focus_season)
            or entry.get("resolution_status") != "resolved_exact"
            or not isinstance(entry.get("task_graph"), dict)
            or not isinstance(entry.get("monster_skills"), list)
            or not entry.get("monster_skills")
            or not isinstance(entry.get("skill_cast_sites"), list)
            or not entry.get("skill_cast_sites")
        ):
            raise ChallengeTimelineError(
                f"behavior artifact is not an isolated season {focus_season} diagnostic"
            )
    return value


@dataclasses.dataclass(frozen=True)
class SpotBundleResolution:
    catalog_name: str
    addressable_key: str
    asset_internal_id: str
    bundle_key: str
    bundle_hash: str
    bundle_size: int


_SPOT_ASSET_SQL = """
SELECT e.quality_texture, e.quality_mesh, e.dependency_key_rowid,
       i.internal_id, p.provider_id, t.class_name
FROM keys AS k
JOIN key_entries AS ke ON ke.key_rowid=k.rowid
JOIN entries AS e ON e.rowid=ke.entry_rowid
LEFT JOIN internal_ids AS i ON i.rowid=e.internal_id_rowid
LEFT JOIN provider_ids AS p ON p.rowid=e.provider_id_rowid
LEFT JOIN types AS t ON t.rowid=e.type_rowid
WHERE k.key=?
"""

_DEPENDENCY_SET_SQL = """
SELECT pk.key, d.hash, d.bundle_size, p.provider_id, t.class_name
FROM key_entries AS ke
JOIN entries AS e ON e.rowid=ke.entry_rowid
JOIN keys AS pk ON pk.rowid=e.primary_key_rowid
LEFT JOIN entry_data AS d ON d.rowid=e.data_rowid
LEFT JOIN provider_ids AS p ON p.rowid=e.provider_id_rowid
LEFT JOIN types AS t ON t.rowid=e.type_rowid
WHERE ke.key_rowid=?
"""


def _resolve_spot_bundle(
    catalogs: list[NKDBCatalog],
    addressable_key: str,
    prefab: str,
) -> SpotBundleResolution | None:
    variants: list[tuple[NKDBCatalog, tuple[Any, ...]]] = []
    for catalog in catalogs:
        for row in catalog.connection.execute(_SPOT_ASSET_SQL, (addressable_key,)):
            if row[1] == 2:  # current catalog quality_mesh=2 is the SD variant
                variants.append((catalog, row))
    if not variants:
        return None
    if len(variants) != 1:
        raise ChallengeTimelineError(
            f"{addressable_key}: expected one SD quality entry, found {len(variants)}"
        )
    catalog, row = variants[0]
    _quality_texture, _quality_mesh, dependency_rowid, internal_id, provider, class_name = row
    if provider != "UnityEngine.ResourceManagement.ResourceProviders.BundledAssetProvider":
        raise ChallengeTimelineError(f"{addressable_key}: unexpected asset provider")
    if class_name != "UnityEngine.GameObject":
        raise ChallengeTimelineError(f"{addressable_key}: expected GameObject")
    if not isinstance(internal_id, str) or not internal_id:
        raise ChallengeTimelineError(f"{addressable_key}: missing internal ID")
    if not isinstance(dependency_rowid, int) or dependency_rowid <= 0:
        raise ChallengeTimelineError(f"{addressable_key}: invalid dependency set")

    prefix = f"spotmonster(sd)_assets_spotmonster/{prefab.lower()}_"
    matches: list[tuple[Any, ...]] = []
    for item in catalog.connection.execute(_DEPENDENCY_SET_SQL, (dependency_rowid,)):
        key, content_hash, size, bundle_provider, bundle_class = item
        if (
            isinstance(key, str)
            and key.lower().startswith(prefix)
            and key.lower().endswith(".bundle")
        ):
            matches.append(item)
    if len(matches) != 1:
        raise ChallengeTimelineError(
            f"{addressable_key}: expected one main SD bundle, found {len(matches)}"
        )
    bundle_key, content_hash, size, bundle_provider, bundle_class = matches[0]
    if bundle_provider != "UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider":
        raise ChallengeTimelineError(f"{addressable_key}: unexpected bundle provider")
    if bundle_class != "UnityEngine.ResourceManagement.ResourceProviders.IAssetBundleResource":
        raise ChallengeTimelineError(f"{addressable_key}: unexpected bundle type")
    if not isinstance(content_hash, str) or not HASH_RE.fullmatch(content_hash):
        raise ChallengeTimelineError(f"{addressable_key}: invalid bundle hash")
    if not isinstance(size, int) or size <= 0:
        raise ChallengeTimelineError(f"{addressable_key}: invalid bundle size")
    expected_suffix = f"_{content_hash}.bundle"
    if not bundle_key.lower().endswith(expected_suffix):
        raise ChallengeTimelineError(f"{addressable_key}: bundle key/hash mismatch")
    return SpotBundleResolution(
        catalog_name=catalog.identity.logical_name,
        addressable_key=addressable_key,
        asset_internal_id=internal_id,
        bundle_key=bundle_key,
        bundle_hash=content_hash,
        bundle_size=size,
    )


def _cached_path(naps_root: Path, resolution: SpotBundleResolution) -> Path:
    path = naps_root / resolution.bundle_hash[:2] / resolution.bundle_hash
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise ChallengeTimelineError(
            f"{resolution.bundle_hash}: SpotMonster bundle missing from NAPS"
        ) from exc
    if size != resolution.bundle_size:
        raise ChallengeTimelineError(
            f"{resolution.bundle_hash}: bundle size mismatch"
        )
    with path.open("rb") as stream:
        if stream.read(8) != b"UnityFS\0":
            raise ChallengeTimelineError(
                f"{resolution.bundle_hash}: bundle is not plain UnityFS"
            )
    return path


def _compact_frame(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "missing", "frame": None}
    integral = value.get("integral") is True
    return {
        "status": "exact_integer" if integral else "nonintegral_symbolic",
        "frame": value.get("value") if integral else None,
        "raw_frame": value.get("raw"),
    }


def _compact_marker(marker: dict[str, Any]) -> dict[str, Any]:
    return {
        "path_id": marker.get("path_id"),
        "time_seconds": marker.get("time_seconds"),
        "frame_60fps": _compact_frame(marker.get("canonical_60_frame")),
        "target_enum": marker.get("target"),
        "hit_effect_type_enum": marker.get("hit_effect_type"),
    }


def _compact_clip(clip: dict[str, Any]) -> dict[str, Any]:
    detail = clip.get("asset_detail")
    compact_detail = None
    if isinstance(detail, dict):
        compact_detail = {"kind": detail.get("kind")}
        if detail.get("kind") == "AnimationPlayableAsset":
            compact_detail["animation_clip"] = (detail.get("clip") or {}).get("name")
            compact_detail["animation_clip_path_id"] = (detail.get("clip") or {}).get(
                "path_id"
            )
        elif detail.get("kind") == "ControlPlayableAsset":
            compact_detail["exposed_name"] = detail.get("exposed_name")
    return {
        "display_name": clip.get("display_name"),
        "start_frame_60fps": _compact_frame(clip.get("start_canonical_60_frame")),
        "duration_frames_60fps": _compact_frame(
            clip.get("duration_canonical_60_frames")
        ),
        "clip_in_seconds": clip.get("clip_in_seconds"),
        "time_scale": clip.get("time_scale"),
        "asset": compact_detail,
    }


def _compact_timeline(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    tracks = []
    for track in row.get("tracks") or []:
        clips = [_compact_clip(item) for item in track.get("clips") or []]
        nested = track.get("nested_timeline_by_exact_name")
        if clips or nested or track.get("marker_refs"):
            obj = track.get("object") or {}
            tracks.append(
                {
                    "path_id": obj.get("path_id"),
                    "name": obj.get("name"),
                    "script_class": obj.get("script_class"),
                    "nested_timeline_path_id": nested,
                    "clips": clips,
                }
            )
    return {
        "path_id": row.get("path_id"),
        "name": row.get("name"),
        "framerate": row.get("framerate"),
        "duration_seconds": row.get("fixed_duration_seconds"),
        "duration_mode": row.get("duration_mode"),
        "duration_frames_60fps": _compact_frame(
            row.get("fixed_duration_canonical_60_frames")
        ),
        "attack_markers": [
            _compact_marker(item) for item in row.get("attack_markers") or []
        ],
        "tracks": tracks,
    }


def _compact_routes(manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
    timelines = {item["path_id"]: item for item in manifest.get("all_timelines") or []}
    routes: list[dict[str, Any]] = []
    by_ani: dict[int, list[str]] = defaultdict(list)
    for route in manifest.get("ani_number_route_groups") or []:
        route_id = str(route.get("route_id"))
        ani_numbers = route.get("ani_numbers")
        if not isinstance(ani_numbers, list) or not ani_numbers:
            raise ChallengeTimelineError(f"route {route_id}: empty aniNumberLists")
        normalized_ani = []
        for value in ani_numbers:
            if type(value) is not int or not 1 <= value <= 99:
                raise ChallengeTimelineError(f"route {route_id}: invalid ani number")
            normalized_ani.append(value)
            by_ani[value].append(route_id)
        top = route.get("top_timeline") or {}
        model = route.get("model_timeline") or {}
        routes.append(
            {
                "route_id": route_id,
                "ani_numbers": normalized_ani,
                "shot_keys": [f"Shot_{value:02d}" for value in normalized_ani],
                "disabled": route.get("disabled"),
                "scene_type_enum": route.get("scene_type"),
                "trigger_enum": route.get("trigger"),
                "owner_game_object": route.get("owner_game_object"),
                "top_timeline": _compact_timeline(timelines.get(top.get("path_id"))),
                "model_timeline": _compact_timeline(
                    timelines.get(model.get("path_id"))
                ),
            }
        )
    routes.sort(key=lambda item: item["route_id"])
    return routes, dict(sorted(by_ani.items()))


def _active_shot_counts(entry: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for site in entry.get("skill_cast_sites") or []:
        if site.get("active_graph") is True and site.get("effective_enabled") is True:
            for shot in site.get("shot_keys") or []:
                result[shot] += 1
    return dict(result)


def _skill_route_rows(
    entry: dict[str, Any],
    routes: list[dict[str, Any]],
    by_ani: dict[int, list[str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    routes_by_id = {item["route_id"]: item for item in routes}
    active_counts = _active_shot_counts(entry)
    rows = []
    stats = defaultdict(int)
    for skill in entry.get("monster_skills") or []:
        animation = skill.get("animation") or {}
        ani = animation.get("enum_value")
        shot = animation.get("shot_key")
        route_ids = by_ani.get(ani, []) if type(ani) is int else []
        candidates = [routes_by_id[item] for item in route_ids]
        markers = [
            marker
            for route in candidates
            if route.get("disabled") is not True
            for marker in (route.get("top_timeline") or {}).get("attack_markers") or []
        ]
        integral_markers = [
            marker
            for marker in markers
            if marker.get("frame_60fps", {}).get("status") == "exact_integer"
        ]
        if len(candidates) > 1:
            route_status = "ambiguous_multiple_route_groups"
        elif len(candidates) == 1:
            route_status = "exact_monster_timeline_route"
        else:
            route_status = "no_monster_timeline_route"
        if len(candidates) == 1 and markers and len(markers) == len(integral_markers):
            event_status = "timeline_attack_marker_exact"
        elif len(candidates) == 1:
            event_status = "timeline_route_without_exact_attack_marker"
        elif len(candidates) > 1:
            event_status = "ambiguous_timeline_route"
        else:
            event_status = "animation_or_runtime_callback_unresolved"
        active_sites = active_counts.get(shot, 0)
        timeline_duration = None
        timeline_duration_seconds = None
        timeline_asset = None
        if len(candidates) == 1:
            top_timeline = candidates[0].get("top_timeline") or {}
            duration = top_timeline.get("duration_frames_60fps")
            if isinstance(duration, dict):
                timeline_duration = duration
            timeline_duration_seconds = top_timeline.get("duration_seconds")
            timeline_asset = {
                "route_id": candidates[0].get("route_id"),
                "path_id": top_timeline.get("path_id"),
                "name": top_timeline.get("name"),
                "framerate": top_timeline.get("framerate"),
                "duration_mode": top_timeline.get("duration_mode"),
            }
        stats[f"route:{route_status}"] += 1
        stats[f"event:{event_status}"] += 1
        if active_sites:
            stats["active_skill_rows"] += 1
            if event_status == "timeline_attack_marker_exact":
                stats["active_skill_rows_with_exact_marker"] += 1
        rows.append(
            {
                "skill_id": skill.get("skill_id"),
                "shot_key": shot,
                "active_behavior_site_count": active_sites,
                "monster_skill_timing": skill.get("timing"),
                "route_status": route_status,
                "route_ids": route_ids,
                "event_frame_status": event_status,
                "attack_markers_relative_to_timeline_start": integral_markers,
                "timeline_duration_frames_60fps": timeline_duration,
                "timeline_duration_seconds": timeline_duration_seconds,
                "timeline_asset": timeline_asset,
            }
        )
    return rows, dict(stats)


def build_timeline_catalog(
    *,
    behavior_path: Path,
    catalog_paths: list[Path] | None,
    catalog_dir: Path,
    naps_root: Path,
    season: int | None = None,
) -> dict[str, Any]:
    behavior = _load_behavior(behavior_path, focus_season=season)
    focused = season is not None
    target_count = len(behavior["entries"])
    if catalog_paths is None:
        catalog_paths = _find_catalog_files(catalog_dir)
    catalogs: list[NKDBCatalog] = []
    try:
        for path in sorted(catalog_paths, key=lambda item: item.name):
            catalogs.append(open_nkdb(path))
        actual_catalogs = [
            dataclasses.asdict(item.identity)
            for item in sorted(catalogs, key=lambda item: item.identity.logical_name)
        ]
        expected_catalogs = sorted(
            behavior.get("source", {}).get("addressables_catalogs") or [],
            key=lambda item: item.get("logical_name", ""),
        )
        if actual_catalogs != expected_catalogs:
            raise ChallengeTimelineError(
                "current Addressables catalogs do not match behavior artifact sources"
            )

        entries = []
        missing = []
        totals = defaultdict(int)
        bundle_sources = []
        for index, source_entry in enumerate(behavior["entries"], 1):
            entry_season = source_entry.get("season")
            expected_season = season if focused else index
            if str(entry_season) != str(expected_season):
                raise ChallengeTimelineError("behavior seasons do not match selected scope")
            model = source_entry.get("monster_model") or {}
            prefab = model.get("mon_prefab")
            addressable_key = model.get("spotmonster_addressable_key")
            if not isinstance(prefab, str) or addressable_key != f"SpotMonster/{prefab}":
                raise ChallengeTimelineError(f"season {entry_season}: invalid MonsterModel FK")
            resolution = _resolve_spot_bundle(catalogs, addressable_key, prefab)
            base = {
                "season": str(entry_season),
                "monster_id": source_entry.get("monster_id"),
                "mon_prefab": prefab,
                "spotmonster_addressable_key": addressable_key,
            }
            if resolution is None:
                missing.append(
                    {
                        "season": str(entry_season),
                        "addressable_key": addressable_key,
                        "reason": "missing_in_client_snapshot",
                    }
                )
                base.update(
                    {
                        "resolution_status": "missing_in_client_snapshot",
                        "routes": [],
                        "skill_timeline_join": [],
                    }
                )
                entries.append(base)
                continue
            path = _cached_path(naps_root, resolution)
            print(
                f"timeline {entry_season}/{EXPECTED_CHALLENGES}: {prefab} "
                f"({resolution.bundle_hash})",
                flush=True,
            )
            manifest = extract_timeline_manifest(path)
            if manifest.get("source", {}).get("cache_key") != resolution.bundle_hash:
                raise ChallengeTimelineError(
                    f"season {entry_season}: parser source hash mismatch"
                )
            routes, by_ani = _compact_routes(manifest)
            skill_rows, stats = _skill_route_rows(source_entry, routes, by_ani)
            for key, value in stats.items():
                totals[key] += value
            totals["resolved_spotmonster_bundles"] += 1
            totals["route_groups"] += len(routes)
            totals["routed_ani_numbers"] += sum(len(v) for v in by_ani.values())
            totals["attack_markers"] += sum(
                len((route.get("top_timeline") or {}).get("attack_markers") or [])
                for route in routes
            )
            source = dict(manifest["source"])
            source.update(
                {
                    "catalog_logical_name": resolution.catalog_name,
                    "catalog_bundle_size": resolution.bundle_size,
                    "catalog_bundle_key": resolution.bundle_key,
                    "spotmonster_asset_internal_id": resolution.asset_internal_id,
                }
            )
            bundle_sources.append(source)
            base.update(
                {
                    "resolution_status": "resolved_exact",
                    "bundle_content_hash": resolution.bundle_hash,
                    "parser_counts": manifest.get("counts"),
                    "multi_route_ani_numbers": manifest.get(
                        "multi_route_ani_numbers", []
                    ),
                    "monster_anim_controllers": manifest.get(
                        "monster_anim_controllers", []
                    ),
                    "routes": routes,
                    "skill_timeline_join": skill_rows,
                    "statistics": stats,
                }
            )
            entries.append(base)

        active_total = totals.get("active_skill_rows", 0)
        active_exact = totals.get("active_skill_rows_with_exact_marker", 0)
        frame_complete = (
            not focused
            and len(entries) == EXPECTED_CHALLENGES
            and len(missing) == 0
            and behavior.get("status") == "behavior_graph_complete"
            and active_total > 0
            and active_exact == active_total
        )
        artifact: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "catalog_kind": CATALOG_KIND,
            "status": (
                "event_frame_complete" if frame_complete else "event_frame_partial"
            ),
            "scope": {
                "mode": "solo_raid_challenge_only",
                "expected_seasons": EXPECTED_CHALLENGES,
                "fps": 60,
                **(
                    {
                        "selection_mode": "focused_diagnostic",
                        "selected_seasons": [str(season)],
                        "promotion_eligible": False,
                    }
                    if focused
                    else {}
                ),
            },
            "coverage": {
                "challenge_rows": len(entries),
                "spotmonster_bundles_resolved": totals.get(
                    "resolved_spotmonster_bundles", 0
                ),
                "spotmonster_bundles_missing": len(missing),
                "route_groups": totals.get("route_groups", 0),
                "routed_ani_numbers": totals.get("routed_ani_numbers", 0),
                "timeline_attack_markers": totals.get("attack_markers", 0),
                "active_skill_rows": active_total,
                "active_skill_rows_with_exact_timeline_marker": active_exact,
            },
            "semantics": {
                "authoritative_shot_fk": (
                    "MonsterTimeLineData.aniNumberLists -> owner GameObject -> "
                    "PlayableDirector.m_PlayableAsset"
                ),
                "timeline_name_shot_number": "hint_only_not_authoritative",
                "marker_origin": "relative_to_timeline_action_start",
                "absolute_battle_frame": (
                    "behavior_dispatch_frame + relative marker frame; symbolic when "
                    "conditions, branches, repeats, movement, or preemption are unresolved"
                ),
                "non_timeline_attack_event": "animation_or_runtime_callback_unresolved",
            },
            "missing": missing,
            "source": {
                "behavior_artifact": {
                    "logical_path": (
                        "repo/Database/raw/staticdata/assembled/"
                        + behavior_path.name
                    ),
                    "sha256": _sha256_file(behavior_path),
                    "catalog_digest_sha256": behavior.get(
                        "catalog_digest_sha256"
                    ),
                },
                "addressables_catalogs": actual_catalogs,
                "spotmonster_bundles": sorted(
                    bundle_sources, key=lambda item: item["cache_key"]
                ),
            },
            "statistics": dict(sorted(totals.items())),
            "entries": entries,
            "validation": {
                "status": "frame_complete" if frame_complete else "partial",
                "checks": [
                    {
                        "name": "spotmonster_sd_bundle_exact_resolution",
                        "expected": target_count,
                        "actual": totals.get("resolved_spotmonster_bundles", 0),
                        "status": "passed" if not missing else "blocked",
                    },
                    {
                        "name": "active_skill_event_frame_coverage",
                        "expected": active_total,
                        "actual": active_exact,
                        "status": "passed" if frame_complete else "pending",
                    },
                    *(
                        [
                            {
                                "name": "canonical_scope_promotion",
                                "expected": EXPECTED_CHALLENGES,
                                "actual": target_count,
                                "status": "blocked",
                            }
                        ]
                        if focused
                        else []
                    ),
                ],
            },
        }
        artifact["catalog_digest_sha256"] = _sha256(_canonical_bytes(artifact))
        return artifact
    except (NKDBError, UnityFSError, SerializedTimelineError) as exc:
        raise ChallengeTimelineError(str(exc)) from exc
    finally:
        for catalog in catalogs:
            catalog.close()


def write_catalog(
    value: dict[str, Any], output: Path, *, static_root: Path
) -> Path:
    allowed = static_root.resolve() / "assembled"
    resolved = output.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ChallengeTimelineError(
            "output must stay below static-root/assembled"
        ) from exc
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-root", type=Path, default=DEFAULT_STATIC_ROOT)
    parser.add_argument("--behavior", type=Path, default=None)
    parser.add_argument("--catalog-dir", type=Path, default=DEFAULT_CATALOG_DIR)
    parser.add_argument("--catalog", type=Path, action="append", default=None)
    parser.add_argument("--naps-root", type=Path, default=DEFAULT_NAPS_ROOT)
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="extract one season from an isolated behavior diagnostic",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--partial-output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.season is not None and (
        args.output is not None or args.partial_output is not None
    ):
        parser.error("--season uses an isolated diagnostic output; do not pass output paths")
    behavior_path = args.behavior
    if behavior_path is None:
        if args.season is not None:
            behavior_path = (
                args.static_root
                / "assembled"
                / f"solo_raid_challenge_behavior.season_{args.season}.partial.json"
            )
        else:
            full = args.static_root / "assembled" / DEFAULT_BEHAVIOR_FULL.name
            partial = args.static_root / "assembled" / DEFAULT_BEHAVIOR_PARTIAL.name
            behavior_path = full if full.is_file() else partial
    output = args.output or (
        args.static_root / "assembled" / DEFAULT_OUTPUT.name
    )
    partial_name = (
        f"solo_raid_challenge_timeline.season_{args.season}.partial.json"
        if args.season is not None
        else DEFAULT_PARTIAL_OUTPUT.name
    )
    partial_output = args.partial_output or (
        args.static_root / "assembled" / partial_name
    )
    try:
        artifact = build_timeline_catalog(
            behavior_path=behavior_path,
            catalog_paths=args.catalog,
            catalog_dir=args.catalog_dir,
            naps_root=args.naps_root,
            season=args.season,
        )
        complete = artifact["status"] == "event_frame_complete"
        destination = write_catalog(
            artifact,
            output if complete else partial_output,
            static_root=args.static_root,
        )
        if complete:
            allowed = args.static_root.resolve() / "assembled"
            stale_partial = partial_output.resolve()
            try:
                stale_partial.relative_to(allowed)
            except ValueError as exc:
                raise ChallengeTimelineError(
                    "partial-output must stay below static-root/assembled"
                ) from exc
            if stale_partial.is_file():
                stale_partial.unlink()
    except ChallengeTimelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"wrote {destination} "
        f"({artifact['coverage']['spotmonster_bundles_resolved']}/"
        f"{artifact['coverage']['challenge_rows']} bundles, "
        f"status={artifact['status']})"
    )
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
