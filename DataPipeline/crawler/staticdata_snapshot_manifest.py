#!/usr/bin/env python3
"""Solo Raid Challenge 데이터 원천의 안전한 로컬 snapshot manifest 생성기.

목표
----
* attend 범위를 ``SoloRaidPreset.Difficulty_type == 2`` (challenge)로 고정한다.
* StaticData, 공개 roledata, C:\\NIKKE Addressables 원천과 현재 파생 산출물을 해시로 묶는다.
* challenge catalog가 있으면 WaveData -> monster/spot_ai exact join을 검증해 반영한다.
  catalog가 없을 때만 명시적인 source-only coverage gap으로 남긴다.
* 복호키, host/URL, .nds 내용, 절대경로, 개인 계정 데이터는 manifest에 넣지 않는다.

출력은 게임데이터와 같은 gitignore 경계 아래에만 쓴다::

    Database/raw/staticdata/snapshots/solo_raid_challenge/
      <data_version>/manifest.json
      latest.json

사용::

    python DataPipeline/crawler/staticdata_snapshot_manifest.py

표준 라이브러리만 사용한다. 라이브 fetch나 bundle 복호는 수행하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .memorypack_decode import SCHEMAS as _MEMORYPACK_SCHEMAS
    from .memorypack_decode import decode_table as _decode_memorypack_table
    from .staticdata_challenge_catalog import CatalogError as _ChallengeCatalogError
    from .staticdata_challenge_catalog import EXPECTED_CHALLENGE_ROWS
    from .staticdata_challenge_catalog import EXPECTED_SCOPE_DIGEST
    from .staticdata_challenge_catalog import build_catalog as _rebuild_challenge_catalog
except ImportError:  # 직접 스크립트 실행 시 crawler/가 sys.path에 잡힌다.
    from memorypack_decode import SCHEMAS as _MEMORYPACK_SCHEMAS
    from memorypack_decode import decode_table as _decode_memorypack_table
    from staticdata_challenge_catalog import CatalogError as _ChallengeCatalogError
    from staticdata_challenge_catalog import EXPECTED_CHALLENGE_ROWS
    from staticdata_challenge_catalog import EXPECTED_SCOPE_DIGEST
    from staticdata_challenge_catalog import build_catalog as _rebuild_challenge_catalog

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 이모지 대응
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SCHEMA_VERSION = 1
SNAPSHOT_KIND = "solo_raid_challenge"
DIFFICULTY_TYPE = 2

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_NIKKE_ROOT = Path(r"C:\NIKKE")
DEFAULT_STATIC_ROOT = REPO_ROOT / "Database" / "raw" / "staticdata"
DEFAULT_OUTPUT_ROOT = DEFAULT_STATIC_ROOT / "snapshots" / SNAPSHOT_KIND

RELEVANT_STATIC_ENTRIES = (
    "SoloRaidManagerTable.mpk",
    "SoloRaidPresetTable.mpk",
    "WaveData.GroupDict.csv",
    "WaveDataTable.wave_Intercept_001.mpk",
    "MonsterTable.mpk",
    "MonsterModelTable.mpk",
    "MonsterSkillTable.mpk",
    "MonsterPartsTable.mpk",
    "MonsterStatEnhanceTable.mpk",
    "MonsterStageLvChangeTable.mpk",
    "FunctionTable.mpk",
    "StateEffectTable.mpk",
)

SAFE_SD_ENTRIES = (
    "CampaignChapterTable.json",
    "CampaignStageTable.json",
    "CharacterReactionTable.json",
    "ConfigBattleTable.json",
    "ConfigGameTable.json",
)

SAFE_INITIALIZERS = {
    "HostSettingsInitialization": "NK.Addressable.HostSettingsInitialization",
    "CacheInitialization": "UnityEngine.AddressableAssets.Initialization.CacheInitialization",
}

SOLO_RAID_SCOPE_SCHEMAS = {
    name: _MEMORYPACK_SCHEMAS[name]
    for name in ("SoloRaidManagerData", "SoloRaidPresetData")
}

PIPELINE_FILES = (
    "DataPipeline/run_pipeline.py",
    "DataPipeline/crawler/staticdata_snapshot_manifest.py",
    "DataPipeline/crawler/staticdata_challenge_catalog.py",
    "DataPipeline/crawler/addressables_nkdb.py",
    "DataPipeline/crawler/unityfs_minimal.py",
    "DataPipeline/crawler/unity_serialized_timeline.py",
    "DataPipeline/crawler/staticdata_challenge_behavior.py",
    "DataPipeline/crawler/staticdata_challenge_timeline.py",
    "DataPipeline/crawler/memorypack_decode.py",
    "DataPipeline/crawler/staticdata_raid_decode.py",
    "DataPipeline/crawler/staticdata_solo_raid.py",
    "DataPipeline/crawler/staticdata_skill_chains.py",
    "DataPipeline/schema/solo_raid_challenge_snapshot.schema.json",
)

FORBIDDEN_OUTPUT_KEYS = {
    "keys",
    "m_data",
    "relativepath",
    "url",
    "salt1",
    "salt2",
    "password",
    "cookie",
    "authorization",
    "uid",
    "email",
}


class ManifestError(RuntimeError):
    """입력 누락 또는 manifest 불변식 위반."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _logical_path(path: Path, root: Path, prefix: str) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ManifestError(f"allowlist root 밖 경로: {path}") from exc
    return f"{prefix}/{rel.as_posix()}" if rel.parts else prefix


def _file_fingerprint(
    path: Path,
    *,
    logical_path: str,
    hash_content: bool = True,
    magic_bytes: int = 0,
    required: bool = True,
) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise ManifestError(f"필수 파일 없음: {logical_path}")
        return {"path": logical_path, "present": False}
    out: dict[str, Any] = {
        "path": logical_path,
        "present": True,
        "bytes": path.stat().st_size,
    }
    if hash_content:
        out["sha256"] = _sha256_file(path)
    if magic_bytes:
        with path.open("rb") as f:
            raw = f.read(magic_bytes)
        out["magic_ascii"] = raw.decode("ascii", "replace").rstrip("\x00")
    return out


def _id_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def _sort_id_strings(values: Iterable[str]) -> list[str]:
    def key(value: str) -> tuple[int, int | str]:
        try:
            return (0, int(value))
        except ValueError:
            return (1, value)

    return sorted(set(values), key=key)


def _load_json(path: Path, logical_path: str) -> Any:
    if not path.is_file():
        raise ManifestError(f"필수 JSON 없음: {logical_path}")
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"JSON 읽기 실패: {logical_path}: {exc}") from exc


