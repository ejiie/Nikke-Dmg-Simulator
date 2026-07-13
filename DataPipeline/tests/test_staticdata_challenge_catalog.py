import contextlib
import hashlib
import io
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from DataPipeline.crawler.memorypack_decode import SCHEMAS
from DataPipeline.crawler.staticdata_challenge_catalog import (
    CatalogError,
    build_catalog,
    main,
    write_catalog,
)


def _default_value(type_name):
    if type_name.endswith("[]"):
        return []
    if type_name == "string":
        return ""
    if type_name == "bool":
        return False
    if type_name in {"int", "long", "enum", "float", "double"}:
        return 0
    if type_name.startswith("@"):
        return {}
    raise AssertionError(type_name)


def _encode_string(value):
    if value is None:
        return struct.pack("<i", -1)
    if value == "":
        return struct.pack("<i", 0)
    raw = value.encode("utf-8")
    return struct.pack("<ii", ~len(raw), len(value)) + raw


def _encode_value(type_name, value):
    if type_name.endswith("[]"):
        inner = type_name[:-2]
        if value is None:
            return struct.pack("<i", -1)
        return struct.pack("<i", len(value)) + b"".join(
            _encode_value(inner, item) for item in value
        )
    if type_name.startswith("@"):
        return _encode_object(type_name[1:], value)
    if type_name in {"int", "enum"}:
        return struct.pack("<i", value)
    if type_name == "long":
        return struct.pack("<q", value)
    if type_name == "float":
        return struct.pack("<f", value)
    if type_name == "double":
        return struct.pack("<d", value)
    if type_name == "bool":
        return struct.pack("<B", int(value))
    if type_name == "string":
        return _encode_string(value)
    raise AssertionError(type_name)


def _encode_object(schema_name, values):
    schema = SCHEMAS[schema_name]
    payload = [struct.pack("<B", len(schema))]
    for name, type_name in schema:
        payload.append(_encode_value(type_name, values.get(name, _default_value(type_name))))
    return b"".join(payload)


def _encode_table(schema_name, rows):
    return struct.pack("<i", len(rows)) + b"".join(
        _encode_object(schema_name, row) for row in rows
    )


