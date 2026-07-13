#!/usr/bin/env python3
"""Compile a focused Challenge behavior tree into a branch-aware frame IR.

This stage deliberately does not flatten conditionals, random composites,
repeaters, movement, QTEs, or client-specific action completion into guessed
absolute frames.  It joins exact SpotMonster timeline markers to skill action
sites and emits recurrence-style frame expressions whose unresolved leaves can
later be replaced by recovered client runtime semantics.

Only isolated ``--season N`` diagnostics are accepted.  The resulting
``season_N.partial.json`` artifact is never eligible for canonical promotion.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
import struct
import sys
import tempfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    from .staticdata_challenge_behavior import DEFAULT_STATIC_ROOT
    from .staticdata_challenge_runtime_contracts import (
        DEFAULT_GAME_ASSEMBLY,
        RuntimeContractBuildError,
        SCHEDULER_CONTRACT,
        runtime_build_evidence,
        runtime_task_contracts,
        task_contract,
        validate_runtime_build,
    )
except ImportError:
    from staticdata_challenge_behavior import DEFAULT_STATIC_ROOT
    from staticdata_challenge_runtime_contracts import (
        DEFAULT_GAME_ASSEMBLY,
        RuntimeContractBuildError,
        SCHEDULER_CONTRACT,
        runtime_build_evidence,
        runtime_task_contracts,
        task_contract,
        validate_runtime_build,
    )

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SCHEMA_VERSION = 2
CATALOG_KIND = "solo_raid_challenge_battle_timeline"
EXPECTED_CHALLENGES = 39
FPS = 60
SPOT_TICK_DELTA_SECONDS = "0.017000000923871994"

_S39_DISPATCH_PAIRS = {
    (9, "Shot_02"),
    (11, "Shot_07"),
    (25, "Shot_06"),
    (45, "Shot_09"),
    (63, "Shot_09"),
    (81, "Shot_09"),
    (99, "Shot_09"),
    (104, "Shot_08"),
    (106, "Shot_01"),
    (108, "Shot_06"),
    (110, "Shot_01"),
    (112, "Shot_08"),
    (117, "Shot_10"),
    (118, "Shot_17"),
    (119, "Shot_05"),
    (120, "Shot_11"),
    (121, "Shot_11"),
    (127, "Shot_18"),
    (130, "Shot_18"),
    (133, "Shot_18"),
    (138, "Shot_16"),
    (142, "Shot_04"),
    (148, "Shot_12"),
    (152, "Shot_04"),
    (158, "Shot_14"),
    (162, "Shot_04"),
    (168, "Shot_15"),
    (172, "Shot_04"),
    (178, "Shot_13"),
    (182, "Shot_04"),
}
_S39_EXACT_MARKERS = {
    (11, "Shot_07"): 189,
    (45, "Shot_09"): 217,
    (63, "Shot_09"): 217,
    (81, "Shot_09"): 217,
    (99, "Shot_09"): 217,
    (104, "Shot_08"): 265,
    (112, "Shot_08"): 265,
    (119, "Shot_05"): 276,
    (142, "Shot_04"): 282,
    (152, "Shot_04"): 282,
    (162, "Shot_04"): 282,
    (172, "Shot_04"): 282,
    (182, "Shot_04"): 282,
}
_S39_RUNTIME_MARKER_OFFSETS = {
    (11, "Shot_07"): 185,
    (45, "Shot_09"): 212,
    (63, "Shot_09"): 212,
    (81, "Shot_09"): 212,
    (99, "Shot_09"): 212,
    (104, "Shot_08"): 259,
    (112, "Shot_08"): 259,
    (119, "Shot_05"): 270,
    (142, "Shot_04"): 276,
    (152, "Shot_04"): 276,
    (162, "Shot_04"): 276,
    (172, "Shot_04"): 276,
    (182, "Shot_04"): 276,
}
_S39_PATTERN_TIMEOUTS = {3: "43", 14: "27", 26: "18", 102: "37", 113: "105"}
_S39_REPEATERS = {5, 8, 22, 100, 123}
_S39_RANDOM_NODES = {27, 135}


class ChallengeBattleTimelineError(RuntimeError):
    """A source artifact or task graph cannot be compiled without drift."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_artifact(path: Path, expected_kind: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {token}")
            ),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ChallengeBattleTimelineError(f"cannot read artifact {path}") from exc
    if not isinstance(value, dict) or value.get("catalog_kind") != expected_kind:
        raise ChallengeBattleTimelineError(
            f"{path.name}: expected artifact kind {expected_kind}"
        )
    stored = value.get("catalog_digest_sha256")
    payload = dict(value)
    payload.pop("catalog_digest_sha256", None)
    if not isinstance(stored, str) or stored != _sha256(_canonical_bytes(payload)):
        raise ChallengeBattleTimelineError(f"{path.name}: catalog digest mismatch")
    return value


def _focused_entry(
    artifact: dict[str, Any], *, season: int, expected_status: str
) -> dict[str, Any]:
    scope = artifact.get("scope")
    entries = artifact.get("entries")
    expected = [str(season)]
    entry = entries[0] if isinstance(entries, list) and len(entries) == 1 else {}
    if (
        artifact.get("status") != expected_status
        or not isinstance(scope, dict)
        or scope.get("mode") != "solo_raid_challenge_only"
        or scope.get("expected_seasons") != EXPECTED_CHALLENGES
        or scope.get("selection_mode") != "focused_diagnostic"
        or scope.get("selected_seasons") != expected
        or scope.get("promotion_eligible") is not False
        or not isinstance(entry, dict)
        or str(entry.get("season")) != str(season)
        or entry.get("resolution_status") != "resolved_exact"
    ):
        raise ChallengeBattleTimelineError(
            f"artifact is not an isolated season {season} non-promotable diagnostic"
        )
    return entry


