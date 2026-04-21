"""
Unit tests for the tiered ApiKeyRotator + error-classification + retry-delay logic.
No Gemini API calls; monkey-patches genai.Client to a dummy.
"""
from __future__ import annotations

import io
import os
import sys
import time
import types

# utf-8 stdout for Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                   line_buffering=True)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from DataPipeline.schema import skill_parser_llm as mod  # noqa: E402


# ── test helpers ─────────────────────────────────────────
def _patch_genai_client() -> None:
    """genai.Client 를 호출할 일 없어야 하지만 방어적으로 noop stub."""
    class DummyClient:
        def __init__(self, *a, **kw): pass
    mod.genai.Client = DummyClient  # type: ignore[attr-defined]


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  PASS: {msg}")


# ── 1) _is_quota_error & _extract_retry_delay ────────────
def test_classification():
    print("\n=== classification + retry delay ===")

    # per-minute: message has 'quota' AND 'per minute' + retryDelay 48s
    per_min = RuntimeError(
        "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, "
        "'message': 'Quota exceeded ...GenerateRequestsPerMinute... "
        "Please retry in 48s', 'retryDelay': '48s'}}"
    )
    per_min.code = 429
    _assert(mod._is_quota_error(per_min) is False,
            "per-minute error -> backoff (not quota)")
    _assert(mod._extract_retry_delay(per_min) == 48.0,
            "retry_delay 48 extracted")

    # per-day
    per_day = RuntimeError(
        "429 RESOURCE_EXHAUSTED per day. retryDelay: 3600s"
    )
    per_day.code = 429
    _assert(mod._is_quota_error(per_day) is True,
            "per-day error -> quota (rotate)")

    # 500 server error
    srv = RuntimeError("500 internal error")
    srv.code = 500
    _assert(mod._is_quota_error(srv) is False,
            "500 is not a quota error")

    # ambiguous 429 no signals — default to backoff (safer)
    amb = RuntimeError("429 something odd")
    amb.code = 429
    _assert(mod._is_quota_error(amb) is False,
            "ambiguous 429 -> backoff by default")


# ── 2) ApiKeyRotator tiered preference ───────────────────
def test_tiered_preference():
    print("\n=== rotator: free first, paid fallback ===")
    _patch_genai_client()

    r = mod.ApiKeyRotator(["K1", "K2", "K3", "K4", "PAID5"], paid_indices=[4])
    # initial pick must be free
    _assert(not r._is_paid[r._idx], "initial pick is free")
    idx0 = r._idx

    # exhaust all free keys one by one → should finally fall through to paid
    free_seen: set[int] = set()
    while not r._is_paid[r._idx]:
        free_seen.add(r._idx)
        if not r.rotate():
            break
    _assert(r._is_paid[r._idx],
            f"after exhausting all free keys, current is paid (free_seen={free_seen})")
    _assert(free_seen == {0, 1, 2, 3},
            f"all 4 free keys were visited before paid (free_seen={free_seen})")


# ── 3) Cooldown: free in cooldown → paid → free resumes ──
def test_cooldown_then_resume():
    print("\n=== rotator: free cooldown -> paid -> free resumes after expiry ===")
    _patch_genai_client()

    r = mod.ApiKeyRotator(["K1", "PAID2"], paid_indices=[1])
    _assert(r._idx == 0, "start on free K1")

    # Cool K1 for 0.6s, pick_next should take PAID2 (free unavailable now)
    r.cool_down_current(0.6)
    r.pick_next()
    _assert(r._idx == 1, "free cooling -> switch to paid")

    # Wait until K1 cooldown expires, then pick_next should prefer K1 again.
    time.sleep(0.8)
    r.pick_next()
    _assert(r._idx == 0,
            "free cooldown expired -> prefer free again (paid not monopolized)")


# ── 4) Exhaust + cooldown combined ───────────────────────
def test_exhaust_and_cooldown_mix():
    print("\n=== rotator: exhaust K1 permanently, K2 cools, K3 free ===")
    _patch_genai_client()

    r = mod.ApiKeyRotator(["K1", "K2", "K3", "PAID4"], paid_indices=[3])
    # start at K1
    r.exhaust_current()   # K1 dead
    r.pick_next()
    _assert(r._idx == 1, "after K1 exhausted, move to K2 (free)")

    # cool K2 for 0.4s
    r.cool_down_current(0.4)
    r.pick_next()
    _assert(r._idx == 2, "K2 cooling -> K3 (still free)")

    # exhaust K3 → only K2 (cooling) + PAID4 left
    r.exhaust_current()
    r.pick_next()
    # K2 cooling, PAID4 available. Free is preferred only if immediately available.
    # K2 not immediately available → fallthrough to PAID4.
    _assert(r._idx == 3,
            f"K3 dead, K2 cooling -> PAID4 (got idx={r._idx})")

    # wait K2 expiry → should return to K2
    time.sleep(0.5)
    r.pick_next()
    _assert(r._idx == 1,
            f"K2 cooldown expired -> back to K2 (got idx={r._idx})")

    # exhaust K2 → only PAID4 alive
    r.exhaust_current()
    got = r.pick_next()
    _assert(got and r._idx == 3, "only PAID4 alive -> pick PAID4")

    # exhaust PAID4 → pick_next returns False
    r.exhaust_current()
    _assert(r.pick_next() is False, "all keys exhausted -> pick_next False")


# ── 5) _load_api_keys paid-index parsing ─────────────────
def test_load_api_keys_paid_parse():
    print("\n=== _load_api_keys: paid-index parsing from env ===")
    # save env
    saved = {k: os.environ.get(k) for k in
             list(os.environ.keys())
             if k.startswith(("GEMINI_", "GOOGLE_"))}
    # reset
    for k in list(os.environ.keys()):
        if k.startswith(("GEMINI_", "GOOGLE_")):
            del os.environ[k]
    try:
        os.environ["GEMINI_API_KEY_1"] = "free-a"
        os.environ["GEMINI_API_KEY_2"] = "free-b"
        os.environ["GEMINI_API_KEY_5"] = "paid-five"
        os.environ["GEMINI_PAID_KEY_INDICES"] = "5"

        keys, paid = mod._load_api_keys()
        _assert(keys == ["free-a", "free-b", "paid-five"],
                "keys loaded in env order, skipping empty slots")
        _assert(paid == [2],
                f"env slot 5 -> 0-based idx 2 in keys list (got {paid})")
    finally:
        # restore env
        for k in list(os.environ.keys()):
            if k.startswith(("GEMINI_", "GOOGLE_")):
                del os.environ[k]
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# ── main ────────────────────────────────────────────────
if __name__ == "__main__":
    test_classification()
    test_tiered_preference()
    test_cooldown_then_resume()
    test_exhaust_and_cooldown_mix()
    test_load_api_keys_paid_parse()
    print("\nALL ROTATOR TIER TESTS PASSED.")
