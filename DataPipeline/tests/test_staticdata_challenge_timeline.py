import json
import tempfile
import unittest
from pathlib import Path

from DataPipeline.crawler.staticdata_challenge_timeline import (
    ChallengeTimelineError,
    _canonical_bytes,
    _compact_routes,
    _load_behavior,
    _sha256,
    _skill_route_rows,
    write_catalog,
)


def _frame(value):
    return {"value": value, "integral": True, "raw": float(value)}


class ChallengeTimelineTests(unittest.TestCase):
    def test_focused_behavior_requires_isolated_nonpromotable_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "behavior.json"
            value = {
                "schema_version": 1,
                "catalog_kind": "solo_raid_challenge_behavior",
                "status": "behavior_graph_partial",
                "scope": {
                    "mode": "solo_raid_challenge_only",
                    "difficulty_type": 2,
                    "expected_seasons": 39,
                    "selection_mode": "focused_diagnostic",
                    "selected_seasons": ["39"],
                    "promotion_eligible": False,
                },
                "entries": [
                    {
                        "season": "39",
                        "resolution_status": "resolved_exact",
                        "task_graph": {},
                        "monster_skills": [{"skill_id": "1"}],
                        "skill_cast_sites": [{"node_id": 1}],
                    }
                ],
            }
            value["catalog_digest_sha256"] = _sha256(_canonical_bytes(value))
            path.write_text(json.dumps(value), encoding="utf-8")

            loaded = _load_behavior(path, focus_season=39)
            self.assertEqual("39", loaded["entries"][0]["season"])
            with self.assertRaisesRegex(ChallengeTimelineError, "exact 39-row"):
                _load_behavior(path)

            value["scope"]["promotion_eligible"] = True
            value.pop("catalog_digest_sha256")
            value["catalog_digest_sha256"] = _sha256(_canonical_bytes(value))
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ChallengeTimelineError, "not an isolated"):
                _load_behavior(path, focus_season=39)

    def test_monster_timeline_ani_list_overrides_name_hint(self):
        manifest = {
            "ani_number_route_groups": [
                {
                    "route_id": "route-a",
                    "ani_numbers": [8, 9, 10],
                    "disabled": False,
                    "scene_type": 1,
                    "trigger": 22,
                    "owner_game_object": {"path_id": "1", "name": "owner"},
                    "top_timeline": {
                        "path_id": "top",
                        "name": "model_hsta_shot_10_attackall",
                    },
                    "model_timeline": {
                        "path_id": "model",
                        "name": "model_shot_06_attackall_model",
                    },
                }
            ],
            "all_timelines": [
                {
                    "path_id": "top",
                    "name": "model_hsta_shot_10_attackall",
                    "framerate": 60.0,
                    "fixed_duration_canonical_60_frames": _frame(404),
                    "attack_markers": [
                        {
                            "path_id": "marker",
                            "time_seconds": 5.0,
                            "canonical_60_frame": _frame(300),
                            "target": 0,
                            "hit_effect_type": 0,
                        }
                    ],
                    "tracks": [],
                },
                {
                    "path_id": "model",
                    "name": "model_shot_06_attackall_model",
                    "framerate": 60.0,
                    "fixed_duration_canonical_60_frames": _frame(0),
                    "attack_markers": [],
                    "tracks": [],
                },
            ],
        }
        routes, by_ani = _compact_routes(manifest)
        self.assertEqual(["route-a"], by_ani[8])
        self.assertEqual(["route-a"], by_ani[9])
        self.assertEqual(["route-a"], by_ani[10])

        entry = {
            "monster_skills": [
                {
                    "skill_id": "100",
                    "animation": {"enum_value": 8, "shot_key": "Shot_08"},
                    "timing": {"is_using_timeline": True},
                }
            ],
            "skill_cast_sites": [
                {
                    "active_graph": True,
                    "effective_enabled": True,
                    "shot_keys": ["Shot_08"],
                }
            ],
        }
        skills, stats = _skill_route_rows(entry, routes, by_ani)
        self.assertEqual("exact_monster_timeline_route", skills[0]["route_status"])
        self.assertEqual("timeline_attack_marker_exact", skills[0]["event_frame_status"])
        self.assertEqual(
            300,
            skills[0]["attack_markers_relative_to_timeline_start"][0]
            ["frame_60fps"]["frame"],
        )
        self.assertEqual(1, stats["active_skill_rows_with_exact_marker"])

    def test_output_cannot_escape_staticdata_assembled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "staticdata"
            outside = Path(temporary) / "timeline.json"
            with self.assertRaises(ChallengeTimelineError):
                write_catalog({}, outside, static_root=root)
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
