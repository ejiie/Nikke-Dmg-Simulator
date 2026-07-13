import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from DataPipeline.crawler.staticdata_challenge_scenario_evaluator import (
    OUTPUT_KIND,
    SCENARIO_KIND,
    ScenarioEvaluationError,
    build_scenario_evaluation,
    finalize_scenario,
    write_catalog,
)


def _canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _finalize(value):
    result = copy.deepcopy(value)
    result.pop("catalog_digest_sha256", None)
    result["catalog_digest_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def _node(
    node_id,
    short_type,
    op,
    start,
    *,
    children=None,
    policy=None,
    iterations=None,
    choices=None,
    guards=None,
):
    return {
        "id": node_id,
        "source_type": f"Test.{short_type}",
        "op": op,
        "children": children or [],
        "policy": policy or {},
        "activation": {
            "start_frame": start,
            "iteration_vars": iterations or [],
            "choice_path": choices or [],
            "guards": guards or [],
        },
    }


def _base_timeline(nodes, events, *, root=1):
    return _finalize(
        {
            "schema_version": 2,
            "catalog_kind": "solo_raid_challenge_battle_timeline",
            "status": "branch_aware_battle_frame_partial",
            "scope": {"fps": 60, "promotion_eligible": False},
            "entry": {"season": "39"},
            "runtime_evidence": {
                "game_assembly": {"sha256": "a" * 64},
            },
            "ir": {"root_node_id": root, "nodes": nodes, "skill_events": events},
        }
    )


def _scenario(timeline_path, timeline, *, bindings=None, instances=None, origin=100):
    return finalize_scenario(
        {
            "schema_version": 1,
            "catalog_kind": SCENARIO_KIND,
            "scenario_id": "unit-scenario",
            "season": "39",
            "source": {
                "battle_timeline": {
                    "sha256": hashlib.sha256(timeline_path.read_bytes()).hexdigest(),
                    "catalog_digest_sha256": timeline["catalog_digest_sha256"],
                    "game_assembly_sha256": "a" * 64,
                }
            },
            "battle": {
                "behavior_enable_frame": origin,
                "delta_model": "fixed_60fps_float32_projection",
            },
            "bindings": bindings
            or {
                "task_terminals": [],
                "random_permutations": [],
                "skill_effects": [],
            },
            "event_instances": instances or [],
        }
    )


def _write_pair(root, timeline, scenario_factory):
    timeline_path = root / "timeline.json"
    timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False), encoding="utf-8"
    )
    scenario = scenario_factory(timeline_path)
    scenario_path = root / "scenario.json"
    scenario_path.write_text(
        json.dumps(scenario, ensure_ascii=False), encoding="utf-8"
    )
    return timeline_path, scenario_path, scenario


def _horizon_scenario(timeline_path, timeline, *, bindings=None, origin=0):
    scenario = _scenario(
        timeline_path,
        timeline,
        bindings=bindings,
        instances=[],
        origin=origin,
    )
    scenario["evaluation_mode"] = "expand_180s_horizon"
    scenario["battle"]["frame_horizon_exclusive"] = origin + 180 * 60
    scenario["battle"]["pattern_tick_model"] = "next_fixed60_frame"
    return finalize_scenario(scenario)


def _node_9_tick_coroutine_projection():
    return {
        "status": "exact_build_native_and_serialized_asset_bound",
        "delta_model": "fixed_60fps_float32_projection",
        "tick_delta_seconds_float32": "0.017000000923871994",
        "coroutine_context": "MonsterContext",
        "first_coroutine_update_offset_frames": 1,
        "completion_observation": "same_frame_later_BTContext_tick",
        "wait_threshold": (
            "float32(registration_total_tick_time + seconds_float32)"
        ),
        "wait_resume": "first_frame_total_tick_time_gte_threshold",
        "newly_yielded_current_processing": "next_monster_context_tick",
        "completed_child_parent_resume": "same_monster_context_tick",
        "trace_program": [
            {
                "op": "yield_wait",
                "kind": "FireCastingV2_cast_runtime",
                "seconds_float32": "0.5",
            },
            {"op": "yield_nested_coroutine", "kind": "Fire"},
            {"op": "yield_nested_coroutine", "kind": "ConcurrenceFire"},
            {
                "op": "yield_immediate_nested_coroutines",
                "kind": "WaitFire",
                "count": 14,
                "immediate_condition": "fire_index_zero_skips_delay",
            },
            {"op": "yield_nested_coroutine", "kind": "PlayAnimEnd"},
            {
                "op": "yield_wait",
                "kind": "PlayAnimEnd_shot_anim_time",
                "seconds_float32": "0.5",
            },
            {
                "op": "yield_wait",
                "kind": "PlayAnimEnd_fire_end_anim_time",
                "seconds_float32": "1.533333420753479",
            },
            {"op": "terminal_cascade"},
        ],
        "terminal_status": "success",
    }


