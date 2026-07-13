import hashlib
import json
import struct
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from DataPipeline.crawler.staticdata_snapshot_manifest import ManifestError, build_manifest, write_manifest


class SnapshotFixture:
    def __init__(self, root: Path):
        self.repo = root / "repo"
        self.nikke = root / "nikke_root"
        self.static = self.repo / "Database" / "raw" / "staticdata"
        self._make_repo_files()
        self._make_nikke_files()
        self._make_staticdata()

    @staticmethod
    def _write(path: Path, data: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    @staticmethod
    def _mp_string(value: str) -> bytes:
        raw = value.encode("utf-8")
        return struct.pack("<ii", ~len(raw), len(value)) + raw

    @classmethod
    def _manager_mpk(cls, rows):
        payload = [struct.pack("<i", len(rows))]
        for row in rows:
            payload.append(
                struct.pack(
                    "<Biii",
                    3,
                    row["Id"],
                    row["Monster_preset"],
                    row["Ranking_group_id"],
                )
            )
        return b"".join(payload)

    @classmethod
    def _preset_mpk(cls, rows):
        payload = [struct.pack("<i", len(rows))]
        for row in rows:
            payload.append(struct.pack("<B", 19))
            for key in (
                "Id",
                "Preset_group_id",
                "Difficulty_type",
                "Quick_battle_type",
                "Character_lv",
                "Wave_open_condition",
                "Wave_order",
                "Wave",
                "Monster_stage_lv",
                "Monster_stage_lv_change_group",
                "Dynamic_object_stage_lv",
                "Cover_stage_lv",
            ):
                payload.append(struct.pack("<i", row[key]))
            payload.append(struct.pack("<B", int(row["Spot_autocontrol"])))
            for key in (
                "Wave_name",
                "Wave_description",
                "Monster_image_si",
                "Monster_image",
            ):
                payload.append(cls._mp_string(row[key]))
            payload.append(struct.pack("<ii", row["First_clear_reward_id"], row["Reward_id"]))
        return b"".join(payload)

    def _make_repo_files(self):
        for rel in (
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
        ):
            self._write(self.repo / rel, rel.encode())
        roledata = self.repo / "Database" / "raw" / "blabla_roledata.json"
        roledata.parent.mkdir(parents=True, exist_ok=True)
        roledata.write_text(json.dumps({"roster": {"1001": {}}}), encoding="utf-8")

    def _make_nikke_files(self):
        game = self.nikke / "NIKKE" / "game"
        data = game / "nikke_Data"
        aa = data / "StreamingAssets" / "aa"
        self._write(game / "GameAssembly.dll", b"game-assembly")
        self._write(data / "ScriptingAssemblies.json", b"{}")
        self._write(data / "il2cpp_data" / "Metadata" / "global-metadata.dat", b"")
        self._write(aa / "catalog.db", b"NKDBcatalog")
        self._write(aa / "catalog.db.nds", b"S" * 96)

        host = {
            "Version": "645",
            "ResourceHosts2": [
                {
                    "relativePath": "https://SECRET_HOST.example/path",
                    "projects": [
                        {"projectName": "core", "relativePath": "SECRET_PROJECT", "catalogMain": "catalog.db"},
                        {"projectName": "dp", "relativePath": "SECRET_PROJECT", "catalogMain": "catalog.db"},
                    ],
                }
            ],
            "KeySets": [{"version": 37, "keys": ["SECRET_AES_KEY", "SECRET_AES_KEY_2"]}],
        }
        settings = {
            "m_AddressablesVersion": "1.22.22",
            "m_buildTarget": "StandaloneWindows64",
            "m_CatalogLocations": [{"InternalId": "https://SECRET_CATALOG.example/signed"}],
            "m_SettingsHash": "SECRET_SETTINGS_HASH",
            "m_ExtraInitializationData": [
                {
                    "m_Id": "HostSettingsInitialization",
                    "m_ObjectType": {"m_ClassName": "NK.Addressable.HostSettingsInitialization"},
                    "m_Data": json.dumps(host),
                },
                {
                    "m_Id": "https://SECRET_INITIALIZER.example/token",
                    "m_ObjectType": {"m_ClassName": "leak@example.test"},
                    "m_Data": "SECRET_UNKNOWN_INITIALIZER",
                },
            ],
        }
        aa.mkdir(parents=True, exist_ok=True)
        (aa / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

        sd_path = data / "StreamingAssets" / "sd.bin"
        sd_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(sd_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, count in (
                ("CampaignChapterTable.json", 1),
                ("CampaignStageTable.json", 2),
                ("CharacterReactionTable.json", 3),
                ("ConfigBattleTable.json", 4),
                ("ConfigGameTable.json", 5),
            ):
                z.writestr(name, json.dumps({"version": "0.0.1", "records": [{}] * count}))

        self._write(
            self.nikke / "Unity" / "com_proximabeta_NIKKE" / "naps" / "00" / "aaa",
            b"UnityFS\0payload",
        )
        self._write(
            self.nikke / "Unity" / "com_proximabeta_NIKKE" / "naps" / "01" / "bbb",
            b"NKAB\x04\0payload",
        )

    def _make_staticdata(self):
        raid = self.static / "raid"
        assembled = self.static / "assembled"
        raid.mkdir(parents=True, exist_ok=True)
        assembled.mkdir(parents=True, exist_ok=True)
        managers = [
            {"Id": 1000001, "Monster_preset": 10001, "Ranking_group_id": 1},
            {"Id": 1000002, "Monster_preset": 10001, "Ranking_group_id": 1},
            {"Id": 1000003, "Monster_preset": 10002, "Ranking_group_id": 2},
        ]
        def preset(row_id, group, difficulty, order, wave, level, change_group, code):
            return {
                "Id": row_id,
                "Preset_group_id": group,
                "Difficulty_type": difficulty,
                "Quick_battle_type": 1,
                "Character_lv": 400 if difficulty == 2 else 0,
                "Wave_open_condition": 0,
                "Wave_order": order,
                "Wave": wave,
                "Monster_stage_lv": level,
                "Monster_stage_lv_change_group": change_group,
                "Dynamic_object_stage_lv": 400 if difficulty == 2 else 200,
                "Cover_stage_lv": 1,
                "Spot_autocontrol": True,
                "Wave_name": f"Locale_System:{code}_name",
                "Wave_description": f"Locale_System:{code}_description",
                "Monster_image_si": f"si_{code}",
                "Monster_image": f"full_{code}",
                "First_clear_reward_id": 0,
                "Reward_id": 0,
            }

        presets = [
            preset(10001001, 10001, 1, 1, 6700101, 200, 0, "boss_one"),
            preset(10001008, 10001, 2, 8, 6700102, 390, 901, "boss_one"),
            preset(10002008, 10002, 2, 8, 6700202, 390, 902, "boss_two"),
        ]
        (raid / "SoloRaidManagerTable.json").write_text(json.dumps(managers), encoding="utf-8")
        (raid / "SoloRaidPresetTable.json").write_text(json.dumps(presets), encoding="utf-8")
        (raid / "solo_raid_boss.json").write_text(
            json.dumps([{"season": 1, "monster_id": 1}, {"season": 2, "monster_id": None}]),
            encoding="utf-8",
        )
        (assembled / "skill_chains.json").write_text(
            json.dumps({"bosses": {"1": {}}, "functions": {}, "state_effects": {}, "character_skills": {}}),
            encoding="utf-8",
        )

        group_csv = "stage_id, group_id\n6700102, wave_Intercept_001\n6700202, wave_Intercept_001\n"
        mpk = struct.pack("<iB", 2, 20)
        entries = {
            "SoloRaidManagerTable.mpk": self._manager_mpk(managers),
            "SoloRaidPresetTable.mpk": self._preset_mpk(presets),
            "WaveData.GroupDict.csv": group_csv.encode(),
            "WaveDataTable.wave_Intercept_001.mpk": mpk,
            "MonsterTable.mpk": struct.pack("<iB", 1, 32),
            "MonsterModelTable.mpk": struct.pack("<iB", 1, 13),
            "MonsterSkillTable.mpk": struct.pack("<iB", 1, 46),
            "MonsterPartsTable.mpk": struct.pack("<iB", 1, 23),
            "MonsterStatEnhanceTable.mpk": struct.pack("<iB", 1, 12),
            "MonsterStageLvChangeTable.mpk": struct.pack("<iB", 1, 10),
            "FunctionTable.mpk": struct.pack("<iB", 1, 55),
            "StateEffectTable.mpk": struct.pack("<iB", 1, 5),
        }
        with zipfile.ZipFile(self.static / "StaticData.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for name, payload in entries.items():
                z.writestr(name, payload)


class StaticDataSnapshotManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = SnapshotFixture(Path(self.temp.name))
        self.when_a = datetime(2026, 7, 12, 0, 0, tzinfo=timezone.utc)
        self.when_b = datetime(2026, 7, 12, 1, 0, tzinfo=timezone.utc)
        self.rebuilt_catalog = None

    def tearDown(self):
        self.temp.cleanup()

    def build(self, when):
        kwargs = {
            "repo_root": self.fixture.repo,
            "nikke_root": self.fixture.nikke,
            "static_root": self.fixture.static,
            "generated_at": when,
            "include_cache": True,
            "expected_challenge_rows": 2,
            "expected_scope_digest": None,
        }
        if self.rebuilt_catalog is None:
            return build_manifest(**kwargs)
        with mock.patch(
            "DataPipeline.crawler.staticdata_snapshot_manifest._rebuild_challenge_catalog",
            return_value=self.rebuilt_catalog,
        ):
            return build_manifest(**kwargs)

    @staticmethod
    def _canonical_bytes(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def install_exact_catalog(self):
        source_manifest = self.build(self.when_a)
        entries = []
        for index, row in enumerate(source_manifest["challenge"]["entries"], 1):
            boss_id = str(9000 + index)
            spot = f"bt_challenge_{index}"
            entries.append(
                {
                    "season": row["season"],
                    "manager_ids": row["manager_ids"],
                    "preset_id": row["preset_id"],
                    "preset_group_id": row["preset_group_id"],
                    "difficulty_type": 2,
                    "wave_id": row["wave_id"],
                    "wave_group_id": row["wave_group_id"],
                    "wave_archive_entry": row["wave_archive_entry"],
                    "wave_record": {
                        "stage_id": row["wave_id"],
                        "spot_mod": 17,
                        "battle_time": 180,
                        "target_monster_ids": [boss_id],
                        "spawned_monster_ids": [boss_id],
                        "boss_candidates": [boss_id],
                    },
                    "exact_boss_monster_id": boss_id,
                    "monster": {"monster_id": boss_id},
                    "spot_ai": {
                        "normal": spot,
                        "defense": spot,
                        "base_defense": spot,
                    },
                }
            )
        denominator = len(entries)
        mapping = "".join(
            f"{row['season']}|{row['wave_id']}|{row['exact_boss_monster_id']}|{row['spot_ai']['normal']}\n"
            for row in entries
        ).encode("utf-8")
        source_entries = {}
        for table in source_manifest["challenge"]["coverage"]["wave_table_decode"].values():
            source_entries[table["archive_entry"]] = {
                "record_count": table["wire_root_count"],
            }
        catalog = {
            "schema_version": 1,
            "catalog_kind": "solo_raid_challenge_static",
            "difficulty_type": 2,
            "source": {
                "staticdata_zip": {
                    "sha256": source_manifest["sources"]["staticdata"]["sha256"],
                },
                "entries": source_entries,
            },
            "scope": {
                "scope_digest_sha256": source_manifest["challenge"]["scope"]["scope_digest_sha256"],
            },
            "coverage": {
                "denominator": denominator,
                "wave_records_exact": denominator,
                "boss_monsters_exact": denominator,
                "monster_spot_ai_exact": denominator,
            },
            "mapping_digest_sha256": hashlib.sha256(mapping).hexdigest(),
            "entries": entries,
            "validation": {"status": "complete"},
        }
        catalog["catalog_digest_sha256"] = hashlib.sha256(
            self._canonical_bytes(catalog)
        ).hexdigest()
        path = self.fixture.static / "assembled" / "solo_raid_challenge_catalog.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        self.rebuilt_catalog = json.loads(json.dumps(catalog))
        return path, catalog

    def test_challenge_scope_and_data_version_are_deterministic(self):
        first = self.build(self.when_a)
        second = self.build(self.when_b)
        self.assertEqual(first["data_version"], second["data_version"])
        self.assertNotEqual(first["generated_at_utc"], second["generated_at_utc"])
        self.assertEqual(first["challenge"]["scope"]["difficulty_type"], 2)
        self.assertEqual(first["challenge"]["scope"]["selected"]["preset_rows"], 2)
        self.assertEqual(first["challenge"]["coverage"]["preset_to_wave_group"]["resolved_exact"], 2)
        self.assertEqual(first["challenge"]["coverage"]["wave_to_boss_monster"]["resolved_exact"], 0)
        self.assertEqual(first["challenge"]["entries"][0]["manager_ids"], ["1000001", "1000002"])
        self.assertTrue(all(row["difficulty_type"] == 2 for row in first["challenge"]["entries"]))

        output_root = self.fixture.repo / "Database" / "raw" / "staticdata" / "snapshots" / "solo_raid_challenge"
        manifest_path, latest_path = write_manifest(
            first,
            output_root,
            repo_root=self.fixture.repo,
        )
        self.assertTrue(manifest_path.is_file())
        self.assertTrue(latest_path.is_file())

    def test_settings_secret_material_never_reaches_manifest(self):
        manifest = self.build(self.when_a)
        text = json.dumps(manifest, ensure_ascii=False)
        for forbidden in (
            "SECRET_AES_KEY",
            "SECRET_HOST",
            "SECRET_PROJECT",
            "SECRET_SETTINGS_HASH",
            "https://",
        ):
            self.assertNotIn(forbidden, text)
        safe = manifest["sources"]["client"]["settings_safe"]
        self.assertEqual(safe["host_settings"]["project_names"], ["core", "dp"])
        self.assertEqual(safe["host_settings"]["keysets"], [{"version": 37, "key_count": 2}])
        self.assertNotIn("sha256", manifest["sources"]["client"]["settings_file"])
        self.assertNotIn("sha256", manifest["sources"]["client"]["addressables_catalog_sidecar"])

    def test_unselected_cache_changes_do_not_change_data_version(self):
        before = self.build(self.when_a)
        cache_file = self.fixture.nikke / "Unity" / "com_proximabeta_NIKKE" / "naps" / "00" / "aaa"
        cache_file.write_bytes(cache_file.read_bytes() + b"changed")
        after = self.build(self.when_a)
        self.assertNotEqual(
            before["sources"]["client"]["naps_inventory"]["metadata_sha256"],
            after["sources"]["client"]["naps_inventory"]["metadata_sha256"],
        )
        self.assertEqual(before["data_version"], after["data_version"])

    def test_output_root_cannot_escape_gitignored_snapshot_boundary(self):
        manifest = self.build(self.when_a)
        with self.assertRaises(ManifestError):
            write_manifest(
                manifest,
                Path(self.temp.name) / "outside",
                repo_root=self.fixture.repo,
            )

    def test_stale_decoded_scope_artifact_is_rejected(self):
        preset_path = self.fixture.static / "raid" / "SoloRaidPresetTable.json"
        rows = json.loads(preset_path.read_text(encoding="utf-8"))
        rows[-1]["Wave"] = 9999999
        preset_path.write_text(json.dumps(rows), encoding="utf-8")
        with self.assertRaises(ManifestError):
            self.build(self.when_a)

    def test_exact_catalog_upgrades_manifest_to_static_only(self):
        source_only = self.build(self.when_a)
        self.assertEqual(source_only["validation"]["completeness_tier"], "source_snapshot")
        self.install_exact_catalog()

        first = self.build(self.when_a)
        second = self.build(self.when_b)
        self.assertEqual(first["validation"]["completeness_tier"], "static_only")
        self.assertEqual(first["challenge"]["coverage"]["wave_to_boss_monster"]["resolved_exact"], 2)
        self.assertEqual(first["challenge"]["coverage"]["monster_to_spot_ai"]["resolved_exact"], 2)
        self.assertEqual(first["challenge"]["entries"][0]["exact_boss_monster_id"], "9001")
        self.assertEqual(first["challenge"]["entries"][0]["spot_ai"]["normal"], "bt_challenge_1")
        self.assertNotEqual(source_only["data_version"], first["data_version"])
        self.assertEqual(first["data_version"], second["data_version"])

    def test_stale_existing_catalog_is_rejected_instead_of_downgraded(self):
        path, catalog = self.install_exact_catalog()
        catalog["source"]["staticdata_zip"]["sha256"] = "0" * 64
        catalog.pop("catalog_digest_sha256")
        catalog["catalog_digest_sha256"] = hashlib.sha256(
            self._canonical_bytes(catalog)
        ).hexdigest()
        path.write_text(json.dumps(catalog), encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "direct join 결과"):
            self.build(self.when_a)

    def test_stale_authoritative_behavior_catalog_is_rejected(self):
        self.install_exact_catalog()
        behavior = {
            "schema_version": 1,
            "catalog_kind": "solo_raid_challenge_behavior",
            "status": "behavior_graph_complete",
            "coverage": {"behavior_resolved": 2},
            "source": {"challenge_catalog": {"sha256": "0" * 64}},
            "validation": {"status": "behavior_graph_complete"},
        }
        behavior["catalog_digest_sha256"] = hashlib.sha256(
            self._canonical_bytes(behavior)
        ).hexdigest()
        path = (
            self.fixture.static
            / "assembled"
            / "solo_raid_challenge_behavior.json"
        )
        path.write_text(json.dumps(behavior), encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "source does not match"):
            self.build(self.when_a)

    def test_current_partial_behavior_invalidates_old_authoritative_file(self):
        challenge_path, _catalog = self.install_exact_catalog()
        challenge_sha = hashlib.sha256(challenge_path.read_bytes()).hexdigest()
        behavior = {
            "schema_version": 1,
            "catalog_kind": "solo_raid_challenge_behavior",
            "status": "behavior_graph_complete",
            "coverage": {"behavior_resolved": 2},
            "source": {"challenge_catalog": {"sha256": challenge_sha}},
            "validation": {"status": "behavior_graph_complete"},
        }
        behavior["catalog_digest_sha256"] = hashlib.sha256(
            self._canonical_bytes(behavior)
        ).hexdigest()
        assembled = self.fixture.static / "assembled"
        (assembled / "solo_raid_challenge_behavior.json").write_text(
            json.dumps(behavior), encoding="utf-8"
        )
        (assembled / "solo_raid_challenge_behavior.partial.json").write_text(
            json.dumps({"status": "behavior_graph_partial"}), encoding="utf-8"
        )
        with self.assertRaisesRegex(ManifestError, "partial Challenge behavior"):
            self.build(self.when_a)

    def test_non_frame_complete_timeline_cannot_enter_snapshot(self):
        path = (
            self.fixture.static
            / "assembled"
            / "solo_raid_challenge_timeline.json"
        )
        path.write_text(
            json.dumps(
                {
                    "catalog_kind": "solo_raid_challenge_timeline",
                    "status": "event_frame_partial",
                    "validation": {"status": "partial"},
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ManifestError, "not frame-complete"):
            self.build(self.when_a)


if __name__ == "__main__":
    unittest.main()
