import json
import sqlite3
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

try:
    from cryptography.hazmat.decrepit.ciphers.modes import OFB
except ImportError:
    from cryptography.hazmat.primitives.ciphers.modes import OFB

from DataPipeline.crawler.addressables_nkdb import (
    NKDBError,
    cached_bundle_path,
    decode_nkdb,
    open_nkdb,
    resolve_addressable,
)
from DataPipeline.crawler.memorypack_decode import SCHEMAS
from DataPipeline.crawler.staticdata_challenge_behavior import (
    BehaviorCatalogError,
    BehaviorDocument,
    _normalize_skill,
    _normalize_task_graph,
    _id,
    _select_challenge_entries,
    extract_behavior_documents,
    write_catalog,
)
from DataPipeline.crawler.unityfs_minimal import (
    UnityFSBundle,
    UnityFSError,
    UnityFSNode,
    decompress_lz4_block,
    parse_unityfs,
)


def _encrypt_nkdb(sqlite_image, segment_size=1024, *, trailing_zlib=False):
    key = bytes(range(16))
    chunks = [
        sqlite_image[offset : offset + segment_size]
        for offset in range(0, len(sqlite_image), segment_size)
    ]
    compressed = [zlib.compress(chunk) for chunk in chunks]
    if trailing_zlib:
        compressed[-1] += b"trailing"
    count = len(compressed)
    width = 5 if segment_size * count > 0xFFFFFFFF else 4
    first_offset = 32 + (count + 1) * width
    offsets = [first_offset]
    for chunk in compressed:
        offsets.append(offsets[-1] + len(chunk))
    encrypted = []
    for index, (offset, chunk) in enumerate(zip(offsets, compressed)):
        iv = struct.pack("<II", index, offset) + bytes(8)
        encryptor = Cipher(algorithms.AES(key), OFB(iv)).encryptor()
        encrypted.append(encryptor.update(chunk) + encryptor.finalize())
    header = (
        b"NKDB"
        + struct.pack(">I", 1)
        + key
        + struct.pack(">II", segment_size, count)
        + b"".join(value.to_bytes(width, "big") for value in offsets)
    )
    return header + b"".join(encrypted)