def _timeline_terminal_projection():
    return {
        "status": "exact_build_native_and_serialized_asset_bound",
        "delta_model": "spot_update_round_3_float32",
        "tick_delta_seconds_float32": "0.017000000923871994",
        "duration_seconds_decimal": "4.0",
        "duration_comparison": "gte",
        "clock_accumulator": "PlayableGraph_double_manual_time",
        "controller_first_update_offset_frames": 0,
        "duration_terminal_update_count_1_based": 236,
        "controller_stop_offset_from_task_start_frames": 235,
        "completion_observation": "next_frame_earlier_BTContext_tick",
        "completion_observation_offset_frames": 1,
        "terminal_offset_from_task_start_frames": 236,
        "terminal_status": "success",
    }


class ChallengeScenarioEvaluatorTests(unittest.TestCase):
    def test_tick_coroutine_program_resolves_node_9_terminal_at_frame_232(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Sequence",
                "sequence",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3, 9, 10],
            ),
            _node(
                3,
                "TimeCount",
                "custom_wait",
                {"op": "task_start", "node_id": 2},
                policy={
                    "configured_duration": {
                        "fixed_60fps_projection": {
                            "terminal_offset_from_task_start_frames": 60
                        }
                    }
                },
            ),
            _node(
                9,
                "AttackV3",
                "custom_action",
                {
                    "op": "task_terminal",
                    "node_id": 3,
                    "required_status": "success",
                },
                policy={
                    "fixed_60fps_tick_coroutine_projection": (
                        _node_9_tick_coroutine_projection()
                    )
                },
            ),
            _node(
                10,
                "SetMoveType",
                "custom_action",
                {
                    "op": "task_terminal",
                    "node_id": 9,
                    "required_status": "success",
                },
            ),
        ]
        timeline = _base_timeline(
            nodes,
            events=[
                {
                    "event_id": "after_node_9",
                    "kind": "skill_dispatch",
                    "node_id": 10,
                    "shot_key": "Shot_03",
                    "skill_id": "2",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _scenario(
                    path,
                    timeline,
                    instances=[{"event_id": "after_node_9"}],
                    origin=0,
                ),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual(232, artifact["events"][0]["battle_frame"])

    def test_timecount_and_exact_timeline_projection_resolve_same_tick_chain(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Sequence",
                "sequence",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3, 4],
            ),
            _node(
                3,
                "TimeCount",
                "custom_wait",
                {"op": "task_start", "node_id": 2},
                policy={
                    "configured_duration": {
                        "fixed_60fps_projection": {
                            "terminal_offset_from_task_start_frames": 60
                        }
                    }
                },
            ),
            _node(
                4,
                "TimelineSkill",
                "custom_action",
                {
                    "op": "task_terminal",
                    "node_id": 3,
                    "required_status": "success",
                },
                policy={
                    "fixed_60fps_timeline_terminal_projection": (
                        _timeline_terminal_projection()
                    )
                },
            ),
        ]
        events = [
            {
                "event_id": "dispatch",
                "kind": "skill_dispatch",
                "node_id": 4,
                "shot_key": "Shot_01",
                "skill_id": "1",
            },
            {
                "event_id": "effect",
                "kind": "skill_effect",
                "node_id": 4,
                "shot_key": "Shot_01",
                "skill_id": "1",
                "relative_to_timeline_action_start": {"frames": 185},
            },
        ]
        timeline = _base_timeline(nodes, events)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _scenario(
                    path,
                    timeline,
                    instances=[
                        {"event_id": "dispatch"},
                        {"event_id": "effect"},
                    ],
                ),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("complete_for_requested_instances", artifact["status"])
        self.assertEqual([160, 345], [item["battle_frame"] for item in artifact["events"]])

    def test_timeline_projection_rejects_contradictory_terminal_offset(self):
        projection = _timeline_terminal_projection()
        projection["terminal_offset_from_task_start_frames"] = 237
        nodes = [
            _node(
                1,
                "TimelineSkill",
                "custom_action",
                {"op": "variable", "name": "behavior_enable_frame"},
                policy={
                    "fixed_60fps_timeline_terminal_projection": projection
                },
            )
        ]
        timeline = _base_timeline(
            nodes,
            events=[
                {
                    "event_id": "effect",
                    "kind": "skill_effect",
                    "node_id": 1,
                    "shot_key": "Shot_07",
                    "skill_id": "1543429",
                    "relative_to_timeline_action_start": {"frames": 185},
                }
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _scenario(
                    path,
                    timeline,
                    instances=[{"event_id": "effect"}],
                    origin=0,
                ),
            )
            with self.assertRaisesRegex(
                ScenarioEvaluationError,
                "timeline terminal projection equation mismatch",
            ):
                build_scenario_evaluation(
                    timeline_path=timeline_path, scenario_path=scenario_path
                )

    def test_missing_terminal_is_unresolved_and_effect_binding_is_separate(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "AttackV3",
                "custom_action",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
            ),
            _node(
                3,
                "TimelineSkill",
                "custom_action",
                {
                    "op": "task_terminal",
                    "node_id": 2,
                    "required_status": "success",
                },
            ),
        ]
        events = [
            {
                "event_id": "attack_effect",
                "kind": "skill_effect",
                "node_id": 2,
                "shot_key": "Shot_01",
                "skill_id": "1",
            },
            {
                "event_id": "next_dispatch",
                "kind": "skill_dispatch",
                "node_id": 3,
                "shot_key": "Shot_02",
                "skill_id": "2",
            },
        ]
        timeline = _base_timeline(nodes, events)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _scenario(
                    path,
                    timeline,
                    instances=[
                        {"event_id": "attack_effect"},
                        {"event_id": "next_dispatch"},
                    ],
                ),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("partial", artifact["status"])
        self.assertEqual(["unresolved", "unresolved"], [x["resolution_status"] for x in artifact["events"]])
        self.assertEqual("missing_skill_effect_frame", artifact["events"][0]["dependencies"][0]["kind"])
        self.assertEqual("missing_task_terminal", artifact["events"][1]["dependencies"][0]["kind"])

    def test_repeat_context_and_random_activation_are_not_conflated(self):
        repeat_nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Repeater",
                "repeat",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3],
                policy={"repeat_forever": False, "count": 3, "end_on_failure": True},
            ),
            _node(
                3,
                "TimeCount",
                "custom_wait",
                {
                    "op": "repeat_iteration_start",
                    "repeat_node_id": 2,
                    "iteration_var": "repeat_2",
                    "definition": {
                        "recursive_case": {
                            "frame": {
                                "prior_body_terminal": {
                                    "body_node_id": 3,
                                    "required_statuses": ["success"],
                                }
                            }
                        }
                    },
                },
                policy={
                    "configured_duration": {
                        "fixed_60fps_projection": {
                            "terminal_offset_from_task_start_frames": 5
                        }
                    }
                },
                iterations=[{"variable": "repeat_2"}],
            ),
        ]
        repeat_events = [
            {
                "event_id": "wait_dispatch",
                "kind": "skill_dispatch",
                "node_id": 3,
                "shot_key": "Shot_01",
                "skill_id": "1",
            }
        ]
        timeline = _base_timeline(repeat_nodes, repeat_events)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _scenario(
                    path,
                    timeline,
                    instances=[
                        {"event_id": "wait_dispatch", "context": {"repeat_2": 0}},
                        {"event_id": "wait_dispatch", "context": {"repeat_2": 1}},
                        {"event_id": "wait_dispatch", "context": {"repeat_2": 2}},
                    ],
                ),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual([100, 105, 110], [x["battle_frame"] for x in artifact["events"]])

        random_choice = {
            "node_id": 10,
            "kind": "custom_random_selector",
        }
        random_nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[10],
            ),
            _node(
                10,
                "SpotRandomSelector",
                "custom_random_selector",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[11, 12],
            ),
            _node(
                11,
                "AttackV3",
                "custom_action",
                {
                    "op": "custom_random_child_start",
                    "random_node_id": 10,
                    "child_node_id": 11,
                },
                choices=[random_choice],
            ),
            _node(
                12,
                "AttackV3",
                "custom_action",
                {
                    "op": "custom_random_child_start",
                    "random_node_id": 10,
                    "child_node_id": 12,
                },
                choices=[random_choice],
            ),
        ]
        random_events = [
            {
                "event_id": "second_dispatch",
                "kind": "skill_dispatch",
                "node_id": 12,
                "shot_key": "Shot_02",
                "skill_id": "2",
            }
        ]
        timeline = _base_timeline(random_nodes, random_events)
        bindings = {
            "task_terminals": [
                {
                    "node_id": 11,
                    "context": {"random_10": 0},
                    "frame": 110,
                    "status": "failure",
                }
            ],
            "random_permutations": [
                {"node_id": 10, "activation_index": 0, "children": [11, 12]}
            ],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _scenario(
                    path,
                    timeline,
                    bindings=bindings,
                    instances=[
                        {
                            "event_id": "second_dispatch",
                            "context": {"random_10": 0},
                        },
                        {
                            "event_id": "second_dispatch",
                            "context": {"random_10": 1},
                        },
                    ],
                ),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("resolved", artifact["events"][0]["resolution_status"])
        self.assertEqual(110, artifact["events"][0]["battle_frame"])
        self.assertEqual("unresolved", artifact["events"][1]["resolution_status"])
        self.assertEqual("missing_random_permutation", artifact["events"][1]["dependencies"][0]["kind"])

    def test_validation_and_output_confinement(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
            )
        ]
        events = [
            {
                "event_id": "dispatch",
                "kind": "skill_dispatch",
                "node_id": 1,
                "shot_key": "Shot_01",
                "skill_id": "1",
            }
        ]
        timeline = _base_timeline(nodes, events)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, scenario = _write_pair(
                root,
                timeline,
                lambda path: _scenario(
                    path, timeline, instances=[{"event_id": "dispatch"}]
                ),
            )
            drifted = dict(scenario)
            drifted["battle"] = dict(drifted["battle"])
            drifted["battle"]["behavior_enable_frame"] = 1
            scenario_path.write_text(json.dumps(drifted), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioEvaluationError, "digest"):
                build_scenario_evaluation(
                    timeline_path=timeline_path, scenario_path=scenario_path
                )

            outside = root / "outside.json"
            with self.assertRaisesRegex(ScenarioEvaluationError, "assembled"):
                write_catalog({}, outside, static_root=root / "staticdata")
            self.assertFalse(outside.exists())

    def test_rejects_occurrence_aliases_and_semantic_overrides(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Repeater",
                "repeat",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3],
                policy={"repeat_forever": False, "count": 1, "end_on_failure": True},
            ),
            _node(
                3,
                "TimelineSkill",
                "custom_action",
                {
                    "op": "repeat_iteration_start",
                    "repeat_node_id": 2,
                    "iteration_var": "repeat_2",
                    "definition": {
                        "recursive_case": {
                            "frame": {
                                "prior_body_terminal": {
                                    "body_node_id": 3,
                                    "required_statuses": ["success"],
                                }
                            }
                        }
                    },
                },
                iterations=[{"variable": "repeat_2"}],
            ),
        ]
        events = [
            {
                "event_id": "effect",
                "kind": "skill_effect",
                "node_id": 3,
                "shot_key": "Shot_01",
                "skill_id": "1",
                "relative_to_timeline_action_start": {"frames": 10},
            }
        ]
        timeline = _base_timeline(nodes, events)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path = root / "timeline.json"
            timeline_path.write_text(json.dumps(timeline), encoding="utf-8")

            overflow = _scenario(
                timeline_path,
                timeline,
                instances=[{"event_id": "effect", "context": {"repeat_2": 1}}],
            )
            scenario_path = root / "overflow.json"
            scenario_path.write_text(json.dumps(overflow), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioEvaluationError, "finite range"):
                build_scenario_evaluation(
                    timeline_path=timeline_path, scenario_path=scenario_path
                )

            composite = _scenario(
                timeline_path,
                timeline,
                bindings={
                    "task_terminals": [
                        {
                            "node_id": 2,
                            "context": {},
                            "frame": 100,
                            "status": "success",
                        }
                    ],
                    "random_permutations": [],
                    "skill_effects": [],
                },
                instances=[{"event_id": "effect", "context": {"repeat_2": 0}}],
            )
            scenario_path = root / "composite.json"
            scenario_path.write_text(json.dumps(composite), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioEvaluationError, "runtime-dependent"):
                build_scenario_evaluation(
                    timeline_path=timeline_path, scenario_path=scenario_path
                )

            exact_override = _scenario(
                timeline_path,
                timeline,
                bindings={
                    "task_terminals": [],
                    "random_permutations": [],
                    "skill_effects": [
                        {
                            "event_id": "effect",
                            "context": {"repeat_2": 0},
                            "frame": 999,
                        }
                    ],
                },
                instances=[{"event_id": "effect", "context": {"repeat_2": 0}}],
            )
            scenario_path = root / "exact.json"
            scenario_path.write_text(json.dumps(exact_override), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioEvaluationError, "exact timeline"):
                build_scenario_evaluation(
                    timeline_path=timeline_path, scenario_path=scenario_path
                )

    def test_parallel_sibling_proof_and_native_status_constraints(self):
        parallel_guard_a = {
            "op": "parallel_branch_active",
            "parallel_node_id": 2,
            "branch_node_id": 3,
        }
        parallel_guard_b = {
            "op": "parallel_branch_active",
            "parallel_node_id": 2,
            "branch_node_id": 6,
        }
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Parallel",
                "parallel",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3, 6],
            ),
            _node(
                3,
                "Sequence",
                "sequence",
                {"op": "task_start", "node_id": 2},
                children=[4, 5],
                guards=[parallel_guard_a],
            ),
            _node(
                4,
                "AttackV3",
                "custom_action",
                {"op": "task_start", "node_id": 3},
                guards=[parallel_guard_a],
            ),
            _node(
                5,
                "AttackV3",
                "custom_action",
                {
                    "op": "task_terminal",
                    "node_id": 4,
                    "required_status": "success",
                },
                guards=[parallel_guard_a],
            ),
            _node(
                6,
                "AttackV3",
                "custom_action",
                {"op": "task_start", "node_id": 2},
                guards=[parallel_guard_b],
            ),
        ]
        events = [
            {
                "event_id": "branch_second_dispatch",
                "kind": "skill_dispatch",
                "node_id": 5,
                "shot_key": "Shot_01",
                "skill_id": "1",
            }
        ]
        timeline = _base_timeline(nodes, events)
        bindings = {
            "task_terminals": [
                {"node_id": 4, "context": {}, "frame": 110, "status": "success"},
                {"node_id": 6, "context": {}, "frame": 200, "status": "success"},
            ],
            "random_permutations": [],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _scenario(
                    path,
                    timeline,
                    bindings=bindings,
                    instances=[{"event_id": "branch_second_dispatch"}],
                ),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("resolved", artifact["events"][0]["resolution_status"])
        self.assertEqual(110, artifact["events"][0]["battle_frame"])

        move_nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "MoveToVer3",
                "custom_action",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
            ),
        ]
        timeline = _base_timeline(move_nodes, events=[])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path = root / "timeline.json"
            timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
            scenario = _scenario(
                timeline_path,
                timeline,
                bindings={
                    "task_terminals": [
                        {
                            "node_id": 2,
                            "context": {},
                            "frame": 110,
                            "status": "failure",
                        }
                    ],
                    "random_permutations": [],
                    "skill_effects": [],
                },
                instances=[{"event_id": "unused"}],
            )
            scenario_path = root / "scenario.json"
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioEvaluationError, "native contract"):
                build_scenario_evaluation(
                    timeline_path=timeline_path, scenario_path=scenario_path
                )

    def test_horizon_expansion_bounds_an_infinite_repeater(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Repeater",
                "repeat",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3],
                policy={"repeat_forever": True, "count": 0, "end_on_failure": False},
            ),
            _node(
                3,
                "TimeCount",
                "custom_wait",
                {
                    "op": "repeat_iteration_start",
                    "repeat_node_id": 2,
                    "iteration_var": "repeat_2",
                    "definition": {
                        "recursive_case": {
                            "frame": {
                                "prior_body_terminal": {
                                    "body_node_id": 3,
                                    "required_statuses": ["success", "failure"],
                                }
                            }
                        }
                    },
                },
                policy={
                    "configured_duration": {
                        "fixed_60fps_projection": {
                            "terminal_offset_from_task_start_frames": 1
                        }
                    }
                },
                iterations=[{"variable": "repeat_2"}],
            ),
        ]
        events = [
            {
                "event_id": "tick_dispatch",
                "kind": "skill_dispatch",
                "node_id": 3,
                "shot_key": "Shot_01",
                "skill_id": "1",
            }
        ]
        timeline = _base_timeline(nodes, events)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path = root / "timeline.json"
            timeline_path.write_text(json.dumps(timeline), encoding="utf-8")
            scenario = _horizon_scenario(
                timeline_path, timeline, origin=100
            )
            scenario_path = root / "scenario.json"
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("complete_180s_window", artifact["status"])
        self.assertEqual(10800, artifact["coverage"]["resolved_dispatches"])
        self.assertEqual(0, artifact["coverage"]["unresolved_frontiers"])
        self.assertEqual(100, artifact["events"][0]["battle_frame"])
        self.assertEqual(10899, artifact["events"][-1]["battle_frame"])

    def test_horizon_keeps_long_task_running_without_fabricated_terminal(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "TimelineSkill",
                "custom_action",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
            ),
        ]
        timeline = _base_timeline(
            nodes,
            events=[
                {
                    "event_id": "after_window_marker",
                    "kind": "skill_effect",
                    "node_id": 2,
                    "shot_key": "Shot_01",
                    "skill_id": "1",
                    "relative_to_timeline_action_start": {"frames": 11000},
                }
            ],
        )
        bindings = {
            "task_terminals": [
                {"node_id": 2, "context": {}, "frame": 20000, "status": "success"}
            ],
            "random_permutations": [],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(path, timeline, bindings=bindings),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("complete_180s_window", artifact["status"])
        self.assertIsNone(artifact["expansion"]["root_terminal"])
        attack = next(item for item in artifact["activations"] if item["node_id"] == 2)
        self.assertEqual("running_at_horizon", attack["end_kind"])
        self.assertEqual(10800, attack["running_until_frame"])
        self.assertEqual("outside_horizon", artifact["events"][0]["resolution_status"])

    def test_parallel_failure_preempts_later_sibling_marker(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Parallel",
                "parallel",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3, 4],
            ),
            _node(3, "TimelineSkill", "custom_action", {"op": "task_start", "node_id": 2}),
            _node(4, "AttackV3", "custom_action", {"op": "task_start", "node_id": 2}),
        ]
        events = [
            {
                "event_id": "late_marker",
                "kind": "skill_effect",
                "node_id": 3,
                "shot_key": "Shot_01",
                "skill_id": "1",
                "relative_to_timeline_action_start": {"frames": 100},
            }
        ]
        timeline = _base_timeline(nodes, events)
        bindings = {
            "task_terminals": [
                {"node_id": 3, "context": {}, "frame": 200, "status": "success"},
                {"node_id": 4, "context": {}, "frame": 50, "status": "failure"},
            ],
            "random_permutations": [],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(path, timeline, bindings=bindings),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("complete_execution_before_horizon", artifact["status"])
        self.assertEqual("inactive", artifact["events"][0]["resolution_status"])
        self.assertEqual(
            "parallel_preempted_before_event", artifact["events"][0]["reason"]["kind"]
        )
        branch = next(item for item in artifact["activations"] if item["node_id"] == 3)
        self.assertEqual("parallel_preempted", branch["end_kind"])
        self.assertEqual(50, branch["running_until_frame"])

    def test_horizon_status_is_partial_for_unresolved_event_without_frontier(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "AttackV3",
                "custom_action",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
            ),
        ]
        events = [
            {
                "event_id": "runtime_effect",
                "kind": "skill_effect",
                "node_id": 2,
                "shot_key": "Shot_01",
                "skill_id": "1",
            }
        ]
        timeline = _base_timeline(nodes, events)
        bindings = {
            "task_terminals": [
                {"node_id": 2, "context": {}, "frame": 100, "status": "success"}
            ],
            "random_permutations": [],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(path, timeline, bindings=bindings),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("partial", artifact["status"])
        self.assertEqual(0, artifact["coverage"]["unresolved_frontiers"])
        self.assertEqual("unresolved", artifact["events"][0]["resolution_status"])

    def test_pattern_terminal_cannot_exceed_fixed60_deadline(self):
        nodes = [
            _node(
                1,
                "Pattern",
                "custom_pattern_timeout",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
                policy={
                    "configured_timeout": {"seconds_decimal": "43"},
                    "timeout_terminal_status": "success",
                },
            ),
            _node(2, "AttackV3", "custom_action", {"op": "task_start", "node_id": 1}),
        ]
        timeline = _base_timeline(nodes, events=[])
        bindings = {
            "task_terminals": [
                {"node_id": 1, "context": {}, "frame": 4000, "status": "success"},
                {"node_id": 2, "context": {}, "frame": 5000, "status": "success"},
            ],
            "random_permutations": [],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(path, timeline, bindings=bindings),
            )
            with self.assertRaisesRegex(ScenarioEvaluationError, "fixed60 deadline"):
                build_scenario_evaluation(
                    timeline_path=timeline_path, scenario_path=scenario_path
                )

            conflicting = copy.deepcopy(bindings)
            conflicting["task_terminals"][0] = {
                "node_id": 1,
                "context": {},
                "frame": 2530,
                "status": "failure",
            }
            scenario = _horizon_scenario(
                timeline_path, timeline, bindings=conflicting
            )
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            with self.assertRaisesRegex(
                ScenarioEvaluationError,
                "deadline terminal conflicts with the native timeout status",
            ):
                build_scenario_evaluation(
                    timeline_path=timeline_path, scenario_path=scenario_path
                )

            matching = copy.deepcopy(conflicting)
            matching["task_terminals"][0]["status"] = "success"
            scenario = _horizon_scenario(timeline_path, timeline, bindings=matching)
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual(
            "pattern_fixed60_timeout",
            artifact["expansion"]["root_terminal"]["source"],
        )

    def test_pattern_terminal_after_horizon_stays_running(self):
        nodes = [
            _node(
                1,
                "Pattern",
                "custom_pattern_timeout",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
                policy={
                    "configured_timeout": {"seconds_decimal": "300"},
                    "timeout_terminal_status": "success",
                },
            ),
            _node(2, "AttackV3", "custom_action", {"op": "task_start", "node_id": 1}),
        ]
        timeline = _base_timeline(nodes, events=[])
        bindings = {
            "task_terminals": [
                {"node_id": 1, "context": {}, "frame": 12000, "status": "success"},
                {"node_id": 2, "context": {}, "frame": 15000, "status": "success"},
            ],
            "random_permutations": [],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(path, timeline, bindings=bindings),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("complete_180s_window", artifact["status"])
        self.assertIsNone(artifact["expansion"]["root_terminal"])
        self.assertEqual("running_at_horizon", artifact["activations"][0]["end_kind"])

        without_pattern_terminal = copy.deepcopy(bindings)
        without_pattern_terminal["task_terminals"] = [
            item
            for item in without_pattern_terminal["task_terminals"]
            if item["node_id"] != 1
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(
                    path, timeline, bindings=without_pattern_terminal
                ),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        pattern = next(item for item in artifact["activations"] if item["node_id"] == 1)
        self.assertEqual("running_at_horizon", pattern["end_kind"])
        self.assertEqual(10800, pattern["running_until_frame"])

    def test_pattern_deterministic_child_starts_next_sequence_sibling_same_frame(self):
        nodes = [
            _node(
                1,
                "Sequence",
                "sequence",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2, 4],
            ),
            _node(
                2,
                "Pattern",
                "custom_pattern_timeout",
                {"op": "task_start", "node_id": 1},
                children=[3],
                policy={
                    "configured_timeout": {"seconds_decimal": "43"},
                    "timeout_terminal_status": "success",
                },
            ),
            _node(
                3,
                "TimeCount",
                "custom_wait",
                {"op": "custom_pattern_child_start", "pattern_node_id": 2},
                policy={
                    "configured_duration": {
                        "fixed_60fps_projection": {
                            "terminal_offset_from_task_start_frames": 10
                        }
                    }
                },
            ),
            _node(
                4,
                "SetMoveType",
                "custom_action",
                {
                    "op": "task_terminal",
                    "node_id": 2,
                    "required_status": "success",
                },
            ),
        ]
        timeline = _base_timeline(nodes, events=[])
        bindings = {
            "task_terminals": [],
            "random_permutations": [],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(path, timeline, bindings=bindings),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )

        pattern = next(item for item in artifact["activations"] if item["node_id"] == 2)
        sibling = next(item for item in artifact["activations"] if item["node_id"] == 4)
        self.assertEqual("pattern_child_terminal", pattern["terminal"]["source"])
        self.assertEqual(10, pattern["terminal"]["frame"])
        self.assertEqual(10, sibling["start_frame"])
        self.assertEqual(10, sibling["terminal"]["frame"])
        self.assertEqual(0, artifact["coverage"]["unresolved_frontiers"])

    def test_unresolved_parallel_sibling_makes_later_marker_conditional(self):
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Parallel",
                "parallel",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3, 4],
            ),
            _node(3, "TimelineSkill", "custom_action", {"op": "task_start", "node_id": 2}),
            _node(4, "AttackV3", "custom_action", {"op": "task_start", "node_id": 2}),
        ]
        timeline = _base_timeline(
            nodes,
            events=[
                {
                    "event_id": "marker",
                    "kind": "skill_effect",
                    "node_id": 3,
                    "shot_key": "Shot_01",
                    "skill_id": "1",
                    "relative_to_timeline_action_start": {"frames": 100},
                }
            ],
        )
        bindings = {
            "task_terminals": [
                {"node_id": 3, "context": {}, "frame": 300, "status": "success"}
            ],
            "random_permutations": [],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(path, timeline, bindings=bindings),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("partial", artifact["status"])
        self.assertEqual("conditional", artifact["events"][0]["resolution_status"])
        self.assertEqual(
            "missing_parallel_sibling_terminal_order",
            artifact["events"][0]["dependencies"][0]["kind"],
        )
        known_branch = next(
            item for item in artifact["activations"] if item["node_id"] == 3
        )
        self.assertEqual("conditional", known_branch["resolution_status"])
        self.assertEqual(
            "missing_parallel_sibling_terminal_order",
            known_branch["dependencies"][0]["kind"],
        )

    def test_repeat_uses_actual_prior_random_body_terminal(self):
        repeat_choice = {"node_id": 3, "kind": "custom_random_selector"}
        repeat_start = {
            "op": "repeat_iteration_start",
            "repeat_node_id": 2,
            "iteration_var": "repeat_2",
            "definition": {
                "recursive_case": {
                    "frame": {
                        "prior_body_terminal": {
                            "body_node_id": 3,
                            "required_statuses": ["success", "failure"],
                        }
                    }
                }
            },
        }
        nodes = [
            _node(
                1,
                "InitVariables",
                "custom_initialization_scope",
                {"op": "variable", "name": "behavior_enable_frame"},
                children=[2],
            ),
            _node(
                2,
                "Repeater",
                "repeat",
                {"op": "custom_initialization_child_start", "scope_node_id": 1},
                children=[3],
                policy={"repeat_forever": False, "count": 2, "end_on_failure": False},
            ),
            _node(
                3,
                "SpotRandomSelector",
                "custom_random_selector",
                repeat_start,
                children=[4, 5],
                iterations=[{"variable": "repeat_2"}],
            ),
            _node(
                4,
                "TimeCount",
                "custom_wait",
                {"op": "custom_random_child_start", "random_node_id": 3, "child_node_id": 4},
                policy={"configured_duration": {"fixed_60fps_projection": {"terminal_offset_from_task_start_frames": 10}}},
                iterations=[{"variable": "repeat_2"}],
                choices=[repeat_choice],
            ),
            _node(
                5,
                "TimeCount",
                "custom_wait",
                {"op": "custom_random_child_start", "random_node_id": 3, "child_node_id": 5},
                policy={"configured_duration": {"fixed_60fps_projection": {"terminal_offset_from_task_start_frames": 20}}},
                iterations=[{"variable": "repeat_2"}],
                choices=[repeat_choice],
            ),
        ]
        timeline = _base_timeline(nodes, events=[])
        bindings = {
            "task_terminals": [],
            "random_permutations": [
                {"node_id": 3, "activation_index": 0, "children": [4, 5]},
                {"node_id": 3, "activation_index": 1, "children": [5, 4]},
            ],
            "skill_effects": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline_path, scenario_path, _ = _write_pair(
                root,
                timeline,
                lambda path: _horizon_scenario(path, timeline, bindings=bindings),
            )
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        random_activations = [
            item for item in artifact["activations"] if item["node_id"] == 3
        ]
        self.assertEqual([0, 10], [item["start_frame"] for item in random_activations])
        self.assertEqual(
            [10, 30], [item["terminal"]["frame"] for item in random_activations]
        )

    @unittest.skipUnless(
        (
            Path(__file__).resolve().parents[2]
            / "Database/raw/staticdata/assembled/solo_raid_challenge_battle_timeline.season_39.partial.json"
        ).exists(),
        "focused season 39 artifact is intentionally gitignored",
    )
    def test_current_s39_early_recurrence_oracle(self):
        timeline_path = (
            Path(__file__).resolve().parents[2]
            / "Database/raw/staticdata/assembled/solo_raid_challenge_battle_timeline.season_39.partial.json"
        )
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        scenario = finalize_scenario(
            {
                "schema_version": 1,
                "catalog_kind": SCENARIO_KIND,
                "scenario_id": "s39-early-recurrence-test",
                "season": "39",
                "source": {
                    "battle_timeline": {
                        "sha256": hashlib.sha256(timeline_path.read_bytes()).hexdigest(),
                        "catalog_digest_sha256": timeline["catalog_digest_sha256"],
                        "game_assembly_sha256": timeline["runtime_evidence"][
                            "game_assembly"
                        ]["sha256"],
                    }
                },
                "battle": {
                    "behavior_enable_frame": 0,
                    "delta_model": "fixed_60fps_float32_projection",
                    "pattern_tick_model": "next_fixed60_frame",
                    "frame_horizon_exclusive": 800,
                },
                "bindings": {
                    "task_terminals": [],
                    "random_permutations": [],
                    "skill_effects": [],
                },
                "event_instances": [
                    {
                        "event_id": "node_11_shot_07_dispatch",
                        "context": {"repeat_5": 0},
                    },
                    {
                        "event_id": "node_11_shot_07_impact_0",
                        "context": {"repeat_5": 0},
                    },
                ],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            scenario_path = Path(temporary) / "scenario.json"
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual(
            [460, 645],
            [item["battle_frame"] for item in artifact["events"]],
        )
        self.assertTrue(
            all(item["resolution_status"] == "resolved" for item in artifact["events"])
        )
        self.assertEqual(2, artifact["coverage"]["resolved"])
        self.assertEqual(OUTPUT_KIND, artifact["catalog_kind"])

    @unittest.skipUnless(
        (
            Path(__file__).resolve().parents[2]
            / "Database/raw/staticdata/assembled/solo_raid_challenge_battle_timeline.season_39.partial.json"
        ).exists(),
        "focused season 39 artifact is intentionally gitignored",
    )
    def test_current_s39_180s_expansion_reaches_runtime_phase_frontier(self):
        timeline_path = (
            Path(__file__).resolve().parents[2]
            / "Database/raw/staticdata/assembled/solo_raid_challenge_battle_timeline.season_39.partial.json"
        )
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        scenario = finalize_scenario(
            {
                "schema_version": 1,
                "catalog_kind": SCENARIO_KIND,
                "scenario_id": "s39-180s-frontier-test",
                "evaluation_mode": "expand_180s_horizon",
                "season": "39",
                "source": {
                    "battle_timeline": {
                        "sha256": hashlib.sha256(timeline_path.read_bytes()).hexdigest(),
                        "catalog_digest_sha256": timeline["catalog_digest_sha256"],
                        "game_assembly_sha256": timeline["runtime_evidence"][
                            "game_assembly"
                        ]["sha256"],
                    }
                },
                "battle": {
                    "behavior_enable_frame": 0,
                    "delta_model": "fixed_60fps_float32_projection",
                    "pattern_tick_model": "next_fixed60_frame",
                    "frame_horizon_exclusive": 10800,
                },
                "bindings": {
                    "task_terminals": [],
                    "random_permutations": [],
                    "skill_effects": [],
                },
                "event_instances": [],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            scenario_path = Path(temporary) / "scenario.json"
            scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
            artifact = build_scenario_evaluation(
                timeline_path=timeline_path, scenario_path=scenario_path
            )
        self.assertEqual("partial", artifact["status"])
        self.assertEqual(28, artifact["coverage"]["activations"])
        node_9 = [
            item for item in artifact["activations"] if item["node_id"] == 9
        ]
        self.assertEqual(
            [58, 230, 754, 926, 1450, 1622],
            [item["start_frame"] for item in node_9],
        )
        self.assertEqual(
            [230, 402, 926, 1098, 1622, 1794],
            [item["terminal"]["frame"] for item in node_9],
        )
        node_11 = [
            item for item in artifact["activations"] if item["node_id"] == 11
        ]
        self.assertEqual(
            [460, 1156, 1852], [item["start_frame"] for item in node_11]
        )
        self.assertEqual(
            [696, 1392, 2088],
            [item["terminal"]["frame"] for item in node_11],
        )
        self.assertEqual(
            [645, 1341, 2037],
            [
                item["battle_frame"]
                for item in artifact["events"]
                if item["template_event_id"] == "node_11_shot_07_impact_0"
            ],
        )
        self.assertEqual(13, artifact["unresolved_frontiers"][0]["node_id"])
        self.assertEqual(2088, artifact["unresolved_frontiers"][0]["start_frame"])
        self.assertEqual(
            ["failure"],
            artifact["unresolved_frontiers"][0]["dependencies"][0][
                "known_terminal_statuses"
            ],
        )
        pattern = next(item for item in artifact["activations"] if item["node_id"] == 3)
        self.assertEqual(2088, pattern["terminal"]["frame"])
        self.assertEqual("pattern_child_terminal", pattern["terminal"]["source"])


if __name__ == "__main__":
    unittest.main()