class CatalogFixture:
    def __init__(self, static_root):
        self.static_root = static_root
        static_root.mkdir(parents=True)

    @staticmethod
    def _preset(row_id, group, difficulty, wave):
        return {
            "Id": row_id,
            "Preset_group_id": group,
            "Difficulty_type": difficulty,
            "Wave_order": 8 if difficulty == 2 else 1,
            "Wave": wave,
            "Monster_stage_lv": 390 if difficulty == 2 else 200,
            "Monster_stage_lv_change_group": group,
            "Spot_autocontrol": True,
            "Wave_name": f"name_{row_id}",
            "Wave_description": f"description_{row_id}",
            "Monster_image_si": f"si_{row_id}",
            "Monster_image": f"full_{row_id}",
        }

    @staticmethod
    def _wave(stage, monster_id, *, ambiguous=False):
        target_list = [monster_id]
        monster_list = [{"wave_monster_id": monster_id, "spawn_type": 1}]
        if ambiguous:
            target_list.append(9999)
            monster_list.append({"wave_monster_id": 9999, "spawn_type": 1})
        return {
            "stage_id": stage,
            "group_id": "wave_test",
            "spot_mod": 17,
            "battle_time": 180,
            "target_list": target_list,
            "wave_data": [
                {
                    "wave_path": f"path_{stage}",
                    "private_monster_count": -1,
                    "wave_monster_list": monster_list,
                }
            ],
            "far_monster_count": 1,
        }

    @staticmethod
    def _monster(monster_id, spot_ai):
        return {
            "id": monster_id,
            "monster_model_id": monster_id // 10,
            "spot_ai": spot_ai,
            "spot_ai_defense": spot_ai,
            "spot_ai_basedefense": spot_ai,
            "skill_data": [
                {
                    "skill_id": monster_id + 100,
                    "use_function_id_skill": [],
                    "hurt_function_id_skill": [],
                }
            ],
            "statenhance_id": 230000,
        }

    def write_zip(self, *, ambiguous=False, wave_member_drift=False, invalid_spot_utf8=False):
        managers = [
            {"Id": 101, "Monster_preset": 1001, "Ranking_group_id": 1},
            {"Id": 102, "Monster_preset": 1002, "Ranking_group_id": 2},
        ]
        presets = [
            self._preset(10011, 1001, 1, 6700101),
            self._preset(10012, 1001, 2, 6700102),
            self._preset(10022, 1002, 2, 6700202),
        ]
        waves = [
            self._wave(6700102, 9001, ambiguous=ambiguous),
            self._wave(6700202, 9002),
        ]
        wave_raw = bytearray(_encode_table("WaveData", waves))
        if wave_member_drift:
            wave_raw[4] = 19
        monster_raw = _encode_table(
            "MonsterData",
            [self._monster(9001, "bt_test_one"), self._monster(9002, "bt_test_two")],
        )
        if invalid_spot_utf8:
            monster_raw = monster_raw.replace(b"bt_test_one", b"\xfft_test_one", 1)
        payloads = {
            "SoloRaidManagerTable.mpk": _encode_table("SoloRaidManagerData", managers),
            "SoloRaidPresetTable.mpk": _encode_table("SoloRaidPresetData", presets),
            "WaveData.GroupDict.csv": (
                b"stage_id,group_id\n6700102,wave_test\n6700202,wave_test\n"
            ),
            "WaveDataTable.wave_test.mpk": bytes(wave_raw),
            "MonsterTable.mpk": monster_raw,
        }
        with zipfile.ZipFile(self.static_root / "StaticData.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for name, payload in payloads.items():
                z.writestr(name, payload)


class StaticDataChallengeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.static_root = Path(self.temp.name) / "staticdata"
        self.fixture = CatalogFixture(self.static_root)
        self.fixture.write_zip()

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        return build_catalog(
            self.static_root,
            expected_challenge_rows=2,
            expected_scope_digest=None,
        )

    def test_exact_challenge_mapping_and_digest(self):
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        self.assertEqual(first["coverage"]["denominator"], 2)
        self.assertEqual(first["coverage"]["monster_spot_ai_exact"], 2)
        self.assertEqual(
            [(row["season"], row["exact_boss_monster_id"], row["spot_ai"]["normal"])
             for row in first["entries"]],
            [("1", "9001", "bt_test_one"), ("2", "9002", "bt_test_two")],
        )
        mapping = b"1|6700102|9001|bt_test_one\n2|6700202|9002|bt_test_two\n"
        self.assertEqual(first["mapping_digest_sha256"], hashlib.sha256(mapping).hexdigest())

    def test_ambiguous_target_spawn_intersection_preserves_old_catalog(self):
        catalog = self.build()
        output = self.static_root / "assembled" / "solo_raid_challenge_catalog.json"
        write_catalog(catalog, output, static_root=self.static_root)
        previous = output.read_bytes()

        self.fixture.write_zip(ambiguous=True)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(["--static-root", str(self.static_root)])
        self.assertEqual(exit_code, 1)
        self.assertEqual(output.read_bytes(), previous)

    def test_wave_member_count_drift_is_rejected(self):
        self.fixture.write_zip(wave_member_drift=True)
        with self.assertRaisesRegex(CatalogError, "memberCount drift"):
            self.build()

    def test_invalid_utf8_in_authoritative_string_is_rejected(self):
        self.fixture.write_zip(invalid_spot_utf8=True)
        with self.assertRaisesRegex(CatalogError, "MemoryPack decode 실패"):
            self.build()

    def test_output_cannot_escape_ignored_assembled_boundary(self):
        catalog = self.build()
        with self.assertRaises(CatalogError):
            write_catalog(
                catalog,
                Path(self.temp.name) / "outside.json",
                static_root=self.static_root,
            )

    def test_approved_production_scope_cannot_silently_shrink(self):
        with self.assertRaisesRegex(
            CatalogError,
            "approved Challenge scope row count drift: expected=39 actual=2",
        ):
            build_catalog(self.static_root)

    def test_atomic_replace_failure_preserves_old_catalog_and_cleans_temp(self):
        output = self.static_root / "assembled" / "solo_raid_challenge_catalog.json"
        write_catalog(self.build(), output, static_root=self.static_root)
        previous = output.read_bytes()
        with mock.patch(
            "DataPipeline.crawler.staticdata_challenge_catalog.os.replace",
            side_effect=OSError("injected replace failure"),
        ):
            with self.assertRaises(OSError):
                write_catalog(self.build(), output, static_root=self.static_root)
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(list(output.parent.glob(f".{output.name}.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
