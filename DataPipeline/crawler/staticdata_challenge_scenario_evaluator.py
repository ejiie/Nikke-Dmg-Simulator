#!/usr/bin/env python3
"""Evaluate branch-aware Challenge timeline expressions for explicit scenarios.

The evaluator is intentionally activation-instance based.  Repeated and random
tasks are addressed by their repeat/random context, never by ``node_id`` alone.
It resolves only values proven by the schema-v2 runtime contracts or supplied
by the scenario; missing runtime state remains a structured unresolved result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .staticdata_challenge_behavior import DEFAULT_STATIC_ROOT
except ImportError:
    from staticdata_challenge_behavior import DEFAULT_STATIC_ROOT


SCHEMA_VERSION = 1
SCENARIO_KIND = "solo_raid_challenge_battle_scenario"
OUTPUT_KIND = "solo_raid_challenge_battle_scenario_evaluation"
TIMELINE_KIND = "solo_raid_challenge_battle_timeline"
SUPPORTED_TIMELINE_SCHEMA = 2
FPS = 60
SPOT_TICK_DELTA_SECONDS = "0.017000000923871994"
_SCENARIO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_STATUSES = {"success", "failure"}


class ScenarioEvaluationError(RuntimeError):
    """A scenario or source artifact violates the evaluator contract."""


class _Blocked(Exception):
    def __init__(self, *dependencies: dict[str, Any]):
        super().__init__("scenario input is incomplete")
        self.dependencies = list(dependencies)


class _Inactive(Exception):
    def __init__(self, reason: dict[str, Any]):
        super().__init__("scenario path is inactive")
        self.reason = reason


@dataclass(frozen=True)
class _Terminal:
    frame: int
    status: str
    source: str


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


def finalize_scenario(value: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with a canonical self-excluding catalog digest."""

    result = dict(value)
    result.pop("catalog_digest_sha256", None)
    result["catalog_digest_sha256"] = _sha256(_canonical_bytes(result))
    return result


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant {token}")
            ),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ScenarioEvaluationError(f"cannot read JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ScenarioEvaluationError(f"JSON artifact is not an object: {path}")
    return value, _sha256(raw)


def _verify_digest(value: dict[str, Any], label: str) -> None:
    stored = value.get("catalog_digest_sha256")
    payload = dict(value)
    payload.pop("catalog_digest_sha256", None)
    if not isinstance(stored, str) or stored != _sha256(_canonical_bytes(payload)):
        raise ScenarioEvaluationError(f"{label} catalog digest mismatch")


def _short_type(node: dict[str, Any]) -> str:
    value = node.get("source_type")
    if not isinstance(value, str) or not value:
        raise ScenarioEvaluationError("timeline node has no source type")
    return value.rsplit(".", 1)[-1]


def _valid_frame(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ScenarioEvaluationError(f"{label} must be a nonnegative integer frame")
    return value


def _valid_context(
    value: Any, *, allowed: set[str], label: str
) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ScenarioEvaluationError(f"{label} context must be an object")
    result: dict[str, int] = {}
    for key, item in value.items():
        if key not in allowed or type(item) is not int or item < 0:
            raise ScenarioEvaluationError(f"{label} has invalid context entry {key!r}")
        result[key] = item
    return result


def _context_record(context: dict[str, int]) -> dict[str, int]:
    return dict(sorted(context.items()))


def _deduplicate_dependencies(
    dependencies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[bytes, dict[str, Any]] = {}
    for item in dependencies:
        unique[_canonical_bytes(item)] = item
    return [unique[key] for key in sorted(unique)]


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _fixed60_gte_update_count(seconds: Any) -> int:
    try:
        target = _float32(float(seconds))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ScenarioEvaluationError("pattern timeout duration is invalid") from exc
    if target < 0:
        raise ScenarioEvaluationError("pattern timeout duration is negative")
    elapsed = _float32(0.0)
    delta = _float32(float(SPOT_TICK_DELTA_SECONDS))
    for update_count in range(1, 10_000_001):
        elapsed = _float32(elapsed + delta)
        if elapsed >= target:
            return update_count
    raise ScenarioEvaluationError("pattern timeout projection did not converge")


def _manual_timeline_gte_update_count(seconds: Any) -> int:
    try:
        target = float(seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ScenarioEvaluationError("timeline duration is invalid") from exc
    if not math.isfinite(target) or target < 0:
        raise ScenarioEvaluationError("timeline duration is invalid")
    delta = _float32(float(SPOT_TICK_DELTA_SECONDS))
    elapsed = 0.0
    for update_count in range(1, 10_000_001):
        elapsed += delta
        if elapsed >= target:
            return update_count
    raise ScenarioEvaluationError("timeline projection did not converge")


def _allowed_bound_statuses(node: dict[str, Any]) -> set[str]:
    short = _short_type(node)
    if short in {"MoveToVer2", "MoveToVer3", "TeleportToVer2"}:
        return {"success"}
    if short == "isPhaseAction":
        return {"failure"}
    if short in {"AttackV3", "TimelineSkill", "BreakCol"}:
        failure_check = (
            node.get("policy", {})
            .get("parameters", {})
            .get("BooleanFailueCheck")
        )
        if failure_check is False:
            return {"success"}
    return set(_STATUSES)


class _Evaluator:
    def __init__(self, timeline: dict[str, Any], scenario: dict[str, Any]):
        self.timeline = timeline
        self.scenario = scenario
        raw_nodes = timeline.get("ir", {}).get("nodes")
        raw_events = timeline.get("ir", {}).get("skill_events")
        if not isinstance(raw_nodes, list) or not isinstance(raw_events, list):
            raise ScenarioEvaluationError("timeline has no evaluable IR")
        self.nodes: dict[int, dict[str, Any]] = {}
        for node in raw_nodes:
            node_id = node.get("id") if isinstance(node, dict) else None
            if type(node_id) is not int or node_id in self.nodes:
                raise ScenarioEvaluationError("timeline has invalid node IDs")
            self.nodes[node_id] = node
        self.events: dict[str, dict[str, Any]] = {}
        for event in raw_events:
            event_id = event.get("event_id") if isinstance(event, dict) else None
            if not isinstance(event_id, str) or event_id in self.events:
                raise ScenarioEvaluationError("timeline has invalid event IDs")
            self.events[event_id] = event

        self.repeat_variables = {
            item.get("variable")
            for node in self.nodes.values()
            for item in node.get("activation", {}).get("iteration_vars", [])
            if isinstance(item, dict) and isinstance(item.get("variable"), str)
        }
        self.random_nodes = {
            node_id
            for node_id, node in self.nodes.items()
            if node.get("op")
            in {"custom_random_selector", "custom_random_sequence"}
        }
        self.random_variables = {f"random_{item}" for item in self.random_nodes}
        self.allowed_context = self.repeat_variables | self.random_variables
        self.behavior_enable_frame = _valid_frame(
            scenario.get("battle", {}).get("behavior_enable_frame"),
            "behavior_enable_frame",
        )
        delta_model = scenario.get("battle", {}).get("delta_model")
        if delta_model != "fixed_60fps_float32_projection":
            raise ScenarioEvaluationError(
                "only fixed_60fps_float32_projection is supported in schema v1"
            )
        self._tick_total_times: dict[float, list[float]] = {}
        self.pattern_tick_model = scenario.get("battle", {}).get(
            "pattern_tick_model"
        )
        horizon = scenario.get("battle", {}).get("frame_horizon_exclusive")
        self.horizon = (
            _valid_frame(horizon, "frame_horizon_exclusive")
            if horizon is not None
            else None
        )
        if self.horizon is not None and self.horizon <= self.behavior_enable_frame:
            raise ScenarioEvaluationError("frame horizon must follow behavior enable")

        self.terminals: dict[tuple[int, tuple[tuple[str, int], ...]], _Terminal] = {}
        self.permutations: dict[tuple[int, int], tuple[int, ...]] = {}
        self.effect_frames: dict[
            tuple[str, tuple[tuple[str, int], ...]], int
        ] = {}
        self._parse_bindings()
        self.start_cache: dict[
            tuple[int, tuple[tuple[str, int], ...]], int
        ] = {}
        self.terminal_cache: dict[
            tuple[int, tuple[tuple[str, int], ...]], _Terminal
        ] = {}
        self.resolving_starts: set[
            tuple[int, tuple[tuple[str, int], ...]]
        ] = set()
        self.resolving_terminals: set[
            tuple[int, tuple[tuple[str, int], ...]]
        ] = set()
        self.parallel_guard_stack: set[tuple[int, int]] = set()
        self.pattern_guard_stack: set[int] = set()

    def pattern_deadline(
        self, node_id: int, context: dict[str, int]
    ) -> int:
        if self.pattern_tick_model != "next_fixed60_frame":
            raise _Blocked(
                {
                    "kind": "missing_pattern_tick_model",
                    "pattern_node_id": node_id,
                    "required_contract": (
                        "next BehaviorManager reevaluation tick with a new battle tick"
                    ),
                }
            )
        node = self.nodes[node_id]
        seconds = (
            node.get("policy", {})
            .get("configured_timeout", {})
            .get("seconds_decimal")
        )
        updates = _fixed60_gte_update_count(seconds)
        first_counted_frame = self._resolve_start(node_id, context) + 1
        return first_counted_frame + updates - 1

    def _fixed60_total_time(self, frame: int, tick_delta: float) -> float:
        """Return SpotManagement's float32 totalTickTime for one battle frame."""

        index = frame - self.behavior_enable_frame
        if index < 0:
            raise ScenarioEvaluationError(
                "fixed60 total time requested before behavior enable"
            )
        times = self._tick_total_times.setdefault(tick_delta, [0.0])
        while len(times) <= index:
            times.append(_float32(times[-1] + tick_delta))
        return times[index]

    def _fixed60_wait_resume(
        self, registration_frame: int, seconds: Any, tick_delta: float
    ) -> int:
        try:
            duration = _float32(float(seconds))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ScenarioEvaluationError(
                "tick-coroutine wait duration is invalid"
            ) from exc
        if not math.isfinite(duration) or duration < 0:
            raise ScenarioEvaluationError(
                "tick-coroutine wait duration must be finite and nonnegative"
            )
        threshold = _float32(
            self._fixed60_total_time(registration_frame, tick_delta) + duration
        )
        for frame in range(
            registration_frame, registration_frame + 10_000_001
        ):
            if self._fixed60_total_time(frame, tick_delta) >= threshold:
                return frame
        raise ScenarioEvaluationError("tick-coroutine wait projection did not converge")

    def _fixed60_tick_coroutine_terminal(
        self, start: int, projection: dict[str, Any]
    ) -> _Terminal:
        if (
            projection.get("status")
            != "exact_build_native_and_serialized_asset_bound"
            or projection.get("delta_model")
            != "fixed_60fps_float32_projection"
            or projection.get("coroutine_context") != "MonsterContext"
            or projection.get("completion_observation")
            != "same_frame_later_BTContext_tick"
            or projection.get("wait_threshold")
            != "float32(registration_total_tick_time + seconds_float32)"
            or projection.get("wait_resume")
            != "first_frame_total_tick_time_gte_threshold"
            or projection.get("newly_yielded_current_processing")
            != "next_monster_context_tick"
            or projection.get("completed_child_parent_resume")
            != "same_monster_context_tick"
            or projection.get("terminal_status") != "success"
        ):
            raise ScenarioEvaluationError(
                "unsupported fixed60 tick-coroutine projection contract"
            )
        offset = projection.get("first_coroutine_update_offset_frames")
        operations = projection.get("trace_program")
        try:
            tick_delta = _float32(
                float(projection.get("tick_delta_seconds_float32"))
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ScenarioEvaluationError(
                "fixed60 tick-coroutine projection has invalid tick delta"
            ) from exc
        if (
            type(offset) is not int
            or offset < 0
            or not isinstance(operations, list)
            or not operations
            or not math.isfinite(tick_delta)
            or tick_delta <= 0
            or tick_delta != _float32(0.017)
        ):
            raise ScenarioEvaluationError(
                "fixed60 tick-coroutine projection has invalid scheduler data"
            )
        frame = start + offset
        for operation in operations:
            if not isinstance(operation, dict):
                raise ScenarioEvaluationError(
                    "tick-coroutine trace operation must be an object"
                )
            op = operation.get("op")
            if op == "yield_wait":
                frame = self._fixed60_wait_resume(
                    frame + 1,
                    operation.get("seconds_float32"),
                    tick_delta,
                )
            elif op == "yield_nested_coroutine":
                frame += 1
            elif op == "yield_immediate_nested_coroutines":
                count = operation.get("count")
                if (
                    type(count) is not int
                    or count <= 0
                    or operation.get("immediate_condition")
                    != "fire_index_zero_skips_delay"
                ):
                    raise ScenarioEvaluationError(
                        "tick-coroutine immediate child run is invalid"
                    )
                frame += count
            elif op == "terminal_cascade":
                continue
            else:
                raise ScenarioEvaluationError(
                    f"unsupported tick-coroutine trace operation {op!r}"
                )
        return _Terminal(
            frame,
            "success",
            "native_fixed60_tick_coroutine_projection",
        )

    def _fixed60_timeline_terminal(
        self, start: int, projection: dict[str, Any]
    ) -> _Terminal:
        if (
            projection.get("status")
            != "exact_build_native_and_serialized_asset_bound"
            or projection.get("delta_model") != "spot_update_round_3_float32"
            or projection.get("tick_delta_seconds_float32")
            != SPOT_TICK_DELTA_SECONDS
            or projection.get("duration_comparison") != "gte"
            or projection.get("clock_accumulator")
            != "PlayableGraph_double_manual_time"
            or projection.get("controller_first_update_offset_frames") != 0
            or projection.get("completion_observation")
            != "next_frame_earlier_BTContext_tick"
            or projection.get("completion_observation_offset_frames") != 1
            or projection.get("terminal_status") != "success"
        ):
            raise ScenarioEvaluationError(
                "unsupported fixed60 timeline terminal projection contract"
            )
        update_count = _manual_timeline_gte_update_count(
            projection.get("duration_seconds_decimal")
        )
        stop_offset = projection.get(
            "controller_stop_offset_from_task_start_frames"
        )
        terminal_offset = projection.get("terminal_offset_from_task_start_frames")
        if (
            projection.get("duration_terminal_update_count_1_based")
            != update_count
            or stop_offset != update_count - 1
            or terminal_offset != stop_offset + 1
        ):
            raise ScenarioEvaluationError(
                "fixed60 timeline terminal projection equation mismatch"
            )
        return _Terminal(
            start + terminal_offset,
            "success",
            "native_fixed60_timeline_terminal_projection",
        )

    def _relevant_context_keys(self, node_id: int) -> set[str]:
        node = self.nodes[node_id]
        result = {
            item["variable"]
            for item in node.get("activation", {}).get("iteration_vars", [])
            if isinstance(item, dict) and isinstance(item.get("variable"), str)
        }
        for choice in node.get("activation", {}).get("choice_path", []):
            if (
                isinstance(choice, dict)
                and choice.get("kind")
                in {"custom_random_selector", "custom_random_sequence"}
                and type(choice.get("node_id")) is int
            ):
                result.add(f"random_{choice['node_id']}")
        if node.get("op") in {
            "custom_random_selector",
            "custom_random_sequence",
        }:
            result.add(f"random_{node_id}")
        return result

    def _signature(
        self,
        node_id: int,
        context: dict[str, int],
        *,
        require_complete: bool,
    ) -> tuple[tuple[str, int], ...]:
        relevant = self._relevant_context_keys(node_id)
        missing = sorted(relevant - context.keys())
        if missing and require_complete:
            raise ScenarioEvaluationError(
                f"node {node_id} binding misses context variables {missing}"
            )
        extra = sorted(context.keys() - relevant)
        if extra and require_complete:
            raise ScenarioEvaluationError(
                f"node {node_id} binding has irrelevant context variables {extra}"
            )
        return tuple(sorted((key, context[key]) for key in relevant if key in context))

    def _validate_context_bounds(
        self, context: dict[str, int], *, label: str
    ) -> None:
        for variable, iteration in context.items():
            if not variable.startswith("repeat_"):
                continue
            try:
                repeat_node_id = int(variable.removeprefix("repeat_"))
                repeat_node = self.nodes[repeat_node_id]
            except (ValueError, KeyError) as exc:
                raise ScenarioEvaluationError(
                    f"{label} references an unknown repeater {variable}"
                ) from exc
            policy = repeat_node.get("policy", {})
            if repeat_node.get("op") != "repeat":
                raise ScenarioEvaluationError(f"{label} context is not a repeater")
            if policy.get("repeat_forever") is False:
                count = policy.get("count")
                if type(count) is not int or iteration >= count:
                    raise ScenarioEvaluationError(
                        f"{label} repeat iteration is outside its finite range"
                    )

    def _runtime_signature(
        self, node_id: int, context: dict[str, int]
    ) -> tuple[tuple[str, int], ...]:
        relevant = self._relevant_context_keys(node_id)
        missing = sorted(relevant - context.keys())
        if missing:
            raise _Blocked(
                {
                    "kind": "missing_activation_context",
                    "node_id": node_id,
                    "variables": missing,
                }
            )
        return tuple(sorted((key, context[key]) for key in relevant))

    def _parse_bindings(self) -> None:
        bindings = self.scenario.get("bindings")
        if not isinstance(bindings, dict):
            raise ScenarioEvaluationError("scenario bindings must be an object")
        terminals = bindings.get("task_terminals", [])
        permutations = bindings.get("random_permutations", [])
        effects = bindings.get("skill_effects", [])
        if not all(isinstance(item, list) for item in (terminals, permutations, effects)):
            raise ScenarioEvaluationError("scenario binding collections must be arrays")

        for index, item in enumerate(terminals):
            if not isinstance(item, dict):
                raise ScenarioEvaluationError("task terminal binding must be an object")
            node_id = item.get("node_id")
            if type(node_id) is not int or node_id not in self.nodes:
                raise ScenarioEvaluationError(f"terminal binding {index} has unknown node")
            context = _valid_context(
                item.get("context", {}),
                allowed=self.allowed_context,
                label=f"terminal binding {index}",
            )
            self._validate_context_bounds(
                context, label=f"terminal binding {index}"
            )
            signature = self._signature(node_id, context, require_complete=True)
            frame = _valid_frame(item.get("frame"), f"terminal binding {index}")
            if frame < self.behavior_enable_frame:
                raise ScenarioEvaluationError("task terminal precedes behavior enable")
            status = item.get("status")
            if status not in _STATUSES:
                raise ScenarioEvaluationError("task terminal has invalid status")
            node = self.nodes[node_id]
            if node.get("op") not in {
                "custom_action",
                "custom_guard",
                "custom_pattern_timeout",
            } or _short_type(node) in {"SetMoveType", "StopMoveSuccess"}:
                raise ScenarioEvaluationError(
                    "task terminal bindings are limited to runtime-dependent tasks"
                )
            if status not in _allowed_bound_statuses(node):
                raise ScenarioEvaluationError(
                    f"node {node_id} terminal status contradicts its native contract"
                )
            key = (node_id, signature)
            if key in self.terminals:
                raise ScenarioEvaluationError("duplicate task terminal binding")
            source = item.get("source", "explicit_scenario_binding")
            if not isinstance(source, str) or not source:
                raise ScenarioEvaluationError("task terminal source is invalid")
            self.terminals[key] = _Terminal(frame, status, source)

        for index, item in enumerate(permutations):
            if not isinstance(item, dict):
                raise ScenarioEvaluationError("random permutation must be an object")
            node_id = item.get("node_id")
            activation = item.get("activation_index")
            children = item.get("children")
            if (
                type(node_id) is not int
                or node_id not in self.random_nodes
                or type(activation) is not int
                or activation < 0
                or not isinstance(children, list)
                or any(type(child) is not int for child in children)
            ):
                raise ScenarioEvaluationError(
                    f"random permutation {index} has invalid identity"
                )
            expected = self.nodes[node_id].get("children")
            if (
                not isinstance(expected, list)
                or len(children) != len(expected)
                or len(children) != len(set(children))
                or set(children) != set(expected)
            ):
                raise ScenarioEvaluationError(
                    f"random permutation {index} is not a complete child permutation"
                )
            key = (node_id, activation)
            if key in self.permutations:
                raise ScenarioEvaluationError("duplicate random permutation binding")
            self.permutations[key] = tuple(children)

        for index, item in enumerate(effects):
            if not isinstance(item, dict):
                raise ScenarioEvaluationError("skill effect binding must be an object")
            event_id = item.get("event_id")
            event = self.events.get(event_id)
            if event is None or event.get("kind") != "skill_effect":
                raise ScenarioEvaluationError(
                    f"skill effect binding {index} has unknown effect event"
                )
            if "relative_to_timeline_action_start" in event:
                raise ScenarioEvaluationError(
                    "exact timeline effects cannot have explicit effect bindings"
                )
            node_id = event.get("node_id")
            context = _valid_context(
                item.get("context", {}),
                allowed=self.allowed_context,
                label=f"skill effect binding {index}",
            )
            self._validate_context_bounds(
                context, label=f"skill effect binding {index}"
            )
            signature = self._signature(node_id, context, require_complete=True)
            frame = _valid_frame(item.get("frame"), f"skill effect binding {index}")
            key = (event_id, signature)
            if key in self.effect_frames:
                raise ScenarioEvaluationError("duplicate skill effect binding")
            self.effect_frames[key] = frame

    def _task_dependency(
        self, node_id: int, context: dict[str, int]
    ) -> dict[str, Any]:
        node = self.nodes[node_id]
        dependency = {
            "kind": "missing_task_terminal",
            "node_id": node_id,
            "context": _context_record(context),
            "source_type": _short_type(node),
            "known_terminal_statuses": sorted(_allowed_bound_statuses(node)),
        }
        external_inputs = node.get("terminal", {}).get("external_inputs")
        if isinstance(external_inputs, list) and external_inputs:
            dependency["missing_frame_inputs"] = external_inputs
        return dependency

    def _resolve_start(self, node_id: int, context: dict[str, int]) -> int:
        if node_id not in self.nodes:
            raise ScenarioEvaluationError(f"unknown task start node {node_id}")
        signature = self._runtime_signature(node_id, context)
        key = (node_id, signature)
        if key in self.start_cache:
            return self.start_cache[key]
        if key in self.resolving_starts:
            raise ScenarioEvaluationError("task start recurrence contains a cycle")
        self.resolving_starts.add(key)
        try:
            expression = self.nodes[node_id].get("activation", {}).get("start_frame")
            if not isinstance(expression, dict):
                raise ScenarioEvaluationError(f"node {node_id} has no start expression")
            frame = self._eval_start_expression(expression, context)
            self._validate_activation(node_id, context, frame)
            if frame < self.behavior_enable_frame:
                raise ScenarioEvaluationError("resolved task start precedes behavior enable")
            self.start_cache[key] = frame
            return frame
        finally:
            self.resolving_starts.remove(key)

    def _validate_activation(
        self, node_id: int, context: dict[str, int], frame: int
    ) -> None:
        guards = self.nodes[node_id].get("activation", {}).get("guards", [])
        if not isinstance(guards, list):
            raise ScenarioEvaluationError(f"node {node_id} has invalid activation guards")
        for guard in guards:
            if not isinstance(guard, dict):
                raise ScenarioEvaluationError(f"node {node_id} has invalid guard")
            op = guard.get("op")
            if op == "repeat_iteration":
                variable = guard.get("variable")
                if variable not in context:
                    raise _Blocked(
                        {
                            "kind": "missing_repeat_iteration",
                            "repeat_node_id": guard.get("repeat_node_id"),
                            "variable": variable,
                        }
                    )
                maximum = guard.get("max_exclusive")
                if type(maximum) is int and context[variable] >= maximum:
                    raise _Inactive(
                        {
                            "kind": "repeat_iteration_out_of_range",
                            "repeat_node_id": guard.get("repeat_node_id"),
                            "variable": variable,
                            "iteration": context[variable],
                            "max_exclusive": maximum,
                        }
                    )
            elif op == "task_status":
                self._require_terminal(
                    guard["node_id"], context, guard.get("status")
                )
            elif op == "condition":
                self._require_terminal(
                    guard["node_id"], context, guard.get("required_task_status")
                )
            elif op == "custom_pattern_branch_active":
                pattern_node_id = guard["pattern_node_id"]
                if pattern_node_id in self.pattern_guard_stack:
                    continue
                signature = self._runtime_signature(pattern_node_id, context)
                explicit = self.terminals.get((pattern_node_id, signature))
                pattern_end = (
                    explicit.frame
                    if explicit is not None
                    else self.pattern_deadline(pattern_node_id, context)
                )
                if frame >= pattern_end:
                    raise _Inactive(
                        {
                            "kind": "pattern_not_active_at_task_start",
                            "pattern_node_id": pattern_node_id,
                            "pattern_terminal_frame": pattern_end,
                            "task_start_frame": frame,
                        }
                    )
            elif op == "parallel_branch_active":
                parallel_node_id = guard["parallel_node_id"]
                branch_node_id = guard["branch_node_id"]
                if (parallel_node_id, branch_node_id) in self.parallel_guard_stack:
                    continue
                parallel_start = self._resolve_start(parallel_node_id, context)
                if frame == parallel_start:
                    continue
                dependencies: list[dict[str, Any]] = []
                for sibling_node_id in self.nodes[parallel_node_id]["children"]:
                    if sibling_node_id == branch_node_id:
                        continue
                    marker = (parallel_node_id, sibling_node_id)
                    self.parallel_guard_stack.add(marker)
                    try:
                        sibling = self._resolve_terminal(sibling_node_id, context)
                    except _Blocked as exc:
                        dependencies.extend(exc.dependencies)
                        continue
                    finally:
                        self.parallel_guard_stack.remove(marker)
                    if sibling.status != "failure":
                        continue
                    if sibling.frame < frame:
                        raise _Inactive(
                            {
                                "kind": "parallel_sibling_preempted_before_task_start",
                                "parallel_node_id": parallel_node_id,
                                "sibling_branch_node_id": sibling_node_id,
                                "parallel_failure_frame": sibling.frame,
                                "task_start_frame": frame,
                            }
                        )
                    if sibling.frame == frame:
                        dependencies.append(
                            {
                                "kind": "missing_same_frame_parallel_order",
                                "parallel_node_id": parallel_node_id,
                                "sibling_branch_node_id": sibling_node_id,
                                "frame": frame,
                            }
                        )
                if dependencies:
                    raise _Blocked(*dependencies)
            elif op == "custom_random_child_activated":
                random_node_id = guard["node_id"]
                variable = f"random_{random_node_id}"
                if variable not in context:
                    raise _Blocked(
                        {
                            "kind": "missing_random_activation_index",
                            "random_node_id": random_node_id,
                            "variable": variable,
                        }
                    )
                if (random_node_id, context[variable]) not in self.permutations:
                    raise _Blocked(
                        {
                            "kind": "missing_random_permutation",
                            "random_node_id": random_node_id,
                            "activation_index": context[variable],
                        }
                    )
            elif op == "custom_initialization_completed":
                continue
            else:
                raise ScenarioEvaluationError(
                    f"node {node_id} has unsupported activation guard {op!r}"
                )

    def _require_terminal(
        self,
        node_id: int,
        context: dict[str, int],
        required: str | list[str] | None,
    ) -> _Terminal:
        terminal = self._resolve_terminal(node_id, context)
        expected = [required] if isinstance(required, str) else required
        if expected is not None and terminal.status not in expected:
            raise _Inactive(
                {
                    "kind": "required_terminal_status_mismatch",
                    "node_id": node_id,
                    "context": _context_record(context),
                    "required_statuses": expected,
                    "actual_status": terminal.status,
                    "terminal_frame": terminal.frame,
                }
            )
        return terminal

    def _eval_start_expression(
        self, expression: dict[str, Any], context: dict[str, int]
    ) -> int:
        op = expression.get("op")
        if op == "variable":
            if expression.get("name") != "behavior_enable_frame":
                raise ScenarioEvaluationError("unsupported frame variable")
            return self.behavior_enable_frame
        if op == "task_start":
            return self._resolve_start(expression["node_id"], context)
        if op == "task_terminal":
            return self._require_terminal(
                expression["node_id"], context, expression.get("required_status")
            ).frame
        if op == "custom_initialization_child_start":
            return self._resolve_start(expression["scope_node_id"], context)
        if op == "custom_pattern_child_start":
            return self._resolve_start(expression["pattern_node_id"], context)
        if op == "repeat_iteration_start":
            variable = expression.get("iteration_var")
            if variable not in context:
                raise _Blocked(
                    {
                        "kind": "missing_repeat_iteration",
                        "repeat_node_id": expression.get("repeat_node_id"),
                        "variable": variable,
                    }
                )
            iteration = context[variable]
            repeat_policy = self.nodes[expression["repeat_node_id"]].get(
                "policy", {}
            )
            if (
                repeat_policy.get("repeat_forever") is False
                and type(repeat_policy.get("count")) is int
                and iteration >= repeat_policy["count"]
            ):
                raise _Inactive(
                    {
                        "kind": "repeat_iteration_out_of_range",
                        "repeat_node_id": expression["repeat_node_id"],
                        "variable": variable,
                        "iteration": iteration,
                        "max_exclusive": repeat_policy["count"],
                    }
                )
            if iteration == 0:
                return self._resolve_start(expression["repeat_node_id"], context)
            prior = dict(context)
            prior[variable] = iteration - 1
            recursive = expression.get("definition", {}).get("recursive_case", {})
            terminal = recursive.get("frame", {}).get("prior_body_terminal", {})
            return self._require_terminal(
                terminal["body_node_id"], prior, terminal.get("required_statuses")
            ).frame
        if op == "custom_random_child_start":
            random_node = expression["random_node_id"]
            variable = f"random_{random_node}"
            if variable not in context:
                raise _Blocked(
                    {
                        "kind": "missing_random_activation_index",
                        "random_node_id": random_node,
                        "variable": variable,
                    }
                )
            activation = context[variable]
            permutation = self.permutations.get((random_node, activation))
            if permutation is None:
                raise _Blocked(
                    {
                        "kind": "missing_random_permutation",
                        "random_node_id": random_node,
                        "activation_index": activation,
                    }
                )
            child = expression["child_node_id"]
            rank = permutation.index(child)
            if rank == 0:
                return self._resolve_start(random_node, context)
            required = (
                "failure"
                if self.nodes[random_node]["op"] == "custom_random_selector"
                else "success"
            )
            return self._require_terminal(
                permutation[rank - 1], context, required
            ).frame
        raise ScenarioEvaluationError(f"unsupported start expression op {op!r}")

    def _deterministic_leaf(
        self, node_id: int, context: dict[str, int]
    ) -> _Terminal | None:
        node = self.nodes[node_id]
        short = _short_type(node)
        tick_coroutine = node.get("policy", {}).get(
            "fixed_60fps_tick_coroutine_projection"
        )
        if tick_coroutine is not None:
            if short != "AttackV3" or not isinstance(tick_coroutine, dict):
                raise ScenarioEvaluationError(
                    "tick-coroutine projection is attached to an unsupported task"
                )
            start = self._resolve_start(node_id, context)
            return self._fixed60_tick_coroutine_terminal(start, tick_coroutine)
        timeline_projection = node.get("policy", {}).get(
            "fixed_60fps_timeline_terminal_projection"
        )
        if timeline_projection is not None:
            if short != "TimelineSkill" or not isinstance(
                timeline_projection, dict
            ):
                raise ScenarioEvaluationError(
                    "timeline projection is attached to an unsupported task"
                )
            start = self._resolve_start(node_id, context)
            return self._fixed60_timeline_terminal(start, timeline_projection)
        if node.get("op") == "custom_wait":
            start = self._resolve_start(node_id, context)
            projection = node.get("policy", {}).get("configured_duration", {}).get(
                "fixed_60fps_projection", {}
            )
            offset = projection.get("terminal_offset_from_task_start_frames")
            if type(offset) is not int or offset < 0:
                return None
            return _Terminal(start + offset, "success", "native_fixed60_projection")
        if short in {"SetMoveType", "StopMoveSuccess"}:
            start = self._resolve_start(node_id, context)
            return _Terminal(start, "success", "native_same_tick_contract")
        return None

    def _resolve_terminal(
        self, node_id: int, context: dict[str, int]
    ) -> _Terminal:
        if node_id not in self.nodes:
            raise ScenarioEvaluationError(f"unknown terminal node {node_id}")
        signature = self._runtime_signature(node_id, context)
        key = (node_id, signature)
        if key in self.terminal_cache:
            return self.terminal_cache[key]
        if key in self.resolving_terminals:
            raise ScenarioEvaluationError("terminal recurrence contains a zero-time cycle")
        self.resolving_terminals.add(key)
        try:
            explicit = self.terminals.get(key)
            if explicit is not None:
                try:
                    deterministic = self._deterministic_leaf(node_id, context)
                except _Blocked:
                    deterministic = None
                try:
                    start = self._resolve_start(node_id, context)
                except _Blocked:
                    start = None
                if start is not None and explicit.frame < start:
                    raise ScenarioEvaluationError(
                        f"node {node_id} terminal precedes its resolved start"
                    )
                if deterministic is not None and (
                    explicit.frame != deterministic.frame
                    or explicit.status != deterministic.status
                ):
                    raise ScenarioEvaluationError(
                        f"node {node_id} binding contradicts deterministic contract"
                    )
                self.terminal_cache[key] = explicit
                return explicit
            deterministic = self._deterministic_leaf(node_id, context)
            if deterministic is not None:
                self.terminal_cache[key] = deterministic
                return deterministic

            node = self.nodes[node_id]
            op = node.get("op")
            children = node.get("children")
            if not isinstance(children, list):
                raise ScenarioEvaluationError(f"node {node_id} has invalid children")
            result: _Terminal | None = None
            if op == "sequence":
                for child in children:
                    terminal = self._resolve_terminal(child, context)
                    if terminal.status == "failure":
                        result = _Terminal(terminal.frame, "failure", "sequence_child")
                        break
                else:
                    if children:
                        terminal = self._resolve_terminal(children[-1], context)
                        result = _Terminal(terminal.frame, "success", "sequence_children")
            elif op == "selector":
                for child in children:
                    terminal = self._resolve_terminal(child, context)
                    if terminal.status == "success":
                        result = _Terminal(terminal.frame, "success", "selector_child")
                        break
                else:
                    if children:
                        terminal = self._resolve_terminal(children[-1], context)
                        result = _Terminal(terminal.frame, "failure", "selector_children")
            elif op == "parallel":
                terminals: list[_Terminal] = []
                blocked: list[dict[str, Any]] = []
                for child in children:
                    try:
                        terminals.append(self._resolve_terminal(child, context))
                    except _Blocked as exc:
                        blocked.extend(exc.dependencies)
                if blocked:
                    raise _Blocked(*blocked)
                failures = [item for item in terminals if item.status == "failure"]
                if failures:
                    first = min(failures, key=lambda item: item.frame)
                    result = _Terminal(first.frame, "failure", "parallel_first_failure")
                elif terminals:
                    last = max(terminals, key=lambda item: item.frame)
                    result = _Terminal(last.frame, "success", "parallel_all_success")
            elif op == "invert":
                terminal = self._resolve_terminal(children[0], context)
                status = "failure" if terminal.status == "success" else "success"
                result = _Terminal(terminal.frame, status, "inverted_child")
            elif op == "force_status":
                terminal = self._resolve_terminal(children[0], context)
                result = _Terminal(
                    terminal.frame,
                    node.get("policy", {}).get("forced_terminal_status"),
                    "forced_child_status",
                )
            elif op == "custom_initialization_scope":
                terminal = self._resolve_terminal(children[0], context)
                result = _Terminal(terminal.frame, terminal.status, "transparent_child")
            elif op == "repeat":
                policy = node.get("policy", {})
                if policy.get("repeat_forever") is not False:
                    raise _Blocked(self._task_dependency(node_id, context))
                count = policy.get("count")
                if type(count) is not int or count < 0:
                    raise ScenarioEvaluationError("finite repeater has invalid count")
                if count == 0:
                    result = _Terminal(
                        self._resolve_start(node_id, context),
                        "success",
                        "zero_count_repeater",
                    )
                else:
                    variable = f"repeat_{node_id}"
                    last = None
                    for iteration in range(count):
                        child_context = dict(context)
                        child_context[variable] = iteration
                        last = self._resolve_terminal(children[0], child_context)
                        if last.status == "failure" and policy.get("end_on_failure"):
                            result = _Terminal(
                                last.frame, "failure", "repeater_end_on_failure"
                            )
                            break
                    if result is None and last is not None:
                        result = _Terminal(last.frame, "success", "repeater_complete")
            elif op == "custom_pattern_timeout":
                if len(children) != 1:
                    raise ScenarioEvaluationError(
                        "pattern timeout node must have exactly one child"
                    )
                deadline = self.pattern_deadline(node_id, context)
                timeout_status = node.get("policy", {}).get(
                    "timeout_terminal_status"
                )
                if timeout_status not in _STATUSES:
                    raise ScenarioEvaluationError(
                        "pattern timeout terminal status is invalid"
                    )
                child = self._resolve_terminal(children[0], context)
                if child.frame < deadline:
                    result = _Terminal(
                        child.frame, child.status, "pattern_child_terminal"
                    )
                else:
                    result = _Terminal(
                        deadline, timeout_status, "pattern_fixed60_timeout"
                    )
            elif op in {"custom_random_selector", "custom_random_sequence"}:
                variable = f"random_{node_id}"
                if variable not in context:
                    raise _Blocked(
                        {
                            "kind": "missing_random_activation_index",
                            "random_node_id": node_id,
                            "variable": variable,
                        }
                    )
                activation = context[variable]
                permutation = self.permutations.get((node_id, activation))
                if permutation is None:
                    raise _Blocked(
                        {
                            "kind": "missing_random_permutation",
                            "random_node_id": node_id,
                            "activation_index": activation,
                        }
                    )
                selector = op == "custom_random_selector"
                last = None
                for child in permutation:
                    last = self._resolve_terminal(child, context)
                    if selector and last.status == "success":
                        result = _Terminal(last.frame, "success", "random_selector_child")
                        break
                    if not selector and last.status == "failure":
                        result = _Terminal(last.frame, "failure", "random_sequence_child")
                        break
                if result is None and last is not None:
                    result = _Terminal(
                        last.frame,
                        "failure" if selector else "success",
                        "random_children_exhausted",
                    )
            if result is None:
                raise _Blocked(self._task_dependency(node_id, context))
            if result.status not in _STATUSES:
                raise ScenarioEvaluationError(f"node {node_id} produced invalid status")
            self.terminal_cache[key] = result
            return result
        finally:
            self.resolving_terminals.remove(key)

    def evaluate_event_instance(
        self, instance: dict[str, Any], index: int
    ) -> dict[str, Any]:
        if not isinstance(instance, dict):
            raise ScenarioEvaluationError("event instance must be an object")
        event_id = instance.get("event_id")
        event = self.events.get(event_id)
        if event is None:
            raise ScenarioEvaluationError(f"event instance {index} has unknown event")
        context = _valid_context(
            instance.get("context", {}),
            allowed=self.allowed_context,
            label=f"event instance {index}",
        )
        self._validate_context_bounds(context, label=f"event instance {index}")
        self._signature(event["node_id"], context, require_complete=True)
        instance_id = instance.get("instance_id", f"{event_id}@{index}")
        if not isinstance(instance_id, str) or not instance_id:
            raise ScenarioEvaluationError("event instance ID is invalid")
        common = {
            "instance_id": instance_id,
            "template_event_id": event_id,
            "kind": event.get("kind"),
            "node_id": event.get("node_id"),
            "shot_key": event.get("shot_key"),
            "skill_id": event.get("skill_id"),
            "context": _context_record(context),
        }
        try:
            action_start = self._resolve_start(event["node_id"], context)
            if event.get("kind") == "skill_dispatch":
                frame = action_start
                evidence = "resolved_task_activation_start"
            elif "relative_to_timeline_action_start" in event:
                offset = event["relative_to_timeline_action_start"].get("frames")
                if type(offset) is not int or offset < 0:
                    raise ScenarioEvaluationError("exact effect marker is invalid")
                frame = action_start + offset
                evidence = "resolved_action_start_plus_exact_timeline_marker"
                if self.horizon is not None and frame >= self.horizon:
                    return {
                        **common,
                        "resolution_status": "outside_horizon",
                        "battle_frame": frame,
                        "action_start_frame": action_start,
                        "evidence": evidence,
                    }
                try:
                    terminal = self._resolve_terminal(event["node_id"], context)
                except _Blocked as exc:
                    return {
                        **common,
                        "resolution_status": "conditional",
                        "battle_frame": frame,
                        "action_start_frame": action_start,
                        "condition": "action_survives_through_exact_marker_frame",
                        "dependencies": _deduplicate_dependencies(exc.dependencies),
                        "evidence": evidence,
                    }
                if terminal.frame < frame:
                    return {
                        **common,
                        "resolution_status": "inactive",
                        "reason": {
                            "kind": "action_terminal_before_exact_marker",
                            "terminal_frame": terminal.frame,
                            "marker_frame": frame,
                            "terminal_status": terminal.status,
                        },
                    }
                if terminal.frame == frame:
                    return {
                        **common,
                        "resolution_status": "conditional",
                        "battle_frame": frame,
                        "action_start_frame": action_start,
                        "condition": "same_frame_marker_terminal_order",
                        "dependencies": [
                            {
                                "kind": "missing_same_frame_order_binding",
                                "node_id": event["node_id"],
                                "frame": frame,
                            }
                        ],
                        "evidence": evidence,
                    }
            else:
                signature = self._runtime_signature(event["node_id"], context)
                frame = self.effect_frames.get((event_id, signature))
                if frame is None:
                    return {
                        **common,
                        "resolution_status": "unresolved",
                        "action_start_frame": action_start,
                        "dependencies": [
                            {
                                "kind": "missing_skill_effect_frame",
                                "event_id": event_id,
                                "node_id": event["node_id"],
                                "context": _context_record(context),
                                "action_start_frame": action_start,
                            }
                        ],
                    }
                if frame < action_start:
                    raise ScenarioEvaluationError("skill effect precedes action start")
                evidence = "explicit_scenario_skill_effect_binding"
            result = {
                **common,
                "resolution_status": "resolved",
                "battle_frame": frame,
                "action_start_frame": action_start,
                "evidence": evidence,
            }
            if self.horizon is not None and frame >= self.horizon:
                result["resolution_status"] = "outside_horizon"
            return result
        except _Blocked as exc:
            return {
                **common,
                "resolution_status": "unresolved",
                "dependencies": _deduplicate_dependencies(exc.dependencies),
            }
        except _Inactive as exc:
            return {
                **common,
                "resolution_status": "inactive",
                "reason": exc.reason,
            }


class _HorizonExpander:
    """Walk concrete activation instances until the scenario horizon/frontiers."""

    def __init__(self, evaluator: _Evaluator):
        if evaluator.horizon is None:
            raise ScenarioEvaluationError("horizon expansion requires a frame horizon")
        self.evaluator = evaluator
        self.activations: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.frontiers: list[dict[str, Any]] = []
        self.random_activation_counts: Counter[int] = Counter()
        self.event_counts: Counter[str] = Counter()
        self.transition_count = 0
        self.reached_horizon = False
        self.events_by_node: dict[int, list[dict[str, Any]]] = {}
        for event in evaluator.events.values():
            self.events_by_node.setdefault(event["node_id"], []).append(event)

    def _node_context(
        self, node_id: int, context: dict[str, int]
    ) -> dict[str, int]:
        keys = self.evaluator._relevant_context_keys(node_id)
        return {key: context[key] for key in sorted(keys) if key in context}

    def _record_frontier(
        self,
        node_id: int,
        context: dict[str, int],
        dependencies: list[dict[str, Any]],
        *,
        start_frame: int | None = None,
    ) -> None:
        self.frontiers.append(
            {
                "node_id": node_id,
                "source_type": _short_type(self.evaluator.nodes[node_id]),
                "context": _context_record(self._node_context(node_id, context)),
                "start_frame": start_frame,
                "dependencies": _deduplicate_dependencies(dependencies),
            }
        )

    def _emit_events(
        self,
        node_id: int,
        context: dict[str, int],
        *,
        cutoff: int,
    ) -> None:
        node_context = self._node_context(node_id, context)
        for event in self.events_by_node.get(node_id, []):
            event_id = event["event_id"]
            occurrence = self.event_counts[event_id]
            self.event_counts[event_id] += 1
            result = self.evaluator.evaluate_event_instance(
                {
                    "event_id": event_id,
                    "instance_id": f"{event_id}@{occurrence}",
                    "context": node_context,
                },
                len(self.events),
            )
            frame = result.get("battle_frame")
            if type(frame) is int and frame >= cutoff:
                if cutoff == self.evaluator.horizon:
                    self.events.append(result)
                    continue
                result = {
                    **result,
                    "resolution_status": "inactive",
                    "reason": {
                        "kind": "activation_preempted_before_event",
                        "preemption_frame": cutoff,
                        "event_frame": frame,
                    },
                }
                result.pop("battle_frame", None)
            self.events.append(result)

    def _finish(
        self,
        activation: dict[str, Any],
        terminal: _Terminal,
        *,
        end_kind: str = "completed",
    ) -> _Terminal:
        activation["terminal"] = {
            "frame": terminal.frame,
            "status": terminal.status,
            "source": terminal.source,
            "end_kind": end_kind,
        }
        return terminal

    def _run(
        self,
        node_id: int,
        context: dict[str, int],
        *,
        cutoff: int,
        start_override: int | None = None,
    ) -> _Terminal | None:
        self.transition_count += 1
        if self.transition_count > 1_000_000:
            raise ScenarioEvaluationError("horizon expansion transition cap exceeded")
        node = self.evaluator.nodes[node_id]
        local_context = dict(context)
        assigned_random_activation = False
        if node.get("op") in {
            "custom_random_selector",
            "custom_random_sequence",
        }:
            variable = f"random_{node_id}"
            if variable not in local_context:
                local_context[variable] = self.random_activation_counts[node_id]
                assigned_random_activation = True
        if start_override is not None:
            signature = self.evaluator._runtime_signature(node_id, local_context)
            self.evaluator.start_cache[(node_id, signature)] = start_override
        try:
            start = self.evaluator._resolve_start(node_id, local_context)
        except _Blocked as exc:
            self._record_frontier(node_id, local_context, exc.dependencies)
            return None
        except _Inactive:
            return None
        horizon = self.evaluator.horizon
        if start >= cutoff or start >= horizon:
            if start >= horizon:
                self.reached_horizon = True
            return None
        if assigned_random_activation:
            self.random_activation_counts[node_id] += 1
        activation = {
            "activation_id": f"node_{node_id}@{len(self.activations)}",
            "node_id": node_id,
            "source_type": _short_type(node),
            "context": _context_record(self._node_context(node_id, local_context)),
            "start_frame": start,
        }
        self.activations.append(activation)
        self._emit_events(node_id, local_context, cutoff=min(cutoff, horizon))
        op = node.get("op")
        children = node.get("children", [])

        try:
            if op == "sequence":
                last = None
                for child in children:
                    last = self._run(child, local_context, cutoff=cutoff)
                    if last is None:
                        return None
                    if last.status == "failure":
                        return self._finish(
                            activation,
                            _Terminal(last.frame, "failure", "sequence_child"),
                        )
                if last is not None:
                    return self._finish(
                        activation,
                        _Terminal(last.frame, "success", "sequence_children"),
                    )
            elif op == "selector":
                last = None
                for child in children:
                    last = self._run(child, local_context, cutoff=cutoff)
                    if last is None:
                        return None
                    if last.status == "success":
                        return self._finish(
                            activation,
                            _Terminal(last.frame, "success", "selector_child"),
                        )
                if last is not None:
                    return self._finish(
                        activation,
                        _Terminal(last.frame, "failure", "selector_children"),
                    )
            elif op == "parallel":
                branches = []
                for child in children:
                    activation_start = len(self.activations)
                    event_start = len(self.events)
                    frontier_start = len(self.frontiers)
                    terminal = self._run(child, local_context, cutoff=cutoff)
                    branches.append(
                        {
                            "node_id": child,
                            "terminal": terminal,
                            "activation_start": activation_start,
                            "activation_end": len(self.activations),
                            "event_start": event_start,
                            "event_end": len(self.events),
                            "new_frontier": len(self.frontiers) > frontier_start,
                        }
                    )
                unresolved_branches = [
                    branch
                    for branch in branches
                    if branch["terminal"] is None and branch["new_frontier"]
                ]
                for unresolved_branch in unresolved_branches:
                    branch_activations = self.activations[
                        unresolved_branch["activation_start"] : unresolved_branch[
                            "activation_end"
                        ]
                    ]
                    possible_failure_from = (
                        branch_activations[0]["start_frame"]
                        if branch_activations
                        else start
                    )
                    dependency = {
                        "kind": "missing_parallel_sibling_terminal_order",
                        "parallel_node_id": node_id,
                        "sibling_branch_node_id": unresolved_branch["node_id"],
                        "sibling_possible_failure_from_frame": possible_failure_from,
                    }
                    for branch in branches:
                        if branch is unresolved_branch:
                            continue
                        for branch_activation in self.activations[
                            branch["activation_start"] : branch["activation_end"]
                        ]:
                            terminal_record = branch_activation.get("terminal")
                            terminal_frame = (
                                terminal_record.get("frame")
                                if isinstance(terminal_record, dict)
                                else branch_activation.get("running_until_frame")
                            )
                            if (
                                branch_activation["start_frame"]
                                < possible_failure_from
                                and (
                                    type(terminal_frame) is not int
                                    or terminal_frame < possible_failure_from
                                )
                            ):
                                continue
                            branch_activation["resolution_status"] = "conditional"
                            branch_activation["condition"] = (
                                "parallel_sibling_does_not_fail_before_terminal"
                            )
                            branch_activation["dependencies"] = (
                                _deduplicate_dependencies(
                                    [
                                        *branch_activation.get("dependencies", []),
                                        dependency,
                                    ]
                                )
                            )
                        for event in self.events[
                            branch["event_start"] : branch["event_end"]
                        ]:
                            event_frame = event.get(
                                "battle_frame", event.get("action_start_frame")
                            )
                            if (
                                type(event_frame) is not int
                                or event_frame < possible_failure_from
                                or event.get("resolution_status")
                                not in {"resolved", "conditional"}
                            ):
                                continue
                            event["resolution_status"] = "conditional"
                            event["condition"] = (
                                "parallel_sibling_does_not_fail_before_event"
                            )
                            event["dependencies"] = _deduplicate_dependencies(
                                [*event.get("dependencies", []), dependency]
                            )
                concrete = [
                    item["terminal"]
                    for item in branches
                    if item["terminal"] is not None
                ]
                failures = [item for item in concrete if item.status == "failure"]
                if failures:
                    first = min(failures, key=lambda item: item.frame)
                    for branch in branches:
                        for child_activation in self.activations[
                            branch["activation_start"] : branch["activation_end"]
                        ]:
                            if child_activation["start_frame"] > first.frame:
                                child_activation["terminal"] = None
                                child_activation["end_kind"] = (
                                    "not_activated_parallel_preempted"
                                )
                                child_activation["preemption_frame"] = first.frame
                                child_activation.pop("running_until_frame", None)
                                continue
                            terminal_record = child_activation.get("terminal")
                            terminal_frame = (
                                terminal_record.get("frame")
                                if isinstance(terminal_record, dict)
                                else None
                            )
                            was_still_running = (
                                terminal_frame is not None
                                and terminal_frame > first.frame
                            ) or (
                                terminal_record is None
                                and not branch["new_frontier"]
                                and child_activation.get("running_until_frame", first.frame)
                                > first.frame
                            )
                            if was_still_running:
                                child_activation["terminal"] = None
                                child_activation["running_until_frame"] = first.frame
                                child_activation["end_kind"] = "parallel_preempted"
                                child_activation["preemption_frame"] = first.frame
                        for event in self.events[
                            branch["event_start"] : branch["event_end"]
                        ]:
                            event_frame = event.get(
                                "battle_frame", event.get("action_start_frame")
                            )
                            if type(event_frame) is not int:
                                continue
                            if event_frame > first.frame:
                                event["resolution_status"] = "inactive"
                                event["reason"] = {
                                    "kind": "parallel_preempted_before_event",
                                    "preemption_frame": first.frame,
                                    "event_frame": event_frame,
                                }
                                event.pop("battle_frame", None)
                            elif event_frame == first.frame:
                                event["resolution_status"] = "conditional"
                                event["condition"] = "same_frame_parallel_order"
                                event["dependencies"] = [
                                    {
                                        "kind": "missing_same_frame_parallel_order",
                                        "parallel_node_id": node_id,
                                        "frame": first.frame,
                                    }
                                ]
                    if any(
                        branch["terminal"] is None and branch["new_frontier"]
                        for branch in branches
                    ):
                        self._record_frontier(
                            node_id,
                            local_context,
                            [
                                {
                                    "kind": "indeterminate_parallel_terminal_before_known_failure",
                                    "parallel_node_id": node_id,
                                    "known_failure_frame": first.frame,
                                }
                            ],
                            start_frame=start,
                        )
                        return None
                    return self._finish(
                        activation,
                        _Terminal(first.frame, "failure", "parallel_first_failure"),
                    )
                if any(branch["terminal"] is None for branch in branches):
                    return None
                last = max(concrete, key=lambda item: item.frame)
                return self._finish(
                    activation,
                    _Terminal(last.frame, "success", "parallel_all_success"),
                )
            elif op == "invert":
                child = self._run(children[0], local_context, cutoff=cutoff)
                if child is None:
                    return None
                status = "failure" if child.status == "success" else "success"
                return self._finish(
                    activation, _Terminal(child.frame, status, "inverted_child")
                )
            elif op == "force_status":
                child = self._run(children[0], local_context, cutoff=cutoff)
                if child is None:
                    return None
                return self._finish(
                    activation,
                    _Terminal(
                        child.frame,
                        node["policy"]["forced_terminal_status"],
                        "forced_child_status",
                    ),
                )
            elif op == "custom_initialization_scope":
                child = self._run(children[0], local_context, cutoff=cutoff)
                if child is None:
                    return None
                return self._finish(activation, child)
            elif op == "repeat":
                policy = node["policy"]
                forever = policy.get("repeat_forever") is True
                count = policy.get("count") if not forever else None
                iteration = 0
                prior_frame = start
                while forever or iteration < count:
                    body_context = dict(local_context)
                    body_context[f"repeat_{node_id}"] = iteration
                    body = self._run(
                        children[0],
                        body_context,
                        cutoff=cutoff,
                        start_override=prior_frame,
                    )
                    if body is None:
                        return None
                    if body.status == "failure" and policy.get("end_on_failure"):
                        return self._finish(
                            activation,
                            _Terminal(body.frame, "failure", "repeater_end_on_failure"),
                        )
                    if forever and body.frame == prior_frame:
                        self._record_frontier(
                            node_id,
                            local_context,
                            [
                                {
                                    "kind": "zero_time_infinite_repeater",
                                    "repeat_node_id": node_id,
                                    "iteration": iteration,
                                    "frame": body.frame,
                                }
                            ],
                            start_frame=start,
                        )
                        return None
                    prior_frame = body.frame
                    iteration += 1
                return self._finish(
                    activation,
                    _Terminal(prior_frame, "success", "repeater_complete"),
                )
            elif op == "custom_pattern_timeout":
                signature = self.evaluator._runtime_signature(node_id, local_context)
                terminal = self.evaluator.terminals.get((node_id, signature))
                deadline = self.evaluator.pattern_deadline(node_id, local_context)
                timeout_status = node.get("policy", {}).get(
                    "timeout_terminal_status"
                )
                if timeout_status not in _STATUSES:
                    raise ScenarioEvaluationError(
                        "pattern timeout terminal status is invalid"
                    )
                if terminal is not None and terminal.frame > deadline:
                    raise ScenarioEvaluationError(
                        f"pattern node {node_id} terminal exceeds its fixed60 deadline"
                    )
                if (
                    terminal is not None
                    and terminal.frame == deadline
                    and terminal.status != timeout_status
                ):
                    raise ScenarioEvaluationError(
                        f"pattern node {node_id} deadline terminal conflicts with "
                        "the native timeout status"
                    )
                pattern_end_exclusive = (
                    terminal.frame if terminal is not None else deadline + 1
                )
                pattern_cutoff = min(
                    cutoff,
                    pattern_end_exclusive,
                    horizon,
                )
                frontier_count = len(self.frontiers)
                self.evaluator.pattern_guard_stack.add(node_id)
                try:
                    child = self._run(
                        children[0], local_context, cutoff=pattern_cutoff
                    )
                finally:
                    self.evaluator.pattern_guard_stack.remove(node_id)
                if terminal is not None:
                    observation_end = min(cutoff, horizon)
                    if terminal.frame >= observation_end:
                        activation["terminal"] = None
                        activation["running_until_frame"] = observation_end
                        activation["end_kind"] = (
                            "running_at_horizon"
                            if observation_end == horizon
                            else "preempted"
                        )
                        if observation_end == horizon:
                            self.reached_horizon = True
                        return None
                    if terminal.frame < deadline:
                        return self._finish(activation, terminal)
                    return self._finish(
                        activation,
                        _Terminal(
                            deadline, timeout_status, "pattern_fixed60_timeout"
                        ),
                    )
                if child is None and len(self.frontiers) > frontier_count:
                    activation["timeout_candidate_frame"] = deadline
                    return None
                if child is None and pattern_cutoff <= deadline:
                    activation["terminal"] = None
                    activation["running_until_frame"] = pattern_cutoff
                    activation["end_kind"] = (
                        "running_at_horizon"
                        if pattern_cutoff == horizon
                        else "preempted"
                    )
                    if pattern_cutoff == horizon:
                        self.reached_horizon = True
                    return None
                if child is not None and child.frame < deadline:
                    return self._finish(
                        activation,
                        _Terminal(child.frame, child.status, "pattern_child_terminal"),
                    )
                return self._finish(
                    activation,
                    _Terminal(deadline, timeout_status, "pattern_fixed60_timeout"),
                )
            elif op in {
                "custom_random_selector",
                "custom_random_sequence",
            }:
                variable = f"random_{node_id}"
                activation_index = local_context[variable]
                permutation = self.evaluator.permutations.get(
                    (node_id, activation_index)
                )
                if permutation is None:
                    raise _Blocked(
                        {
                            "kind": "missing_random_permutation",
                            "random_node_id": node_id,
                            "activation_index": activation_index,
                        }
                    )
                selector = op == "custom_random_selector"
                last = None
                for child_id in permutation:
                    last = self._run(child_id, local_context, cutoff=cutoff)
                    if last is None:
                        return None
                    if selector and last.status == "success":
                        return self._finish(activation, last)
                    if not selector and last.status == "failure":
                        return self._finish(activation, last)
                if last is not None:
                    status = "failure" if selector else "success"
                    return self._finish(
                        activation,
                        _Terminal(last.frame, status, "random_children_exhausted"),
                    )
            else:
                terminal = self.evaluator._resolve_terminal(node_id, local_context)
                if terminal.frame >= cutoff:
                    activation["terminal"] = None
                    activation["running_until_frame"] = cutoff
                    activation["end_kind"] = (
                        "running_at_horizon" if cutoff == horizon else "preempted"
                    )
                    if cutoff == horizon:
                        self.reached_horizon = True
                    return None
                return self._finish(activation, terminal)
        except _Blocked as exc:
            self._record_frontier(
                node_id, local_context, exc.dependencies, start_frame=start
            )
            return None
        except _Inactive:
            return None
        return None

    def expand(self) -> dict[str, Any]:
        root_id = self.evaluator.timeline["ir"]["root_node_id"]
        terminal = self._run(root_id, {}, cutoff=self.evaluator.horizon)
        if terminal is None and not self.reached_horizon and not self.frontiers:
            self._record_frontier(
                root_id,
                {},
                [
                    {
                        "kind": "indeterminate_root_terminal",
                        "node_id": root_id,
                    }
                ],
            )
        frontiers = _deduplicate_dependencies(self.frontiers)
        return {
            "root_terminal": (
                {
                    "frame": terminal.frame,
                    "status": terminal.status,
                    "source": terminal.source,
                }
                if terminal is not None
                else None
            ),
            "activations": self.activations,
            "events": self.events,
            "unresolved_frontiers": frontiers,
            "reached_horizon": self.reached_horizon,
        }


def _validate_source_and_scenario(
    timeline: dict[str, Any],
    scenario: dict[str, Any],
    *,
    timeline_sha256: str,
) -> None:
    _verify_digest(timeline, "battle timeline")
    _verify_digest(scenario, "scenario")
    if (
        timeline.get("schema_version") != SUPPORTED_TIMELINE_SCHEMA
        or timeline.get("catalog_kind") != TIMELINE_KIND
        or timeline.get("status") != "branch_aware_battle_frame_partial"
        or timeline.get("scope", {}).get("fps") != FPS
        or timeline.get("scope", {}).get("promotion_eligible") is not False
    ):
        raise ScenarioEvaluationError("unsupported battle timeline artifact")
    if (
        scenario.get("schema_version") != SCHEMA_VERSION
        or scenario.get("catalog_kind") != SCENARIO_KIND
    ):
        raise ScenarioEvaluationError("unsupported scenario artifact")
    scenario_id = scenario.get("scenario_id")
    if not isinstance(scenario_id, str) or not _SCENARIO_ID.fullmatch(scenario_id):
        raise ScenarioEvaluationError("scenario ID is invalid")
    season = str(timeline.get("entry", {}).get("season"))
    if str(scenario.get("season")) != season:
        raise ScenarioEvaluationError("scenario season does not match timeline")
    source = scenario.get("source", {}).get("battle_timeline")
    if (
        not isinstance(source, dict)
        or source.get("sha256") != timeline_sha256
        or source.get("catalog_digest_sha256")
        != timeline.get("catalog_digest_sha256")
        or source.get("game_assembly_sha256")
        != timeline.get("runtime_evidence", {})
        .get("game_assembly", {})
        .get("sha256")
    ):
        raise ScenarioEvaluationError("scenario source binding does not match timeline")
    mode = scenario.get("evaluation_mode", "requested_instances")
    if mode not in {"requested_instances", "expand_180s_horizon"}:
        raise ScenarioEvaluationError("unsupported scenario evaluation mode")
    instances = scenario.get("event_instances", [])
    if not isinstance(instances, list) or (
        mode == "requested_instances" and not instances
    ):
        raise ScenarioEvaluationError("scenario must request event instances")
    if mode == "expand_180s_horizon":
        if instances:
            raise ScenarioEvaluationError(
                "180-second expansion does not accept requested event instances"
            )
        battle = scenario.get("battle", {})
        origin = battle.get("behavior_enable_frame")
        horizon = battle.get("frame_horizon_exclusive")
        if type(origin) is not int or type(horizon) is not int or horizon != origin + 180 * FPS:
            raise ScenarioEvaluationError(
                "180-second expansion requires horizon = behavior enable + 10800"
            )
        if battle.get("pattern_tick_model") != "next_fixed60_frame":
            raise ScenarioEvaluationError(
                "180-second expansion requires an explicit pattern tick model"
            )


def build_scenario_evaluation(
    *, timeline_path: Path, scenario_path: Path
) -> dict[str, Any]:
    timeline, timeline_sha256 = _load_json(timeline_path)
    scenario, scenario_sha256 = _load_json(scenario_path)
    _validate_source_and_scenario(
        timeline, scenario, timeline_sha256=timeline_sha256
    )
    evaluator = _Evaluator(timeline, scenario)
    mode = scenario.get("evaluation_mode", "requested_instances")
    activations: list[dict[str, Any]] = []
    frontiers: list[dict[str, Any]] = []
    expansion_result = None
    if mode == "expand_180s_horizon":
        expansion_result = _HorizonExpander(evaluator).expand()
        events = expansion_result["events"]
        activations = expansion_result["activations"]
        frontiers = expansion_result["unresolved_frontiers"]
    else:
        raw_instances = scenario["event_instances"]
        seen_ids: set[str] = set()
        events = []
        for index, instance in enumerate(raw_instances):
            result = evaluator.evaluate_event_instance(instance, index)
            if result["instance_id"] in seen_ids:
                raise ScenarioEvaluationError("duplicate event instance ID")
            seen_ids.add(result["instance_id"])
            events.append(result)
    counts = Counter(item["resolution_status"] for item in events)
    counts_by_kind = Counter(
        (item["kind"], item["resolution_status"]) for item in events
    )
    if mode == "expand_180s_horizon":
        status = (
            "partial"
            if frontiers
            or counts.get("unresolved", 0) > 0
            or counts.get("conditional", 0) > 0
            else (
                "complete_180s_window"
                if expansion_result["reached_horizon"]
                else "complete_execution_before_horizon"
            )
        )
    else:
        status = (
            "complete_for_requested_instances"
            if counts.get("unresolved", 0) == 0
            and counts.get("conditional", 0) == 0
            else "partial"
        )
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "catalog_kind": OUTPUT_KIND,
        "status": status,
        "scope": {
            "mode": "solo_raid_challenge_only",
            "season": str(scenario["season"]),
            "scenario_id": scenario["scenario_id"],
            "evaluation_mode": mode,
            "fps": FPS,
            "promotion_eligible": False,
        },
        "battle_frame_model": {
            "behavior_enable_frame": evaluator.behavior_enable_frame,
            "delta_model": scenario["battle"]["delta_model"],
            "pattern_tick_model": scenario["battle"].get("pattern_tick_model"),
            "frame_horizon_exclusive": evaluator.horizon,
            "missing_input_policy": "preserve_unresolved",
            "same_tick_scheduler_contract": True,
        },
        "source": {
            "battle_timeline": {
                "logical_path": (
                    "repo/Database/raw/staticdata/assembled/" + timeline_path.name
                ),
                "sha256": timeline_sha256,
                "catalog_digest_sha256": timeline["catalog_digest_sha256"],
            },
            "scenario": {
                "logical_path": "repo/" + scenario_path.name,
                "sha256": scenario_sha256,
                "catalog_digest_sha256": scenario["catalog_digest_sha256"],
            },
            "game_assembly_sha256": timeline["runtime_evidence"]["game_assembly"][
                "sha256"
            ],
        },
        "events": events,
        "activations": activations,
        "unresolved_frontiers": frontiers,
        "expansion": (
            {
                "reached_horizon": expansion_result["reached_horizon"],
                "root_terminal": expansion_result["root_terminal"],
            }
            if expansion_result is not None
            else None
        ),
        "coverage": {
            "requested_event_instances": len(events),
            "resolved": counts.get("resolved", 0),
            "unresolved": counts.get("unresolved", 0),
            "inactive": counts.get("inactive", 0),
            "conditional": counts.get("conditional", 0),
            "outside_horizon": counts.get("outside_horizon", 0),
            "resolved_dispatches": counts_by_kind.get(
                ("skill_dispatch", "resolved"), 0
            ),
            "resolved_effects": counts_by_kind.get(("skill_effect", "resolved"), 0),
            "activations": len(activations),
            "unresolved_frontiers": len(frontiers),
        },
        "validation": {
            "status": "passed",
            "checks": [
                {"name": "source_digest_binding", "status": "passed"},
                {"name": "activation_context_binding", "status": "passed"},
                {"name": "no_missing_input_fabrication", "status": "passed"},
            ],
        },
    }
    artifact["catalog_digest_sha256"] = _sha256(_canonical_bytes(artifact))
    return artifact


def write_catalog(
    value: dict[str, Any], output: Path, *, static_root: Path = DEFAULT_STATIC_ROOT
) -> Path:
    allowed = (static_root.resolve() / "assembled").resolve()
    resolved = output.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ScenarioEvaluationError(
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
        description="evaluate explicit Challenge scenario bindings into battle frames"
    )
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--static-root", type=Path, default=DEFAULT_STATIC_ROOT)
    args = parser.parse_args(argv)
    try:
        artifact = build_scenario_evaluation(
            timeline_path=args.timeline,
            scenario_path=args.scenario,
        )
        written = write_catalog(artifact, args.output, static_root=args.static_root)
    except ScenarioEvaluationError as exc:
        print(f"scenario evaluation blocked: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {written}")
    print(f"status={artifact['status']}")
    print(f"catalog_digest_sha256={artifact['catalog_digest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
