#!/usr/bin/env python3
"""Extract NIKKE monster Timeline metadata without exporting Unity assets.

This module is deliberately narrow and fail-closed.  It supports the Unity
2021.3 SerializedFile v22 layout observed inside NIKKE SpotMonster bundles and
decodes only the object schemas needed to connect:

    Shot_N -> MonsterTimeLineData.aniNumberLists
           -> owner GameObject -> PlayableDirector -> top TimelineAsset
           -> modelDirector -> model TimelineAsset
           -> TrackAsset -> NKSpotMonsterAttackMarker

    MonsterAnimController -> mAnimatorList -> Animator.m_Controller

The latter route also proves that ``ShotAnimTime`` is not serialized in the
controller payload; exact-build native evidence locates it in a runtime-only
dictionary instead.

It also decodes the common TrackAsset prefix (including TimelineClip records),
so a control/animation clip can be followed to its PlayableAsset reference.
The decrypted CAB and ``.resS`` bytes remain in memory; the CLI writes JSON to
stdout only.

Relevant v22 object layouts, all relative to the object's data start:

* MonoBehaviour base:
  ``PPtr m_GameObject; u8 m_Enabled; align4; PPtr m_Script;
  aligned-string m_Name``.
* TimelineAsset suffix:
  ``i32 m_Version; PPtr[] m_Tracks; f64 m_FixedDuration;
  f64 m_Framerate; u8 m_ScenePreview; align4; i32 m_DurationMode;
  PPtr m_MarkerTrack``.
* NKSpotMonsterAttackMarker suffix:
  ``f64 m_Time; i32 Target; i32 hitEffectType``.
* MonsterTimeLineData suffix:
  ``i32 sceneType; i32 trigger; PPtr cutSceneOption;
  PPtr modelDirector; PPtr skillOption; i32[] aniNumberLists;
  u8 disable; align4``.
* MonsterAnimController suffix:
  ``PPtr<Animator>[] mAnimatorList; PPtr<AnimEventTrigger>[] animEventTriggers;
  u8 isUpdateParameter; align4``.
* TrackAsset suffix:
  ``i32 m_Version; PPtr m_AnimClip; u8 m_Locked; align4;
  u8 m_Muted; align4; aligned-string m_CustomPlayableFullTypename;
  PPtr m_Curves; PPtr m_Parent; PPtr[] m_Children;
  TimelineClip[] m_Clips; PPtr[] m_Markers``.

The parser records the actual relative offsets reached after every variable
length field.  These offsets are evidence for a particular object, not global
constants.  A schema drift, unexpected count, trailing byte in an object that
must be exact, or out-of-range PPtr causes an explicit error rather than a
best-effort result.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path
from typing import Any, Iterable

try:  # Package import.
    from .unityfs_minimal import UnityFSBundle, UnityFSNode, read_unityfs
except ImportError:  # Direct ``python unity_serialized_timeline.py`` use.
    from unityfs_minimal import UnityFSBundle, UnityFSNode, read_unityfs


class SerializedTimelineError(RuntimeError):
    """The serialized file or one of the supported schemas is malformed."""


MAX_OBJECTS = 1_000_000
MAX_TYPES = 100_000
MAX_NODES = 1_000_000
MAX_ARRAY_ITEMS = 1_000_000
MAX_STRING_BYTES = 64 * 1024 * 1024
MONSTER_ANIM_CONTROLLER_TYPE_HASH = bytes.fromhex(
    "73787b534c8d2f3133afab8ee9d5f178"
)


BUILTIN_CLASS_NAMES: dict[int, str] = {
    1: "GameObject",
    4: "Transform",
    21: "Material",
    23: "MeshRenderer",
    28: "Texture2D",
    33: "MeshFilter",
    43: "Mesh",
    64: "MeshCollider",
    65: "BoxCollider",
    74: "AnimationClip",
    90: "Avatar",
    91: "AnimatorController",
    95: "Animator",
    114: "MonoBehaviour",
    115: "MonoScript",
    120: "LineRenderer",
    136: "CapsuleCollider",
    137: "SkinnedMeshRenderer",
    142: "AssetBundle",
    143: "CharacterController",
    198: "ParticleSystem",
    199: "ParticleSystemRenderer",
    210: "SortingGroup",
    320: "PlayableDirector",
}


@dataclasses.dataclass(frozen=True)
class PPtr:
    file_id: int
    path_id: int

    def json(self) -> dict[str, int | str]:
        # PathIDs routinely exceed JavaScript's exact integer range.
        return {"file_id": self.file_id, "path_id": str(self.path_id)}


@dataclasses.dataclass(frozen=True)
class TypeTreeNode:
    version: int
    level: int
    type_flags: int
    type_string_offset: int
    name_string_offset: int
    byte_size: int
    index: int
    meta_flag: int
    ref_type_hash: int


@dataclasses.dataclass(frozen=True)
class SerializedType:
    class_id: int
    is_stripped_type: bool
    script_type_index: int
    script_id: bytes | None
    old_type_hash: bytes
    nodes: tuple[TypeTreeNode, ...]
    string_buffer: bytes
    dependencies: tuple[int, ...]


@dataclasses.dataclass(frozen=True)
class ObjectInfo:
    path_id: int
    byte_start: int
    byte_size: int
    type_id: int


@dataclasses.dataclass(frozen=True)
class ScriptTypeRef:
    file_id: int
    path_id: int


@dataclasses.dataclass(frozen=True)
class MonoScriptInfo:
    path_id: int
    name: str
    execution_order: int
    properties_hash: str
    class_name: str
    namespace: str
    assembly_name: str

    @property
    def qualified_name(self) -> str:
        return (
            f"{self.namespace}.{self.class_name}"
            if self.namespace
            else self.class_name
        )


class _Reader:
    def __init__(
        self,
        data: bytes,
        *,
        endian: str,
        offset: int = 0,
        end: int | None = None,
        label: str,
    ) -> None:
        if endian not in ("<", ">"):
            raise ValueError(f"invalid endian prefix {endian!r}")
        self.data = data
        self.endian = endian
        self.offset = offset
        self.start = offset
        self.end = len(data) if end is None else end
        self.label = label
        if offset < 0 or self.end < offset or self.end > len(data):
            raise SerializedTimelineError(f"{label}: invalid reader bounds")

    @property
    def remaining(self) -> int:
        return self.end - self.offset

    @property
    def relative(self) -> int:
        return self.offset - self.start

    def _take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > self.end:
            raise SerializedTimelineError(
                f"{self.label}: truncated at {self.offset} while reading {size} bytes"
            )
        value = self.data[self.offset : self.offset + size]
        self.offset += size
        return value

    def _unpack(self, fmt: str, size: int) -> int | float:
        if self.offset + size > self.end:
            raise SerializedTimelineError(
                f"{self.label}: truncated at {self.offset} while reading {fmt}"
            )
        value = struct.unpack_from(self.endian + fmt, self.data, self.offset)[0]
        self.offset += size
        return value

    def u8(self) -> int:
        return int(self._unpack("B", 1))

    def i16(self) -> int:
        return int(self._unpack("h", 2))

    def u16(self) -> int:
        return int(self._unpack("H", 2))

    def i32(self) -> int:
        return int(self._unpack("i", 4))

    def u32(self) -> int:
        return int(self._unpack("I", 4))

    def i64(self) -> int:
        return int(self._unpack("q", 8))

    def u64(self) -> int:
        return int(self._unpack("Q", 8))

    def f32(self) -> float:
        return float(self._unpack("f", 4))

    def f64(self) -> float:
        return float(self._unpack("d", 8))

    def bytes(self, size: int) -> bytes:
        return self._take(size)

    def align(self, alignment: int = 4) -> None:
        if alignment <= 0 or alignment & (alignment - 1):
            raise ValueError("alignment must be a positive power of two")
        aligned = (self.offset + alignment - 1) & ~(alignment - 1)
        padding = self._take(aligned - self.offset)
        if any(padding):
            raise SerializedTimelineError(
                f"{self.label}: nonzero {alignment}-byte alignment padding"
            )

    def cstring(self, *, max_size: int = 4096) -> str:
        limit = min(self.end, self.offset + max_size + 1)
        zero = self.data.find(b"\0", self.offset, limit)
        if zero < 0:
            raise SerializedTimelineError(
                f"{self.label}: unterminated string at {self.offset}"
            )
        raw = self.data[self.offset:zero]
        self.offset = zero + 1
        try:
            return raw.decode("utf-8", "strict")
        except UnicodeError as exc:
            raise SerializedTimelineError(
                f"{self.label}: non-UTF8 C string at {self.offset}"
            ) from exc

    def aligned_string(self) -> str:
        size = self.i32()
        if size < 0 or size > MAX_STRING_BYTES or size > self.remaining:
            raise SerializedTimelineError(
                f"{self.label}: invalid string size {size} at {self.offset - 4}"
            )
        raw = self.bytes(size)
        try:
            value = raw.decode("utf-8", "strict")
        except UnicodeError as exc:
            raise SerializedTimelineError(
                f"{self.label}: non-UTF8 aligned string at {self.offset - size}"
            ) from exc
        self.align(4)
        return value

    def pptr(self) -> PPtr:
        return PPtr(file_id=self.i32(), path_id=self.i64())

    def count(self, field: str, *, maximum: int = MAX_ARRAY_ITEMS) -> int:
        value = self.i32()
        if value < 0 or value > maximum:
            raise SerializedTimelineError(
                f"{self.label}: invalid {field} count {value} at {self.offset - 4}"
            )
        return value

    def finish(self) -> None:
        if self.offset != self.end:
            raise SerializedTimelineError(
                f"{self.label}: {self.end - self.offset} unconsumed bytes"
            )


@dataclasses.dataclass
class SerializedFile:
    data: bytes
    format_version: int
    unity_version: str
    target_platform: int
    endian: str
    metadata_size: int
    data_offset: int
    types: tuple[SerializedType, ...]
    objects: tuple[ObjectInfo, ...]
    script_types: tuple[ScriptTypeRef, ...]
    metadata_consumed: int

    def __post_init__(self) -> None:
        self.objects_by_path: dict[int, ObjectInfo] = {
            item.path_id: item for item in self.objects
        }
        if len(self.objects_by_path) != len(self.objects):
            raise SerializedTimelineError("duplicate SerializedFile PathID")

    def object_reader(self, obj: ObjectInfo, label: str) -> _Reader:
        start = self.data_offset + obj.byte_start
        end = start + obj.byte_size
        if start < self.data_offset or end > len(self.data):
            raise SerializedTimelineError(
                f"{label}: object PathID {obj.path_id} lies outside serialized data"
            )
        return _Reader(
            self.data,
            endian=self.endian,
            offset=start,
            end=end,
            label=label,
        )


def parse_serialized_file(data: bytes) -> SerializedFile:
    """Parse the v22 metadata and object table from one CAB node."""

    header = _Reader(data, endian=">", label="SerializedFile header")
    legacy_metadata_size = header.u32()
    legacy_file_size = header.u32()
    format_version = header.u32()
    legacy_data_offset = header.u32()
    endian_flag = header.u8()
    reserved = header.bytes(3)
    if any(reserved):
        raise SerializedTimelineError("SerializedFile header has nonzero reserved bytes")
    if format_version != 22:
        raise SerializedTimelineError(
            f"unsupported SerializedFile version {format_version}; expected 22"
        )

    metadata_size = header.u32()
    file_size = header.u64()
    data_offset = header.u64()
    unknown = header.u64()
    if unknown != 0:
        raise SerializedTimelineError(f"unexpected v22 header value {unknown}")
    if file_size != len(data):
        raise SerializedTimelineError(
            f"SerializedFile size mismatch header={file_size} actual={len(data)}"
        )
    if any((legacy_metadata_size, legacy_file_size, legacy_data_offset)):
        raise SerializedTimelineError("v22 legacy header fields are unexpectedly nonzero")
    if endian_flag == 0:
        endian = "<"
    elif endian_flag == 1:
        endian = ">"
    else:
        raise SerializedTimelineError(f"invalid SerializedFile endian flag {endian_flag}")

    metadata_start = header.offset
    metadata_end = metadata_start + metadata_size
    if metadata_end > len(data) or data_offset < metadata_end:
        raise SerializedTimelineError("SerializedFile metadata/data ranges overlap or truncate")
    reader = _Reader(
        data,
        endian=endian,
        offset=metadata_start,
        end=metadata_end,
        label="SerializedFile metadata",
    )
    unity_version = reader.cstring(max_size=256)
    target_platform = reader.i32()
    enable_type_tree = reader.u8()
    if enable_type_tree != 1:
        raise SerializedTimelineError("type tree is required for timeline validation")

    type_count = reader.count("serialized type", maximum=MAX_TYPES)
    types: list[SerializedType] = []
    for type_index in range(type_count):
        class_id = reader.i32()
        is_stripped = bool(reader.u8())
        script_type_index = reader.i16()
        script_id = (
            reader.bytes(16) if class_id == 114 or class_id < 0 else None
        )
        old_type_hash = reader.bytes(16)

        node_count = reader.count("type-tree node", maximum=MAX_NODES)
        string_buffer_size = reader.count(
            "type-tree string byte", maximum=MAX_STRING_BYTES
        )
        nodes = tuple(
            TypeTreeNode(
                version=reader.u16(),
                level=reader.u8(),
                type_flags=reader.u8(),
                type_string_offset=reader.u32(),
                name_string_offset=reader.u32(),
                byte_size=reader.i32(),
                index=reader.i32(),
                meta_flag=reader.i32(),
                ref_type_hash=reader.u64(),
            )
            for _ in range(node_count)
        )
        string_buffer = reader.bytes(string_buffer_size)
        dependency_count = reader.count("type dependency", maximum=MAX_TYPES)
        dependencies = tuple(reader.i32() for _ in range(dependency_count))
        if nodes and nodes[0].level != 0:
            raise SerializedTimelineError(
                f"serialized type {type_index} root level is {nodes[0].level}"
            )
        types.append(
            SerializedType(
                class_id=class_id,
                is_stripped_type=is_stripped,
                script_type_index=script_type_index,
                script_id=script_id,
                old_type_hash=old_type_hash,
                nodes=nodes,
                string_buffer=string_buffer,
                dependencies=dependencies,
            )
        )

    object_count = reader.count("object", maximum=MAX_OBJECTS)
    objects: list[ObjectInfo] = []
    for _ in range(object_count):
        reader.align(4)
        item = ObjectInfo(
            path_id=reader.i64(),
            byte_start=reader.i64(),
            byte_size=reader.u32(),
            type_id=reader.i32(),
        )
        if item.type_id < 0 or item.type_id >= len(types):
            raise SerializedTimelineError(
                f"object PathID {item.path_id} has invalid type ID {item.type_id}"
            )
        if item.byte_start < 0 or item.byte_size < 0:
            raise SerializedTimelineError(
                f"object PathID {item.path_id} has a negative data range"
            )
        objects.append(item)

    script_type_count = reader.count("script type", maximum=MAX_TYPES)
    script_types = tuple(
        ScriptTypeRef(file_id=reader.i32(), path_id=reader.i64())
        for _ in range(script_type_count)
    )

    return SerializedFile(
        data=data,
        format_version=format_version,
        unity_version=unity_version,
        target_platform=target_platform,
        endian=endian,
        metadata_size=metadata_size,
        data_offset=data_offset,
        types=tuple(types),
        objects=tuple(objects),
        script_types=script_types,
        metadata_consumed=reader.offset - metadata_start,
    )


def _decode_mono_script(sf: SerializedFile, obj: ObjectInfo) -> MonoScriptInfo:
    reader = sf.object_reader(obj, f"MonoScript {obj.path_id}")
    name = reader.aligned_string()
    execution_order = reader.i32()
    properties_hash = reader.bytes(16).hex()
    class_name = reader.aligned_string()
    namespace = reader.aligned_string()
    assembly_name = reader.aligned_string()
    reader.finish()
    return MonoScriptInfo(
        path_id=obj.path_id,
        name=name,
        execution_order=execution_order,
        properties_hash=properties_hash,
        class_name=class_name,
        namespace=namespace,
        assembly_name=assembly_name,
    )


def _decode_mono_base(reader: _Reader) -> dict[str, Any]:
    offsets = {"m_GameObject": reader.relative}
    game_object = reader.pptr()
    offsets["m_Enabled"] = reader.relative
    enabled = reader.u8()
    reader.align(4)
    offsets["m_Script"] = reader.relative
    script = reader.pptr()
    offsets["m_Name"] = reader.relative
    name = reader.aligned_string()
    return {
        "game_object": game_object,
        "enabled": enabled,
        "script": script,
        "name": name,
        "field_offsets": offsets,
    }


def _decode_monster_anim_controller(
    sf: SerializedFile, obj: ObjectInfo
) -> dict[str, Any]:
    """Decode the complete serialized MonsterAnimController payload.

    ``GetShotTime`` state is intentionally absent here: the exact-build native
    method reads a runtime dictionary populated by ``SetShotTime``.  This
    decoder proves the serialized boundary instead of scanning arbitrary bytes
    for a float that is not part of the type tree.
    """

    serialized_type = sf.types[obj.type_id]
    if (
        serialized_type.class_id != 114
        or serialized_type.old_type_hash != MONSTER_ANIM_CONTROLLER_TYPE_HASH
    ):
        raise SerializedTimelineError(
            f"MonsterAnimController {obj.path_id}: unexpected serialized type hash"
        )
    reader = sf.object_reader(obj, f"MonsterAnimController {obj.path_id}")
    base = _decode_mono_base(reader)
    offsets = base["field_offsets"]
    offsets["mAnimatorList"] = reader.relative
    animators = _pptr_array(reader, "mAnimatorList")
    offsets["animEventTriggers"] = reader.relative
    event_triggers = _pptr_array(reader, "animEventTriggers")
    offsets["isUpdateParameter"] = reader.relative
    is_update_parameter = reader.u8()
    if is_update_parameter not in (0, 1):
        raise SerializedTimelineError(
            f"MonsterAnimController {obj.path_id}: invalid isUpdateParameter"
        )
    reader.align(4)
    reader.finish()
    return {
        **base,
        "animators": animators,
        "event_triggers": event_triggers,
        "is_update_parameter": bool(is_update_parameter),
        "serialized_shot_time_present": False,
    }


def _decode_animator(sf: SerializedFile, obj: ObjectInfo) -> dict[str, Any]:
    if sf.types[obj.type_id].class_id != 95:
        raise SerializedTimelineError(f"Animator {obj.path_id}: unexpected class ID")
    reader = sf.object_reader(obj, f"Animator {obj.path_id}")
    offsets = {"m_GameObject": reader.relative}
    game_object = reader.pptr()
    offsets["m_Enabled"] = reader.relative
    enabled = reader.u8()
    if enabled not in (0, 1):
        raise SerializedTimelineError(f"Animator {obj.path_id}: invalid m_Enabled")
    reader.align(4)
    offsets["m_Avatar"] = reader.relative
    avatar = reader.pptr()
    offsets["m_Controller"] = reader.relative
    controller = reader.pptr()
    offsets["m_CullingMode"] = reader.relative
    culling_mode = reader.i32()
    offsets["m_UpdateMode"] = reader.relative
    update_mode = reader.i32()
    bool_names = (
        "m_ApplyRootMotion",
        "m_LinearVelocityBlending",
        "m_StabilizeFeet",
        "m_HasTransformHierarchy",
        "m_AllowConstantClipSamplingOptimization",
        "m_KeepAnimatorStateOnDisable",
        "m_WriteDefaultValuesOnDisable",
    )
    bools: dict[str, bool] = {}
    for name in bool_names:
        offsets[name] = reader.relative
        value = reader.u8()
        if value not in (0, 1):
            raise SerializedTimelineError(
                f"Animator {obj.path_id}: invalid boolean field {name}"
            )
        bools[name] = bool(value)
    reader.align(4)
    reader.finish()
    return {
        "game_object": game_object,
        "enabled": bool(enabled),
        "avatar": avatar,
        "controller": controller,
        "culling_mode": culling_mode,
        "update_mode": update_mode,
        "settings": bools,
        "field_offsets": offsets,
    }


def _pptr_array(reader: _Reader, field: str) -> list[PPtr]:
    count = reader.count(field)
    return [reader.pptr() for _ in range(count)]


def _decode_timeline_asset(sf: SerializedFile, obj: ObjectInfo) -> dict[str, Any]:
    reader = sf.object_reader(obj, f"TimelineAsset {obj.path_id}")
    base = _decode_mono_base(reader)
    offsets = base["field_offsets"]
    offsets["m_Version"] = reader.relative
    version = reader.i32()
    offsets["m_Tracks"] = reader.relative
    tracks = _pptr_array(reader, "m_Tracks")
    offsets["m_FixedDuration"] = reader.relative
    fixed_duration = reader.f64()
    offsets["m_EditorSettings.m_Framerate"] = reader.relative
    framerate = reader.f64()
    offsets["m_EditorSettings.m_ScenePreview"] = reader.relative
    scene_preview = reader.u8()
    reader.align(4)
    offsets["m_DurationMode"] = reader.relative
    duration_mode = reader.i32()
    offsets["m_MarkerTrack"] = reader.relative
    marker_track = reader.pptr()
    reader.finish()
    return {
        **base,
        "version": version,
        "tracks": tracks,
        "fixed_duration": fixed_duration,
        "framerate": framerate,
        "scene_preview": scene_preview,
        "duration_mode": duration_mode,
        "marker_track": marker_track,
    }


def _decode_animation_curve(reader: _Reader, field: str) -> dict[str, Any]:
    count = reader.count(f"{field}.keys")
    keys = []
    for _ in range(count):
        keys.append(
            {
                "time": reader.f32(),
                "value": reader.f32(),
                "in_slope": reader.f32(),
                "out_slope": reader.f32(),
                "weighted_mode": reader.i32(),
                "in_weight": reader.f32(),
                "out_weight": reader.f32(),
            }
        )
    reader.align(4)
    return {
        "keys": keys,
        "pre_infinity": reader.i32(),
        "post_infinity": reader.i32(),
        "rotation_order": reader.i32(),
    }


def _decode_timeline_clip(reader: _Reader, index: int) -> dict[str, Any]:
    prefix = f"m_Clips[{index}]"
    offsets: dict[str, int] = {}

    def mark(name: str) -> None:
        offsets[name] = reader.relative

    mark("m_Version")
    version = reader.i32()
    mark("m_Start")
    start = reader.f64()
    mark("m_ClipIn")
    clip_in = reader.f64()
    mark("m_Asset")
    asset = reader.pptr()
    mark("m_Duration")
    duration = reader.f64()
    mark("m_TimeScale")
    time_scale = reader.f64()
    mark("m_ParentTrack")
    parent_track = reader.pptr()
    mark("m_EaseInDuration")
    ease_in = reader.f64()
    mark("m_EaseOutDuration")
    ease_out = reader.f64()
    mark("m_BlendInDuration")
    blend_in = reader.f64()
    mark("m_BlendOutDuration")
    blend_out = reader.f64()
    mark("m_MixInCurve")
    mix_in = _decode_animation_curve(reader, f"{prefix}.m_MixInCurve")
    mark("m_MixOutCurve")
    mix_out = _decode_animation_curve(reader, f"{prefix}.m_MixOutCurve")
    mark("m_BlendInCurveMode")
    blend_in_mode = reader.i32()
    mark("m_BlendOutCurveMode")
    blend_out_mode = reader.i32()
    mark("m_ExposedParameterNames")
    exposed_count = reader.count(f"{prefix}.m_ExposedParameterNames")
    exposed_names = [reader.aligned_string() for _ in range(exposed_count)]
    reader.align(4)
    mark("m_AnimationCurves")
    animation_curves = reader.pptr()
    mark("m_Recordable")
    recordable = reader.u8()
    reader.align(4)
    mark("m_PostExtrapolationMode")
    post_mode = reader.i32()
    mark("m_PreExtrapolationMode")
    pre_mode = reader.i32()
    mark("m_PostExtrapolationTime")
    post_time = reader.f64()
    mark("m_PreExtrapolationTime")
    pre_time = reader.f64()
    mark("m_DisplayName")
    display_name = reader.aligned_string()
    return {
        "version": version,
        "start": start,
        "clip_in": clip_in,
        "asset": asset,
        "duration": duration,
        "time_scale": time_scale,
        "parent_track": parent_track,
        "ease_in_duration": ease_in,
        "ease_out_duration": ease_out,
        "blend_in_duration": blend_in,
        "blend_out_duration": blend_out,
        "mix_in_curve": mix_in,
        "mix_out_curve": mix_out,
        "blend_in_curve_mode": blend_in_mode,
        "blend_out_curve_mode": blend_out_mode,
        "exposed_parameter_names": exposed_names,
        "animation_curves": animation_curves,
        "recordable": recordable,
        "post_extrapolation_mode": post_mode,
        "pre_extrapolation_mode": pre_mode,
        "post_extrapolation_time": post_time,
        "pre_extrapolation_time": pre_time,
        "display_name": display_name,
        "field_offsets": offsets,
    }


def _decode_track_prefix(sf: SerializedFile, obj: ObjectInfo) -> dict[str, Any]:
    """Decode the shared TrackAsset prefix; derived bytes may remain."""

    reader = sf.object_reader(obj, f"TrackAsset {obj.path_id}")
    base = _decode_mono_base(reader)
    offsets = base["field_offsets"]
    offsets["m_Version"] = reader.relative
    version = reader.i32()
    offsets["m_AnimClip"] = reader.relative
    anim_clip = reader.pptr()
    offsets["m_Locked"] = reader.relative
    locked = reader.u8()
    reader.align(4)
    offsets["m_Muted"] = reader.relative
    muted = reader.u8()
    reader.align(4)
    offsets["m_CustomPlayableFullTypename"] = reader.relative
    custom_playable = reader.aligned_string()
    offsets["m_Curves"] = reader.relative
    curves = reader.pptr()
    offsets["m_Parent"] = reader.relative
    parent = reader.pptr()
    offsets["m_Children"] = reader.relative
    children = _pptr_array(reader, "m_Children")
    offsets["m_Clips"] = reader.relative
    clip_count = reader.count("m_Clips")
    clips = [_decode_timeline_clip(reader, index) for index in range(clip_count)]
    offsets["m_Markers"] = reader.relative
    markers = _pptr_array(reader, "m_Markers.m_Objects")
    return {
        **base,
        "version": version,
        "anim_clip": anim_clip,
        "locked": locked,
        "muted": muted,
        "custom_playable_full_typename": custom_playable,
        "curves": curves,
        "parent": parent,
        "children": children,
        "clips": clips,
        "markers": markers,
        "decoded_bytes": reader.relative,
        "remaining_derived_bytes": reader.remaining,
    }


def _decode_attack_marker(sf: SerializedFile, obj: ObjectInfo) -> dict[str, Any]:
    reader = sf.object_reader(obj, f"NKSpotMonsterAttackMarker {obj.path_id}")
    base = _decode_mono_base(reader)
    offsets = base["field_offsets"]
    offsets["m_Time"] = reader.relative
    time = reader.f64()
    offsets["Target"] = reader.relative
    target = reader.i32()
    offsets["hitEffectType"] = reader.relative
    hit_effect_type = reader.i32()
    reader.finish()
    return {
        **base,
        "time": time,
        "target": target,
        "hit_effect_type": hit_effect_type,
    }


def _decode_control_playable_asset(
    sf: SerializedFile, obj: ObjectInfo
) -> dict[str, Any]:
    reader = sf.object_reader(obj, f"ControlPlayableAsset {obj.path_id}")
    base = _decode_mono_base(reader)
    exposed_name = reader.aligned_string()
    default_value = reader.pptr()
    prefab_game_object = reader.pptr()
    update_particle = reader.u8()
    reader.align(4)
    particle_random_seed = reader.u32()
    update_director = reader.u8()
    reader.align(4)
    update_time_control = reader.u8()
    reader.align(4)
    search_hierarchy = reader.u8()
    reader.align(4)
    active = reader.u8()
    reader.align(4)
    post_playback = reader.i32()
    reader.finish()
    return {
        **base,
        "exposed_name": exposed_name,
        "default_value": default_value,
        "prefab_game_object": prefab_game_object,
        "update_particle": update_particle,
        "particle_random_seed": particle_random_seed,
        "update_director": update_director,
        "update_time_control": update_time_control,
        "search_hierarchy": search_hierarchy,
        "active": active,
        "post_playback": post_playback,
    }


def _decode_animation_playable_asset_prefix(
    sf: SerializedFile, obj: ObjectInfo
) -> dict[str, Any]:
    """Decode the stable leading m_Clip field; later versioned fields may vary."""

    reader = sf.object_reader(obj, f"AnimationPlayableAsset {obj.path_id}")
    base = _decode_mono_base(reader)
    clip = reader.pptr()
    return {
        **base,
        "clip": clip,
        "decoded_bytes": reader.relative,
        "remaining_bytes": reader.remaining,
    }


def _decode_game_object(sf: SerializedFile, obj: ObjectInfo) -> dict[str, Any]:
    reader = sf.object_reader(obj, f"GameObject {obj.path_id}")
    components = _pptr_array(reader, "m_Component")
    reader.align(4)
    layer = reader.u32()
    name = reader.aligned_string()
    tag = reader.u16()
    is_active = reader.u8()
    reader.finish()
    return {
        "components": components,
        "layer": layer,
        "name": name,
        "tag": tag,
        "is_active": is_active,
    }


def _decode_playable_director(sf: SerializedFile, obj: ObjectInfo) -> dict[str, Any]:
    reader = sf.object_reader(obj, f"PlayableDirector {obj.path_id}")
    offsets = {"m_GameObject": reader.relative}
    game_object = reader.pptr()
    offsets["m_Enabled"] = reader.relative
    enabled = reader.u8()
    reader.align(4)
    offsets["m_PlayableAsset"] = reader.relative
    playable_asset = reader.pptr()
    offsets["m_InitialState"] = reader.relative
    initial_state = reader.i32()
    offsets["m_WrapMode"] = reader.relative
    wrap_mode = reader.i32()
    offsets["m_DirectorUpdateMode"] = reader.relative
    update_mode = reader.i32()
    offsets["m_InitialTime"] = reader.relative
    initial_time = reader.f64()
    offsets["m_SceneBindings"] = reader.relative
    binding_count = reader.count("m_SceneBindings")
    scene_bindings = [
        {"key": reader.pptr(), "value": reader.pptr()}
        for _ in range(binding_count)
    ]
    reader.align(4)
    offsets["m_ExposedReferences"] = reader.relative
    reference_count = reader.count("m_ExposedReferences.m_References")
    exposed_references = [
        {"id": reader.aligned_string(), "value": reader.pptr()}
        for _ in range(reference_count)
    ]
    reader.align(4)
    reader.finish()
    return {
        "game_object": game_object,
        "enabled": enabled,
        "playable_asset": playable_asset,
        "initial_state": initial_state,
        "wrap_mode": wrap_mode,
        "update_mode": update_mode,
        "initial_time": initial_time,
        "scene_bindings": scene_bindings,
        "exposed_references": exposed_references,
        "field_offsets": offsets,
    }


def _decode_monster_timeline_data(
    sf: SerializedFile, obj: ObjectInfo
) -> dict[str, Any]:
    reader = sf.object_reader(obj, f"MonsterTimeLineData {obj.path_id}")
    base = _decode_mono_base(reader)
    offsets = base["field_offsets"]
    offsets["sceneType"] = reader.relative
    scene_type = reader.i32()
    offsets["trigger"] = reader.relative
    trigger = reader.i32()
    offsets["cutSceneOption"] = reader.relative
    cut_scene_option = reader.pptr()
    offsets["modelDirector"] = reader.relative
    model_director = reader.pptr()
    offsets["skillOption"] = reader.relative
    skill_option = reader.pptr()
    offsets["aniNumberLists"] = reader.relative
    ani_count = reader.count("aniNumberLists")
    ani_numbers = [reader.i32() for _ in range(ani_count)]
    reader.align(4)
    offsets["disable"] = reader.relative
    disable = reader.u8()
    reader.align(4)
    reader.finish()
    return {
        **base,
        "scene_type": scene_type,
        "trigger": trigger,
        "cut_scene_option": cut_scene_option,
        "model_director": model_director,
        "skill_option": skill_option,
        "ani_numbers": ani_numbers,
        "disable": disable,
    }


def _peek_mono_name(sf: SerializedFile, obj: ObjectInfo) -> str:
    reader = sf.object_reader(obj, f"MonoBehaviour name {obj.path_id}")
    return str(_decode_mono_base(reader)["name"])


def _peek_named_object_name(sf: SerializedFile, obj: ObjectInfo) -> str | None:
    # AnimationClip and many other NamedObject-derived built-ins start with
    # aligned m_Name.  Fail silently here because this is presentation-only.
    try:
        reader = sf.object_reader(obj, f"named object {obj.path_id}")
        return reader.aligned_string()
    except SerializedTimelineError:
        return None


def _safe_frame(seconds: float, rate: float) -> dict[str, Any]:
    if not math.isfinite(seconds) or not math.isfinite(rate) or rate <= 0:
        return {"value": None, "integral": False}
    raw = seconds * rate
    nearest = int(round(raw))
    return {
        "value": nearest,
        "integral": math.isclose(raw, nearest, rel_tol=0.0, abs_tol=1e-8),
        "raw": raw,
    }


def _script_maps(
    sf: SerializedFile,
) -> tuple[dict[int, MonoScriptInfo], dict[int, MonoScriptInfo]]:
    mono_by_path: dict[int, MonoScriptInfo] = {}
    for obj in sf.objects:
        if sf.types[obj.type_id].class_id == 115:
            info = _decode_mono_script(sf, obj)
            mono_by_path[obj.path_id] = info

    mono_by_type: dict[int, MonoScriptInfo] = {}
    for type_id, item in enumerate(sf.types):
        if item.class_id != 114 or item.script_type_index < 0:
            continue
        if item.script_type_index >= len(sf.script_types):
            raise SerializedTimelineError(
                f"type {type_id} has invalid script index {item.script_type_index}"
            )
        ref = sf.script_types[item.script_type_index]
        if ref.file_id != 0:
            continue
        script = mono_by_path.get(ref.path_id)
        if script is None:
            raise SerializedTimelineError(
                f"type {type_id} references missing MonoScript {ref.path_id}"
            )
        mono_by_type[type_id] = script
    return mono_by_path, mono_by_type


def _object_descriptor(
    sf: SerializedFile,
    obj: ObjectInfo | None,
    mono_by_type: dict[int, MonoScriptInfo],
) -> dict[str, Any] | None:
    if obj is None:
        return None
    serialized_type = sf.types[obj.type_id]
    script = mono_by_type.get(obj.type_id)
    name: str | None = None
    if serialized_type.class_id == 114:
        name = _peek_mono_name(sf, obj)
    elif serialized_type.class_id == 115:
        name = _decode_mono_script(sf, obj).name
    elif serialized_type.class_id in {74, 91}:
        name = _peek_named_object_name(sf, obj)
    return {
        "path_id": str(obj.path_id),
        "type_id": obj.type_id,
        "class_id": serialized_type.class_id,
        "class_name": BUILTIN_CLASS_NAMES.get(
            serialized_type.class_id, f"ClassID_{serialized_type.class_id}"
        ),
        "script_class": script.qualified_name if script else None,
        "name": name,
        "byte_start": obj.byte_start,
        "byte_size": obj.byte_size,
    }


def _json_clip(
    clip: dict[str, Any],
    *,
    sf: SerializedFile,
    mono_by_type: dict[int, MonoScriptInfo],
    framerate: float,
) -> dict[str, Any]:
    asset_ref: PPtr = clip["asset"]
    asset_obj = (
        sf.objects_by_path.get(asset_ref.path_id) if asset_ref.file_id == 0 else None
    )
    asset_desc = _object_descriptor(sf, asset_obj, mono_by_type)
    asset_detail: dict[str, Any] | None = None
    if asset_obj is not None:
        script = mono_by_type.get(asset_obj.type_id)
        if script and script.class_name == "ControlPlayableAsset":
            decoded = _decode_control_playable_asset(sf, asset_obj)
            asset_detail = {
                "kind": "ControlPlayableAsset",
                "exposed_name": decoded["exposed_name"],
                "default_value": decoded["default_value"].json(),
                "prefab_game_object": decoded["prefab_game_object"].json(),
                "update_director": decoded["update_director"],
                "update_time_control": decoded["update_time_control"],
            }
        elif script and script.class_name == "AnimationPlayableAsset":
            decoded = _decode_animation_playable_asset_prefix(sf, asset_obj)
            clip_ref: PPtr = decoded["clip"]
            clip_obj = (
                sf.objects_by_path.get(clip_ref.path_id)
                if clip_ref.file_id == 0
                else None
            )
            asset_detail = {
                "kind": "AnimationPlayableAsset",
                "clip_ref": clip_ref.json(),
                "clip": _object_descriptor(sf, clip_obj, mono_by_type),
            }

    return {
        "version": clip["version"],
        "display_name": clip["display_name"],
        "start_seconds": clip["start"],
        "start_source_frame": _safe_frame(clip["start"], framerate),
        "start_canonical_60_frame": _safe_frame(clip["start"], 60.0),
        "clip_in_seconds": clip["clip_in"],
        "duration_seconds": clip["duration"],
        "duration_source_frames": _safe_frame(clip["duration"], framerate),
        "duration_canonical_60_frames": _safe_frame(clip["duration"], 60.0),
        "time_scale": clip["time_scale"],
        "asset_ref": asset_ref.json(),
        "asset": asset_desc,
        "asset_detail": asset_detail,
        "parent_track": clip["parent_track"].json(),
        "field_offsets": clip["field_offsets"],
    }


SHOT_RE = re.compile(r"^(?P<prefix>.+)_shot_(?P<number>\d+)(?P<suffix>_.+)$", re.I)


def build_timeline_manifest(
    sf: SerializedFile,
    *,
    bundle: UnityFSBundle,
    bundle_path: Path,
    node: UnityFSNode,
) -> dict[str, Any]:
    """Build a complete TimelineAsset manifest, including markerless shots."""

    _mono_by_path, mono_by_type = _script_maps(sf)

    schema_fingerprints: dict[str, list[dict[str, Any]]] = {}
    for type_id, script in mono_by_type.items():
        serialized_type = sf.types[type_id]
        schema_fingerprints.setdefault(script.qualified_name, []).append(
            {
                "type_id": type_id,
                "script_id": (
                    serialized_type.script_id.hex()
                    if serialized_type.script_id is not None
                    else None
                ),
                "old_type_hash": serialized_type.old_type_hash.hex(),
                "node_count": len(serialized_type.nodes),
                "string_buffer_sha256": hashlib.sha256(
                    serialized_type.string_buffer
                ).hexdigest(),
            }
        )

    def script_class(obj: ObjectInfo) -> str | None:
        script = mono_by_type.get(obj.type_id)
        return script.class_name if script else None

    monster_anim_controller_rows: list[dict[str, Any]] = []
    for obj in sf.objects:
        if script_class(obj) != "MonsterAnimController":
            continue
        decoded = _decode_monster_anim_controller(sf, obj)
        animator_rows = []
        for ref in decoded["animators"]:
            animator_obj = (
                sf.objects_by_path.get(ref.path_id) if ref.file_id == 0 else None
            )
            if ref.file_id == 0 and animator_obj is None:
                raise SerializedTimelineError(
                    f"MonsterAnimController {obj.path_id}: missing Animator {ref.path_id}"
                )
            if animator_obj is None:
                animator_rows.append(
                    {"ref": ref.json(), "resolution_status": "external_reference"}
                )
                continue
            animator = _decode_animator(sf, animator_obj)
            controller_ref: PPtr = animator["controller"]
            controller_obj = (
                sf.objects_by_path.get(controller_ref.path_id)
                if controller_ref.file_id == 0
                else None
            )
            if (
                controller_ref.file_id == 0
                and controller_ref.path_id
                and controller_obj is None
            ):
                raise SerializedTimelineError(
                    f"Animator {animator_obj.path_id}: missing controller "
                    f"{controller_ref.path_id}"
                )
            if (
                controller_obj is not None
                and sf.types[controller_obj.type_id].class_id != 91
            ):
                raise SerializedTimelineError(
                    f"Animator {animator_obj.path_id}: controller is not class 91"
                )
            animator_rows.append(
                {
                    "ref": ref.json(),
                    "resolution_status": "resolved_local",
                    "object": _object_descriptor(sf, animator_obj, mono_by_type),
                    "game_object": animator["game_object"].json(),
                    "avatar": animator["avatar"].json(),
                    "controller": controller_ref.json(),
                    "controller_object": _object_descriptor(
                        sf, controller_obj, mono_by_type
                    ),
                    "enabled": animator["enabled"],
                    "culling_mode": animator["culling_mode"],
                    "update_mode": animator["update_mode"],
                    "settings": animator["settings"],
                    "field_offsets": animator["field_offsets"],
                }
            )
        monster_anim_controller_rows.append(
            {
                "path_id": str(obj.path_id),
                "object_byte_start": obj.byte_start,
                "object_byte_size": obj.byte_size,
                "serialized_type_old_hash": sf.types[obj.type_id].old_type_hash.hex(),
                "serialized_shot_time_present": decoded[
                    "serialized_shot_time_present"
                ],
                "serialized_fields": [
                    "mAnimatorList",
                    "animEventTriggers",
                    "isUpdateParameter",
                ],
                "animators": animator_rows,
                "anim_event_triggers": [
                    ref.json() for ref in decoded["event_triggers"]
                ],
                "is_update_parameter": decoded["is_update_parameter"],
                "field_offsets": decoded["field_offsets"],
            }
        )
    monster_anim_controller_rows.sort(key=lambda item: item["path_id"])

    timelines_internal: dict[int, dict[str, Any]] = {}
    tracks_cache: dict[int, dict[str, Any]] = {}
    attacks_internal: dict[int, dict[str, Any]] = {}

    for obj in sf.objects:
        class_name = script_class(obj)
        if class_name == "TimelineAsset":
            timelines_internal[obj.path_id] = _decode_timeline_asset(sf, obj)
        elif class_name == "NKSpotMonsterAttackMarker":
            attacks_internal[obj.path_id] = _decode_attack_marker(sf, obj)

    def get_track(path_id: int) -> dict[str, Any] | None:
        if path_id in tracks_cache:
            return tracks_cache[path_id]
        obj = sf.objects_by_path.get(path_id)
        if obj is None:
            return None
        class_name = script_class(obj)
        if not class_name or not class_name.endswith("Track"):
            return None
        decoded = _decode_track_prefix(sf, obj)
        decoded["script_class"] = class_name
        tracks_cache[path_id] = decoded
        return decoded

    timeline_by_name = {
        str(decoded["name"]): path_id
        for path_id, decoded in timelines_internal.items()
    }

    # A root-track reference is an independent validation of m_Parent.
    root_track_to_timeline: dict[int, int] = {}
    for timeline_id, decoded in timelines_internal.items():
        for ref in decoded["tracks"]:
            if ref.file_id == 0 and ref.path_id:
                previous = root_track_to_timeline.setdefault(ref.path_id, timeline_id)
                if previous != timeline_id:
                    raise SerializedTimelineError(
                        f"track {ref.path_id} belongs to multiple TimelineAssets"
                    )

    def resolve_timeline(track_path_id: int) -> int | None:
        seen: set[int] = set()
        current = track_path_id
        while current and current not in seen:
            seen.add(current)
            if current in timelines_internal:
                return current
            direct = root_track_to_timeline.get(current)
            if direct is not None:
                return direct
            track = get_track(current)
            if track is None:
                return None
            parent: PPtr = track["parent"]
            if parent.file_id != 0:
                return None
            current = parent.path_id
        return None

    # Attack markers are held by NKSpotMonsterSignalTrack.m_Markers.m_Objects.
    marker_to_track: dict[int, int] = {}
    for obj in sf.objects:
        if script_class(obj) != "NKSpotMonsterSignalTrack":
            continue
        track = get_track(obj.path_id)
        if track is None:
            raise SerializedTimelineError(f"failed to decode signal track {obj.path_id}")
        if track["remaining_derived_bytes"] != 0:
            raise SerializedTimelineError(
                f"signal track {obj.path_id} has unexpected derived bytes"
            )
        for marker in track["markers"]:
            if marker.file_id == 0 and marker.path_id in attacks_internal:
                previous = marker_to_track.setdefault(marker.path_id, obj.path_id)
                if previous != obj.path_id:
                    raise SerializedTimelineError(
                        f"attack marker {marker.path_id} belongs to multiple tracks"
                    )

    attacks_by_timeline: dict[int, list[dict[str, Any]]] = {}
    unattached_attacks: list[str] = []
    for marker_id, decoded in attacks_internal.items():
        track_id = marker_to_track.get(marker_id)
        timeline_id = resolve_timeline(track_id) if track_id is not None else None
        if timeline_id is None:
            unattached_attacks.append(str(marker_id))
            continue
        timeline = timelines_internal[timeline_id]
        rate = float(timeline["framerate"])
        attacks_by_timeline.setdefault(timeline_id, []).append(
            {
                "path_id": str(marker_id),
                "track_path_id": str(track_id),
                "name": decoded["name"],
                "time_seconds": decoded["time"],
                "source_frame": _safe_frame(decoded["time"], rate),
                "canonical_60_frame": _safe_frame(decoded["time"], 60.0),
                "target": decoded["target"],
                "hit_effect_type": decoded["hit_effect_type"],
                "field_offsets": decoded["field_offsets"],
            }
        )

    # Authoritative Shot_N routing.  TimelineAsset names are only labels: one
    # MonsterTimeLineData may deliberately map several animation numbers to a
    # differently numbered top/model timeline.
    route_groups: list[dict[str, Any]] = []
    route_group_ids_by_ani: dict[int, list[str]] = {}
    top_ani_by_timeline: dict[int, set[int]] = {}
    model_ani_by_timeline: dict[int, set[int]] = {}

    def director_timeline(ref: PPtr, field: str) -> tuple[ObjectInfo, dict[str, Any], int]:
        if ref.file_id != 0 or not ref.path_id:
            raise SerializedTimelineError(f"{field}: expected a nonzero local PPtr")
        director_obj = sf.objects_by_path.get(ref.path_id)
        if director_obj is None or sf.types[director_obj.type_id].class_id != 320:
            raise SerializedTimelineError(
                f"{field}: PathID {ref.path_id} is not a local PlayableDirector"
            )
        director = _decode_playable_director(sf, director_obj)
        asset: PPtr = director["playable_asset"]
        if asset.file_id != 0 or asset.path_id not in timelines_internal:
            raise SerializedTimelineError(
                f"{field}: director {ref.path_id} does not reference a local TimelineAsset"
            )
        return director_obj, director, asset.path_id

    for obj in sf.objects:
        if script_class(obj) != "MonsterTimeLineData":
            continue
        data = _decode_monster_timeline_data(sf, obj)
        if not data["ani_numbers"]:
            continue

        owner_ref: PPtr = data["game_object"]
        if owner_ref.file_id != 0 or not owner_ref.path_id:
            raise SerializedTimelineError(
                f"MonsterTimeLineData {obj.path_id} has no local owner GameObject"
            )
        owner_obj = sf.objects_by_path.get(owner_ref.path_id)
        if owner_obj is None or sf.types[owner_obj.type_id].class_id != 1:
            raise SerializedTimelineError(
                f"MonsterTimeLineData {obj.path_id} owner is not a GameObject"
            )
        owner = _decode_game_object(sf, owner_obj)

        top_candidates: list[tuple[ObjectInfo, dict[str, Any], int]] = []
        for component in owner["components"]:
            if component.file_id != 0:
                continue
            component_obj = sf.objects_by_path.get(component.path_id)
            if (
                component_obj is None
                or sf.types[component_obj.type_id].class_id != 320
            ):
                continue
            director = _decode_playable_director(sf, component_obj)
            asset: PPtr = director["playable_asset"]
            if asset.file_id == 0 and asset.path_id in timelines_internal:
                top_candidates.append((component_obj, director, asset.path_id))
        if len(top_candidates) != 1:
            raise SerializedTimelineError(
                f"MonsterTimeLineData {obj.path_id} owner has "
                f"{len(top_candidates)} top TimelineAsset directors"
            )
        top_director_obj, top_director, top_timeline_id = top_candidates[0]
        model_director_obj, model_director, model_timeline_id = director_timeline(
            data["model_director"],
            f"MonsterTimeLineData {obj.path_id}.modelDirector",
        )

        route_id = str(obj.path_id)
        ani_numbers = [int(value) for value in data["ani_numbers"]]
        for ani_number in ani_numbers:
            route_group_ids_by_ani.setdefault(ani_number, []).append(route_id)
            top_ani_by_timeline.setdefault(top_timeline_id, set()).add(ani_number)
            model_ani_by_timeline.setdefault(model_timeline_id, set()).add(ani_number)

        top_timeline = timelines_internal[top_timeline_id]
        model_timeline = timelines_internal[model_timeline_id]
        route_groups.append(
            {
                "route_id": route_id,
                "ani_numbers": ani_numbers,
                "shot_keys": [f"Shot_{value:02d}" for value in ani_numbers],
                "disabled": bool(data["disable"]),
                "scene_type": data["scene_type"],
                "trigger": data["trigger"],
                "timeline_data_field_offsets": data["field_offsets"],
                "owner_game_object": {
                    "path_id": str(owner_obj.path_id),
                    "name": owner["name"],
                },
                "top_director": {
                    "path_id": str(top_director_obj.path_id),
                    "field_offsets": top_director["field_offsets"],
                },
                "top_timeline": {
                    "path_id": str(top_timeline_id),
                    "name": top_timeline["name"],
                    "attack_markers": attacks_by_timeline.get(top_timeline_id, []),
                },
                "model_director": {
                    "path_id": str(model_director_obj.path_id),
                    "field_offsets": model_director["field_offsets"],
                },
                "model_timeline": {
                    "path_id": str(model_timeline_id),
                    "name": model_timeline["name"],
                },
                "cut_scene_option": data["cut_scene_option"].json(),
                "skill_option": data["skill_option"].json(),
            }
        )

    route_groups.sort(
        key=lambda item: (
            min(item["ani_numbers"]) if item["ani_numbers"] else 2**31,
            item["route_id"],
        )
    )
    multi_route_ani_numbers = {
        str(key): value
        for key, value in sorted(route_group_ids_by_ani.items())
        if len(value) > 1
    }

    timeline_rows: list[dict[str, Any]] = []
    for path_id, decoded in timelines_internal.items():
        rate = float(decoded["framerate"])
        track_rows: list[dict[str, Any]] = []
        for ref in decoded["tracks"]:
            obj = sf.objects_by_path.get(ref.path_id) if ref.file_id == 0 else None
            desc = _object_descriptor(sf, obj, mono_by_type)
            track = get_track(ref.path_id) if obj is not None else None
            track_row: dict[str, Any] = {
                "ref": ref.json(),
                "object": desc,
                "clips": [],
                "marker_refs": [],
            }
            if track is not None:
                track_row["parent"] = track["parent"].json()
                track_row["clips"] = [
                    _json_clip(
                        clip,
                        sf=sf,
                        mono_by_type=mono_by_type,
                        framerate=rate,
                    )
                    for clip in track["clips"]
                ]
                track_row["marker_refs"] = [item.json() for item in track["markers"]]
                track_row["remaining_derived_bytes"] = track[
                    "remaining_derived_bytes"
                ]
                track_name = str(track["name"])
                nested_id = timeline_by_name.get(track_name)
                if nested_id is not None and nested_id != path_id:
                    track_row["nested_timeline_by_exact_name"] = str(nested_id)
            track_rows.append(track_row)

        match = SHOT_RE.match(str(decoded["name"]))
        shot_name_hint: dict[str, Any] | None = None
        if match:
            suffix = match.group("suffix")
            shot_name_hint = {
                "skill_ani_number": int(match.group("number")),
                "prefix": match.group("prefix"),
                "suffix": suffix,
                "is_model_timeline": suffix.lower().endswith("_model"),
                "authoritative": False,
            }

        row = {
            "path_id": str(path_id),
            "name": decoded["name"],
            "shot_name_hint": shot_name_hint,
            "authoritative_top_ani_numbers": sorted(
                top_ani_by_timeline.get(path_id, set())
            ),
            "authoritative_model_ani_numbers": sorted(
                model_ani_by_timeline.get(path_id, set())
            ),
            "fixed_duration_seconds": decoded["fixed_duration"],
            "fixed_duration_source_frames": _safe_frame(
                decoded["fixed_duration"], rate
            ),
            "fixed_duration_canonical_60_frames": _safe_frame(
                decoded["fixed_duration"], 60.0
            ),
            "framerate": rate,
            "duration_mode": decoded["duration_mode"],
            "scene_preview": decoded["scene_preview"],
            "marker_track": decoded["marker_track"].json(),
            "attack_markers": sorted(
                attacks_by_timeline.get(path_id, []),
                key=lambda item: (item["time_seconds"], item["path_id"]),
            ),
            "tracks": track_rows,
            "field_offsets": decoded["field_offsets"],
            "object_byte_start": sf.objects_by_path[path_id].byte_start,
            "object_byte_size": sf.objects_by_path[path_id].byte_size,
        }
        timeline_rows.append(row)

    timeline_rows.sort(key=lambda item: (str(item["name"]).lower(), item["path_id"]))
    shot_rows = [
        item for item in timeline_rows if item["shot_name_hint"] is not None
    ]

    return {
        "source": {
            "cache_key": bundle_path.name,
            "unityfs_sha256": bundle.sha256,
            "unityfs_format": bundle.format_version,
            "unity_version": bundle.unity_version,
            "unity_revision": bundle.unity_revision,
            "serialized_node": node.path,
            "serialized_node_sha256": hashlib.sha256(node.data).hexdigest(),
            "serialized_file_version": sf.format_version,
            "serialized_target_platform": sf.target_platform,
            "serialized_object_count": len(sf.objects),
            "serialized_type_count": len(sf.types),
        },
        "counts": {
            "timeline_assets": len(timeline_rows),
            "shot_timeline_assets": len(shot_rows),
            "attack_markers": len(attacks_internal),
            "attached_attack_markers": sum(
                len(item["attack_markers"]) for item in timeline_rows
            ),
            "monster_timeline_route_groups": len(route_groups),
            "routed_ani_numbers": len(route_group_ids_by_ani),
            "multi_route_ani_numbers": len(multi_route_ani_numbers),
            "disabled_route_groups": sum(
                1 for item in route_groups if item["disabled"]
            ),
            "monster_anim_controllers": len(monster_anim_controller_rows),
        },
        "schema_fingerprints": schema_fingerprints,
        "ani_number_route_groups": route_groups,
        "route_group_ids_by_ani_number": {
            str(key): value for key, value in sorted(route_group_ids_by_ani.items())
        },
        "multi_route_ani_numbers": multi_route_ani_numbers,
        "monster_anim_controllers": monster_anim_controller_rows,
        "shot_timelines": shot_rows,
        "all_timelines": timeline_rows,
        "unattached_attack_marker_path_ids": sorted(unattached_attacks),
    }


def _choose_serialized_node(
    bundle: UnityFSBundle, requested_path: str | None
) -> UnityFSNode:
    if requested_path is not None:
        matches = [item for item in bundle.nodes if item.path == requested_path]
        if len(matches) != 1:
            raise SerializedTimelineError(
                f"serialized node {requested_path!r} matched {len(matches)} nodes"
            )
        return matches[0]

    candidates = []
    for item in bundle.nodes:
        if item.path.lower().endswith(".ress") or len(item.data) < 48:
            continue
        if struct.unpack_from(">I", item.data, 8)[0] == 22:
            candidates.append(item)
    if len(candidates) != 1:
        raise SerializedTimelineError(
            f"expected one SerializedFile v22 node, found {len(candidates)}"
        )
    return candidates[0]


def extract_timeline_manifest(
    bundle_path: Path, *, node_path: str | None = None
) -> dict[str, Any]:
    bundle = read_unityfs(bundle_path)
    node = _choose_serialized_node(bundle, node_path)
    serialized = parse_serialized_file(node.data)
    return build_timeline_manifest(
        serialized,
        bundle=bundle,
        bundle_path=bundle_path,
        node=node,
    )


def _parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="NAPS/UnityFS SpotMonster bundle")
    parser.add_argument(
        "--node",
        help="exact UnityFS node path; auto-detected when the bundle has one CAB",
    )
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        manifest = extract_timeline_manifest(args.bundle, node_path=args.node)
    except (OSError, SerializedTimelineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    json.dump(manifest, sys.stdout, ensure_ascii=False, indent=args.indent)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
