import hashlib
import struct
import unittest
from pathlib import Path

from DataPipeline.crawler.unity_serialized_timeline import (
    ObjectInfo,
    ScriptTypeRef,
    SerializedFile,
    SerializedType,
    build_timeline_manifest,
)
from DataPipeline.crawler.unityfs_minimal import UnityFSBundle, UnityFSNode


def _aligned_string(value):
    raw = value.encode("utf-8")
    result = struct.pack("<i", len(raw)) + raw
    return result + bytes((-len(result)) % 4)


def _pptr(path_id=0, file_id=0):
    return struct.pack("<iq", file_id, path_id)


def _mono_base(script_path, name, *, game_object=0):
    return (
        _pptr(game_object)
        + b"\x01\x00\x00\x00"
        + _pptr(script_path)
        + _aligned_string(name)
    )


def _mono_script(path_id, class_name, namespace, assembly):
    payload = (
        _aligned_string(class_name)
        + struct.pack("<i", 0)
        + bytes.fromhex("00112233445566778899aabbccddeeff")
        + _aligned_string(class_name)
        + _aligned_string(namespace)
        + _aligned_string(assembly)
    )
    return path_id, payload


def _timeline(script_path, name, tracks, duration):
    return (
        _mono_base(script_path, name)
        + struct.pack("<i", 0)
        + struct.pack("<i", len(tracks))
        + b"".join(_pptr(path_id) for path_id in tracks)
        + struct.pack("<dd", duration, 60.0)
        + b"\x01\x00\x00\x00"
        + struct.pack("<i", 1)
        + _pptr()
    )


def _signal_track(script_path, parent, marker):
    return (
        _mono_base(script_path, "NK Spot Monster Signal Track")
        + struct.pack("<i", 3)
        + _pptr()
        + b"\x00\x00\x00\x00"  # m_Locked + alignment
        + b"\x00\x00\x00\x00"  # m_Muted + alignment
        + _aligned_string("")
        + _pptr()  # m_Curves
        + _pptr(parent)
        + struct.pack("<i", 0)  # m_Children
        + struct.pack("<i", 0)  # m_Clips
        + struct.pack("<i", 1)
        + _pptr(marker)
    )


def _attack_marker(script_path, time_seconds):
    return (
        _mono_base(script_path, "SpotMonster/Attack")
        + struct.pack("<dii", time_seconds, 0, 0)
    )


def _playable_director(owner, timeline):
    return (
        _pptr(owner)
        + b"\x01\x00\x00\x00"
        + _pptr(timeline)
        + struct.pack("<iiid", 0, 2, 1, 0.0)
        + struct.pack("<i", 0)  # m_SceneBindings
        + struct.pack("<i", 0)  # m_ExposedReferences
    )


def _game_object(name, components):
    return (
        struct.pack("<i", len(components))
        + b"".join(_pptr(item) for item in components)
        + struct.pack("<I", 0)
        + _aligned_string(name)
        + struct.pack("<HB", 0, 1)
    )


def _monster_timeline_data(script_path, owner, model_director, ani_numbers):
    return (
        _mono_base(script_path, "", game_object=owner)
        + struct.pack("<ii", 1, 23)
        + _pptr()  # cutSceneOption
        + _pptr(model_director)
        + _pptr()  # skillOption
        + struct.pack("<i", len(ani_numbers))
        + b"".join(struct.pack("<i", item) for item in ani_numbers)
        + b"\x00\x00\x00\x00"  # disable + alignment
    )


def _serialized_type(class_id, script_index=-1, *, old_type_hash=bytes(16)):
    return SerializedType(
        class_id=class_id,
        is_stripped_type=False,
        script_type_index=script_index,
        script_id=bytes(16) if class_id == 114 else None,
        old_type_hash=old_type_hash,
        nodes=(),
        string_buffer=b"",
        dependencies=(),
    )