def _load_focused_sources(
    behavior_path: Path, timeline_path: Path, *, season: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if type(season) is not int or not 1 <= season <= EXPECTED_CHALLENGES:
        raise ChallengeBattleTimelineError(
            f"season must be an integer in 1..{EXPECTED_CHALLENGES}"
        )
    behavior = _load_artifact(behavior_path, "solo_raid_challenge_behavior")
    timeline = _load_artifact(timeline_path, "solo_raid_challenge_timeline")
    behavior_entry = _focused_entry(
        behavior, season=season, expected_status="behavior_graph_partial"
    )
    timeline_entry = _focused_entry(
        timeline, season=season, expected_status="event_frame_partial"
    )
    if (timeline.get("scope") or {}).get("fps") != FPS:
        raise ChallengeBattleTimelineError("timeline artifact is not canonical 60fps")
    source = timeline.get("source", {}).get("behavior_artifact")
    if (
        not isinstance(source, dict)
        or source.get("sha256") != _sha256_file(behavior_path)
        or source.get("catalog_digest_sha256")
        != behavior.get("catalog_digest_sha256")
    ):
        raise ChallengeBattleTimelineError(
            "timeline artifact does not reference the supplied behavior artifact"
        )
    for field in ("monster_id", "mon_prefab", "spotmonster_addressable_key"):
        left = (
            behavior_entry.get(field)
            if field == "monster_id"
            else (behavior_entry.get("monster_model") or {}).get(field)
        )
        if left != timeline_entry.get(field):
            raise ChallengeBattleTimelineError(
                f"behavior/timeline entry mismatch for {field}"
            )
    return behavior, timeline, behavior_entry, timeline_entry


def _short_type(node: dict[str, Any]) -> str:
    value = node.get("type")
    if not isinstance(value, str) or not value:
        raise ChallengeBattleTimelineError("task node has no type")
    return value.rsplit(".", 1)[-1]


def _active_graph(
    task_graph: dict[str, Any],
) -> tuple[dict[int, dict[str, Any]], int, int]:
    raw_nodes = task_graph.get("nodes")
    root_id = task_graph.get("root_id")
    if not isinstance(raw_nodes, list) or type(root_id) is not int:
        raise ChallengeBattleTimelineError("invalid behavior task graph")
    all_nodes: dict[int, dict[str, Any]] = {}
    for node in raw_nodes:
        node_id = node.get("id") if isinstance(node, dict) else None
        if type(node_id) is not int or node_id in all_nodes:
            raise ChallengeBattleTimelineError("task graph has invalid/duplicate node ID")
        all_nodes[node_id] = node
    active = {
        node_id: node
        for node_id, node in all_nodes.items()
        if node.get("active_graph") is True and node.get("effective_enabled") is True
    }
    if root_id not in active:
        raise ChallengeBattleTimelineError("active task graph has no root")
    for node_id, node in active.items():
        parent_id = node.get("parent_id")
        if node_id == root_id:
            if parent_id is not None:
                raise ChallengeBattleTimelineError("root task unexpectedly has a parent")
        elif type(parent_id) is not int or parent_id not in active:
            raise ChallengeBattleTimelineError(
                f"active task {node_id} has no active parent"
            )
        child_ids = node.get("child_ids")
        if not isinstance(child_ids, list) or any(type(item) is not int for item in child_ids):
            raise ChallengeBattleTimelineError(f"task {node_id} has invalid child IDs")
        for child_id in child_ids:
            child = all_nodes.get(child_id)
            if child is None:
                raise ChallengeBattleTimelineError(
                    f"task {node_id} references missing child {child_id}"
                )
            if child_id in active and child.get("parent_id") != node_id:
                raise ChallengeBattleTimelineError(
                    f"task {child_id} parent relation is inconsistent"
                )
    visiting: set[int] = set()
    visited: set[int] = set()

    def walk(node_id: int) -> None:
        if node_id in visiting:
            raise ChallengeBattleTimelineError("active task graph contains a cycle")
        if node_id in visited:
            raise ChallengeBattleTimelineError(
                f"active task {node_id} is reachable more than once"
            )
        visiting.add(node_id)
        for child_id in _children(active[node_id], active):
            walk(child_id)
        visiting.remove(node_id)
        visited.add(node_id)

    walk(root_id)
    if visited != set(active):
        missing = sorted(set(active) - visited)
        raise ChallengeBattleTimelineError(
            f"active task graph has disconnected nodes {missing[:5]}"
        )
    return active, root_id, len(all_nodes) - len(active)


def _children(node: dict[str, Any], active: dict[int, dict[str, Any]]) -> list[int]:
    return [item for item in node.get("child_ids", []) if item in active]


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _fixed_60fps_projection(
    duration: Decimal, *, comparison: str, minimum_updates: int = 1
) -> dict[str, Any]:
    """Project a native float accumulator under an explicit fixed-step model.

    The pinned client rounds the scaled fixed-60 delta to three decimals in
    ``SpotManagement.UpdateSpot`` before passing it to ``BTContext``.
    """

    if comparison not in {"gte", "gt"} or minimum_updates < 1:
        raise ChallengeBattleTimelineError("invalid fixed-step projection contract")
    target = _float32(float(duration))
    delta = _float32(float(SPOT_TICK_DELTA_SECONDS))
    elapsed = _float32(0.0)
    update_count = 0
    while True:
        update_count += 1
        elapsed = _float32(elapsed + delta)
        reached = elapsed >= target if comparison == "gte" else elapsed > target
        if update_count >= minimum_updates and reached:
            break
        if update_count > 10_000_000:
            raise ChallengeBattleTimelineError("fixed-step projection did not converge")
    return {
        "status": "exact_build_spot_tick_delta_projection",
        "delta_model": "spot_update_round_3_float32",
        "tick_delta_seconds_float32": SPOT_TICK_DELTA_SECONDS,
        "duration_float32": format(target, ".9g"),
        "comparison": comparison,
        "terminal_update_count_1_based": update_count,
        "terminal_offset_from_task_start_frames": update_count - 1,
        "first_update_occurs_on_task_start_frame": True,
    }


def _manual_timeline_projection(seconds: Any) -> dict[str, Any]:
    """Project a Manual PlayableGraph advanced by the rounded Spot tick."""

    try:
        decimal = Decimal(str(seconds))
        target = float(decimal)
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        raise ChallengeBattleTimelineError("invalid timeline clock target") from exc
    if not decimal.is_finite() or decimal < 0:
        raise ChallengeBattleTimelineError("invalid timeline clock target")
    delta = _float32(float(SPOT_TICK_DELTA_SECONDS))
    elapsed = 0.0
    update_count = 0
    while elapsed < target:
        update_count += 1
        elapsed += delta
        if update_count > 10_000_000:
            raise ChallengeBattleTimelineError(
                "manual timeline projection did not converge"
            )
    return {
        "status": "exact_build_manual_playable_graph_projection",
        "delta_model": "spot_update_round_3_float32",
        "tick_delta_seconds_float32": SPOT_TICK_DELTA_SECONDS,
        "clock_accumulator": "PlayableGraph_double_manual_time",
        "target_seconds_decimal": format(decimal, "f"),
        "comparison": "gte",
        "terminal_update_count_1_based": update_count,
        "offset_from_timeline_action_start_frames": update_count - 1,
        "controller_first_update_offset_frames": 0,
    }


def _decimal_frames(
    value: Any,
    label: str,
    *,
    comparison: str,
    minimum_updates: int = 1,
    project_from_task_start: bool = True,
) -> dict[str, Any]:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ChallengeBattleTimelineError(f"{label}: invalid duration") from exc
    if not decimal.is_finite() or decimal < 0:
        raise ChallengeBattleTimelineError(f"{label}: invalid duration")
    frame_value = decimal * FPS
    integral = frame_value == frame_value.to_integral_value()
    result = {
        "seconds_decimal": format(decimal, "f"),
        "configured_frame_60fps": (
            int(frame_value) if integral else format(frame_value, "f")
        ),
        "configured_frame_integral": integral,
        "runtime_completion": {
            "status": "comparison_recovered_delta_sequence_unobserved",
            "accumulator": "float32_battle_delta_before_compare",
            "comparison": comparison,
            "terminal_update": "first_update_satisfying_comparison",
        },
    }
    result["fixed_60fps_projection"] = (
        _fixed_60fps_projection(
            decimal, comparison=comparison, minimum_updates=minimum_updates
        )
        if project_from_task_start
        else {
            "status": "not_emitted_first_counted_battle_tick_unbound",
            "delta_model": "spot_update_round_3_float32",
            "tick_delta_seconds_float32": SPOT_TICK_DELTA_SECONDS,
            "comparison": comparison,
        }
    )
    return result


def _shared_value(value: Any, field: str, expected_type: type) -> Any:
    if not isinstance(value, dict):
        raise ChallengeBattleTimelineError(f"{field}: expected SharedVariable object")
    keys = {
        bool: "BooleanmValue",
        int: "Int32mValue",
    }
    result = value.get(keys[expected_type])
    if type(result) is not expected_type:
        raise ChallengeBattleTimelineError(f"{field}: invalid SharedVariable value")
    return result


_GENERIC_OPS = {
    "Sequence": "sequence",
    "Selector": "selector",
    "Parallel": "parallel",
    "Repeater": "repeat",
    "Inverter": "invert",
    "ReturnSuccess": "force_status",
    "ReturnFailure": "force_status",
}


def _node_op(node: dict[str, Any]) -> str:
    short = _short_type(node)
    if short in _GENERIC_OPS:
        return _GENERIC_OPS[short]
    if short == "InitVariables":
        return "custom_initialization_scope"
    if short == "PatternSequence":
        return "custom_pattern_timeout"
    if short == "SpotRandomSelector":
        return "custom_random_selector"
    if short == "SpotRandomSequence":
        return "custom_random_sequence"
    if short == "TimeCount":
        return "custom_wait"
    if short in {"IsTargetAlive", "isPhaseAction"}:
        return "custom_guard"
    return "custom_action"


def _control_policy(
    node: dict[str, Any], active: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    short = _short_type(node)
    op = _node_op(node)
    children = _children(node, active)
    if op in {
        "repeat",
        "invert",
        "force_status",
        "custom_initialization_scope",
        "custom_pattern_timeout",
    } and len(children) != 1:
        raise ChallengeBattleTimelineError(
            f"task {node.get('id')} ({short}) requires exactly one active child"
        )
    if op in {
        "sequence",
        "selector",
        "parallel",
        "custom_random_selector",
        "custom_random_sequence",
    } and not children:
        raise ChallengeBattleTimelineError(
            f"task {node.get('id')} ({short}) requires an active child"
        )
    params = node.get("params")
    if not isinstance(params, dict):
        raise ChallengeBattleTimelineError(f"task {node.get('id')}: invalid params")
    if op == "sequence":
        return {
            "status": "vendor_documented",
            "order": "left_to_right",
            "continue_on": "success",
            "terminal_failure": "first_child_failure",
            "terminal_success": "all_children_success",
        }
    if op == "selector":
        return {
            "status": "vendor_documented",
            "order": "left_to_right",
            "continue_on": "failure",
            "terminal_success": "first_child_success",
            "terminal_failure": "all_children_failure",
        }
    if op == "parallel":
        return {
            "status": "vendor_documented",
            "start": "all_children_share_parent_activation",
            "terminal_failure": "first_child_failure_aborts_other_children",
            "terminal_success": "all_children_success",
        }
    if op == "repeat":
        repeat_forever = _shared_value(
            params.get("SharedBoolrepeatForever"), "repeatForever", bool
        )
        end_on_failure = _shared_value(
            params.get("SharedBoolendOnFailure"), "endOnFailure", bool
        )
        count = _shared_value(params.get("SharedIntcount"), "count", int)
        if count < 0:
            raise ChallengeBattleTimelineError("Repeater count cannot be negative")
        return {
            "status": "vendor_documented_parameters_preserved",
            "repeat_forever": repeat_forever,
            "count": count,
            "end_on_failure": end_on_failure,
            "iteration_max_exclusive": None if repeat_forever else count,
        }
    if op == "invert":
        return {
            "status": "vendor_documented",
            "running": "preserved",
            "success": "failure",
            "failure": "success",
        }
    if op == "force_status":
        return {
            "status": "vendor_documented",
            "child_duration": "preserved",
            "forced_terminal_status": (
                "success" if short == "ReturnSuccess" else "failure"
            ),
        }
    if op == "custom_pattern_timeout":
        contract = task_contract(short)
        if contract is None:
            raise ChallengeBattleTimelineError("PatternSequence contract is unavailable")
        configured_result = params.get("PatternResult_timeOutResult")
        timeout_terminal_status = {
            "Success": "success",
            "Failure": "failure",
        }.get(configured_result)
        if timeout_terminal_status is None:
            raise ChallengeBattleTimelineError(
                f"task {node.get('id')}: unsupported PatternSequence timeout result"
            )
        return {
            "status": contract["status"],
            "runtime_contract_ref": short,
            "configured_timeout": _decimal_frames(
                params.get("Single_timeOut"),
                f"task {node.get('id')} timeout",
                comparison="gte",
                project_from_task_start=False,
            ),
            "configured_timeout_result": configured_result,
            "timeout_terminal_status": timeout_terminal_status,
            "normal_child_flow": contract["normal_flow"],
            "timeout_runtime": contract["timeout"],
            "unresolved": ["live_battle_delta_sequence", "absolute_pattern_start"],
        }
    if op in {"custom_random_selector", "custom_random_sequence"}:
        use_seed = params.get("BooleanuseSeed")
        seed = params.get("Int32seed")
        if type(use_seed) is not bool or type(seed) is not int:
            raise ChallengeBattleTimelineError(
                f"task {node.get('id')}: invalid custom random parameters"
            )
        contract = task_contract(short)
        if contract is None:
            raise ChallengeBattleTimelineError(f"{short} contract is unavailable")
        return {
            "status": contract["status"],
            "runtime_contract_ref": short,
            "use_seed": use_seed,
            "serialized_seed": seed,
            "fixed_seed_injected_by_pipeline": False,
            "normal_child_flow": contract["normal_flow"],
            "rng": contract["rng"],
            "unresolved": [
                "System.Random_default_runtime_state",
                "prior_rng_consumption_history",
                "resulting_child_permutation",
            ],
        }
    if op == "custom_wait":
        timer = node.get("timer")
        if not isinstance(timer, dict):
            raise ChallengeBattleTimelineError(
                f"task {node.get('id')}: TimeCount has no timer metadata"
            )
        contract = task_contract(short)
        if contract is None:
            raise ChallengeBattleTimelineError("TimeCount contract is unavailable")
        configured_duration = _decimal_frames(
            timer.get("seconds_decimal"),
            f"task {node.get('id')} TimeCount",
            comparison="gte",
        )
        if timer.get("mode") == "AttackTime":
            configured_duration["fixed_60fps_projection"] = {
                "status": "not_emitted_runtime_AttackTime_replaces_custom_time",
                "comparison": "gte",
            }
        return {
            "status": contract["status"],
            "runtime_contract_ref": short,
            "mode": timer.get("mode"),
            "configured_duration": configured_duration,
            "duration_source": contract["duration_source"],
            "terminal_runtime": contract["terminal"],
        }
    if op == "custom_initialization_scope":
        contract = task_contract(short)
        if contract is None:
            raise ChallengeBattleTimelineError("InitVariables contract is unavailable")
        return {
            "status": contract["status"],
            "runtime_contract_ref": short,
            "child_activation_after_initialization": "same_behavior_manager_tick",
            "normal_flow": contract["normal_flow"],
        }
    if op == "custom_guard":
        contract = task_contract(short)
        return {
            "status": (
                contract["status"]
                if contract is not None
                else "client_implementation_unavailable"
            ),
            "runtime_contract_ref": short if contract is not None else None,
            "evaluation": "task_status_symbolic",
            "parameters": params,
        }
    duration_hint = None
    if short == "TeleportToVer2" and "Single_teleportTime" in params:
        duration_hint = _decimal_frames(
            params["Single_teleportTime"],
            f"task {node.get('id')} teleport",
            comparison="gt",
            minimum_updates=2,
        )
    contract = task_contract(short)
    return {
        "status": (
            contract["status"]
            if contract is not None
            else "client_implementation_unavailable"
        ),
        "runtime_contract_ref": short if contract is not None else None,
        "completion": (
            contract.get("terminal", "custom_task_terminal_symbolic")
            if contract is not None
            else "custom_task_terminal_symbolic"
        ),
        "configured_duration_hint": duration_hint,
        "parameters": params,
        "skill_action": bool(node.get("shot_keys")),
        "children": _children(node, active),
    }


def _task_start(node_id: int) -> dict[str, Any]:
    return {"op": "task_start", "node_id": node_id}


def _task_terminal(node_id: int, required_status: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"op": "task_terminal", "node_id": node_id}
    if required_status is not None:
        value["required_status"] = required_status
    return value


def _repeat_iteration_start(
    repeat_node: dict[str, Any],
    body_node_id: int,
    active: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    repeat_node_id = repeat_node["id"]
    iteration_var = f"repeat_{repeat_node_id}"
    policy = _control_policy(repeat_node, active)
    prior_statuses = (
        ["success"] if policy["end_on_failure"] else ["success", "failure"]
    )
    return {
        "op": "repeat_iteration_start",
        "repeat_node_id": repeat_node_id,
        "body_node_id": body_node_id,
        "iteration_var": iteration_var,
        "definition": {
            "base_case": {
                "when": {"op": "eq", "variable": iteration_var, "value": 0},
                "frame": _task_start(repeat_node_id),
            },
            "recursive_case": {
                "when": {"op": "gt", "variable": iteration_var, "value": 0},
                "frame": {
                    "op": "repeat_next_iteration_dispatch",
                    "prior_body_terminal": {
                        "op": "repeat_body_terminal",
                        "body_node_id": body_node_id,
                        "iteration": {
                            "op": "subtract",
                            "variable": iteration_var,
                            "value": 1,
                        },
                        "required_statuses": prior_statuses,
                        "aborted_continues": False,
                    },
                    "same_tick_after_prior_terminal": True,
                    "behavior_manager_execution_policy": "client_runtime_recovered",
                },
            },
        },
    }


def _random_child_start(
    random_node: dict[str, Any],
    child_node_id: int,
    active: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    random_node_id = random_node["id"]
    short = _short_type(random_node)
    contract = task_contract(short)
    if contract is None:
        raise ChallengeBattleTimelineError(f"{short} contract is unavailable")
    continue_status = (
        "failure" if short == "SpotRandomSelector" else "success"
    )
    activation_index = {
        "op": "task_activation_index",
        "node_id": random_node_id,
        "increments_on": "each_OnStart",
    }
    permutation = {
        "op": "random_permutation",
        "random_node_id": random_node_id,
        "activation_index": activation_index,
    }
    return {
        "op": "custom_random_child_start",
        "random_node_id": random_node_id,
        "child_node_id": child_node_id,
        "permutation_variable": permutation,
        "activation_index": activation_index,
        "permutation_source": contract["rng"],
        "child_rank": {
            "op": "index_of",
            "sequence": permutation,
            "node_id": child_node_id,
        },
        "definition": {
            "base_case": {
                "when_rank": 0,
                "frame": _task_start(random_node_id),
            },
            "recursive_case": {
                "when_rank_gt": 0,
                "frame": {
                    "op": "task_terminal",
                    "node_id": {
                        "op": "permutation_at_previous_rank",
                        "sequence": permutation,
                        "current_node_id": child_node_id,
                    },
                    "required_status": continue_status,
                },
            },
        },
        "binding_status": "client_runtime_recovered_random_order_symbolic",
        "scheduler_relation": "selected_child_starts_in_same_tick",
    }


def _pattern_deadline(
    pattern_node_id: int, active: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    pattern_node = active[pattern_node_id]
    policy = _control_policy(pattern_node, active)
    return {
        "op": "configured_timeout_deadline",
        "pattern_node_id": pattern_node_id,
        "start": _task_start(pattern_node_id),
        "configured_timeout": policy["configured_timeout"],
        "comparison_tick_order": (
            "accumulate_once_per_new_battle_tick_then_compare_gte_at_reevaluation_end"
        ),
        "threshold_effect": "abort_current_child_then_mark_pattern_interrupted",
        "runtime_contract_ref": "PatternSequence",
    }


def _node_start_expression(
    node_id: int,
    active: dict[int, dict[str, Any]],
    root_id: int,
) -> dict[str, Any]:
    if node_id == root_id:
        return {
            "op": "variable",
            "name": "behavior_enable_frame",
            "origin": "battle_start",
            "binding_status": "unresolved",
        }
    node = active[node_id]
    parent_id = node.get("parent_id")
    parent = active[parent_id]
    siblings = _children(parent, active)
    try:
        position = siblings.index(node_id)
    except ValueError as exc:
        raise ChallengeBattleTimelineError(
            f"task {node_id} absent from active parent child list"
        ) from exc
    parent_op = _node_op(parent)
    if parent_op in {"sequence", "selector"}:
        if position == 0:
            return _task_start(parent_id)
        required = "success" if parent_op == "sequence" else "failure"
        return _task_terminal(siblings[position - 1], required)
    if parent_op == "parallel":
        return _task_start(parent_id)
    if parent_op == "repeat":
        return _repeat_iteration_start(parent, node_id, active)
    if parent_op == "custom_pattern_timeout":
        return {
            "op": "custom_pattern_child_start",
            "pattern_node_id": parent_id,
            "pattern_start": _task_start(parent_id),
            "binding_status": "client_runtime_recovered",
            "scheduler_relation": "same_tick_no_pattern_inserted_delay",
        }
    if parent_op in {"custom_random_selector", "custom_random_sequence"}:
        return _random_child_start(parent, node_id, active)
    if parent_op == "custom_initialization_scope":
        return {
            "op": "custom_initialization_child_start",
            "scope_node_id": parent_id,
            "scope_start": _task_start(parent_id),
            "binding_status": "client_runtime_recovered",
            "scheduler_relation": "same_tick_transparent_wrapper",
        }
    return _task_start(parent_id)


def _status_guard(
    node_id: int, status: str, active: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    node = active[node_id]
    if _node_op(node) == "custom_guard":
        contract = task_contract(_short_type(node))
        return {
            "op": "condition",
            "node_id": node_id,
            "condition_type": _short_type(node),
            "parameters": node.get("params") or {},
            "at": _task_start(node_id),
            "required_task_status": status,
            "evaluation_status": (
                contract["status"]
                if contract is not None
                else "client_implementation_unavailable"
            ),
            "runtime_contract_ref": _short_type(node) if contract is not None else None,
        }
    return {"op": "task_status", "node_id": node_id, "status": status}


def _activation_context(
    node_id: int,
    active: dict[int, dict[str, Any]],
    root_id: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    chain: list[tuple[dict[str, Any], dict[str, Any]]] = []
    current = active[node_id]
    while current.get("id") != root_id:
        parent = active[current["parent_id"]]
        chain.append((parent, current))
        current = parent
    guards: list[dict[str, Any]] = []
    choices: list[dict[str, Any]] = []
    iterations: list[dict[str, Any]] = []
    for parent, child in reversed(chain):
        parent_id = parent["id"]
        siblings = _children(parent, active)
        position = siblings.index(child["id"])
        op = _node_op(parent)
        if op == "sequence":
            guards.extend(
                _status_guard(item, "success", active) for item in siblings[:position]
            )
        elif op == "selector":
            guards.extend(
                _status_guard(item, "failure", active) for item in siblings[:position]
            )
            choices.append(
                {
                    "node_id": parent_id,
                    "kind": "ordered_selector_branch",
                    "child_node_id": child["id"],
                    "child_position": position,
                }
            )
        elif op == "parallel":
            guards.append(
                {
                    "op": "parallel_branch_active",
                    "parallel_node_id": parent_id,
                    "branch_node_id": child["id"],
                    "not_preempted_before": _task_start(node_id),
                }
            )
        elif op == "repeat":
            policy = _control_policy(parent, active)
            prior_statuses = (
                ["success"]
                if policy["end_on_failure"]
                else ["success", "failure"]
            )
            item = {
                "repeat_node_id": parent_id,
                "variable": f"repeat_{parent_id}",
                "min_inclusive": 0,
                "max_exclusive": policy["iteration_max_exclusive"],
                "repeat_forever": policy["repeat_forever"],
                "continue_after_failure": not policy["end_on_failure"],
                "prior_iteration_required_statuses": prior_statuses,
                "aborted_continues": False,
            }
            iterations.append(item)
            guards.append({"op": "repeat_iteration", **item})
        elif op == "custom_pattern_timeout":
            guards.append(
                {
                    "op": "custom_pattern_branch_active",
                    "pattern_node_id": parent_id,
                    "deadline": _pattern_deadline(parent_id, active),
                    "not_timed_out_before": _task_start(node_id),
                    "same_tick_timeout_vs_dispatch_order": (
                        "reevaluation_end_aborts_current_child_before_pattern_terminal"
                    ),
                    "binding_status": "client_runtime_recovered",
                }
            )
        elif op in {"custom_random_selector", "custom_random_sequence"}:
            contract = task_contract(_short_type(parent))
            choice = {
                "node_id": parent_id,
                "kind": op,
                "child_node_id": child["id"],
                "serialized_child_position": position,
                "serialized_children": siblings,
                "permutation_variable": {
                    "op": "random_permutation",
                    "random_node_id": parent_id,
                    "activation_index": {
                        "op": "task_activation_index",
                        "node_id": parent_id,
                        "increments_on": "each_OnStart",
                    },
                },
                "selection_or_order_status": (
                    "runtime_permutation_unresolved_without_seed_and_rng_history"
                ),
                "runtime_contract_ref": _short_type(parent),
                "rng": contract["rng"] if contract is not None else None,
            }
            choices.append(choice)
            guards.append({"op": "custom_random_child_activated", **choice})
        elif op == "custom_initialization_scope":
            guards.append(
                {
                    "op": "custom_initialization_completed",
                    "scope_node_id": parent_id,
                    "binding_status": "client_runtime_recovered_same_tick",
                }
            )
    return guards, choices, iterations


def _terminal_expression(
    node: dict[str, Any], active: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    node_id = node["id"]
    op = _node_op(node)
    children = _children(node, active)
    if op == "sequence":
        return {
            "op": "sequence_terminal",
            "children": children,
            "failure": "first_failure",
            "success": "last_child_success",
        }
    if op == "selector":
        return {
            "op": "selector_terminal",
            "children": children,
            "success": "first_success",
            "failure": "last_child_failure",
        }
    if op == "parallel":
        return {
            "op": "parallel_terminal",
            "children": children,
            "failure": "first_failure_aborts_others",
            "success": "all_success",
        }
    if op == "repeat":
        return {
            "op": "repeat_terminal",
            "repeat_node_id": node_id,
            "body_node_id": children[0] if len(children) == 1 else None,
        }
    if op == "invert":
        return {"op": "invert_terminal", "child_node_id": children[0]}
    if op == "force_status":
        return {
            "op": "force_status_terminal",
            "child_node_id": children[0],
            "status": (
                "success" if _short_type(node) == "ReturnSuccess" else "failure"
            ),
        }
    if op == "custom_pattern_timeout":
        return {
            "op": "custom_pattern_terminal",
            "pattern_node_id": node_id,
            "child_node_id": children[0] if len(children) == 1 else None,
            "deadline": _pattern_deadline(node_id, active),
            "binding_status": "client_runtime_recovered",
            "runtime_contract_ref": "PatternSequence",
        }
    if op in {"custom_random_selector", "custom_random_sequence"}:
        return {
            "op": "custom_random_terminal",
            "random_node_id": node_id,
            "children": children,
            "binding_status": "client_runtime_recovered_random_order_symbolic",
            "runtime_contract_ref": _short_type(node),
        }
    if op == "custom_initialization_scope":
        return {
            "op": "custom_initialization_scope_terminal",
            "scope_node_id": node_id,
            "children": children,
            "binding_status": "client_runtime_recovered",
            "runtime_contract_ref": "InitVariables",
        }
    if op == "custom_wait":
        return {
            "op": "custom_timer_terminal",
            "node_id": node_id,
            "configured_duration": _control_policy(node, active)[
                "configured_duration"
            ],
            "binding_status": "client_runtime_recovered_delta_sequence_symbolic",
            "runtime_contract_ref": "TimeCount",
        }
    short = _short_type(node)
    if short in {"MoveToVer2", "MoveToVer3"}:
        terminal_op = "movement_complete"
    elif short == "TeleportToVer2":
        terminal_op = "teleport_complete"
    elif short == "QuickTimeEvent":
        terminal_op = "qte_terminal"
    elif node.get("shot_keys"):
        terminal_op = "skill_action_terminal"
    else:
        terminal_op = "custom_task_terminal"
    contract = task_contract(short)
    result = {
        "op": terminal_op,
        "node_id": node_id,
        "binding_status": (
            contract["status"]
            if contract is not None
            else "client_implementation_unavailable"
        ),
    }
    if contract is not None:
        result["runtime_contract_ref"] = short
        result["runtime_terminal"] = contract.get("terminal")
        result["external_inputs"] = contract.get("external_inputs", [])
        offset = (contract.get("terminal") or {}).get(
            "offset_from_task_start_ticks"
        )
        if offset == 0:
            result["terminal_frame"] = _task_start(node_id)
    return result


def _compile_nodes(
    active: dict[int, dict[str, Any]], root_id: int
) -> list[dict[str, Any]]:
    result = []
    for node_id in sorted(active):
        node = active[node_id]
        guards, choices, iterations = _activation_context(node_id, active, root_id)
        result.append(
            {
                "id": node_id,
                "source_type": node["type"],
                "op": _node_op(node),
                "children": _children(node, active),
                "instant": node.get("instant"),
                "abort_type": node.get("abort_type"),
                "shot_keys": node.get("shot_keys") or [],
                "policy": _control_policy(node, active),
                "activation": {
                    "start_frame": _node_start_expression(node_id, active, root_id),
                    "guards": guards,
                    "choice_path": choices,
                    "iteration_vars": iterations,
                },
                "terminal": _terminal_expression(node, active),
            }
        )
    return result


def _skill_rows_by_shot(timeline_entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    rows = timeline_entry.get("skill_timeline_join")
    if not isinstance(rows, list):
        raise ChallengeBattleTimelineError("timeline entry has no skill join rows")
    for row in rows:
        shot = row.get("shot_key") if isinstance(row, dict) else None
        if not isinstance(shot, str) or shot in result:
            raise ChallengeBattleTimelineError("timeline skill rows have invalid shots")
        result[shot] = row
    return result


def _monster_skills_by_shot(behavior_entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    skills = behavior_entry.get("monster_skills")
    if not isinstance(skills, list):
        raise ChallengeBattleTimelineError("behavior entry has no monster skills")
    for skill in skills:
        shot = (skill.get("animation") or {}).get("shot_key") if isinstance(skill, dict) else None
        if not isinstance(shot, str) or shot in result:
            raise ChallengeBattleTimelineError("monster skills have invalid shots")
        result[shot] = skill
    return result


def _bind_s39_node_9_terminal_projection(
    compiled_nodes: list[dict[str, Any]],
    behavior_entry: dict[str, Any],
    timeline_entry: dict[str, Any],
    runtime_evidence: dict[str, Any],
) -> None:
    """Bind the exact node-9 coroutine wait chain for the pinned s39 build."""

    route = runtime_evidence.get("season_39_node_9_terminal_route")
    if not isinstance(route, dict) or route.get("status") != (
        "exact_build_native_and_serialized_asset_bound"
    ):
        raise ChallengeBattleTimelineError("season 39 node-9 timing route is unavailable")
    matches = [item for item in compiled_nodes if item.get("id") == 9]
    if len(matches) != 1:
        raise ChallengeBattleTimelineError("season 39 node-9 timing site drift")
    node = matches[0]
    source_type = node.get("source_type")
    if (
        not isinstance(source_type, str)
        or source_type.rsplit(".", 1)[-1] != "AttackV3"
        or node.get("shot_keys") != ["Shot_02"]
        or node.get("children") != []
    ):
        raise ChallengeBattleTimelineError("season 39 node-9 attack contract drift")

    skill = _monster_skills_by_shot(behavior_entry).get("Shot_02") or {}
    timing = skill.get("timing") or {}
    rows = _skill_rows_by_shot(timeline_entry)
    row = rows.get("Shot_02") or {}
    if (
        skill.get("skill_id") != route.get("skill_id")
        or (skill.get("animation") or {}).get("enum_value")
        != route.get("ani_number")
        or timing.get("casting_centiseconds") != 50
        or timing.get("delay_centiseconds") != 50
        or timing.get("shot_count") != 1
        or timing.get("shot_timing_enum") != 1
        or timing.get("is_using_timeline") is not False
        or row.get("skill_id") != route.get("skill_id")
        or row.get("shot_key") != route.get("shot_key")
        or timeline_entry.get("bundle_content_hash")
        != runtime_evidence["season_39_get_shot_time_route"][
            "spotmonster_bundle_content_hash"
        ]
    ):
        raise ChallengeBattleTimelineError("season 39 node-9 timing inputs drift")

    weapon = route.get("serialized_weapon_evidence") or {}
    trace_program = route.get("fixed_60fps_projection", {}).get("trace_program")
    wait_fire_runs = [
        item
        for item in trace_program or []
        if isinstance(item, dict)
        and item.get("op") == "yield_immediate_nested_coroutines"
        and item.get("kind") == "WaitFire"
    ]
    if (
        weapon.get("weapon_object_enum") != 2
        or weapon.get("weapon_object_enum_2_match_count") != 1
        or weapon.get("muzzle_count") != 14
        or len(wait_fire_runs) != 1
        or wait_fire_runs[0].get("count") != weapon.get("muzzle_count")
    ):
        raise ChallengeBattleTimelineError("season 39 node-9 weapon route drift")

    projection = {
        "status": "exact_build_native_and_serialized_asset_bound",
        "delta_model": "fixed_60fps_float32_projection",
        "tick_delta_seconds_float32": route["fixed_60fps_projection"][
            "tick_delta_seconds_float32"
        ],
        "coroutine_context": route["context_order"]["coroutine_context"],
        "first_coroutine_update_offset_frames": route["context_order"][
            "first_coroutine_update_offset_frames"
        ],
        "completion_observation": route["context_order"][
            "completion_observed_by_behavior_manager"
        ],
        "wait_threshold": route["fixed_60fps_projection"]["wait_threshold"],
        "wait_resume": route["fixed_60fps_projection"]["wait_resume"],
        "newly_yielded_current_processing": route["fixed_60fps_projection"][
            "newly_yielded_current_processing"
        ],
        "completed_child_parent_resume": route["fixed_60fps_projection"][
            "completed_child_parent_resume"
        ],
        "wait_chain": deepcopy(route["wait_chain"]),
        "trace_program": deepcopy(
            route["fixed_60fps_projection"]["trace_program"]
        ),
        "reference_absolute_trace": deepcopy(route["reference_absolute_trace"]),
        "terminal_status": route["fixed_60fps_projection"]["terminal_status"],
        "runtime_evidence_ref": "season_39_node_9_terminal_route",
    }
    node["policy"]["fixed_60fps_tick_coroutine_projection"] = deepcopy(
        projection
    )
    terminal = node["terminal"]
    terminal["binding_status"] = (
        "exact_build_native_and_serialized_asset_bound_fixed60_projection"
    )
    terminal["fixed_60fps_tick_coroutine_projection"] = deepcopy(projection)
    terminal["resolved_external_inputs"] = terminal.pop("external_inputs", [])


def _bind_s39_timeline_skill_projections(
    compiled_nodes: list[dict[str, Any]],
    behavior_entry: dict[str, Any],
    timeline_entry: dict[str, Any],
    runtime_evidence: dict[str, Any],
) -> None:
    """Bind the Manual PlayableGraph clock used by all active s39 TimelineSkill nodes."""

    route = runtime_evidence.get("season_39_timeline_skill_terminal_route")
    if not isinstance(route, dict) or route.get("status") != (
        "exact_build_native_serialized_timeline_and_scheduler_bound"
    ):
        raise ChallengeBattleTimelineError(
            "season 39 TimelineSkill scheduler route is unavailable"
        )
    tick_order = route.get("tick_order") or {}
    spot_tick = route.get("spot_tick_time") or {}
    manual_graph = route.get("manual_graph") or {}
    if (
        tick_order.get("update_tick_list_order")
        != ["contexts", "presentations", "ticks"]
        or tick_order.get("first_timeline_update_offset_frames") != 0
        or tick_order.get("timeline_completion_observed_by_bt_context")
        != "next_frame"
        or spot_tick.get("tick_delta_seconds_float32")
        != SPOT_TICK_DELTA_SECONDS
        or manual_graph.get("director_update_mode") != "Manual"
        or manual_graph.get("advance_delta_source")
        != "float32_accumulated_spot_tick_delta"
    ):
        raise ChallengeBattleTimelineError(
            "season 39 TimelineSkill clock evidence drift"
        )

    raw_nodes = {
        item.get("id"): item
        for item in (behavior_entry.get("task_graph") or {}).get("nodes", [])
        if isinstance(item, dict) and type(item.get("id")) is int
    }
    compiled = {item.get("id"): item for item in compiled_nodes}
    rows = _skill_rows_by_shot(timeline_entry)
    expected_pairs = set(_S39_EXACT_MARKERS)
    actual_pairs: set[tuple[int, str]] = set()
    for node_id, node in compiled.items():
        if not isinstance(node, dict) or node.get("source_type", "").rsplit(
            ".", 1
        )[-1] != "TimelineSkill":
            continue
        shots = node.get("shot_keys")
        if not isinstance(shots, list) or len(shots) != 1:
            raise ChallengeBattleTimelineError(
                f"task {node_id}: TimelineSkill shot route is not singular"
            )
        shot = shots[0]
        actual_pairs.add((node_id, shot))
        raw = raw_nodes.get(node_id) or {}
        params = raw.get("params") or {}
        if (
            params.get("BooleanFailueCheck") is not False
            or params.get("Boolean_isKeepCastingTime") is not False
            or params.get("Boolean_isUseContinuousTimeline") is not True
            or params.get("Boolean_moveStopAtStart") is not True
        ):
            raise ChallengeBattleTimelineError(
                f"task {node_id}: unsupported TimelineSkill parameters"
            )
        row = rows.get(shot) or {}
        duration_record = row.get("timeline_duration_frames_60fps") or {}
        asset = row.get("timeline_asset") or {}
        duration_seconds = row.get("timeline_duration_seconds")
        markers = row.get("attack_markers_relative_to_timeline_start")
        if (
            row.get("route_status") != "exact_monster_timeline_route"
            or row.get("event_frame_status") != "timeline_attack_marker_exact"
            or duration_record.get("status") != "exact_integer"
            or type(duration_record.get("frame")) is not int
            or not isinstance(duration_seconds, (int, float))
            or asset.get("framerate") != 60.0
            or asset.get("duration_mode") != 1
            or not isinstance(markers, list)
            or not markers
        ):
            raise ChallengeBattleTimelineError(
                f"task {node_id}: exact TimelineSkill asset route drift"
            )
        duration_clock = _manual_timeline_projection(duration_seconds)
        marker_projections = []
        for marker in markers:
            if not isinstance(marker, dict):
                raise ChallengeBattleTimelineError(
                    f"task {node_id}: invalid timeline marker"
                )
            marker_clock = _manual_timeline_projection(marker.get("time_seconds"))
            if (
                marker_clock["offset_from_timeline_action_start_frames"]
                >= duration_clock["offset_from_timeline_action_start_frames"]
            ):
                raise ChallengeBattleTimelineError(
                    f"task {node_id}: attack marker is not before timeline end"
                )
            marker_projections.append(
                {
                    "path_id": marker.get("path_id"),
                    "asset_nominal_frame_60fps": (
                        marker.get("frame_60fps") or {}
                    ).get("frame"),
                    **marker_clock,
                }
            )
        stop_offset = duration_clock[
            "offset_from_timeline_action_start_frames"
        ]
        projection = {
            "status": "exact_build_native_and_serialized_asset_bound",
            "delta_model": duration_clock["delta_model"],
            "tick_delta_seconds_float32": duration_clock[
                "tick_delta_seconds_float32"
            ],
            "clock_accumulator": duration_clock["clock_accumulator"],
            "duration_seconds_decimal": duration_clock[
                "target_seconds_decimal"
            ],
            "duration_comparison": duration_clock["comparison"],
            "duration_terminal_update_count_1_based": duration_clock[
                "terminal_update_count_1_based"
            ],
            "controller_first_update_offset_frames": 0,
            "controller_stop_offset_from_task_start_frames": stop_offset,
            "completion_observation": "next_frame_earlier_BTContext_tick",
            "completion_observation_offset_frames": 1,
            "terminal_offset_from_task_start_frames": stop_offset + 1,
            "terminal_status": "success",
            "asset": deepcopy(asset),
            "asset_nominal_duration_frames_60fps": duration_record["frame"],
            "marker_projections": marker_projections,
            "runtime_evidence_ref": "season_39_timeline_skill_terminal_route",
        }
        node["policy"]["fixed_60fps_timeline_terminal_projection"] = deepcopy(
            projection
        )
        terminal = node["terminal"]
        terminal["binding_status"] = (
            "exact_build_native_and_serialized_asset_bound_manual_graph_projection"
        )
        terminal["fixed_60fps_timeline_terminal_projection"] = deepcopy(
            projection
        )
        terminal["resolved_external_inputs"] = terminal.pop(
            "external_inputs", []
        )

    if actual_pairs != expected_pairs:
        raise ChallengeBattleTimelineError(
            "season 39 TimelineSkill node/shot coverage drift"
        )


def _skill_events(
    behavior_entry: dict[str, Any],
    timeline_entry: dict[str, Any],
    active: dict[int, dict[str, Any]],
    root_id: int,
    compiled_nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    timeline_rows = _skill_rows_by_shot(timeline_entry)
    skills = _monster_skills_by_shot(behavior_entry)
    if set(timeline_rows) != set(skills):
        raise ChallengeBattleTimelineError(
            "timeline rows do not exactly cover the behavior monster skills"
        )
    expected_pairs = [
        (node_id, shot)
        for node_id, node in active.items()
        for shot in (node.get("shot_keys") or [])
    ]
    if len(expected_pairs) != len(set(expected_pairs)):
        raise ChallengeBattleTimelineError("active graph has duplicate skill pairs")
    expected_pair_set = set(expected_pairs)
    expected_shot_counts = Counter(shot for _node_id, shot in expected_pairs)
    for shot, skill in skills.items():
        row = timeline_rows[shot]
        if (
            row.get("skill_id") != skill.get("skill_id")
            or row.get("monster_skill_timing") != skill.get("timing")
            or row.get("active_behavior_site_count")
            != expected_shot_counts.get(shot, 0)
        ):
            raise ChallengeBattleTimelineError(
                f"{shot}: behavior/timeline skill row drift"
            )
    raw_sites = behavior_entry.get("skill_cast_sites")
    if not isinstance(raw_sites, list):
        raise ChallengeBattleTimelineError("behavior entry has no skill cast sites")
    sites = [
        site
        for site in raw_sites
        if isinstance(site, dict)
        and site.get("active_graph") is True
        and site.get("effective_enabled") is True
    ]
    events: list[dict[str, Any]] = []
    compiled_by_id = {item["id"]: item for item in compiled_nodes}
    stats = Counter()
    seen_pairs: set[tuple[int, str]] = set()
    for site in sorted(sites, key=lambda item: item.get("node_id", -1)):
        node_id = site.get("node_id")
        if type(node_id) is not int or node_id not in active:
            raise ChallengeBattleTimelineError("active skill site has no active node")
        node = active[node_id]
        action_contract = task_contract(_short_type(node))
        shots = site.get("shot_keys")
        if not isinstance(shots, list) or shots != node.get("shot_keys") or not shots:
            raise ChallengeBattleTimelineError(
                f"task {node_id}: skill site/node shot drift"
            )
        guards, choices, iterations = _activation_context(node_id, active, root_id)
        for shot in shots:
            pair = (node_id, shot)
            if pair in seen_pairs:
                raise ChallengeBattleTimelineError(
                    f"task {node_id}: duplicate active skill site for {shot}"
                )
            seen_pairs.add(pair)
            skill = skills.get(shot)
            row = timeline_rows.get(shot)
            if skill is None or row is None:
                raise ChallengeBattleTimelineError(
                    f"task {node_id}: missing skill/timeline join for {shot}"
                )
            common = {
                "node_id": node_id,
                "source_task_type": _short_type(node),
                "runtime_contract_ref": (
                    _short_type(node) if action_contract is not None else None
                ),
                "shot_key": shot,
                "skill_id": skill.get("skill_id"),
                "guards": guards,
                "choice_path": choices,
                "iteration_vars": iterations,
            }
            events.append(
                {
                    "event_id": f"node_{node_id}_{shot.lower()}_dispatch",
                    "kind": "skill_dispatch",
                    **common,
                    "battle_frame": {
                        "status": "symbolic",
                        "expression": _task_start(node_id),
                    },
                    "evidence": "exact_behavior_action_site_and_native_OnStart_dispatch",
                    "runtime_dispatch": (
                        action_contract.get("dispatch")
                        if action_contract is not None
                        else None
                    ),
                }
            )
            stats["skill_dispatch_templates"] += 1
            markers = row.get("attack_markers_relative_to_timeline_start")
            if not isinstance(markers, list):
                raise ChallengeBattleTimelineError(
                    f"{shot}: invalid timeline attack marker list"
                )
            if row.get("event_frame_status") == "timeline_attack_marker_exact":
                route_ids = row.get("route_ids")
                if (
                    not markers
                    or row.get("route_status") != "exact_monster_timeline_route"
                    or not isinstance(route_ids, list)
                    or len(route_ids) != 1
                    or _short_type(node) != "TimelineSkill"
                    or (skill.get("timing") or {}).get("is_using_timeline") is not True
                ):
                    raise ChallengeBattleTimelineError(
                        f"{shot}: exact timeline marker contract drift"
                    )
                for marker_index, marker in enumerate(markers):
                    frame_record = (
                        marker.get("frame_60fps")
                        if isinstance(marker, dict)
                        else None
                    )
                    frame = (
                        frame_record.get("frame")
                        if isinstance(frame_record, dict)
                        else None
                    )
                    if (
                        not isinstance(frame_record, dict)
                        or frame_record.get("status") != "exact_integer"
                        or type(frame) is not int
                        or frame < 0
                    ):
                        raise ChallengeBattleTimelineError(
                            f"{shot}: non-integral exact marker"
                        )
                    timeline_projection = (
                        compiled_by_id[node_id]
                        .get("policy", {})
                        .get("fixed_60fps_timeline_terminal_projection")
                    )
                    projected_markers = (
                        timeline_projection.get("marker_projections")
                        if isinstance(timeline_projection, dict)
                        else None
                    )
                    if not isinstance(projected_markers, list):
                        raise ChallengeBattleTimelineError(
                            f"{shot}: exact marker has no runtime clock projection"
                        )
                    projected = [
                        item
                        for item in projected_markers
                        if isinstance(item, dict)
                        and item.get("path_id") == marker.get("path_id")
                    ]
                    if len(projected) != 1:
                        raise ChallengeBattleTimelineError(
                            f"{shot}: runtime marker projection route drift"
                        )
                    runtime_frame = projected[0].get(
                        "offset_from_timeline_action_start_frames"
                    )
                    if type(runtime_frame) is not int or runtime_frame < 0:
                        raise ChallengeBattleTimelineError(
                            f"{shot}: invalid runtime marker frame"
                        )
                    events.append(
                        {
                            "event_id": (
                                f"node_{node_id}_{shot.lower()}_impact_{marker_index}"
                            ),
                            "kind": "skill_effect",
                            **common,
                            "battle_frame": {
                                "status": (
                                    "exact_runtime_tick_marker_symbolic_absolute"
                                ),
                                "expression": {
                                    "op": "add",
                                    "terms": [
                                        {
                                            "op": "timeline_action_start",
                                            "node_id": node_id,
                                            "task_start_binding": (
                                                "runtime_OnStart_same_as_task_start"
                                            ),
                                        },
                                        {"op": "exact", "frames": runtime_frame},
                                    ],
                                },
                            },
                            "relative_to_timeline_action_start": {
                                "status": "exact",
                                "frames": runtime_frame,
                                "asset_nominal_frames_60fps": frame,
                                "manual_graph_projection": deepcopy(projected[0]),
                            },
                            "evidence": (
                                "authoritative_monster_timeline_attack_marker_"
                                "and_manual_graph_runtime_clock"
                            ),
                        }
                    )
                    stats["skill_effect_templates_exact_relative_marker"] += 1
            else:
                events.append(
                    {
                        "event_id": f"node_{node_id}_{shot.lower()}_impact_unresolved",
                        "kind": "skill_effect",
                        **common,
                        "battle_frame": {
                            "status": "runtime_callback_unresolved",
                            "expression": {
                                "op": "skill_runtime_effect",
                                "node_id": node_id,
                                "shot_key": shot,
                            },
                        },
                        "monster_skill_timing": skill.get("timing"),
                        "evidence": "no_exact_timeline_marker",
                    }
                )
                stats["skill_effect_templates_runtime_unresolved"] += 1
    if seen_pairs != expected_pair_set:
        missing = sorted(expected_pair_set - seen_pairs)
        extra = sorted(seen_pairs - expected_pair_set)
        raise ChallengeBattleTimelineError(
            f"active skill site set drift; missing={missing[:5]} extra={extra[:5]}"
        )
    event_ids = [event["event_id"] for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise ChallengeBattleTimelineError("compiled skill event IDs are not unique")
    return events, dict(sorted(stats.items()))


def _runtime_inventory(active: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(node["type"] for node in active.values())
    vendor = {
        "Sequence",
        "Selector",
        "Parallel",
        "Repeater",
        "Inverter",
        "ReturnSuccess",
        "ReturnFailure",
    }
    result = []
    for type_name in sorted(counts):
        short = type_name.rsplit(".", 1)[-1]
        contract = task_contract(short)
        result.append(
            {
                "type": type_name,
                "active_node_count": counts[type_name],
                "semantics_status": (
                    "vendor_documented_control_flow"
                    if short in vendor
                    else (
                        contract["status"]
                        if contract is not None
                        else "client_implementation_unavailable"
                    )
                ),
                "runtime_contract_ref": short if contract is not None else None,
                "external_inputs": (
                    contract.get("external_inputs", [])
                    if contract is not None
                    else []
                ),
            }
        )
    return result


def _validate_s39_oracles(
    active: dict[int, dict[str, Any]],
    pattern_windows: list[dict[str, Any]],
    repeaters: list[dict[str, Any]],
    random_nodes: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    if len(active) != 185:
        raise ChallengeBattleTimelineError("season 39 active-node oracle drift")
    dispatch_pairs = {
        (event["node_id"], event["shot_key"])
        for event in events
        if event.get("kind") == "skill_dispatch"
    }
    if dispatch_pairs != _S39_DISPATCH_PAIRS:
        raise ChallengeBattleTimelineError("season 39 skill-dispatch oracle drift")
    exact_events = [
        event
        for event in events
        if event.get("kind") == "skill_effect"
        and "relative_to_timeline_action_start" in event
    ]
    exact_markers = {
        (event["node_id"], event["shot_key"]): event[
            "relative_to_timeline_action_start"
        ]["frames"]
        for event in exact_events
    }
    nominal_markers = {
        (event["node_id"], event["shot_key"]): event[
            "relative_to_timeline_action_start"
        ]["asset_nominal_frames_60fps"]
        for event in exact_events
    }
    if (
        len(exact_events) != 13
        or exact_markers != _S39_RUNTIME_MARKER_OFFSETS
        or nominal_markers != _S39_EXACT_MARKERS
    ):
        raise ChallengeBattleTimelineError("season 39 exact-marker oracle drift")
    unresolved = [
        event
        for event in events
        if event.get("kind") == "skill_effect"
        and event.get("battle_frame", {}).get("status")
        == "runtime_callback_unresolved"
    ]
    if len(unresolved) != 17:
        raise ChallengeBattleTimelineError("season 39 unresolved-effect oracle drift")
    timeouts = {
        item["node_id"]: item["policy"]["configured_timeout"]["seconds_decimal"]
        for item in pattern_windows
    }
    if timeouts != _S39_PATTERN_TIMEOUTS:
        raise ChallengeBattleTimelineError("season 39 pattern-timeout oracle drift")
    if {item["node_id"] for item in repeaters} != _S39_REPEATERS:
        raise ChallengeBattleTimelineError("season 39 repeater oracle drift")
    if {item["node_id"] for item in random_nodes} != _S39_RANDOM_NODES or any(
        item["policy"].get("use_seed") is not False for item in random_nodes
    ):
        raise ChallengeBattleTimelineError("season 39 random-node oracle drift")


def build_battle_timeline(
    *,
    behavior_path: Path,
    timeline_path: Path,
    season: int,
    runtime_build_verification: dict[str, Any],
) -> dict[str, Any]:
    expected_build = runtime_build_evidence()["game_assembly"]
    if (
        not isinstance(runtime_build_verification, dict)
        or runtime_build_verification.get("status") != "passed"
        or runtime_build_verification.get("size_bytes")
        != expected_build["size_bytes"]
        or runtime_build_verification.get("sha256") != expected_build["sha256"]
    ):
        raise ChallengeBattleTimelineError(
            "exact GameAssembly verification is required for runtime contracts"
        )
    behavior, timeline, behavior_entry, timeline_entry = _load_focused_sources(
        behavior_path, timeline_path, season=season
    )
    runtime_evidence = runtime_build_evidence()
    task_graph = behavior_entry.get("task_graph")
    if not isinstance(task_graph, dict):
        raise ChallengeBattleTimelineError("behavior entry has no task graph")
    active, root_id, excluded_count = _active_graph(task_graph)
    compiled_nodes = _compile_nodes(active, root_id)
    if season == 39:
        _bind_s39_node_9_terminal_projection(
            compiled_nodes,
            behavior_entry,
            timeline_entry,
            runtime_evidence,
        )
        _bind_s39_timeline_skill_projections(
            compiled_nodes,
            behavior_entry,
            timeline_entry,
            runtime_evidence,
        )
    events, event_stats = _skill_events(
        behavior_entry, timeline_entry, active, root_id, compiled_nodes
    )
    pattern_windows = [
        {
            "node_id": node["id"],
            "start_frame": _task_start(node["id"]),
            "deadline": _pattern_deadline(node["id"], active),
            "policy": _control_policy(node, active),
        }
        for node in sorted(active.values(), key=lambda item: item["id"])
        if _node_op(node) == "custom_pattern_timeout"
    ]
    repeaters = [
        {
            "node_id": node["id"],
            "body_node_ids": _children(node, active),
            "policy": _control_policy(node, active),
            "iteration_start_recurrence": _repeat_iteration_start(
                node, _children(node, active)[0], active
            ),
        }
        for node in sorted(active.values(), key=lambda item: item["id"])
        if _node_op(node) == "repeat"
    ]
    random_nodes = [
        {
            "node_id": node["id"],
            "op": _node_op(node),
            "serialized_children": _children(node, active),
            "policy": _control_policy(node, active),
        }
        for node in sorted(active.values(), key=lambda item: item["id"])
        if _node_op(node) in {"custom_random_selector", "custom_random_sequence"}
    ]
    task_contracts = runtime_task_contracts()
    active_custom_types = sorted(
        {
            _short_type(node)
            for node in active.values()
            if _short_type(node) not in _GENERIC_OPS
        }
    )
    recovered_custom_types = [
        item
        for item in active_custom_types
        if item in task_contracts and "pending" not in task_contracts[item]["status"]
    ]
    pending_custom_types = [
        item for item in active_custom_types if item not in recovered_custom_types
    ]
    runtime_evidence["local_build_verification"] = runtime_build_verification
    runtime_evidence["behavior_designer_vendor_documentation"] = [
        "https://opsive.com/support/documentation/behavior-designer/tasks/",
        "https://opsive.com/support/documentation/behavior-designer-pro/concepts/tasks/composite/sequence/",
        "https://opsive.com/support/documentation/behavior-designer-pro/concepts/tasks/composite/selector/",
        "https://opsive.com/support/documentation/behavior-designer-pro/concepts/tasks/composite/parallel/",
        "https://opsive.com/support/documentation/behavior-designer-pro/concepts/tasks/decorator/inverter/",
        "https://opsive.com/support/documentation/behavior-designer-pro/concepts/tasks/decorator/repeater/",
    ]
    runtime_evidence["custom_task_contract_coverage"] = {
        "active_custom_types": len(active_custom_types),
        "recovered_types": recovered_custom_types,
        "pending_types": pending_custom_types,
    }
    runtime_external_inputs = sorted(
        {
            value
            for node in compiled_nodes
            for value in node.get("terminal", {}).get("external_inputs", [])
            if isinstance(value, str)
        }
    )
    runtime_evidence["unresolved_runtime_inputs"] = runtime_external_inputs
    runtime_evidence["absolute_frame_blockers"] = [
        "behavior_enable_frame",
        "live_battle_delta_sequence",
        *runtime_external_inputs,
    ]
    all_instant = all(node.get("instant") is True for node in active.values())
    dispatch_count = event_stats.get("skill_dispatch_templates", 0)
    expected_dispatch = sum(
        len(node.get("shot_keys") or []) for node in active.values()
    )
    if dispatch_count != expected_dispatch:
        raise ChallengeBattleTimelineError(
            "compiled skill dispatch coverage does not match active graph"
        )
    if season == 39:
        _validate_s39_oracles(
            active, pattern_windows, repeaters, random_nodes, events
        )
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "catalog_kind": CATALOG_KIND,
        "status": "branch_aware_battle_frame_partial",
        "scope": {
            "mode": "solo_raid_challenge_only",
            "expected_seasons": EXPECTED_CHALLENGES,
            "selection_mode": "focused_diagnostic",
            "selected_seasons": [str(season)],
            "promotion_eligible": False,
            "fps": FPS,
        },
        "battle_frame_model": {
            "canonical_fps": FPS,
            "origin_variable": "behavior_enable_frame",
            "origin_binding": "relative_to_battle_start_unresolved",
            "task_start_definitions": "ir.nodes[].activation.start_frame",
            "task_terminal_definitions": "ir.nodes[].terminal",
            "scheduler_status": SCHEDULER_CONTRACT["status"],
            "start_and_first_update": SCHEDULER_CONTRACT[
                "start_and_first_update"
            ],
            "terminal_to_next_task": SCHEDULER_CONTRACT[
                "terminal_to_next_task"
            ],
            "instant_semantics": (
                "terminal success/failure can dispatch the next executable task in "
                "the same Behavior Manager tick; Instant does not imply zero duration"
            ),
            "all_active_tasks_instant": all_instant,
            "absolute_numeric_frames": "not_emitted_without_runtime_bindings",
            "fixed_60fps_duration_values": (
                "explicit projections only; live battle-delta sequence is unobserved"
            ),
        },
        "runtime_evidence": runtime_evidence,
        "runtime_task_contracts": task_contracts,
        "source": {
            "behavior_artifact": {
                "logical_path": f"repo/Database/raw/staticdata/assembled/{behavior_path.name}",
                "sha256": _sha256_file(behavior_path),
                "catalog_digest_sha256": behavior.get("catalog_digest_sha256"),
            },
            "timeline_artifact": {
                "logical_path": f"repo/Database/raw/staticdata/assembled/{timeline_path.name}",
                "sha256": _sha256_file(timeline_path),
                "catalog_digest_sha256": timeline.get("catalog_digest_sha256"),
            },
        },
        "entry": {
            "season": str(season),
            "monster_id": behavior_entry.get("monster_id"),
            "mon_prefab": (behavior_entry.get("monster_model") or {}).get(
                "mon_prefab"
            ),
            "behavior_asset": behavior_entry.get("behavior_asset"),
            "spotmonster_bundle_content_hash": timeline_entry.get(
                "bundle_content_hash"
            ),
        },
        "runtime_task_inventory": _runtime_inventory(active),
        "ir": {
            "root_node_id": root_id,
            "nodes": compiled_nodes,
            "pattern_windows": pattern_windows,
            "repeaters": repeaters,
            "random_nodes": random_nodes,
            "skill_events": events,
        },
        "coverage": {
            "active_nodes": len(active),
            "nodes_excluded_from_active_execution": excluded_count,
            "active_skill_dispatch_templates": dispatch_count,
            "skill_effect_templates_exact_relative_marker": event_stats.get(
                "skill_effect_templates_exact_relative_marker", 0
            ),
            "skill_effect_templates_runtime_unresolved": event_stats.get(
                "skill_effect_templates_runtime_unresolved", 0
            ),
            "pattern_windows": len(pattern_windows),
            "repeaters": len(repeaters),
            "custom_random_nodes": len(random_nodes),
            "active_custom_task_types": len(active_custom_types),
            "runtime_contract_types_recovered": len(recovered_custom_types),
            "runtime_contract_types_pending": len(pending_custom_types),
        },
        "validation": {
            "status": "partial",
            "checks": [
                {
                    "name": "focused_nonpromotable_source_scope",
                    "expected": [str(season)],
                    "actual": [str(season)],
                    "status": "passed",
                },
                {
                    "name": "active_skill_dispatch_coverage",
                    "expected": expected_dispatch,
                    "actual": dispatch_count,
                    "status": "passed",
                },
                {
                    "name": "exact_runtime_contract_build",
                    "expected": runtime_evidence["game_assembly"]["sha256"],
                    "actual": runtime_evidence["local_build_verification"].get(
                        "sha256"
                    ),
                    "status": (
                        "passed"
                        if runtime_evidence["local_build_verification"].get(
                            "status"
                        )
                        == "passed"
                        else "not_requested"
                    ),
                },
                *(
                    [
                        {
                            "name": "season_39_static_oracles",
                            "expected": {
                                "active_nodes": 185,
                                "dispatch_sites": 30,
                                "exact_marker_sites": 13,
                                "unresolved_effect_sites": 17,
                            },
                            "actual": {
                                "active_nodes": len(active),
                                "dispatch_sites": dispatch_count,
                                "exact_marker_sites": event_stats.get(
                                    "skill_effect_templates_exact_relative_marker",
                                    0,
                                ),
                                "unresolved_effect_sites": event_stats.get(
                                    "skill_effect_templates_runtime_unresolved",
                                    0,
                                ),
                            },
                            "status": "passed",
                        }
                    ]
                    if season == 39
                    else []
                ),
                {
                    "name": "custom_runtime_completion_semantics",
                    "expected": active_custom_types,
                    "actual": recovered_custom_types,
                    "pending": pending_custom_types,
                    "status": "passed" if not pending_custom_types else "partial",
                },
                {
                    "name": "absolute_battle_frame_binding",
                    "expected": "behavior enable + custom terminal bindings",
                    "actual": "symbolic recurrence IR",
                    "status": "pending",
                },
                {
                    "name": "canonical_scope_promotion",
                    "expected": EXPECTED_CHALLENGES,
                    "actual": 1,
                    "status": "blocked",
                },
            ],
        },
    }
    artifact["catalog_digest_sha256"] = _sha256(_canonical_bytes(artifact))
    return artifact


def write_catalog(
    value: dict[str, Any], output: Path, *, static_root: Path = DEFAULT_STATIC_ROOT
) -> Path:
    allowed = static_root.resolve() / "assembled"
    resolved = output.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ChallengeBattleTimelineError(
            "output must stay below static-root/assembled"
        ) from exc
    resolved.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=resolved.parent,
        prefix=f".{resolved.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, resolved)
    finally:
        temporary.unlink(missing_ok=True)
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="compile a focused Challenge behavior tree into branch-aware frame IR"
    )
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--static-root", type=Path, default=DEFAULT_STATIC_ROOT)
    parser.add_argument(
        "--game-assembly",
        type=Path,
        default=DEFAULT_GAME_ASSEMBLY,
        help="exact local GameAssembly build to verify before applying native contracts",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.season <= EXPECTED_CHALLENGES:
        parser.error(f"--season must be in 1..{EXPECTED_CHALLENGES}")
    assembled = args.static_root / "assembled"
    behavior_path = (
        assembled
        / f"solo_raid_challenge_behavior.season_{args.season}.partial.json"
    )
    timeline_path = (
        assembled
        / f"solo_raid_challenge_timeline.season_{args.season}.partial.json"
    )
    output = (
        assembled
        / f"solo_raid_challenge_battle_timeline.season_{args.season}.partial.json"
    )
    try:
        runtime_verification = validate_runtime_build(args.game_assembly)
        artifact = build_battle_timeline(
            behavior_path=behavior_path,
            timeline_path=timeline_path,
            season=args.season,
            runtime_build_verification=runtime_verification,
        )
        written = write_catalog(artifact, output, static_root=args.static_root)
    except (ChallengeBattleTimelineError, RuntimeContractBuildError) as exc:
        print(f"battle timeline blocked: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {written}")
    print(f"status={artifact['status']}")
    print(f"catalog_digest_sha256={artifact['catalog_digest_sha256']}")
    print("focused diagnostics are partial and never promotion-eligible")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
