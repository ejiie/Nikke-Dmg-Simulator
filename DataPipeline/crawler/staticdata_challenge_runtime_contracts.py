"""Authoritative native runtime contracts for the focused season-39 build.

The contracts in this module come from static disassembly of the exact PC
``GameAssembly.dll`` identified by :data:`RUNTIME_BUILD_EVIDENCE`.  They are
deliberately build-pinned: callers must not silently reuse them for another
client image.  The route is offline-only and never starts or attaches to the
game.

These contracts describe task status/control flow.  They do not turn runtime
inputs such as QTE state, movement state, or battle delta into invented frame
numbers.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any


DEFAULT_GAME_ASSEMBLY = Path(r"C:\NIKKE\NIKKE\game\GameAssembly.dll")


class RuntimeContractBuildError(RuntimeError):
    """The local client is not the exact build used for these contracts."""


TASK_STATUS = {
    "inactive": 0,
    "failure": 1,
    "success": 2,
    "running": 3,
}


RUNTIME_BUILD_EVIDENCE: dict[str, Any] = {
    "status": "exact_build_offline_native_disassembly",
    "analysis_route": "pe_cfg_extract_then_il2cpp_static_dump_no_process_attach",
    "game_assembly": {
        "logical_path": "C:/NIKKE/NIKKE/game/GameAssembly.dll",
        "size_bytes": 262_709_288,
        "sha256": "a14dad78b1401ac8f75a8e4c4a05c5c6dc522f0ae86dce81c51789e9efe670c2",
        "unity_version": "2021.3.56f2",
        "build_label": "qa-260702-07b",
    },
    "fixed_metadata": {
        "logical_path": (
            "repo/Database/raw/staticdata/il2cpp/s39/global-metadata.fixed.dat"
        ),
        "size_bytes": 46_736_256,
        "sha256": "13d63f7ceb0920c621c1347db1703f2034f1ba858a74d13b678eb311a7862a41",
        "metadata_version": 31,
    },
    "static_dump": {
        "tool": "Il2CppDumper 6.7.46",
        "tool_sha256": (
            "071e36d396ae93cb2cfec032513b46a6bfd67e9b93157830711ab6d79db55045"
        ),
        "dump_cs_sha256": (
            "85649bcf7c20355f38ca6d3fc30aefdfba5e6db789b7895ee830717db5e763be"
        ),
        "il2cpp_h_sha256": (
            "f8e1700479eaebdeb7dbe0858c1013e4a43c6e5f95bcda50e16b58ef534ae9b0"
        ),
        "script_json_sha256": (
            "c9cdcb4270a918be955f8ad0042a18a4f7e16323aeae58a828b96a78c3ee8a76"
        ),
    },
    "task_status": TASK_STATUS,
    "season_39_random_route": {
        "StageSDMonsterData.CreateSpotTransporter": "0x64F5800",
        "EnterSpotUnit.CreateSpotDataTransfer": "0x69EA490",
        "SpotManagement.OnInit": "0x5DC72A0",
        "transporter_random_seed": 0,
        "global_spot_random_seed": 0,
        "task_rng_constructor": "System.Random_default",
        "permutation_status": (
            "runtime_entropy_and_prior_task_rng_consumption_required"
        ),
    },
    "season_39_get_shot_time_route": {
        "spotmonster_bundle_content_hash": "7908749ef6c48cea6eed894450948534",
        "spotmonster_bundle_sha256": (
            "591fd058b0b2069b398c9f4f7df5b66b5deaf72d9dbeaed50e0b6b25fac474dc"
        ),
        "serialized_node": "CAB-63f0f8c3ad84194674d6894c3a354589",
        "serialized_node_sha256": (
            "974d769a06ad2224b95cc4b4b2ed21c286cd6ce605875cea78cddfaafd4b23ed"
        ),
        "monster_anim_controller_path_id": "-6855527738699932369",
        "monster_anim_controller_type_hash": (
            "73787b534c8d2f3133afab8ee9d5f178"
        ),
        "serialized_shot_time_present": False,
        "node_9": {
            "skill_id": "1543424",
            "ani_number": 2,
            "casting_time_seconds": "0.5",
            "delay_time_seconds": "0.5",
            "get_shot_time_after_fire_seconds": "0.5",
            "evidence": (
                "WaitFire.MoveNext loads FireData.DelayTime and passes it as "
                "MonsterFireEvent.FireTime; OnFire passes FireTime to PlayAnimFire; "
                "PlayAnimFire calls SetShotTime without conversion"
            ),
        },
    },
    "season_39_node_9_terminal_route": {
        "status": "exact_build_native_and_serialized_asset_bound",
        "node_id": 9,
        "skill_id": "1543424",
        "ani_number": 2,
        "shot_key": "Shot_02",
        "scheduler_methods": {
            "SpotManagement.UpdateSpot": "0x5DC9400",
            "TickRunner.UpdateTick_list": "0x61756E0",
            "TickCoroutineRunner.StartTickCoroutine_IContextBase": "0x5DE4F50",
            "TickCoroutineRunner.UpdateTick_ITick": "0x5DE51F0",
            "TickCoroutine.ProcessIEnumeratorRecursive": "0x5DE5C10",
            "TickCoroutine.YieldProcessor.MoveNext": "0x5DEF2A0",
            "TickCoroutine.YieldProcessor.Set": "0x5DEF360",
            "BTContext.UpdateTick": "0x60BD1D0",
        },
        "attack_methods": {
            "MonsterAttackLogic.Attack": "0x603E2F0",
            "MonsterAttackLogic.FireCastingV2.MoveNext": "0x60546D0",
            "MonsterAttackLogic.Fire.MoveNext": "0x6055410",
            "MonsterAttackLogic.ConcurrenceFire.MoveNext": "0x60531B0",
            "MonsterAttackLogic.WaitFire.MoveNext": "0x6059C40",
            "MonsterAttackLogic.FireCastingV2.weapon_filter": "0x6058A60",
            "MonsterAttackLogic.PlayAnimEnd.MoveNext": "0x6055BD0",
            "MonsterAnimController.GetFireEndAnimTime": "0x5FD7F60",
            "MonsterAnimController.GetShotTime": "0x5FD7FF0",
            "MonsterAnimController.Init": "0x5FD8080",
            "MonsterAnimController.SetShotTime": "0x5FDA810",
        },
        "context_order": {
            "coroutine_context": "MonsterContext",
            "context_instance_method_info": "0xA70F790",
            "monster_context_registration_ordinal": 3,
            "bt_context_registration_ordinal": 10,
            "registered_before": "BTContext",
            "node_start_frame_slot_already_elapsed": True,
            "first_coroutine_update_offset_frames": 1,
            "completion_observed_by_behavior_manager": "same_frame_later_BTContext_tick",
        },
        "spot_tick_time": {
            "unscaled_fixed_60fps_delta_seconds": "0.016666666666666666",
            "rounding": "Math.Round(scaled_delta_seconds_double, 3)",
            "tick_delta_seconds_float32": "0.017000000923871994",
            "total_tick_time_accumulation": "float32(total_tick_time + tick_delta)",
        },
        "wait_chain": [
            {
                "kind": "FireCastingV2_cast_runtime",
                "seconds_float32": "0.5",
                "source": "skill_casting_time",
            },
            {
                "kind": "PlayAnimEnd_shot_anim_time",
                "seconds_float32": "0.5",
                "source": "GetShotTime_ani_2_after_SetShotTime",
            },
            {
                "kind": "PlayAnimEnd_fire_end_anim_time",
                "seconds_float32": "1.533333420753479",
                "source": "GetFireEndAnimTime_ani_2_initialized_from_animation_clip",
            },
        ],
        "serialized_animation_evidence": {
            "animator_controller_path_id": "1693155116836224942",
            "animator_controller_name": "ebg001_animator",
            "animator_controller_object_sha256": (
                "7dbd2d4f6b61e826d1fcc3257cbc9ccf7779ef2ffcc92b21a12b0db71ef9356b"
            ),
            "animation_clip_path_id": "-4234109018660776073",
            "animation_clip_name": "ebg001_shot_fire_02",
            "animation_clip_object_sha256": (
                "47ad196eadc4c6ef5ad0d21b6cd20abfdbb3d3ee3baeb88fe809cdddacec9acd"
            ),
            "animation_clip_sample_rate": "30",
            "animation_clip_start_time_float32": "0.0",
            "animation_clip_stop_time_float32": "1.533333420753479",
            "animator_controller_contains_clip": True,
        },
        "serialized_weapon_evidence": {
            "monster_weapon_prefab_data_path_id": "-2223736765759943526",
            "monster_weapon_prefab_data_game_object_name": "ebg001_island_zeus",
            "monster_weapon_prefab_data_type_hash": (
                "2c44eaaccb583d17326f3263e8ccbb97"
            ),
            "monster_weapons_field_offset": 32,
            "monster_weapons_count": 6,
            "weapon_object_enum_2_match_count": 1,
            "weapon_prefab_path_id": "8841135951600078936",
            "weapon_prefab_game_object_path_id": "-461134227176976143",
            "weapon_prefab_game_object_name": "socket_cannon",
            "weapon_prefab_type_hash": "d6c3b09e1afca473c0c9d250f95e7b9d",
            "weapon_prefab_object_sha256": (
                "dde2887f1d8d13f4a665d5e393d18e054748156e036b70f3b152d90aa5cb0fc8"
            ),
            "weapon_prefab_object_size_bytes": 212,
            "weapon_object_enum_field_offset": 32,
            "weapon_object_enum": 2,
            "muzzles_field_offset": 36,
            "muzzle_count": 14,
            "parts_type_field_offset": 208,
            "parts_type": 6,
            "muzzle_names_in_order": [
                "socket_muzzle_fire_16",
                "socket_muzzle_fire_17",
                "socket_muzzle_fire_18",
                "socket_muzzle_fire_19",
                "socket_muzzle_fire_20",
                "socket_muzzle_fire_21",
                "socket_muzzle_fire_22",
                "socket_muzzle_fire_01",
                "socket_muzzle_fire_02",
                "socket_muzzle_fire_03",
                "socket_muzzle_fire_04",
                "socket_muzzle_fire_05",
                "socket_muzzle_fire_06",
                "socket_muzzle_fire_07",
            ],
            "runtime_filter": (
                "WeaponData.WeaponPrefab.GetWeaponObjectEnum equals skill "
                "WeaponObjectEnum and WeaponData.IsDestroyed is false"
            ),
            "runtime_filter_get_weapon_object_enum": "0x5FE2B30",
        },
        "fixed_60fps_projection": {
            "delta_model": "fixed_60fps_float32_projection",
            "tick_delta_seconds_float32": "0.017000000923871994",
            "wait_threshold": "float32(registration_total_tick_time + seconds_float32)",
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
        },
        "reference_absolute_trace": {
            "behavior_enable_frame": 0,
            "task_start_frame": 58,
            "first_coroutine_update_frame": 59,
            "casting_wait_registration_frame": 60,
            "casting_wait_resume_frame": 90,
            "fire_first_move_next_frame": 91,
            "concurrence_fire_first_move_next_frame": 92,
            "wait_fire_frames_inclusive": [93, 106],
            "play_anim_end_first_move_next_frame": 107,
            "shot_wait_registration_frame": 108,
            "shot_wait_resume_frame": 138,
            "fire_end_wait_registration_frame": 139,
            "fire_end_wait_resume_frame": 230,
            "terminal_frame": 230,
            "terminal_status": "success",
        },
    },
    "season_39_timeline_skill_terminal_route": {
        "status": "exact_build_native_serialized_timeline_and_scheduler_bound",
        "node_id": 11,
        "skill_id": "1543429",
        "ani_number": 7,
        "shot_key": "Shot_07",
        "methods": {
            "TimelineSkill.ActionToUpdate": "0x61AB7F0",
            "TimelineSkill.NodeFailureCheck": "0x61ABA40",
            "TimelineSkill.OnAwake": "0x61ABA50",
            "TimelineSkill.OnStart": "0x61ABB10",
            "TimelineSkill.OnUpdate": "0x61ABEA0",
            "TimelineSkill.PlayEnd": "0x61AC2B0",
            "MonsterPrefabController.IsPlayingTimeLine": "0x5E42040",
            "MonsterTimeLineControl.AnimatorUpdate": "0x5F566E0",
            "MonsterTimeLineControl.IsPlaying": "0x5F5A5C0",
            "MonsterTimeLineControl.LateUpdate": "0x5F5A610",
            "MonsterTimeLineControl.Play": "0x5F5AD10",
            "MonsterTimeLineControl.UpdateTick": "0x5F5C530",
            "MonsterTimeLineControl.get_UseTickSeparate": "0x88B0E0",
            "SpotPlayableDirectorV2.Play": "0x5F1D1D0",
            "SpotPlayableDirectorV2.UpdateTick": "0x5F1E6D0",
            "SpotPlayableDirectorV2.constructor": "0x5F1E7D0",
            "PlayableGraph.SetTimeUpdateMode": "0x7F10DB0",
        },
        "scheduler_methods": {
            "SpotManagement.RegisterTick": "0x5DC8720",
            "SpotManagement.UpdateSpot": "0x5DC9400",
            "SpotManagement.UpdateTickList": "0x5DC96D0",
            "TickRunner.UpdateTick_list": "0x61756E0",
            "BTContext.UpdateTick": "0x60BD1D0",
        },
        "node_parameters": {
            "ani_number_types": [7],
            "position_type": "None",
            "failure_check": False,
            "keep_casting_time": False,
            "use_break_effect": True,
            "use_break_shake": True,
            "casting_action_node_present": False,
            "use_continuous_timeline": True,
            "move_stop_at_start": True,
            "action_to_present": False,
            "pass_start_time": False,
            "timeline_count": 1,
        },
        "casting_time": {
            "skill_casting_time_seconds": "1.5",
            "terminal_delay_seconds": "0.0",
            "evidence": (
                "OnStart copies SpotMonsterSkill.CastingTime into _delayDuration "
                "only when _isKeepCastingTime is true; node 11 serializes it false, "
                "so OnUpdate does not gate this timeline on the 1.5 second casting value"
            ),
        },
        "dispatch_and_terminal": {
            "dispatch": (
                "OnStart synchronously dispatches MonsterPlayCutSceneEvent for ani 7 "
                "and MonsterTimeLineControl.Play registers the control as an ITick"
            ),
            "running": (
                "OnUpdate returns running while "
                "MonsterPrefabController.IsPlayingTimeLine returns true"
            ),
            "success": (
                "the first later BTContext update observing IsPlayingTimeLine false "
                "calls PlayEnd and returns success"
            ),
            "failure_route_active": False,
        },
        "tick_order": {
            "update_tick_list_order": ["contexts", "presentations", "ticks"],
            "behavior_context_category": "contexts",
            "timeline_control_category": "ticks",
            "use_tick_separate": False,
            "registered_during_behavior_on_start": True,
            "first_timeline_update_offset_frames": 0,
            "first_timeline_late_update_offset_frames": 0,
            "timeline_update_relative_to_bt_context": "same_frame_later",
            "timeline_completion_observed_by_bt_context": "next_frame",
        },
        "spot_tick_time": {
            "unscaled_fixed_60fps_delta_seconds": "0.016666666666666666",
            "rounding": "Math.Round(scaled_delta_seconds_double, 3)",
            "tick_delta_seconds_float32": "0.017000000923871994",
            "timeline_accumulator": (
                "MonsterTimeLineControl.UpdateTick adds tick_delta to float32 "
                "_accumulateDt; same-frame LateUpdate passes it to AnimatorUpdate "
                "and then clears the accumulator"
            ),
        },
        "manual_graph": {
            "director_update_mode_enum": 3,
            "director_update_mode": "Manual",
            "set_time_update_mode_call_sites": ["0x5F1EE64", "0x5F1EF7D"],
            "advance_phase": "MonsterTimeLineControl.LateUpdate_after_spot_tick",
            "advance_delta_source": "float32_accumulated_spot_tick_delta",
        },
        "serialized_timeline_evidence": {
            "route_id": "2191832656749640578",
            "timeline_path_id": "6932276864808260886",
            "timeline_name": "ebg001_skill_04",
            "framerate": "60.0",
            "duration_seconds": "4.0",
            "nominal_duration_frames_60fps": 240,
            "attack_marker_path_id": "3933545539173086807",
            "attack_marker_seconds": "3.15",
            "nominal_attack_marker_frames_60fps": 189,
        },
        "fixed_60fps_projection": {
            "comparison": "elapsed_manual_graph_time_gte_asset_time",
            "tick_delta_seconds_float32": "0.017000000923871994",
            "attack_marker_crossing_update_count": 186,
            "attack_marker_frame_offset": 185,
            "duration_crossing_update_count": 236,
            "playback_clear_frame_offset": 235,
            "terminal_observation_frame_offset": 236,
            "terminal_status": "success",
            "nominal_asset_frames_are_not_battle_frame_offsets": True,
        },
        "reference_absolute_trace": {
            "task_start_frame": 460,
            "first_timeline_update_frame": 460,
            "first_timeline_late_update_frame": 460,
            "attack_marker_frame": 645,
            "playback_clear_frame": 695,
            "terminal_frame": 696,
            "terminal_status": "success",
        },
    },
}


SCHEDULER_CONTRACT: dict[str, Any] = {
    "status": "client_runtime_recovered",
    "methods": {
        "BehaviorManager.PushTask": "0x8A5A50",
        "BehaviorManager.RunTask": "0x8A8310",
        "BehaviorManager.Tick": "0x8A91E0",
    },
    "start_and_first_update": "same_behavior_manager_tick",
    "terminal_to_next_task": "same_behavior_manager_tick_when_control_flow_continues",
    "frame_rule": (
        "a task starting on battle tick F receives its first OnUpdate on F; "
        "a terminal status may start the next executable task on F"
    ),
}


# ``terminal`` is a machine-readable summary consumed by the battle timeline
# compiler.  ``external_inputs`` is intentionally explicit so partial output
# remains honest about values unavailable from the behavior asset alone.
TASK_CONTRACTS: dict[str, dict[str, Any]] = {
    "InitVariables": {
        "status": "client_runtime_recovered",
        "methods": {
            "OnStart": "0x874C90",
            "InitBehaviorTree": "0x619E490",
        },
        "normal_flow": {
            "OnStart": "no_op",
            "child": "transparent_single_child_wrapper",
            "child_start": "same_behavior_manager_tick",
        },
        "external_inputs": [],
    },
    "PatternSequence": {
        "status": "client_runtime_recovered",
        "methods": {
            "OnChildStarted": "0x61A7210",
            "OnConditionalAbort": "0x61A7220",
            "OnEnd": "0x61A7230",
            "OnStart": "0x61A7470",
            "CanExecute": "0x61A74A0",
            "OnChildExecuted": "0x61A7500",
            "OnReevaluationEnded": "0x61A7590",
            "OnReevaluationStarted": "0x61A7700",
            "OverrideStatus": "0x61A7480",
        },
        "normal_flow": {
            "order": "serialized_child_order",
            "success_with_remaining_child": "continue",
            "failure": "terminal",
            "self_inserted_frame_delay": False,
        },
        "timeout": {
            "accumulator": "float32_battle_delta_at_most_once_per_unique_battle_tick",
            "first_count_opportunity": (
                "next_BehaviorManager_parent_reevaluation_after_pattern_start"
            ),
            "comparison": "current_timer_gte_configured_timeout",
            "threshold_tick_order": (
                "accumulate_then_RunParentTask_then_compare_and_abort_current_child"
            ),
            "on_threshold": "abort_current_child_then_mark_interrupt",
            "result_mapping": {"serialized_numeric_0": "success", "nonzero": "failure"},
        },
        "external_inputs": ["battle_tick", "battle_delta"],
    },
    "TimeCount": {
        "status": "client_runtime_recovered",
        "methods": {"OnStart": "0x61AB6B0", "OnUpdate": "0x61AB750"},
        "duration_source": {
            "None_0": "serialized_custom_time",
            "AttackTime_1": "SpotMonster.AttackTime",
            "Custom_2": "serialized_custom_time",
        },
        "terminal": {
            "delta_order": "accumulate_float32_battle_delta_before_compare",
            "running_when": "elapsed_lt_duration",
            "success_when": "elapsed_gte_duration",
            "failure_path": False,
        },
        "external_inputs": ["battle_delta", "SpotMonster.AttackTime_if_native_mode_1"],
    },
    "SpotRandomSelector": {
        "status": "client_runtime_recovered_random_order_symbolic",
        "methods": {
            "CanExecute": "0x61745A0",
            "CurrentChildIndex": "0x61745F0",
            "OnAwake": "0x6174640",
            "OnChildExecuted": "0x6174760",
            "OnConditionalAbort": "0x61747D0",
            "OnEnd": "0x6174830",
            "OnStart": "0x6174880",
            "ShuffleChildren": "0x6174890",
        },
        "normal_flow": {
            "order": "Fisher_Yates_permutation_on_each_OnStart",
            "continue_on": "failure",
            "terminal_success": "first_child_success",
            "terminal_failure": "all_children_failure",
        },
        "rng": {
            "range": "SpotRandom.Range(0,remaining_count)_upper_exclusive",
            "object_lifetime": "created_once_in_OnAwake_not_reseeded_per_activation",
            "seed_formula": (
                "global_seed_zero ? System.Random_default : "
                "System.Random(global_seed + (useSeed ? node_seed : 0))"
            ),
        },
        "external_inputs": [
            "System.Random_default_runtime_state",
            "prior_rng_consumption_history",
        ],
    },
    "SpotRandomSequence": {
        "status": "client_runtime_recovered_random_order_symbolic",
        "methods": {
            "CanExecute": "0x6174AE0",
            "CurrentChildIndex": "0x6174B30",
            "OnAwake": "0x6174B80",
            "OnChildExecuted": "0x6174CA0",
            "OnConditionalAbort": "0x6174D10",
            "OnEnd": "0x6174D70",
            "OnStart": "0x6174DC0",
            "ShuffleChildren": "0x6174DD0",
        },
        "normal_flow": {
            "order": "Fisher_Yates_permutation_on_each_OnStart",
            "continue_on": "success",
            "terminal_failure": "first_child_failure",
            "terminal_success": "all_children_success",
        },
        "rng": {
            "range": "SpotRandom.Range(0,remaining_count)_upper_exclusive",
            "object_lifetime": "created_once_in_OnAwake_not_reseeded_per_activation",
            "seed_formula": (
                "global_seed_zero ? System.Random_default : "
                "System.Random(global_seed + (useSeed ? node_seed : 0))"
            ),
        },
        "external_inputs": [
            "System.Random_default_runtime_state",
            "prior_rng_consumption_history",
        ],
    },
    "IsTargetAlive": {
        "status": "client_runtime_recovered",
        "methods": {"OnUpdate": "0x61A0390"},
        "terminal": {
            "target_missing_or_dead": "failure",
            "isNotHide_false_and_alive": "success",
            "isNotHide_true_and_Hide_function_present": "failure",
            "isNotHide_true_and_Hide_function_absent": "success",
            "running_path": False,
            "offset_from_task_start_ticks": 0,
        },
        "external_inputs": ["target_presence", "target_alive", "target_Hide_function"],
    },
    "AttackV3": {
        "status": "client_runtime_recovered_inherited_attack",
        "methods": {
            "Attack.OnStart": "0x61953D0",
            "Attack.OnUpdate": "0x61959A0",
            "Attack.NodeFailure": "0x61953C0",
            "MonsterAnimController.GetShotTime": "0x5FD7FF0",
            "MonsterAnimController.SetShotTime": "0x5FDA810",
            "MonsterAnimController.PlayAnimFire": "0x5FDA330",
            "MonsterAttackLogic.Fire.MoveNext": "0x6055410",
            "MonsterAttackLogic.WaitFire.MoveNext": "0x6059C40",
            "MonsterFireEvent.Send": "0x60A1740",
        },
        "dispatch": "skill_attack_dispatched_in_OnStart",
        "shot_time_route": {
            "serialized_field": False,
            "runtime_dictionary_field_offset": "0x88",
            "dictionary_key": "SkillAniNumberType_from_ani_number",
            "value_type": "MonsterShotAnimData",
            "end_anim_time_object_offset": "0x10",
            "shot_anim_time_object_offset": "0x14",
            "get_shot_time_miss": 0.0,
            "play_anim_fire_write_source": (
                "MonsterFireEvent.FireTime_from_FireData.DelayTime"
            ),
            "wait_fire_delay_source": "fireIndex * FireData.DelayTime",
            "units": "seconds_float32_no_conversion",
        },
        "terminal": {
            "casting_delay": (
                "accumulate_float32_battle_delta_then_run_while_elapsed_lt_delay"
            ),
            "cancel": "failure_if_FailureCheck_else_success",
            "otherwise": "running_while_monster_fire_or_cast_runtime_state_active",
            "success": "runtime_fire_or_cast_state_clear",
        },
        "external_inputs": [
            "battle_delta",
            "skill_casting_time",
            "skill_delay_time_for_animation_end",
            "monster_fire_or_cast_state",
        ],
    },
    "BreakCol": {
        "status": "client_runtime_recovered",
        "methods": {
            "NodeFailureCheck": "0x6196090",
            "OnStart": "0x61960A0",
            "OnUpdate": "0x6196370",
        },
        "dispatch": (
            "non_animated_attack_dispatched_in_OnStart_for_a_random_live_target"
        ),
        "terminal": {
            "casting_delay": "accumulate_float32_battle_delta_then_run_while_elapsed_lt_delay",
            "cancel": "failure_if_FailueCheck_else_success",
            "otherwise": "running_while_monster_IsAttack_returns_true",
            "success": "monster_IsAttack_returns_false",
        },
        "external_inputs": [
            "battle_delta",
            "skill_casting_time",
            "random_target_selection",
            "monster_attack_state",
        ],
    },
    "TimelineSkill": {
        "status": "client_runtime_recovered",
        "methods": {
            "OnAwake": "0x61ABA50",
            "OnStart": "0x61ABB10",
            "OnUpdate": "0x61ABEA0",
            "PlayEnd": "0x61AC2B0",
            "ActionToUpdate": "0x61AB7F0",
            "NodeFailure": "0x61ABA40",
        },
        "dispatch": "timeline_or_skill_dispatched_in_OnStart",
        "terminal": {
            "casting_delay": (
                "accumulate_float32_battle_delta_then_run_while_elapsed_lt_delay"
            ),
            "cancel": "failure_if_FailureCheck_else_success",
            "otherwise": "running_while_timeline_controller_or_callback_active",
            "PlayEnd": "success_after_cleanup",
        },
        "external_inputs": ["battle_delta", "skill_casting_time", "timeline_controller_state"],
    },
    "MoveToVer2": {
        "status": "client_runtime_recovered",
        "methods": {
            "GetDirection": "0x61A2710",
            "IsInPoint": "0x61A27D0",
            "OnStart": "0x61A2A10",
            "OnUpdate": "0x61A2F20",
            "OnEnd": "0x61A28B0",
            "UpdateSpeed": "0x61A34C0",
        },
        "terminal": {
            "success_when": (
                "squared_current_to_destination_distance_lte_squared_distance_threshold"
            ),
            "running_when": (
                "squared_current_to_destination_distance_gt_squared_distance_threshold"
            ),
            "failure_path": False,
        },
        "external_inputs": [
            "current_position",
            "resolved_or_random_destination",
            "movement_speed_and_state",
            "battle_delta",
            "combat_zone_state",
        ],
    },
    "MoveToVer3": {
        "status": "client_runtime_recovered",
        "methods": {
            "OnStart": "0x61A38D0",
            "OnUpdate": "0x61A3BC0",
            "OnEnd": "0x61A35B0",
        },
        "terminal": {
            "running_when": "movement_controller_update_returns_true",
            "success_when": "movement_controller_update_returns_false",
        },
        "external_inputs": ["battle_delta", "movement_controller_state"],
    },
    "QuickTimeEvent": {
        "status": "client_runtime_recovered",
        "methods": {"OnStart": "0x61A77B0", "OnUpdate": "0x61A7870"},
        "dispatch": "QuickTimeStartEvent_dispatched_in_OnStart",
        "terminal": {
            "context_not_awake": "running",
            "last_state_0_or_1": "running",
            "last_state_2": "failure",
            "last_state_other": "success",
        },
        "external_inputs": ["QuickTimeEventContext.isMonsterBtWakeUp", "QuickTimeEventContext.lastState"],
    },
    "SetMoveType": {
        "status": "client_runtime_recovered",
        "methods": {"OnUpdate": "0x61A8F00"},
        "side_effect": "emit_MonsterSetMoveTypeEvent_only_when_type_differs",
        "terminal": {"status": "success", "offset_from_task_start_ticks": 0},
        "external_inputs": [],
    },
    "StopMoveSuccess": {
        "status": "client_runtime_recovered",
        "methods": {"OnUpdate": "0x61AAA40"},
        "side_effect": "emit_MonsterStopMoveEvent_for_monster",
        "terminal": {"status": "success", "offset_from_task_start_ticks": 0},
        "external_inputs": [],
    },
    "TeleportToVer2": {
        "status": "client_runtime_recovered",
        "methods": {"OnStart": "0x61AAEA0", "OnUpdate": "0x61AB180"},
        "dispatch": "teleport_and_destination_events_dispatched_in_OnStart",
        "terminal": {
            "delta_order": "accumulate_float32_battle_delta_before_gates",
            "first_update": "always_running",
            "later_running_when": "timer_lte_teleport_time_or_condition_type_eq_13",
            "success_when": "timer_gt_teleport_time_and_condition_type_ne_13",
            "failure_path": False,
        },
        "external_inputs": ["battle_delta", "monster_condition_type"],
    },
    "isPhaseAction": {
        "status": "client_runtime_recovered",
        "methods": {"OnStart": "0x61AD6D0", "OnUpdate": "0x61AD870"},
        "terminal": {
            "phase_already_passed": "failure",
            "timeline_playing": "running",
            "timeline_finished": "failure",
            "success_path": False,
        },
        "external_inputs": ["monster_phase", "timeline_controller_state"],
    },
}


def runtime_build_evidence() -> dict[str, Any]:
    """Return an isolated JSON-safe copy for generated artifacts."""

    result = deepcopy(RUNTIME_BUILD_EVIDENCE)
    result["scheduler"] = deepcopy(SCHEDULER_CONTRACT)
    return result


def task_contract(short_type: str) -> dict[str, Any] | None:
    """Return the exact-build contract for ``short_type``, if recovered."""

    value = TASK_CONTRACTS.get(short_type)
    return deepcopy(value) if value is not None else None


def runtime_task_contracts() -> dict[str, dict[str, Any]]:
    """Return every recovered exact-build task contract."""

    return deepcopy(TASK_CONTRACTS)


def validate_runtime_build(path: Path = DEFAULT_GAME_ASSEMBLY) -> dict[str, Any]:
    """Hash ``path`` and reject use of the contracts with another build."""

    expected = RUNTIME_BUILD_EVIDENCE["game_assembly"]
    try:
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeContractBuildError(
            f"cannot verify runtime-contract input: {path}"
        ) from exc
    actual_hash = digest.hexdigest()
    if size != expected["size_bytes"] or actual_hash != expected["sha256"]:
        raise RuntimeContractBuildError(
            "runtime contracts are pinned to another GameAssembly build"
        )
    return {
        "status": "passed",
        "logical_path": "local/GameAssembly.dll",
        "size_bytes": size,
        "sha256": actual_hash,
    }