class UnitySerializedTimelineTests(unittest.TestCase):
    def test_monster_anim_controller_proves_shot_time_is_not_serialized(self):
        script_path = 9_300_000_000_000_001
        controller_path = -9_300_000_000_000_001
        animator_path = -9_300_000_000_000_002
        runtime_controller_path = -9_300_000_000_000_003
        animator_payload = (
            _pptr()
            + b"\x01\x00\x00\x00"
            + _pptr()
            + _pptr(runtime_controller_path)
            + struct.pack("<ii", 0, 0)
            + bytes([0, 0, 0, 1, 1, 1, 0, 0])
        )
        controller_payload = (
            _mono_base(script_path, "", game_object=0)
            + struct.pack("<i", 1)
            + _pptr(animator_path)
            + struct.pack("<i", 0)
            + b"\x01\x00\x00\x00"
        )
        payloads = [
            _mono_script(
                script_path,
                "MonsterAnimController",
                "NK.Spot.Monster.Animation",
                "NK.Runtime.dll",
            ),
            (animator_path, 2, animator_payload),
            (runtime_controller_path, 3, _aligned_string("ebg001_animator")),
            (controller_path, 1, controller_payload),
        ]
        normalized = [(payloads[0][0], 0, payloads[0][1]), *payloads[1:]]
        data = bytearray()
        objects = []
        for path_id, type_id, payload in normalized:
            data.extend(bytes((-len(data)) % 8))
            byte_start = len(data)
            data.extend(payload)
            objects.append(ObjectInfo(path_id, byte_start, len(payload), type_id))
        sf = SerializedFile(
            data=bytes(data),
            format_version=22,
            unity_version="2021.3.synthetic",
            target_platform=19,
            endian="<",
            metadata_size=0,
            data_offset=0,
            types=(
                _serialized_type(115),
                _serialized_type(
                    114,
                    0,
                    old_type_hash=bytes.fromhex(
                        "73787b534c8d2f3133afab8ee9d5f178"
                    ),
                ),
                _serialized_type(95),
                _serialized_type(91),
            ),
            objects=tuple(objects),
            script_types=(ScriptTypeRef(0, script_path),),
            metadata_consumed=0,
        )
        node = UnityFSNode("CAB-synthetic", 0, len(data), 4, bytes(data))
        bundle = UnityFSBundle(
            format_version=8,
            unity_version="5.x.x",
            unity_revision="2021.3.synthetic",
            flags=0x243,
            sha256=hashlib.sha256(data).hexdigest(),
            nodes=(node,),
        )
        manifest = build_timeline_manifest(
            sf,
            bundle=bundle,
            bundle_path=Path("C:/private/cache/deadbeef"),
            node=node,
        )

        self.assertEqual(1, manifest["counts"]["monster_anim_controllers"])
        decoded = manifest["monster_anim_controllers"][0]
        self.assertFalse(decoded["serialized_shot_time_present"])
        self.assertEqual(32, decoded["field_offsets"]["mAnimatorList"])
        self.assertEqual(48, decoded["field_offsets"]["animEventTriggers"])
        self.assertEqual(52, decoded["field_offsets"]["isUpdateParameter"])
        self.assertEqual(
            str(runtime_controller_path),
            decoded["animators"][0]["controller"]["path_id"],
        )
        self.assertEqual(
            "ebg001_animator",
            decoded["animators"][0]["controller_object"]["name"],
        )

    def test_ani_number_route_is_authoritative_over_timeline_name(self):
        # Deliberately route Shot_08/09/10 to a top timeline labelled Shot_10
        # and a model timeline labelled Shot_06.  A name-regex join would lose
        # Shot_08 and bind Shot_09 to the wrong asset.
        timeline_script = 9_100_000_000_000_001
        marker_script = 9_100_000_000_000_002
        signal_script = 9_100_000_000_000_003
        data_script = 9_100_000_000_000_004
        top_timeline = -9_200_000_000_000_001
        model_timeline = -9_200_000_000_000_002
        signal_track = -9_200_000_000_000_003
        attack_marker = -9_200_000_000_000_004
        owner = -9_200_000_000_000_005
        top_director = -9_200_000_000_000_006
        model_director = -9_200_000_000_000_007
        timeline_data = -9_200_000_000_000_008

        payloads = []
        for item in (
            _mono_script(
                timeline_script, "TimelineAsset", "UnityEngine.Timeline", "Unity.Timeline.dll"
            ),
            _mono_script(
                marker_script,
                "NKSpotMonsterAttackMarker",
                "NK.Spot.Presentation.Timeline",
                "NK.Runtime.dll",
            ),
            _mono_script(
                signal_script,
                "NKSpotMonsterSignalTrack",
                "NK.Spot.Presentation.Timeline",
                "NK.Runtime.dll",
            ),
            _mono_script(
                data_script,
                "MonsterTimeLineData",
                "NK.Spot.Monster.Timeline",
                "NK.Runtime.dll",
            ),
        ):
            payloads.append((item[0], 0, item[1]))
        payloads.extend(
            [
                (
                    top_timeline,
                    1,
                    _timeline(
                        timeline_script,
                        "synthetic_hsta_shot_10_attackall",
                        [signal_track],
                        6.0,
                    ),
                ),
                (
                    model_timeline,
                    1,
                    _timeline(
                        timeline_script,
                        "synthetic_shot_06_attackall_model",
                        [],
                        0.0,
                    ),
                ),
                (
                    signal_track,
                    2,
                    _signal_track(signal_script, top_timeline, attack_marker),
                ),
                (attack_marker, 3, _attack_marker(marker_script, 5.0)),
                (owner, 6, _game_object("synthetic_route", [top_director])),
                (top_director, 5, _playable_director(owner, top_timeline)),
                (model_director, 5, _playable_director(0, model_timeline)),
                (
                    timeline_data,
                    4,
                    _monster_timeline_data(
                        data_script, owner, model_director, [8, 9, 10]
                    ),
                ),
            ]
        )

        data = bytearray()
        objects = []
        for path_id, type_id, payload in payloads:
            data.extend(bytes((-len(data)) % 8))
            byte_start = len(data)
            data.extend(payload)
            objects.append(ObjectInfo(path_id, byte_start, len(payload), type_id))

        sf = SerializedFile(
            data=bytes(data),
            format_version=22,
            unity_version="2021.3.synthetic",
            target_platform=19,
            endian="<",
            metadata_size=0,
            data_offset=0,
            types=(
                _serialized_type(115),
                _serialized_type(114, 0),  # TimelineAsset
                _serialized_type(114, 2),  # SignalTrack
                _serialized_type(114, 1),  # AttackMarker
                _serialized_type(114, 3),  # MonsterTimeLineData
                _serialized_type(320),
                _serialized_type(1),
            ),
            objects=tuple(objects),
            script_types=(
                ScriptTypeRef(0, timeline_script),
                ScriptTypeRef(0, marker_script),
                ScriptTypeRef(0, signal_script),
                ScriptTypeRef(0, data_script),
            ),
            metadata_consumed=0,
        )
        node = UnityFSNode("CAB-synthetic", 0, len(data), 4, bytes(data))
        bundle = UnityFSBundle(
            format_version=8,
            unity_version="5.x.x",
            unity_revision="2021.3.synthetic",
            flags=0x243,
            sha256=hashlib.sha256(data).hexdigest(),
            nodes=(node,),
        )
        manifest = build_timeline_manifest(
            sf,
            bundle=bundle,
            bundle_path=Path("C:/private/cache/deadbeef"),
            node=node,
        )

        self.assertEqual(manifest["counts"]["monster_timeline_route_groups"], 1)
        self.assertEqual(manifest["counts"]["routed_ani_numbers"], 3)
        route = manifest["ani_number_route_groups"][0]
        self.assertEqual(route["ani_numbers"], [8, 9, 10])
        self.assertEqual(route["top_timeline"]["name"], "synthetic_hsta_shot_10_attackall")
        self.assertEqual(route["model_timeline"]["name"], "synthetic_shot_06_attackall_model")
        self.assertEqual(
            route["top_timeline"]["attack_markers"][0]["canonical_60_frame"]["value"],
            300,
        )
        self.assertEqual(manifest["route_group_ids_by_ani_number"]["8"], [str(timeline_data)])
        self.assertNotIn("bundle_path", manifest["source"])
        self.assertEqual(manifest["source"]["cache_key"], "deadbeef")


if __name__ == "__main__":
    unittest.main()