def _catalog_sqlite(bundle_size):
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE keys(key TEXT);
        CREATE TABLE key_entries(key_rowid INTEGER, entry_rowid INTEGER);
        CREATE TABLE entries(
          internal_id_rowid INTEGER, provider_id_rowid INTEGER,
          type_rowid INTEGER, primary_key_rowid INTEGER,
          dependency_key_rowid INTEGER, dependency_hash INTEGER,
          data_rowid INTEGER, quality_texture INTEGER, quality_mesh INTEGER
        );
        CREATE TABLE entry_data(
          type_rowid INTEGER, hash TEXT, crc INTEGER, timeout INTEGER,
          chunked_transfer INTEGER, redirect_limit INTEGER, retry_count INTEGER,
          bundle_name TEXT, asset_load_mode INTEGER, bundle_size INTEGER,
          use_crc_cache INTEGER, uwr_local INTEGER,
          clear_other_cache_version INTEGER
        );
        CREATE TABLE internal_ids(internal_id TEXT);
        CREATE TABLE provider_ids(provider_id TEXT);
        CREATE TABLE types(assembly_name TEXT, class_name TEXT);
        """
    )
    asset_key = "ExternalBehavior/spot/bt_test"
    bundle_hash = "0123456789abcdef0123456789abcdef"
    bundle_key = f"externalbehavior_assets_all_{bundle_hash}.bundle"
    connection.executemany(
        "INSERT INTO keys(rowid,key) VALUES (?,?)",
        [(1, asset_key), (2, bundle_key)],
    )
    connection.executemany(
        "INSERT INTO key_entries(key_rowid,entry_rowid) VALUES (?,?)",
        [(1, 1), (2, 2)],
    )
    connection.executemany(
        "INSERT INTO internal_ids(rowid,internal_id) VALUES (?,?)",
        [(1, "asset-id"), (2, "bundle-internal-id")],
    )
    connection.executemany(
        "INSERT INTO provider_ids(rowid,provider_id) VALUES (?,?)",
        [
            (
                1,
                "UnityEngine.ResourceManagement.ResourceProviders.BundledAssetProvider",
            ),
            (
                2,
                "UnityEngine.ResourceManagement.ResourceProviders.AssetBundleProvider",
            ),
        ],
    )
    connection.executemany(
        "INSERT INTO types(rowid,assembly_name,class_name) VALUES (?,?,?)",
        [
            (1, "BehaviorDesigner.Unity.Runtime", "BehaviorDesigner.Runtime.ExternalBehaviorTree"),
            (
                2,
                "Unity.ResourceManager",
                "UnityEngine.ResourceManagement.ResourceProviders.IAssetBundleResource",
            ),
        ],
    )
    connection.execute(
        "INSERT INTO entries(rowid,internal_id_rowid,provider_id_rowid,type_rowid,"
        "primary_key_rowid,dependency_key_rowid,dependency_hash,data_rowid,"
        "quality_texture,quality_mesh) VALUES (1,1,1,1,1,2,0,0,0,0)"
    )
    connection.execute(
        "INSERT INTO entries(rowid,internal_id_rowid,provider_id_rowid,type_rowid,"
        "primary_key_rowid,dependency_key_rowid,dependency_hash,data_rowid,"
        "quality_texture,quality_mesh) VALUES (2,2,2,2,2,0,0,1,0,0)"
    )
    connection.execute(
        "INSERT INTO entry_data(rowid,type_rowid,hash,crc,timeout,chunked_transfer,"
        "redirect_limit,retry_count,bundle_name,asset_load_mode,bundle_size,"
        "use_crc_cache,uwr_local,clear_other_cache_version) "
        "VALUES (1,2,?,0,0,0,0,0,'bundle-name',0,?,0,0,0)",
        (bundle_hash, bundle_size),
    )
    return connection.serialize()


def _unityfs(node_data, *, padding=True, at_end=False):
    node_name = b"CAB-test\0"
    metadata = (
        bytes(16)
        + struct.pack(">I", 1)
        + struct.pack(">IIH", len(node_data), len(node_data), 0)
        + struct.pack(">IQQI", 1, 0, len(node_data), 0)
        + node_name
    )
    flags = 0x40 | (0x200 if padding else 0) | (0x80 if at_end else 0)

    def header(file_size):
        return (
            b"UnityFS\0"
            + struct.pack(">I", 8)
            + b"5.x.x\0"
            + b"2021.3.test\0"
            + struct.pack(">QIII", file_size, len(metadata), len(metadata), flags)
        )

    base = header(0)
    base += bytes((-len(base)) % 16)
    if at_end:
        result = base + node_data + metadata
    else:
        payload_offset = len(base) + len(metadata)
        if padding:
            payload_offset = (payload_offset + 15) // 16 * 16
        result = base + metadata + bytes(payload_offset - len(base) - len(metadata)) + node_data
    fixed = header(len(result))
    fixed += bytes((-len(fixed)) % 16)
    return fixed + result[len(base) :]


class NKDBTests(unittest.TestCase):
    def test_exact_fk_and_cache_hash_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle_hash = "0123456789abcdef0123456789abcdef"
            bundle_bytes = b"UnityFS\0"
            naps = root / "naps"
            bundle_path = naps / bundle_hash[:2] / bundle_hash
            bundle_path.parent.mkdir(parents=True)
            bundle_path.write_bytes(bundle_bytes)
            catalog_path = root / "core_test_catalog.db"
            catalog_path.write_bytes(
                _encrypt_nkdb(_catalog_sqlite(len(bundle_bytes)))
            )

            with open_nkdb(catalog_path) as catalog:
                resolution = resolve_addressable(
                    catalog,
                    "ExternalBehavior/spot/bt_test",
                    expected_class="BehaviorDesigner.Runtime.ExternalBehaviorTree",
                )
                self.assertIsNotNone(resolution)
                self.assertEqual(bundle_hash, resolution.bundle_hash)
                self.assertEqual(bundle_path, cached_bundle_path(naps, resolution))
                self.assertIsNone(
                    resolve_addressable(catalog, "ExternalBehavior/spot/missing")
                )

    def test_rejects_non_monotonic_offsets(self):
        encrypted = bytearray(_encrypt_nkdb(_catalog_sqlite(8)))
        encrypted[36:40] = encrypted[32:36]
        with self.assertRaises(NKDBError):
            decode_nkdb(bytes(encrypted))

    def test_rejects_trailing_zlib_bytes(self):
        encrypted = _encrypt_nkdb(_catalog_sqlite(8), trailing_zlib=True)
        with self.assertRaises(NKDBError):
            decode_nkdb(encrypted)


class UnityFSTests(unittest.TestCase):
    def test_raw_lz4_literal_and_match(self):
        self.assertEqual(b"hello", decompress_lz4_block(b"\x50hello", 5))
        self.assertEqual(
            b"abcabcabc",
            decompress_lz4_block(b"\x32abc\x03\x00", 9),
        )
        with self.assertRaises(UnityFSError):
            decompress_lz4_block(b"\x10a\x00\x00", 5)

    def test_unityfs_blocks_info_and_payload_alignment(self):
        bundle = parse_unityfs(_unityfs(b"serialized-node", padding=True))
        self.assertEqual("2021.3.test", bundle.unity_revision)
        self.assertEqual(1, len(bundle.nodes))
        self.assertEqual("CAB-test", bundle.nodes[0].path)
        self.assertEqual(b"serialized-node", bundle.nodes[0].data)

    def test_unityfs_blocks_info_at_end(self):
        bundle = parse_unityfs(
            _unityfs(b"serialized-node", padding=True, at_end=True)
        )
        self.assertEqual(b"serialized-node", bundle.nodes[0].data)

    def test_unityfs_rejects_unknown_archive_flags(self):
        raw = bytearray(_unityfs(b"serialized-node", padding=True))
        flags_offset = (
            len(b"UnityFS\0")
            + 4
            + len(b"5.x.x\0")
            + len(b"2021.3.test\0")
            + 8
            + 4
            + 4
        )
        flags = struct.unpack_from(">I", raw, flags_offset)[0]
        struct.pack_into(">I", raw, flags_offset, flags | 0x400)
        with self.assertRaises(UnityFSError):
            parse_unityfs(bytes(raw))


class BehaviorGraphTests(unittest.TestCase):
    def test_focused_season_selection_is_exact_and_noncanonical(self):
        challenge = {
            "entries": [{"season": str(index)} for index in range(1, 40)]
        }
        selected, targeted = _select_challenge_entries(challenge, 39)
        self.assertTrue(targeted)
        self.assertEqual(["39"], [item["season"] for item in selected])

        full, targeted = _select_challenge_entries(challenge, None)
        self.assertFalse(targeted)
        self.assertEqual(39, len(full))

        for invalid in (True, 0, 40):
            with self.assertRaises(BehaviorCatalogError):
                _select_challenge_entries(challenge, invalid)

    @staticmethod
    def _tree():
        attack = {
            "Type": "NK.Spot.BehaviorTree.Monster.Actions.Attack",
            "NodeData": {"Comment": "active"},
            "ID": 4,
            "Name": "Attack",
            "Instant": True,
            "SkillAniNumberTypemSkillAniNumber": "Shot_01",
        }
        disabled_attack = dict(attack, ID=6, NodeData={"Comment": "disabled"})
        detached_attack = dict(attack, ID=7, NodeData={"Comment": "detached"})
        return {
            "EntryTask": {
                "Type": "BehaviorDesigner.Runtime.Tasks.EntryTask",
                "ID": 0,
                "Name": "Entry",
                "Instant": True,
            },
            "RootTask": {
                "Type": "NK.Spot.BehaviorTree.Monster.Composites.InitVariables",
                "ID": 1,
                "Name": "Init Variables",
                "Instant": True,
                "Children": [
                    {
                        "Type": "BehaviorDesigner.Runtime.Tasks.Sequence",
                        "ID": 2,
                        "Name": "Sequence",
                        "Instant": True,
                        "Children": [
                            {
                                "Type": "NK.Spot.BehaviorTree.Monster.Actions.TimeCount",
                                "ID": 3,
                                "Name": "Time Count",
                                "Instant": False,
                                "ETimeCountTypemType": "Custom",
                                "SinglemCustomTime": 1.25,
                            },
                            attack,
                            {
                                "Type": "BehaviorDesigner.Runtime.Tasks.Sequence",
                                "ID": 5,
                                "Name": "Disabled",
                                "Instant": True,
                                "Disabled": True,
                                "Children": [disabled_attack],
                            },
                        ],
                    }
                ],
            },
            "DetachedTasks": [detached_attack],
        }

    def test_graph_scope_excludes_detached_and_disabled(self):
        raw_json = json.dumps(self._tree(), separators=(",", ":")).encode()
        document = BehaviorDocument(
            asset_internal_id="0" * 32,
            name="bt_test",
            path_id=1,
            source_offset=0,
            raw_json_size=len(raw_json),
            raw_json_sha256="0" * 64,
            tree=self._tree(),
        )
        graph, sites, stats = _normalize_task_graph(
            document, {"Shot_01": [{"skill_id": "100"}]}
        )
        self.assertEqual([7], graph["detached_root_ids"])
        self.assertEqual(3, len(sites))
        active = [
            site
            for site in sites
            if site["active_graph"] and site["effective_enabled"]
        ]
        self.assertEqual([4], [site["node_id"] for site in active])
        self.assertEqual(1, stats["active_shot_reference_count"])
        timer = next(node for node in graph["nodes"] if node["id"] == 3)
        self.assertEqual("1.25", timer["timer"]["seconds_decimal"])
        self.assertIsNone(timer["completion_to_next_dispatch"]["update_ticks"])

    def test_exact_id_and_task_bools_reject_schema_drift(self):
        for value in (1.9, "1.9", True, "01"):
            with self.assertRaises(BehaviorCatalogError):
                _id(value, "test")
        tree = self._tree()
        tree["RootTask"]["Instant"] = "true"
        document = BehaviorDocument(
            asset_internal_id="0" * 32,
            name="bt_test",
            path_id=1,
            source_offset=0,
            raw_json_size=1,
            raw_json_sha256="0" * 64,
            tree=tree,
        )
        with self.assertRaises(BehaviorCatalogError):
            _normalize_task_graph(document, {})

    def test_monster_skill_centiseconds_are_integer_frames(self):
        defaults = {
            name: (
                []
                if type_name.endswith("[]")
                else ""
                if type_name == "string"
                else False
                if type_name == "bool"
                else 0
            )
            for name, type_name in SCHEMAS["MonsterSkillData"]
        }
        defaults.update(
            {
                "id": 100,
                "skill_ani_number": 1,
                "casting_time": 50,
                "delay_time": 25,
            }
        )
        skill = _normalize_skill(defaults)
        self.assertEqual(30, skill["timing"]["casting_frames_60fps"])
        self.assertEqual(15, skill["timing"]["delay_frames_60fps"])

    def test_decrypted_output_cannot_escape_ignored_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "staticdata"
            outside = Path(temporary) / "tracked.json"
            with self.assertRaises(BehaviorCatalogError):
                write_catalog({"secret": True}, outside, static_root=root)
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
