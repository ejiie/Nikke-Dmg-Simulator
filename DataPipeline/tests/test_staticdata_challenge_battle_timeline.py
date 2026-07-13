import copy
import tempfile
import unittest
from pathlib import Path

from DataPipeline.crawler.staticdata_challenge_battle_timeline import (
    ChallengeBattleTimelineError,
    _activation_context,
    _control_policy,
    _node_start_expression,
    _skill_events,
    _terminal_expression,
    build_battle_timeline,
    write_catalog,
)
from DataPipeline.crawler.staticdata_challenge_runtime_contracts import (
    RuntimeContractBuildError,
    validate_runtime_build,
)


def _node(
    node_id,
    short_type,
    *,
    parent=None,
    children=None,
    params=None,
    shots=None,
    timer=None,
):
    value = {
        "id": node_id,
        "type": f"Test.{short_type}",
        "parent_id": parent,
        "child_ids": children or [],
        "params": params or {},
        "shot_keys": shots or [],
        "instant": True,
        "abort_type": "None",
        "active_graph": True,
        "effective_enabled": True,
    }
    if timer is not None:
        value["timer"] = {
            "mode": "Custom",
            "seconds_decimal": str(timer),
        }
    return value


class ChallengeBattleTimelineTests(unittest.TestCase):
    def test_runtime_contracts_reject_a_different_client_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "GameAssembly.dll"
            path.write_bytes(b"different build")
            with self.assertRaisesRegex(RuntimeContractBuildError, "another"):
                validate_runtime_build(path)

    def test_native_timer_teleport_and_instant_contracts_are_explicit(self):
        timer = _node(1, "TimeCount", timer="0.3")
        timer_policy = _control_policy(timer, {1: timer})
        self.assertEqual("client_runtime_recovered", timer_policy["status"])
        projection = timer_policy["configured_duration"][
            "fixed_60fps_projection"
        ]
        self.assertEqual(18, projection["terminal_update_count_1_based"])
        self.assertEqual(17, projection["terminal_offset_from_task_start_frames"])
        self.assertEqual(
            "gte",
            timer_policy["configured_duration"]["runtime_completion"][
                "comparison"
            ],
        )

        teleport = _node(
            2,
            "TeleportToVer2",
            params={"Single_teleportTime": 0},
        )
        teleport_policy = _control_policy(teleport, {2: teleport})
        teleport_projection = teleport_policy["configured_duration_hint"][
            "fixed_60fps_projection"
        ]
        self.assertEqual(2, teleport_projection["terminal_update_count_1_based"])
        self.assertEqual("gt", teleport_projection["comparison"])

        instant = _node(3, "SetMoveType")
        terminal = _terminal_expression(instant, {3: instant})
        self.assertEqual({"op": "task_start", "node_id": 3}, terminal["terminal_frame"])
        self.assertEqual("SetMoveType", terminal["runtime_contract_ref"])

    def test_random_and_initialization_native_scheduler_contracts(self):
        root = _node(1, "InitVariables", children=[2])
        random = _node(
            2,
            "SpotRandomSelector",
            parent=1,
            children=[3, 4],
            params={"BooleanuseSeed": False, "Int32seed": 0},
        )
        first = _node(3, "SetMoveType", parent=2)
        second = _node(4, "StopMoveSuccess", parent=2)
        active = {1: root, 2: random, 3: first, 4: second}

        root_policy = _control_policy(root, active)
        self.assertEqual(
            "same_behavior_manager_tick",
            root_policy["child_activation_after_initialization"],
        )
        random_policy = _control_policy(random, active)
        self.assertEqual(
            "Fisher_Yates_permutation_on_each_OnStart",
            random_policy["normal_child_flow"]["order"],
        )
        self.assertIn(
            "System.Random_default_runtime_state", random_policy["unresolved"]
        )
        start = _node_start_expression(3, active, 1)
        self.assertEqual(
            "client_runtime_recovered_random_order_symbolic",
            start["binding_status"],
        )
        self.assertEqual("task_activation_index", start["activation_index"]["op"])
        self.assertEqual(2, start["activation_index"]["node_id"])

        attack_time = _node(5, "TimeCount", timer="999")
        attack_time["timer"]["mode"] = "AttackTime"
        attack_policy = _control_policy(attack_time, {5: attack_time})
        self.assertEqual(
            "not_emitted_runtime_AttackTime_replaces_custom_time",
            attack_policy["configured_duration"]["fixed_60fps_projection"][
                "status"
            ],
        )

    def test_parallel_delayed_branches_do_not_depend_on_sibling_action(self):
        nodes = {
            1: _node(1, "InitVariables", children=[2]),
            2: _node(2, "Parallel", parent=1, children=[3, 4, 5]),
            3: _node(3, "AttackV3", parent=2, shots=["Shot_18"]),
            4: _node(4, "Sequence", parent=2, children=[6, 7]),
            5: _node(5, "Sequence", parent=2, children=[8, 9]),
            6: _node(6, "TimeCount", parent=4, timer="0.3"),
            7: _node(7, "AttackV3", parent=4, shots=["Shot_18"]),
            8: _node(8, "TimeCount", parent=5, timer="0.6"),
            9: _node(9, "AttackV3", parent=5, shots=["Shot_18"]),
        }

        self.assertEqual(
            {"op": "task_start", "node_id": 2},
            _node_start_expression(3, nodes, 1),
        )
        self.assertEqual(
            {"op": "task_terminal", "node_id": 6, "required_status": "success"},
            _node_start_expression(7, nodes, 1),
        )
        self.assertEqual(
            {"op": "task_terminal", "node_id": 8, "required_status": "success"},
            _node_start_expression(9, nodes, 1),
        )
        self.assertNotIn("3", str(_node_start_expression(7, nodes, 1)))
        self.assertNotIn("3", str(_node_start_expression(9, nodes, 1)))
        guards, _, _ = _activation_context(7, nodes, 1)
        self.assertIn(
            {
                "op": "parallel_branch_active",
                "parallel_node_id": 2,
                "branch_node_id": 4,
                "not_preempted_before": {"op": "task_start", "node_id": 7},
            },
            guards,
        )

        repeater_params = {
            "SharedBoolrepeatForever": {"BooleanmValue": True},
            "SharedBoolendOnFailure": {"BooleanmValue": False},
            "SharedIntcount": {"Int32mValue": 0},
        }
        repeated = {
            1: _node(1, "InitVariables", children=[10]),
            10: _node(
                10,
                "Repeater",
                parent=1,
                children=[11],
                params=repeater_params,
            ),
            11: _node(11, "AttackV3", parent=10, shots=["Shot_01"]),
        }
        recurrence = _node_start_expression(11, repeated, 1)
        self.assertEqual("repeat_iteration_start", recurrence["op"])
        self.assertEqual(
            {"op": "task_start", "node_id": 10},
            recurrence["definition"]["base_case"]["frame"],
        )
        prior = recurrence["definition"]["recursive_case"]["frame"][
            "prior_body_terminal"
        ]
        self.assertEqual(["success", "failure"], prior["required_statuses"])
        self.assertFalse(prior["aborted_continues"])

    def test_random_fallback_and_target_condition_are_structured_guards(self):
        fallback = {
            1: _node(1, "InitVariables", children=[27]),
            27: _node(27, "SpotRandomSelector", parent=1, children=[28]),
            28: _node(28, "Selector", parent=27, children=[29, 42]),
            29: _node(29, "Parallel", parent=28),
            42: _node(42, "Sequence", parent=28, children=[45]),
            45: _node(45, "TimelineSkill", parent=42, shots=["Shot_09"]),
        }
        guards, choices, _ = _activation_context(45, fallback, 1)
        self.assertTrue(
            any(
                item.get("op") == "custom_random_child_activated"
                and item.get("node_id") == 27
                for item in guards
            )
        )
        self.assertIn(
            {"op": "task_status", "node_id": 29, "status": "failure"},
            guards,
        )
        self.assertTrue(
            any(item.get("kind") == "ordered_selector_branch" for item in choices)
        )

        target = {
            1: _node(1, "InitVariables", children=[135]),
            135: _node(135, "SpotRandomSequence", parent=1, children=[146]),
            146: _node(
                146, "Sequence", parent=135, children=[147, 148, 149, 152]
            ),
            147: _node(
                147,
                "IsTargetAlive",
                parent=146,
                params={"ECharacterPosition_targetPosition": "Player1"},
            ),
            148: _node(148, "BreakCol", parent=146, shots=["Shot_12"]),
            149: _node(149, "MoveToVer3", parent=146),
            152: _node(152, "TimelineSkill", parent=146, shots=["Shot_04"]),
        }
        guards, _, _ = _activation_context(152, target, 1)
        condition = next(item for item in guards if item.get("op") == "condition")
        self.assertEqual(147, condition["node_id"])
        self.assertEqual("Player1", condition["parameters"]["ECharacterPosition_targetPosition"])
        self.assertEqual({"op": "task_start", "node_id": 147}, condition["at"])

        pattern = {
            1: _node(1, "InitVariables", children=[2]),
            2: _node(
                2,
                "PatternSequence",
                parent=1,
                children=[3],
                params={
                    "Single_timeOut": 27,
                    "PatternResult_timeOutResult": "Success",
                },
            ),
            3: _node(3, "Sequence", parent=2, children=[4]),
            4: _node(4, "AttackV3", parent=3, shots=["Shot_06"]),
        }
        guards, _, _ = _activation_context(4, pattern, 1)
        deadline_guard = next(
            item for item in guards if item.get("op") == "custom_pattern_branch_active"
        )
        self.assertEqual({"op": "task_start", "node_id": 4}, deadline_guard["not_timed_out_before"])
        self.assertEqual(
            "27",
            deadline_guard["deadline"]["configured_timeout"]["seconds_decimal"],
        )
        self.assertEqual(
            "success", _control_policy(pattern[2], pattern)["timeout_terminal_status"]
        )

    def test_skill_dispatch_and_effect_templates_remain_separate(self):
        nodes = {
            1: _node(1, "Sequence", children=[2, 3]),
            2: _node(2, "TimelineSkill", parent=1, shots=["Shot_04"]),
            3: _node(3, "AttackV3", parent=1, shots=["Shot_01"]),
        }
        behavior_entry = {
            "monster_skills": [
                {
                    "skill_id": "4",
                    "animation": {"shot_key": "Shot_04"},
                    "timing": {"is_using_timeline": True},
                },
                {
                    "skill_id": "1",
                    "animation": {"shot_key": "Shot_01"},
                    "timing": {"is_using_timeline": False},
                },
            ],
            "skill_cast_sites": [
                {
                    "node_id": 2,
                    "shot_keys": ["Shot_04"],
                    "active_graph": True,
                    "effective_enabled": True,
                },
                {
                    "node_id": 3,
                    "shot_keys": ["Shot_01"],
                    "active_graph": True,
                    "effective_enabled": True,
                },
            ],
        }
        timeline_entry = {
            "skill_timeline_join": [
                {
                    "shot_key": "Shot_04",
                    "skill_id": "4",
                    "active_behavior_site_count": 1,
                    "monster_skill_timing": {"is_using_timeline": True},
                    "route_status": "exact_monster_timeline_route",
                    "route_ids": ["route-4"],
                    "event_frame_status": "timeline_attack_marker_exact",
                    "attack_markers_relative_to_timeline_start": [
                        {
                            "frame_60fps": {
                                "status": "exact_integer",
                                "frame": 282,
                            }
                        }
                    ],
                },
                {
                    "shot_key": "Shot_01",
                    "skill_id": "1",
                    "active_behavior_site_count": 1,
                    "monster_skill_timing": {"is_using_timeline": False},
                    "event_frame_status": "animation_or_runtime_callback_unresolved",
                    "attack_markers_relative_to_timeline_start": [],
                },
            ]
        }
        compiled_nodes = [
            {
                "id": 2,
                "policy": {
                    "fixed_60fps_timeline_terminal_projection": {
                        "marker_projections": [
                            {
                                "path_id": None,
                                "offset_from_timeline_action_start_frames": 282,
                            }
                        ]
                    }
                },
            }
        ]

        events, stats = _skill_events(
            behavior_entry,
            timeline_entry,
            nodes,
            root_id=1,
            compiled_nodes=compiled_nodes,
        )
        self.assertEqual(4, len(events))
        self.assertEqual(2, stats["skill_dispatch_templates"])
        self.assertEqual(1, stats["skill_effect_templates_exact_relative_marker"])
        self.assertEqual(1, stats["skill_effect_templates_runtime_unresolved"])
        exact = next(
            item
            for item in events
            if item["kind"] == "skill_effect"
            and item["shot_key"] == "Shot_04"
        )
        self.assertEqual(282, exact["relative_to_timeline_action_start"]["frames"])
        unresolved = next(
            item
            for item in events
            if item["kind"] == "skill_effect"
            and item["shot_key"] == "Shot_01"
        )
        self.assertEqual(
            "runtime_callback_unresolved", unresolved["battle_frame"]["status"]
        )

        duplicate = copy.deepcopy(behavior_entry)
        duplicate["skill_cast_sites"].append(
            copy.deepcopy(duplicate["skill_cast_sites"][0])
        )
        with self.assertRaisesRegex(
            ChallengeBattleTimelineError, "duplicate active skill site"
        ):
            _skill_events(
                duplicate,
                timeline_entry,
                nodes,
                root_id=1,
                compiled_nodes=compiled_nodes,
            )

        drifted = copy.deepcopy(timeline_entry)
        drifted["skill_timeline_join"][0][
            "attack_markers_relative_to_timeline_start"
        ][0]["frame_60fps"]["status"] = "symbolic"
        with self.assertRaisesRegex(
            ChallengeBattleTimelineError, "non-integral exact marker"
        ):
            _skill_events(
                behavior_entry,
                drifted,
                nodes,
                root_id=1,
                compiled_nodes=compiled_nodes,
            )

    @unittest.skipUnless(
        (
            Path(__file__).resolve().parents[2]
            / "Database/raw/staticdata/assembled/solo_raid_challenge_behavior.season_39.partial.json"
        ).exists()
        and (
            Path(__file__).resolve().parents[2]
            / "Database/raw/staticdata/assembled/solo_raid_challenge_timeline.season_39.partial.json"
        ).exists(),
        "focused season 39 raw artifacts are intentionally gitignored",
    )
    def test_current_season_39_production_oracles(self):
        root = Path(__file__).resolve().parents[2]
        assembled = root / "Database/raw/staticdata/assembled"
        artifact = build_battle_timeline(
            behavior_path=(
                assembled
                / "solo_raid_challenge_behavior.season_39.partial.json"
            ),
            timeline_path=(
                assembled
                / "solo_raid_challenge_timeline.season_39.partial.json"
            ),
            season=39,
            runtime_build_verification=validate_runtime_build(),
        )
        self.assertEqual(
            {
                "active_nodes": 185,
                "nodes_excluded_from_active_execution": 24,
                "active_skill_dispatch_templates": 30,
                "skill_effect_templates_exact_relative_marker": 13,
                "skill_effect_templates_runtime_unresolved": 17,
                "pattern_windows": 5,
                "repeaters": 5,
                "custom_random_nodes": 2,
                "active_custom_task_types": 16,
                "runtime_contract_types_recovered": 16,
                "runtime_contract_types_pending": 0,
            },
            artifact["coverage"],
        )
        checks = {item["name"]: item for item in artifact["validation"]["checks"]}
        self.assertEqual("passed", checks["season_39_static_oracles"]["status"])
        shot_time = artifact["runtime_evidence"]["season_39_get_shot_time_route"]
        self.assertFalse(shot_time["serialized_shot_time_present"])
        self.assertEqual(
            "0.5", shot_time["node_9"]["get_shot_time_after_fire_seconds"]
        )
        node_9 = next(item for item in artifact["ir"]["nodes"] if item["id"] == 9)
        projection = node_9["terminal"][
            "fixed_60fps_tick_coroutine_projection"
        ]
        self.assertEqual(
            "0.017000000923871994",
            projection["tick_delta_seconds_float32"],
        )
        self.assertEqual(
            "next_monster_context_tick",
            projection["newly_yielded_current_processing"],
        )
        wait_fire = next(
            item
            for item in projection["trace_program"]
            if item.get("kind") == "WaitFire"
        )
        self.assertEqual(14, wait_fire["count"])
        self.assertEqual(
            230, projection["reference_absolute_trace"]["terminal_frame"]
        )
        self.assertIn(
            "skill_delay_time_for_animation_end",
            node_9["terminal"]["resolved_external_inputs"],
        )

        expected_timeline_projections = {
            (11, "Shot_07"): (240, 185, 236),
            (45, "Shot_09"): (320, 212, 314),
            (63, "Shot_09"): (320, 212, 314),
            (81, "Shot_09"): (320, 212, 314),
            (99, "Shot_09"): (320, 212, 314),
            (104, "Shot_08"): (344, 259, 338),
            (112, "Shot_08"): (344, 259, 338),
            (119, "Shot_05"): (344, 270, 338),
            (142, "Shot_04"): (448, 276, 440),
            (152, "Shot_04"): (448, 276, 440),
            (162, "Shot_04"): (448, 276, 440),
            (172, "Shot_04"): (448, 276, 440),
            (182, "Shot_04"): (448, 276, 440),
        }
        timeline_projections = {}
        for node in artifact["ir"]["nodes"]:
            value = node["terminal"].get(
                "fixed_60fps_timeline_terminal_projection"
            )
            if value is None:
                continue
            marker_projections = value["marker_projections"]
            self.assertEqual(1, len(marker_projections))
            timeline_projections[(node["id"], node["shot_keys"][0])] = (
                value["asset_nominal_duration_frames_60fps"],
                marker_projections[0][
                    "offset_from_timeline_action_start_frames"
                ],
                value["terminal_offset_from_task_start_frames"],
            )
        self.assertEqual(expected_timeline_projections, timeline_projections)
        self.assertEqual(
            {
                "Shot_07": 240,
                "Shot_09": 320,
                "Shot_08": 344,
                "Shot_05": 344,
                "Shot_04": 448,
            },
            {
                shot: duration
                for (_node_id, shot), (
                    duration,
                    _marker,
                    _terminal,
                ) in timeline_projections.items()
            },
        )

    def test_output_cannot_escape_staticdata_assembled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "staticdata"
            outside = Path(temporary) / "battle_timeline.json"
            with self.assertRaises(ChallengeBattleTimelineError):
                write_catalog({}, outside, static_root=root)
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