def _safe_settings_projection(settings_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """settings.json에서 명시적으로 허용한 값만 투영한다.

    raw m_Data, host/relativePath, AES key 값은 반환 객체로 전파하지 않는다.
    """

    raw = _load_json(settings_path, "nikke/StreamingAssets/aa/settings.json")
    addressables_version = str(raw.get("m_AddressablesVersion", ""))
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", addressables_version):
        addressables_version = None
    build_target = str(raw.get("m_buildTarget", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", build_target):
        build_target = None

    projection: dict[str, Any] = {
        "addressables_version": addressables_version,
        "build_target": build_target,
        "catalog_location_count": len(raw.get("m_CatalogLocations") or []),
        "initializers": [],
        "host_settings": {
            "version": None,
            "resource_host_group_count": 0,
            "project_names": [],
            "keysets": [],
        },
    }

    init_rows = raw.get("m_ExtraInitializationData") or []
    host_payload: dict[str, Any] | None = None
    for row in init_rows:
        if not isinstance(row, dict):
            continue
        init_id = str(row.get("m_Id", ""))
        class_name = ""
        obj_type = row.get("m_ObjectType")
        if isinstance(obj_type, dict):
            class_name = str(obj_type.get("m_ClassName", ""))
        expected_class = SAFE_INITIALIZERS.get(init_id)
        if expected_class is not None:
            projection["initializers"].append(
                {"id": init_id, "class_name": class_name if class_name == expected_class else None}
            )
        if init_id == "HostSettingsInitialization":
            payload = row.get("m_Data")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise ManifestError(f"HostSettings m_Data JSON 실패: {exc}") from exc
            if isinstance(payload, dict):
                host_payload = payload

    projection["initializers"] = sorted(
        projection["initializers"], key=lambda row: (row["id"], row["class_name"])
    )

    if host_payload is not None:
        host = projection["host_settings"]
        version_text = str(host_payload.get("Version", ""))
        host["version"] = version_text if re.fullmatch(r"[0-9]{1,10}", version_text) else None
        resource_hosts = host_payload.get("ResourceHosts2") or []
        host["resource_host_group_count"] = len(resource_hosts)

        projects: set[str] = set()
        for resource_host in resource_hosts:
            if not isinstance(resource_host, dict):
                continue
            for project in resource_host.get("projects") or []:
                if not isinstance(project, dict):
                    continue
                name = str(project.get("projectName", ""))
                if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name):
                    projects.add(name)
        host["project_names"] = sorted(projects)

        keysets = []
        for keyset in host_payload.get("KeySets") or []:
            if not isinstance(keyset, dict):
                continue
            version = keyset.get("version")
            if not isinstance(version, int):
                continue
            # key 값에는 접근/직렬화하지 않고 컨테이너 길이만 센다.
            keys_value = keyset.get("keys")
            key_count = len(keys_value) if isinstance(keys_value, list) else 0
            keysets.append({"version": version, "key_count": key_count})
        host["keysets"] = sorted(keysets, key=lambda row: row["version"])

    projection_sha = _sha256_bytes(_canonical_bytes(projection))
    projection["projection_sha256"] = projection_sha
    descriptor = {
        "path": "nikke/NIKKE/game/nikke_Data/StreamingAssets/aa/settings.json",
        "present": True,
        "bytes": settings_path.stat().st_size,
        "content_hash_policy": "omitted_sensitive_host_and_key_material",
    }
    return projection, descriptor


def _sd_bin_inventory(sd_path: Path) -> dict[str, Any]:
    base = _file_fingerprint(
        sd_path,
        logical_path="nikke/NIKKE/game/nikke_Data/StreamingAssets/sd.bin",
        hash_content=True,
        magic_bytes=4,
    )
    entries = []
    try:
        with zipfile.ZipFile(sd_path) as z:
            base["zip_entry_count"] = len(z.infolist())
            infos = {info.filename: info for info in z.infolist()}
            missing = [name for name in SAFE_SD_ENTRIES if name not in infos]
            if missing:
                raise ManifestError(f"sd.bin 필수 table 없음: {', '.join(missing)}")
            for name in SAFE_SD_ENTRIES:
                info = infos[name]
                row: dict[str, Any] = {
                    "name": name,
                    "compressed_bytes": info.compress_size,
                    "uncompressed_bytes": info.file_size,
                    "crc32": f"{info.CRC:08x}",
                    "version": None,
                    "record_count": None,
                }
                try:
                    payload = json.loads(z.read(info).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = None
                if isinstance(payload, dict):
                    version = payload.get("version")
                    if version is not None:
                        row["version"] = str(version)
                    records = payload.get("records")
                    if isinstance(records, list):
                        row["record_count"] = len(records)
                entries.append(row)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ManifestError(f"sd.bin ZIP 읽기 실패: {exc}") from exc
    base["entries"] = entries
    return base


def _is_reparse(entry: os.DirEntry[str]) -> bool:
    try:
        stat = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    attrs = getattr(stat, "st_file_attributes", 0)
    return entry.is_symlink() or bool(attrs & 0x400)


def _cache_inventory(cache_root: Path) -> dict[str, Any]:
    if not cache_root.is_dir():
        raise ManifestError("NAPS 캐시 디렉터리 없음: nikke/Unity/.../naps")

    rows: list[tuple[str, int]] = []
    sampled_headers: defaultdict[str, int] = defaultdict(int)
    sampled_files = 0

    with os.scandir(cache_root) as prefix_entries:
        prefixes = sorted(
            [entry for entry in prefix_entries if entry.is_dir(follow_symlinks=False) and not _is_reparse(entry)],
            key=lambda entry: entry.name.lower(),
        )

    for prefix in prefixes:
        with os.scandir(prefix.path) as file_entries:
            files = sorted(
                [entry for entry in file_entries if entry.is_file(follow_symlinks=False) and not _is_reparse(entry)],
                key=lambda entry: entry.name.lower(),
            )
        for entry in files:
            size = entry.stat(follow_symlinks=False).st_size
            rel = f"{prefix.name}/{entry.name}".lower()
            rows.append((rel, size))
        if files:
            sampled_files += 1
            try:
                with open(files[0].path, "rb") as f:
                    header = f.read(8)
            except OSError:
                sampled_headers["Unreadable"] += 1
            else:
                if header.startswith(b"UnityFS"):
                    sampled_headers["UnityFS"] += 1
                elif header.startswith(b"NKAB"):
                    sampled_headers["NKAB"] += 1
                else:
                    sampled_headers["Other"] += 1

    rows.sort(key=lambda row: row[0])
    digest = hashlib.sha256()
    histogram = {
        "le_64_kib": {"files": 0, "bytes": 0},
        "gt_64_kib_le_1_mib": {"files": 0, "bytes": 0},
        "gt_1_mib_le_5_mib": {"files": 0, "bytes": 0},
        "gt_5_mib": {"files": 0, "bytes": 0},
    }
    total_bytes = 0
    for rel, size in rows:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\n")
        total_bytes += size
        if size <= 64 * 1024:
            bucket = "le_64_kib"
        elif size <= 1024 * 1024:
            bucket = "gt_64_kib_le_1_mib"
        elif size <= 5 * 1024 * 1024:
            bucket = "gt_1_mib_le_5_mib"
        else:
            bucket = "gt_5_mib"
        histogram[bucket]["files"] += 1
        histogram[bucket]["bytes"] += size

    return {
        "path": "nikke/Unity/com_proximabeta_NIKKE/naps",
        "inventory_mode": "sorted_lowercase_relative_path_plus_size",
        "file_count": len(rows),
        "total_bytes": total_bytes,
        "metadata_sha256": digest.hexdigest(),
        "size_histogram": histogram,
        "format_sample": {
            "method": "lexicographically_first_file_per_prefix_directory",
            "sampled_files": sampled_files,
            "counts": dict(sorted(sampled_headers.items())),
            "warning": "sample_only_not_full_cache_distribution",
        },
        "content_hash_policy": "not_hashed_20gb_cache",
    }


def _zip_entry_fingerprint(z: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        info = z.getinfo(name)
    except KeyError as exc:
        raise ManifestError(f"StaticData 필수 entry 없음: {name}") from exc
    raw = z.read(info)
    row: dict[str, Any] = {
        "archive_entry": name,
        "uncompressed_bytes": info.file_size,
        "compressed_bytes": info.compress_size,
        "crc32": f"{info.CRC:08x}",
        "sha256": _sha256_bytes(raw),
        "record_count": None,
        "member_count": None,
    }
    if name.endswith(".mpk") and len(raw) >= 5:
        row["record_count"] = struct.unpack_from("<i", raw, 0)[0]
        row["member_count"] = raw[4]
    return row


def _safe_pack_version(static_root: Path) -> tuple[str | None, str]:
    candidates = (
        static_root / "pack_info.json",
        static_root / "StaticData.pack-info.json",
        static_root / "StaticData.pack_info.json",
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("version") is not None:
            version = str(data["version"])
            if re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", version):
                return version, f"sidecar:{path.name}"
    return None, "missing_safe_pack_info_sidecar"


def _staticdata_inventory(
    static_root: Path,
) -> tuple[dict[str, Any], dict[str, list[str]], dict[str, list[dict[str, Any]]]]:
    zip_path = static_root / "StaticData.zip"
    base = _file_fingerprint(
        zip_path,
        logical_path="repo/Database/raw/staticdata/StaticData.zip",
        hash_content=True,
        magic_bytes=4,
    )
    version, version_source = _safe_pack_version(static_root)
    base["pack_version"] = version
    base["pack_version_source"] = version_source

    group_dict: defaultdict[str, list[str]] = defaultdict(list)
    with zipfile.ZipFile(zip_path) as z:
        base["zip_entry_count"] = len(z.infolist())
        base["relevant_entries"] = {
            name: _zip_entry_fingerprint(z, name) for name in RELEVANT_STATIC_ENTRIES
        }

        expected_members = {
            "SoloRaidManagerTable.mpk": len(SOLO_RAID_SCOPE_SCHEMAS["SoloRaidManagerData"]),
            "SoloRaidPresetTable.mpk": len(SOLO_RAID_SCOPE_SCHEMAS["SoloRaidPresetData"]),
        }
        for name, expected in expected_members.items():
            actual = base["relevant_entries"][name]["member_count"]
            if actual != expected:
                raise ManifestError(
                    f"{name} memberCount drift: expected={expected} actual={actual}"
                )

        managers, managers_clean, managers_count = _decode_memorypack_table(
            z.read("SoloRaidManagerTable.mpk"),
            "SoloRaidManagerData",
            SOLO_RAID_SCOPE_SCHEMAS,
            strict_strings=True,
        )
        presets, presets_clean, presets_count = _decode_memorypack_table(
            z.read("SoloRaidPresetTable.mpk"),
            "SoloRaidPresetData",
            SOLO_RAID_SCOPE_SCHEMAS,
            strict_strings=True,
        )
        if not managers_clean or not presets_clean:
            raise ManifestError("SoloRaid manager/preset MemoryPack off != len")
        if managers_count != len(managers) or presets_count != len(presets):
            raise ManifestError("SoloRaid manager/preset MemoryPack root count 불일치")
        base["scope_tables_decode"] = {
            "SoloRaidManagerTable.mpk": {
                "record_count": managers_count,
                "member_count": base["relevant_entries"]["SoloRaidManagerTable.mpk"]["member_count"],
                "off_eq_len": managers_clean,
            },
            "SoloRaidPresetTable.mpk": {
                "record_count": presets_count,
                "member_count": base["relevant_entries"]["SoloRaidPresetTable.mpk"]["member_count"],
                "off_eq_len": presets_clean,
            },
        }
        raw = z.read("WaveData.GroupDict.csv").decode("utf-8-sig")
        reader = csv.reader(io.StringIO(raw))
        header = next(reader, None)
        if not header or len(header) < 2:
            raise ManifestError("WaveData.GroupDict.csv header 불량")
        total_rows = 0
        group_counts: defaultdict[str, int] = defaultdict(int)
        for row in reader:
            if len(row) < 2:
                continue
            stage_id, group_id = row[0].strip(), row[1].strip()
            if not re.fullmatch(r"[0-9]+", stage_id):
                continue
            if not re.fullmatch(r"[A-Za-z0-9_-]+", group_id):
                continue
            total_rows += 1
            group_counts[group_id] += 1
            group_dict[stage_id].append(group_id)
        base["wave_group_dict"] = {
            "rows": total_rows,
            "group_counts": dict(sorted(group_counts.items())),
        }
    return base, dict(group_dict), {"managers": managers, "presets": presets}


def _json_file_record(path: Path, logical_path: str, *, required: bool = False) -> dict[str, Any]:
    return _file_fingerprint(
        path,
        logical_path=logical_path,
        hash_content=True,
        required=required,
    )


def _artifact_inventory(repo_root: Path, static_root: Path) -> dict[str, Any]:
    roledata_path = repo_root / "Database" / "raw" / "blabla_roledata.json"
    roledata = _json_file_record(
        roledata_path,
        "repo/Database/raw/blabla_roledata.json",
        required=True,
    )
    roledata_json = _load_json(roledata_path, roledata["path"])
    roledata["roster_count"] = len(roledata_json.get("roster") or []) if isinstance(roledata_json, dict) else None

    artifacts: dict[str, Any] = {"public_roledata": roledata}
    paths = {
        "solo_raid_manager": static_root / "raid" / "SoloRaidManagerTable.json",
        "solo_raid_preset": static_root / "raid" / "SoloRaidPresetTable.json",
        "legacy_solo_raid_boss": static_root / "raid" / "solo_raid_boss.json",
        "skill_chains": static_root / "assembled" / "skill_chains.json",
        "monster_skill_table": static_root / "mpk" / "MonsterSkillTable.json",
        "challenge_catalog": static_root / "assembled" / "solo_raid_challenge_catalog.json",
        "behavior_catalog": static_root / "assembled" / "solo_raid_challenge_behavior.json",
        "frame_timeline": static_root / "assembled" / "solo_raid_challenge_timeline.json",
    }
    for key, path in paths.items():
        logical = f"repo/Database/raw/staticdata/{path.relative_to(static_root).as_posix()}"
        artifacts[key] = _json_file_record(
            path,
            logical,
            required=False,
        )

    # A prior run's authoritative behavior artifact must never silently enter a
    # newer StaticData snapshot.  Partial diagnostics use a different filename;
    # the authoritative filename is accepted only when its own digest and the
    # exact Challenge catalog source hash match the current inventory.
    behavior_path = paths["behavior_catalog"]
    if behavior_path.is_file():
        partial_behavior_path = (
            static_root
            / "assembled"
            / "solo_raid_challenge_behavior.partial.json"
        )
        if partial_behavior_path.is_file():
            raise ManifestError(
                "current partial Challenge behavior result invalidates stale authoritative artifact"
            )
        behavior = _load_json(
            behavior_path,
            artifacts["behavior_catalog"]["path"],
        )
        if not isinstance(behavior, dict):
            raise ManifestError("Challenge behavior catalog root is not an object")
        if (
            behavior.get("catalog_kind") != "solo_raid_challenge_behavior"
            or behavior.get("status") != "behavior_graph_complete"
            or behavior.get("validation", {}).get("status")
            != "behavior_graph_complete"
        ):
            raise ManifestError("authoritative Challenge behavior catalog is not complete")
        stored_digest = behavior.get("catalog_digest_sha256")
        digest_payload = dict(behavior)
        digest_payload.pop("catalog_digest_sha256", None)
        if not isinstance(stored_digest, str) or stored_digest != _sha256_bytes(
            _canonical_bytes(digest_payload)
        ):
            raise ManifestError("Challenge behavior catalog digest mismatch")
        challenge_sha = artifacts["challenge_catalog"].get("sha256")
        behavior_challenge_sha = (
            behavior.get("source", {})
            .get("challenge_catalog", {})
            .get("sha256")
        )
        if not challenge_sha or behavior_challenge_sha != challenge_sha:
            raise ManifestError(
                "Challenge behavior catalog source does not match current exact catalog"
            )
        artifacts["behavior_catalog"].update(
            {
                "catalog_digest_sha256": stored_digest,
                "behavior_rows": behavior.get("coverage", {}).get(
                    "behavior_resolved"
                ),
                "source_challenge_sha256": behavior_challenge_sha,
            }
        )

    timeline_path = paths["frame_timeline"]
    if timeline_path.is_file():
        partial_timeline_path = (
            static_root
            / "assembled"
            / "solo_raid_challenge_timeline.partial.json"
        )
        if partial_timeline_path.is_file():
            raise ManifestError(
                "current partial Challenge timeline invalidates stale authoritative artifact"
            )
        timeline = _load_json(timeline_path, artifacts["frame_timeline"]["path"])
        if not isinstance(timeline, dict):
            raise ManifestError("Challenge timeline root is not an object")
        if (
            timeline.get("catalog_kind") != "solo_raid_challenge_timeline"
            or timeline.get("status") != "event_frame_complete"
            or timeline.get("validation", {}).get("status") != "frame_complete"
        ):
            raise ManifestError("authoritative Challenge timeline is not frame-complete")
        stored_digest = timeline.get("catalog_digest_sha256")
        digest_payload = dict(timeline)
        digest_payload.pop("catalog_digest_sha256", None)
        if not isinstance(stored_digest, str) or stored_digest != _sha256_bytes(
            _canonical_bytes(digest_payload)
        ):
            raise ManifestError("Challenge timeline digest mismatch")
        behavior_sha = artifacts["behavior_catalog"].get("sha256")
        timeline_behavior_sha = (
            timeline.get("source", {})
            .get("behavior_artifact", {})
            .get("sha256")
        )
        if not behavior_sha or timeline_behavior_sha != behavior_sha:
            raise ManifestError(
                "Challenge timeline source does not match current behavior artifact"
            )
        artifacts["frame_timeline"].update(
            {
                "catalog_digest_sha256": stored_digest,
                "source_behavior_sha256": timeline_behavior_sha,
            }
        )

    legacy_path = paths["legacy_solo_raid_boss"]
    if legacy_path.is_file():
        data = _load_json(legacy_path, artifacts["legacy_solo_raid_boss"]["path"])
        if isinstance(data, list):
            artifacts["legacy_solo_raid_boss"].update(
                {
                    "rows": len(data),
                    "mapped_monster_rows": sum(row.get("monster_id") is not None for row in data if isinstance(row, dict)),
                    "mapping_authority": "legacy_model_crosscheck_not_challenge_exact",
                }
            )

    chains_path = paths["skill_chains"]
    if chains_path.is_file():
        data = _load_json(chains_path, artifacts["skill_chains"]["path"])
        if isinstance(data, dict):
            artifacts["skill_chains"].update(
                {
                    "bosses": len(data.get("bosses") or {}),
                    "functions": len(data.get("functions") or {}),
                    "state_effects": len(data.get("state_effects") or {}),
                    "character_skills": len(data.get("character_skills") or {}),
                }
            )
    return artifacts


def _challenge_scope(
    staticdata: dict[str, Any],
    wave_group_dict: dict[str, list[str]],
    managers: list[dict[str, Any]],
    presets: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    relation_ids: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    relations_by_preset: defaultdict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for row in managers:
        if not isinstance(row, dict):
            continue
        manager_id = _id_string(row.get("Id"))
        preset_group = _id_string(row.get("Monster_preset"))
        season = _id_string(row.get("Ranking_group_id"))
        if manager_id and preset_group and season:
            relation_ids[(season, preset_group)].append(manager_id)
    for (season, preset_group), ids in relation_ids.items():
        relations_by_preset[preset_group].append((season, _sort_id_strings(ids)))

    challenge_rows = []
    for row in presets:
        if not isinstance(row, dict):
            continue
        try:
            difficulty = int(row.get("Difficulty_type", -1))
        except (TypeError, ValueError):
            continue  # 신버전/결손 값은 scope 밖 unknown으로 graceful skip
        if difficulty == DIFFICULTY_TYPE:
            challenge_rows.append(row)
    if not challenge_rows:
        raise ManifestError("Difficulty_type=2 challenge preset이 없음")
    selected = []
    manager_missing: list[str] = []
    manager_ambiguous: list[str] = []
    wave_missing: list[str] = []
    wave_ambiguous: list[str] = []

    for row in challenge_rows:
        preset_id = _id_string(row.get("Id"))
        preset_group = _id_string(row.get("Preset_group_id"))
        wave_id = _id_string(row.get("Wave"))
        if not preset_id or not preset_group or not wave_id:
            raise ManifestError("challenge preset 핵심 ID 결손")

        relations = relations_by_preset.get(preset_group, [])
        if len(relations) == 1:
            season, manager_ids = relations[0]
            manager_status = "verified_exact"
        elif not relations:
            season, manager_ids = None, []
            manager_status = "missing"
            manager_missing.append(preset_group)
        else:
            season, manager_ids = None, []
            manager_status = "ambiguous"
            manager_ambiguous.append(preset_group)

        groups = sorted(set(wave_group_dict.get(wave_id, [])))
        if len(groups) == 1:
            wave_group = groups[0]
            wave_status = "verified_exact"
        elif not groups:
            wave_group = None
            wave_status = "missing"
            wave_missing.append(wave_id)
        else:
            wave_group = None
            wave_status = "ambiguous"
            wave_ambiguous.append(wave_id)

        image = str(row.get("Monster_image") or row.get("Monster_image_si") or "")
        if not re.fullmatch(r"(?:full_|si_)?[A-Za-z0-9_-]+", image):
            image = ""
        boss_code = image
        for prefix in ("full_", "si_"):
            if boss_code.startswith(prefix):
                boss_code = boss_code[len(prefix):]
                break

        archive_entry = f"WaveDataTable.{wave_group}.mpk" if wave_group else None
        selected.append(
            {
                "season": season,
                "manager_ids": manager_ids,
                "preset_id": preset_id,
                "preset_group_id": preset_group,
                "difficulty_type": DIFFICULTY_TYPE,
                "wave_order": _id_string(row.get("Wave_order")),
                "wave_id": wave_id,
                "wave_group_id": wave_group,
                "wave_archive_entry": archive_entry,
                "monster_stage_lv": _id_string(row.get("Monster_stage_lv")),
                "monster_stage_lv_change_group": _id_string(row.get("Monster_stage_lv_change_group")),
                "display_crosscheck": {
                    "monster_image": image or None,
                    "boss_code": boss_code or None,
                },
                "wave_record": {"record_id": None, "status": "not_decoded"},
                "monster_candidates": [],
                "exact_boss_monster_id": None,
                "spot_ai": {"normal": None, "defense": None, "base_defense": None},
                "verification": {
                    "manager_to_preset": manager_status,
                    "preset_to_wave_group": wave_status,
                    "wave_record_lookup": "not_attempted",
                    "wave_to_boss_monster": "not_attempted",
                    "monster_to_spot_ai": "blocked_upstream",
                    "spot_ai_to_asset": "blocked_upstream",
                },
            }
        )

    selected.sort(key=lambda row: int(row["season"]) if row["season"] is not None else 10**9)
    scope_tuples = [
        [row["season"], row["preset_id"], row["preset_group_id"], row["wave_id"]]
        for row in selected
    ]
    scope_digest = _sha256_bytes(_canonical_bytes(scope_tuples))

    duplicate_relations = [
        {
            "season": season,
            "preset_group_id": preset_group,
            "manager_ids": _sort_id_strings(ids),
        }
        for (season, preset_group), ids in sorted(relation_ids.items())
        if len(set(ids)) > 1
    ]

    group_resolved = sum(row["verification"]["preset_to_wave_group"] == "verified_exact" for row in selected)
    manager_resolved = sum(row["verification"]["manager_to_preset"] == "verified_exact" for row in selected)
    unique_groups = sorted({row["wave_group_id"] for row in selected if row["wave_group_id"]})

    wave_tables = {}
    for group in unique_groups:
        archive_entry = f"WaveDataTable.{group}.mpk"
        entry = staticdata["relevant_entries"].get(archive_entry)
        expected = staticdata["wave_group_dict"]["group_counts"].get(group, 0)
        wave_tables[group] = {
            "archive_entry": archive_entry,
            "expected_records_from_groupdict": expected,
            "wire_root_count": entry.get("record_count") if entry else None,
            "member_count": entry.get("member_count") if entry else None,
            "decoded_records": 0,
            "selected_wave_records_expected": sum(row["wave_group_id"] == group for row in selected),
            "selected_wave_records_resolved": 0,
            "status": "source_present_not_decoded" if entry else "missing",
        }

    denominator = len(selected)
    coverage = {
        "manager_to_preset": {
            "denominator": denominator,
            "resolved_exact": manager_resolved,
            "raw_manager_rows": len(managers),
            "unique_manager_relations": len(relation_ids),
            "duplicate_relations": duplicate_relations,
            "missing_preset_groups": _sort_id_strings(manager_missing),
            "ambiguous_preset_groups": _sort_id_strings(manager_ambiguous),
        },
        "preset_to_wave_group": {
            "denominator": denominator,
            "resolved_exact": group_resolved,
            "wave_groups": {
                group: sum(row["wave_group_id"] == group for row in selected) for group in unique_groups
            },
            "missing_wave_ids": _sort_id_strings(wave_missing),
            "ambiguous_wave_ids": _sort_id_strings(wave_ambiguous),
        },
        "wave_table_decode": wave_tables,
        "wave_to_boss_monster": {
            "denominator": denominator,
            "resolved_exact": 0,
            "missing": [],
            "ambiguous": [],
            "not_attempted": [row["wave_id"] for row in selected],
        },
        "monster_to_spot_ai": {
            "denominator": 0,
            "resolved_exact": 0,
            "missing_monster_ids": [],
            "blank_spot_ai_ids": [],
        },
        "spot_ai_to_asset": {
            "denominator_unique_keys": 0,
            "catalog_resolved": 0,
            "bundle_resolved": 0,
            "decoded": 0,
        },
    }

    checks = [
        {
            "name": "one_challenge_preset_per_manager_relation",
            "status": "passed" if denominator == len(relation_ids) and manager_resolved == denominator else "failed",
            "expected": len(relation_ids),
            "actual": denominator,
        },
        {
            "name": "challenge_preset_to_wave_group_exact",
            "status": "passed" if group_resolved == denominator else "failed",
            "expected": denominator,
            "actual": group_resolved,
        },
    ]
    for group, row in wave_tables.items():
        checks.append(
            {
                "name": f"wave_group_root_count:{group}",
                "status": "passed" if row["expected_records_from_groupdict"] == row["wire_root_count"] else "failed",
                "expected": row["expected_records_from_groupdict"],
                "actual": row["wire_root_count"],
            }
        )

    warnings = []
    if duplicate_relations:
        warnings.append("manager duplicate IDs preserved as arrays; relation itself remains exact")
    warnings.append("WaveData records are present but not decoded; exact challenge monster_id coverage is 0")

    resolved_seasons = [int(row["season"]) for row in selected if row["season"]]
    if not resolved_seasons:
        raise ManifestError("challenge season을 manager와 하나도 연결하지 못함")

    scope = {
        "mode": "solo_raid",
        "difficulty_type": DIFFICULTY_TYPE,
        "label": "challenge",
        "selection": "SoloRaidPresetTable.Difficulty_type == 2",
        "excludes": ["solo_raid_difficulty_type_1", "union_raid"],
        "scope_schema_version": 1,
        "scope_digest_sha256": scope_digest,
        "selected": {
            "preset_rows": denominator,
            "seasons": {
                "min": min(resolved_seasons),
                "max": max(resolved_seasons),
                "unique": len({row["season"] for row in selected if row["season"]}),
            },
            "preset_ids_unique": len({row["preset_id"] for row in selected}),
            "preset_groups_unique": len({row["preset_group_id"] for row in selected}),
            "wave_ids_unique": len({row["wave_id"] for row in selected}),
        },
    }
    return {"scope": scope, "entries": selected, "coverage": coverage}, {"checks": checks}, warnings


def _apply_challenge_catalog(
    static_root: Path,
    staticdata: dict[str, Any],
    challenge: dict[str, Any],
    validation: dict[str, Any],
    warnings: list[str],
    *,
    expected_challenge_rows: int | None,
    expected_scope_digest: str | None,
) -> bool:
    """현재 StaticData/scope와 exact 일치하는 catalog만 manifest에 병합한다.

    catalog 부재는 아직 stage를 실행하지 않은 정상적인 source_snapshot 상태다. 반대로
    파일이 존재하는데 stale/partial/ambiguous하면 조용히 강등하지 않고 snapshot 생성을
    중단한다.
    """

    path = static_root / "assembled" / "solo_raid_challenge_catalog.json"
    if not path.is_file():
        return False
    catalog = _load_json(
        path,
        "repo/Database/raw/staticdata/assembled/solo_raid_challenge_catalog.json",
    )
    if not isinstance(catalog, dict):
        raise ManifestError("challenge catalog 최상위가 object가 아님")
    if (
        catalog.get("schema_version") != 1
        or catalog.get("catalog_kind") != "solo_raid_challenge_static"
        or catalog.get("difficulty_type") != DIFFICULTY_TYPE
    ):
        raise ManifestError("challenge catalog schema/kind/difficulty drift")

    try:
        rebuilt_catalog = _rebuild_challenge_catalog(
            static_root,
            expected_challenge_rows=expected_challenge_rows,
            expected_scope_digest=expected_scope_digest,
        )
    except (
        _ChallengeCatalogError,
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
        raise ManifestError(f"challenge catalog 원천 재검증 실패: {exc}") from exc
    if _canonical_bytes(catalog) != _canonical_bytes(rebuilt_catalog):
        raise ManifestError("challenge catalog가 현재 StaticData.zip direct join 결과와 다름")

    declared_digest = catalog.get("catalog_digest_sha256")
    digest_payload = dict(catalog)
    digest_payload.pop("catalog_digest_sha256", None)
    actual_digest = _sha256_bytes(_canonical_bytes(digest_payload))
    if declared_digest != actual_digest:
        raise ManifestError("challenge catalog 자체 digest 불일치")

    source = catalog.get("source")
    source_zip = source.get("staticdata_zip") if isinstance(source, dict) else None
    if not isinstance(source_zip, dict) or source_zip.get("sha256") != staticdata.get("sha256"):
        raise ManifestError("challenge catalog가 현재 StaticData.zip에서 생성되지 않음")
    catalog_scope = catalog.get("scope")
    if (
        not isinstance(catalog_scope, dict)
        or catalog_scope.get("scope_digest_sha256")
        != challenge["scope"]["scope_digest_sha256"]
    ):
        raise ManifestError("challenge catalog scope digest가 현재 Challenge scope와 다름")

    denominator = len(challenge["entries"])
    catalog_coverage = catalog.get("coverage")
    if not isinstance(catalog_coverage, dict):
        raise ManifestError("challenge catalog coverage 결손")
    for key in ("denominator", "wave_records_exact", "boss_monsters_exact", "monster_spot_ai_exact"):
        if catalog_coverage.get(key) != denominator:
            raise ManifestError(
                f"challenge catalog partial coverage: {key}={catalog_coverage.get(key)} expected={denominator}"
            )
    catalog_validation = catalog.get("validation")
    if not isinstance(catalog_validation, dict) or catalog_validation.get("status") != "complete":
        raise ManifestError("challenge catalog validation이 complete가 아님")

    catalog_entries = catalog.get("entries")
    if not isinstance(catalog_entries, list) or len(catalog_entries) != denominator:
        raise ManifestError("challenge catalog entry 수가 현재 scope와 다름")

    def relation_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
        values = (row.get("season"), row.get("preset_id"), row.get("preset_group_id"), row.get("wave_id"))
        if not all(isinstance(value, str) and re.fullmatch(r"[0-9]+", value) for value in values):
            raise ManifestError("challenge catalog relation ID 결손")
        return values  # type: ignore[return-value]

    by_relation: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in catalog_entries:
        if not isinstance(item, dict):
            raise ManifestError("challenge catalog entry가 object가 아님")
        key = relation_key(item)
        if key in by_relation:
            raise ManifestError(f"challenge catalog duplicate relation: {key}")
        by_relation[key] = item

    mapping_lines: list[str] = []
    for row in challenge["entries"]:
        key = relation_key(row)
        item = by_relation.pop(key, None)
        if item is None:
            raise ManifestError(f"challenge catalog relation 결손: {key}")
        if item.get("difficulty_type") != DIFFICULTY_TYPE:
            raise ManifestError(f"challenge catalog difficulty drift: {key}")
        if item.get("manager_ids") != row.get("manager_ids"):
            raise ManifestError(f"challenge catalog manager_ids drift: {key}")
        if (
            item.get("wave_group_id") != row.get("wave_group_id")
            or item.get("wave_archive_entry") != row.get("wave_archive_entry")
        ):
            raise ManifestError(f"challenge catalog wave group drift: {key}")

        wave_record = item.get("wave_record")
        if not isinstance(wave_record, dict) or wave_record.get("stage_id") != row["wave_id"]:
            raise ManifestError(f"challenge catalog wave record drift: {key}")
        candidates = wave_record.get("boss_candidates")
        boss_id = item.get("exact_boss_monster_id")
        if (
            not isinstance(boss_id, str)
            or not re.fullmatch(r"[0-9]+", boss_id)
            or not isinstance(candidates, list)
            or candidates != [boss_id]
        ):
            raise ManifestError(f"challenge catalog boss candidate가 exact unique가 아님: {key}")
        monster = item.get("monster")
        if not isinstance(monster, dict) or monster.get("monster_id") != boss_id:
            raise ManifestError(f"challenge catalog MonsterTable join drift: {key}")
        spot_ai = item.get("spot_ai")
        if not isinstance(spot_ai, dict) or any(
            not isinstance(spot_ai.get(variant), str) or not spot_ai.get(variant)
            for variant in ("normal", "defense", "base_defense")
        ):
            raise ManifestError(f"challenge catalog spot_ai 결손: {key}")

        row["wave_record"] = {
            "record_id": wave_record["stage_id"],
            "status": "decoded_verified_exact",
            "spot_mod": wave_record.get("spot_mod"),
            "battle_time": wave_record.get("battle_time"),
            "target_monster_ids": wave_record.get("target_monster_ids"),
            "spawned_monster_ids": wave_record.get("spawned_monster_ids"),
        }
        row["monster_candidates"] = list(candidates)
        row["exact_boss_monster_id"] = boss_id
        row["spot_ai"] = {
            "normal": spot_ai["normal"],
            "defense": spot_ai["defense"],
            "base_defense": spot_ai["base_defense"],
        }
        row["verification"].update(
            {
                "wave_record_lookup": "verified_exact",
                "wave_to_boss_monster": "verified_exact_unique_target_spawn_intersection",
                "monster_to_spot_ai": "verified_exact",
                "spot_ai_to_asset": "not_attempted",
            }
        )
        mapping_lines.append(
            f"{row['season']}|{row['wave_id']}|{boss_id}|{spot_ai['normal']}\n"
        )
    if by_relation:
        raise ManifestError("challenge catalog에 현재 scope 밖 relation이 있음")

    actual_mapping_digest = _sha256_bytes("".join(mapping_lines).encode("utf-8"))
    if catalog.get("mapping_digest_sha256") != actual_mapping_digest:
        raise ManifestError("challenge catalog mapping digest 불일치")

    source_entries = source.get("entries") if isinstance(source, dict) else None
    if not isinstance(source_entries, dict):
        raise ManifestError("challenge catalog source entry fingerprints 결손")
    for group, wave_table in challenge["coverage"]["wave_table_decode"].items():
        source_entry = source_entries.get(wave_table["archive_entry"])
        if not isinstance(source_entry, dict):
            raise ManifestError(f"challenge catalog wave source entry 결손: {group}")
        if source_entry.get("record_count") != wave_table["wire_root_count"]:
            raise ManifestError(f"challenge catalog wave root count drift: {group}")
        wave_table.update(
            {
                "decoded_records": source_entry["record_count"],
                "selected_wave_records_resolved": wave_table["selected_wave_records_expected"],
                "status": "decoded_verified_exact",
            }
        )

    coverage = challenge["coverage"]
    coverage["wave_to_boss_monster"] = {
        "denominator": denominator,
        "resolved_exact": denominator,
        "missing": [],
        "ambiguous": [],
        "not_attempted": [],
    }
    coverage["monster_to_spot_ai"] = {
        "denominator": denominator,
        "resolved_exact": denominator,
        "missing_monster_ids": [],
        "blank_spot_ai_ids": [],
    }
    unique_spot_keys = {
        value
        for row in challenge["entries"]
        for value in row["spot_ai"].values()
        if value
    }
    coverage["spot_ai_to_asset"]["denominator_unique_keys"] = len(unique_spot_keys)
    validation["checks"].extend(
        [
            {
                "name": "challenge_catalog_staticdata_and_scope_match",
                "status": "passed",
                "expected": denominator,
                "actual": len(catalog_entries),
            },
            {
                "name": "challenge_monster_spot_ai_exact",
                "status": "passed",
                "expected": denominator,
                "actual": coverage["monster_to_spot_ai"]["resolved_exact"],
            },
        ]
    )
    warnings[:] = [
        warning
        for warning in warnings
        if not warning.startswith("WaveData records are present but not decoded")
    ]
    warnings.append(
        "Challenge monster_id and spot_ai are exact; behavior assets and frame timeline remain undecoded"
    )
    return True


def _decoded_scope_crosscheck(
    static_root: Path,
    managers: list[dict[str, Any]],
    presets: list[dict[str, Any]],
) -> dict[str, Any]:
    """기존 JSON 산출물이 있으면 ZIP 직접 디코드 결과와 bit-semantic 동등성을 확인한다."""

    manager_path = static_root / "raid" / "SoloRaidManagerTable.json"
    preset_path = static_root / "raid" / "SoloRaidPresetTable.json"
    if not manager_path.is_file() and not preset_path.is_file():
        return {"name": "decoded_scope_artifacts_match_zip", "status": "not_present"}
    if not manager_path.is_file() or not preset_path.is_file():
        raise ManifestError("SoloRaid manager/preset JSON 중 하나만 존재함")

    manager_json = _load_json(manager_path, "repo/Database/raw/staticdata/raid/SoloRaidManagerTable.json")
    preset_json = _load_json(preset_path, "repo/Database/raw/staticdata/raid/SoloRaidPresetTable.json")
    if not isinstance(manager_json, list) or not isinstance(preset_json, list):
        raise ManifestError("SoloRaid manager/preset JSON 최상위가 list가 아님")

    def normalized(rows: list[dict[str, Any]]) -> bytes:
        return _canonical_bytes(sorted(rows, key=lambda row: int(row.get("Id", -1))))

    manager_match = normalized(manager_json) == normalized(managers)
    preset_match = normalized(preset_json) == normalized(presets)
    if not manager_match or not preset_match:
        raise ManifestError(
            "decoded SoloRaid manager/preset JSON이 현재 StaticData.zip 직접 디코드와 다름"
        )
    return {
        "name": "decoded_scope_artifacts_match_zip",
        "status": "passed",
        "manager_rows": len(manager_json),
        "preset_rows": len(preset_json),
    }


def _git_identity(repo_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=repo_root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--untracked-files=no")
    return {
        "git_commit": commit,
        "tracked_dirty": bool(status) if status is not None else None,
    }


def _pipeline_identity(repo_root: Path) -> dict[str, Any]:
    scripts = {}
    for rel in PIPELINE_FILES:
        path = repo_root / rel
        scripts[rel] = _file_fingerprint(
            path,
            logical_path=f"repo/{rel}",
            hash_content=True,
            required=True,
        )
    return {
        **_git_identity(repo_root),
        "python_version": platform.python_version(),
        "scripts": scripts,
    }


def _identity_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    artifacts = manifest["artifacts"]
    return {
        "schema_version": manifest["schema_version"],
        "snapshot_kind": manifest["snapshot_kind"],
        "scope_digest_sha256": manifest["challenge"]["scope"]["scope_digest_sha256"],
        "sources": {
            "game_assembly": manifest["sources"]["client"]["game_assembly"]["sha256"],
            "scripting_assemblies": manifest["sources"]["client"]["scripting_assemblies"]["sha256"],
            "sd_bin": manifest["sources"]["client"]["sd_bin"]["sha256"],
            "settings_projection": manifest["sources"]["client"]["settings_safe"]["projection_sha256"],
            "catalog": manifest["sources"]["client"]["addressables_catalog"]["sha256"],
            "staticdata_zip": manifest["sources"]["staticdata"]["sha256"],
            "public_roledata": artifacts["public_roledata"]["sha256"],
        },
        "pipeline_scripts": {
            rel: row["sha256"] for rel, row in manifest["pipeline_identity"]["scripts"].items()
        },
        "artifacts": {
            key: row.get("sha256")
            for key, row in artifacts.items()
            if row.get("present") and key != "public_roledata"
        },
    }


def _audit_manifest(value: Any) -> None:
    """출력 객체에 절대경로/금지 키가 들어오지 않았는지 최종 점검."""

    drive_path = re.compile(r"[A-Za-z]:[\\/]")
    email_like = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key.lower() in FORBIDDEN_OUTPUT_KEYS:
                    raise ManifestError(f"manifest 금지 키 검출: {key}")
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, str):
            if drive_path.search(node) or "\\" in node:
                raise ManifestError("manifest 절대/Windows 경로 문자열 검출")
            if node.startswith(("/", "~")):
                raise ManifestError("manifest Unix/home 절대경로 문자열 검출")
            if "://" in node or email_like.search(node):
                raise ManifestError("manifest URL/email 문자열 검출")

    walk(value)


def build_manifest(
    *,
    repo_root: Path = REPO_ROOT,
    nikke_root: Path = DEFAULT_NIKKE_ROOT,
    static_root: Path = DEFAULT_STATIC_ROOT,
    generated_at: datetime | None = None,
    include_cache: bool = True,
    expected_challenge_rows: int | None = EXPECTED_CHALLENGE_ROWS,
    expected_scope_digest: str | None = EXPECTED_SCOPE_DIGEST,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    nikke_root = nikke_root.resolve()
    static_root = static_root.resolve()

    game_root = nikke_root / "NIKKE" / "game"
    data_root = game_root / "nikke_Data"
    streaming = data_root / "StreamingAssets"
    aa = streaming / "aa"
    cache_root = nikke_root / "Unity" / "com_proximabeta_NIKKE" / "naps"

    settings_safe, settings_descriptor = _safe_settings_projection(aa / "settings.json")
    staticdata, wave_group_dict, scope_tables = _staticdata_inventory(static_root)
    artifacts = _artifact_inventory(repo_root, static_root)
    challenge, validation, warnings = _challenge_scope(
        staticdata,
        wave_group_dict,
        scope_tables["managers"],
        scope_tables["presets"],
    )
    actual_scope_rows = len(challenge["entries"])
    actual_scope_digest = challenge["scope"]["scope_digest_sha256"]
    if expected_challenge_rows is not None and actual_scope_rows != expected_challenge_rows:
        raise ManifestError(
            f"approved Challenge scope row count drift: expected={expected_challenge_rows} "
            f"actual={actual_scope_rows}"
        )
    if expected_scope_digest is not None and actual_scope_digest != expected_scope_digest:
        raise ManifestError(
            "approved Challenge scope digest drift: "
            f"expected={expected_scope_digest} actual={actual_scope_digest}"
        )
    catalog_applied = _apply_challenge_catalog(
        static_root,
        staticdata,
        challenge,
        validation,
        warnings,
        expected_challenge_rows=expected_challenge_rows,
        expected_scope_digest=expected_scope_digest,
    )
    validation["checks"].append(
        _decoded_scope_crosscheck(
            static_root,
            scope_tables["managers"],
            scope_tables["presets"],
        )
    )

    client: dict[str, Any] = {
        "game_assembly": _file_fingerprint(
            game_root / "GameAssembly.dll",
            logical_path="nikke/NIKKE/game/GameAssembly.dll",
            hash_content=True,
        ),
        "scripting_assemblies": _file_fingerprint(
            data_root / "ScriptingAssemblies.json",
            logical_path="nikke/NIKKE/game/nikke_Data/ScriptingAssemblies.json",
            hash_content=True,
        ),
        "global_metadata": _file_fingerprint(
            data_root / "il2cpp_data" / "Metadata" / "global-metadata.dat",
            logical_path="nikke/NIKKE/game/nikke_Data/il2cpp_data/Metadata/global-metadata.dat",
            hash_content=True,
            required=False,
        ),
        "sd_bin": _sd_bin_inventory(streaming / "sd.bin"),
        "settings_file": settings_descriptor,
        "settings_safe": settings_safe,
        "addressables_catalog": _file_fingerprint(
            aa / "catalog.db",
            logical_path="nikke/NIKKE/game/nikke_Data/StreamingAssets/aa/catalog.db",
            hash_content=True,
            magic_bytes=4,
        ),
        "addressables_catalog_sidecar": _file_fingerprint(
            aa / "catalog.db.nds",
            logical_path="nikke/NIKKE/game/nikke_Data/StreamingAssets/aa/catalog.db.nds",
            hash_content=False,
        ),
    }
    client["addressables_catalog_sidecar"]["content_hash_policy"] = "omitted_key_material_sidecar"
    if include_cache:
        client["naps_inventory"] = _cache_inventory(cache_root)
    else:
        client["naps_inventory"] = {
            "path": "nikke/Unity/com_proximabeta_NIKKE/naps",
            "status": "not_scanned",
        }

    if staticdata["pack_version"] is None:
        warnings.append("StaticData safe pack-info sidecar missing; zip SHA-256 is authoritative snapshot identity")

    manifest: dict[str, Any] = {
        "schema_ref": "repo/DataPipeline/schema/solo_raid_challenge_snapshot.schema.json",
        "schema_version": SCHEMA_VERSION,
        "snapshot_kind": SNAPSHOT_KIND,
        "privacy_tier": "internal_local",
        "generated_at_utc": (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "data_version": None,
        "data_version_algorithm": "sha256(canonical_json(identity_payload)); generated_at and unselected NAPS cache excluded",
        "sources": {"client": client, "staticdata": staticdata},
        "pipeline_identity": _pipeline_identity(repo_root),
        "artifacts": artifacts,
        "challenge": challenge,
        "validation": {
            **validation,
            "status": "partial",
            "completeness_tier": "static_only" if catalog_applied else "source_snapshot",
            "warnings": warnings,
        },
        "exclusions": [
            "solo_raid_difficulty_type_1",
            "union_raid",
            "settings_raw_m_Data_and_AES_keys",
            "resource_host_URLs_and_paths",
            "catalog_nds_contents_and_hash",
            "absolute_paths_source_file_mtimes_hostnames",
            "launcher_logs_crash_logs_telemetry",
            "LocalLow_player_state_and_nkcache",
            "personal_roster_equipment_and_account_data",
            "decrypted_full_tables_behavior_assets_and_timeline_payloads",
            "RNG_seed",
        ],
    }

    failed_checks = [
        row for row in manifest["validation"]["checks"]
        if row["status"] not in {"passed", "not_present"}
    ]
    if failed_checks:
        names = ", ".join(row["name"] for row in failed_checks)
        raise ManifestError(f"challenge scope 검증 실패: {names}")

    manifest["data_version"] = f"sha256:{_sha256_bytes(_canonical_bytes(_identity_payload(manifest)))}"
    _audit_manifest(manifest)
    return manifest


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


def write_manifest(
    manifest: dict[str, Any],
    output_root: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> tuple[Path, Path]:
    allowed_root = (repo_root / "Database" / "raw" / "staticdata" / "snapshots" / SNAPSHOT_KIND).resolve()
    resolved_output = output_root.resolve()
    try:
        resolved_output.relative_to(allowed_root)
    except ValueError as exc:
        raise ManifestError(
            "output-root는 repo/Database/raw/staticdata/snapshots/solo_raid_challenge 하위여야 함"
        ) from exc

    version = manifest["data_version"].split(":", 1)[1]
    manifest_path = resolved_output / version / "manifest.json"
    latest_path = resolved_output / "latest.json"
    pointer = {
        "schema_version": SCHEMA_VERSION,
        "snapshot_kind": SNAPSHOT_KIND,
        "data_version": manifest["data_version"],
        "manifest_path": f"{version}/manifest.json",
    }
    _audit_manifest(pointer)
    _atomic_json_write(manifest_path, manifest)
    _atomic_json_write(latest_path, pointer)
    return manifest_path, latest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solo Raid Challenge source snapshot manifest 생성")
    parser.add_argument("--nikke-root", type=Path, default=DEFAULT_NIKKE_ROOT)
    parser.add_argument("--static-root", type=Path, default=DEFAULT_STATIC_ROOT)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="기본=repo/Database/raw/staticdata/snapshots/solo_raid_challenge (그 하위만 허용)",
    )
    parser.add_argument(
        "--skip-cache-inventory",
        action="store_true",
        help="NAPS 상대경로+크기 inventory를 생략(테스트/빠른 진단용)",
    )
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(
            repo_root=REPO_ROOT,
            nikke_root=args.nikke_root,
            static_root=args.static_root,
            include_cache=not args.skip_cache_inventory,
        )
        output_root = args.output_root or DEFAULT_OUTPUT_ROOT
        manifest_path, latest_path = write_manifest(manifest, output_root, repo_root=REPO_ROOT)
    except ManifestError as exc:
        print(f"❌ snapshot manifest 실패: {exc}", file=sys.stderr)
        return 1
    except (
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
        print(f"❌ snapshot manifest 입력/디코드 실패: {exc}", file=sys.stderr)
        return 1

    coverage = manifest["challenge"]["coverage"]
    print(f"✅ {SNAPSHOT_KIND} snapshot: {manifest['data_version']}")
    print(
        "   challenge preset→wave-group "
        f"{coverage['preset_to_wave_group']['resolved_exact']}/"
        f"{coverage['preset_to_wave_group']['denominator']} exact"
    )
    print(
        "   wave→monster "
        f"{coverage['wave_to_boss_monster']['resolved_exact']}/"
        f"{coverage['wave_to_boss_monster']['denominator']} exact"
    )
    print(
        "   monster→spot_ai "
        f"{coverage['monster_to_spot_ai']['resolved_exact']}/"
        f"{coverage['monster_to_spot_ai']['denominator']} exact"
    )
    print(f"   completeness: {manifest['validation']['completeness_tier']}")
    print(f"   manifest: {manifest_path}")
    print(f"   latest:   {latest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
